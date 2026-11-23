-- Reuse the original Run/Attempt authorities. No parallel lifecycle or lease.
ALTER TABLE public.research_deployment_semantic_store_binding ADD CONSTRAINT job_semantic_store_identity UNIQUE(semantic_store_id);
CREATE TABLE public.job_frozen_binding (
  job_kind text NOT NULL CHECK(job_kind IN ('RESEARCH','BACKTEST')),
  run_id uuid NOT NULL,
  namespace_id uuid NOT NULL REFERENCES public.research_deployment_semantic_store_binding(semantic_store_id),
  owner_id text NOT NULL CHECK(btrim(owner_id)<>'' AND octet_length(owner_id)<=512),
  specification_fingerprint text NOT NULL CHECK(specification_fingerprint ~ '^[0-9a-f]{64}$'),
  admission_fingerprint text NOT NULL CHECK(admission_fingerprint ~ '^[0-9a-f]{64}$'),
  binding_fingerprint text NOT NULL CHECK(binding_fingerprint ~ '^[0-9a-f]{64}$'),
  payload text NOT NULL CHECK(octet_length(payload)<=262144),
  research_run_id uuid GENERATED ALWAYS AS (CASE WHEN job_kind='RESEARCH' THEN run_id END) STORED REFERENCES public.research_run(run_id),
  backtest_run_id uuid GENERATED ALWAYS AS (CASE WHEN job_kind='BACKTEST' THEN run_id END) STORED REFERENCES public.backtest_run(run_id),
  PRIMARY KEY(job_kind,run_id),
  CHECK(encode(sha256(convert_to(payload,'UTF8')),'hex')=binding_fingerprint),
  CHECK(payload::jsonb->>'kind' IS NOT DISTINCT FROM job_kind AND payload::jsonb->'scope'->>'run_id' IS NOT DISTINCT FROM run_id::text
    AND payload::jsonb->'scope'->>'namespace' IS NOT DISTINCT FROM namespace_id::text AND payload::jsonb->'scope'->>'owner' IS NOT DISTINCT FROM owner_id)
);
CREATE TABLE public.job_result_member (
  job_kind text NOT NULL,
  run_id uuid NOT NULL,
  member_key text NOT NULL CHECK(btrim(member_key)<>'' AND octet_length(member_key)<=512),
  descriptor text NOT NULL CHECK(octet_length(descriptor)<=8192),
  content text NOT NULL CHECK(octet_length(content)<=134217728),
  content_fingerprint text NOT NULL CHECK(content_fingerprint ~ '^[0-9a-f]{64}$'),
  PRIMARY KEY(job_kind,run_id,member_key),
  FOREIGN KEY(job_kind,run_id) REFERENCES public.job_frozen_binding(job_kind,run_id),
  CHECK(descriptor::jsonb->>'key' IS NOT DISTINCT FROM member_key),
  CHECK(encode(sha256(convert_to(content,'UTF8')),'hex')=content_fingerprint)
);
CREATE TABLE public.job_publication (
  job_kind text NOT NULL,
  run_id uuid NOT NULL,
  attempt_id uuid NOT NULL,
  worker_id uuid NOT NULL,
  attempt_number integer NOT NULL CHECK(attempt_number>0),
  fence bigint NOT NULL CHECK(fence>0),
  binding_fingerprint text NOT NULL CHECK(binding_fingerprint ~ '^[0-9a-f]{64}$'),
  publication_fingerprint text NOT NULL CHECK(publication_fingerprint ~ '^[0-9a-f]{64}$'),
  manifest_payload text NOT NULL CHECK(octet_length(manifest_payload)<=1048576),
  PRIMARY KEY(job_kind,run_id),
  FOREIGN KEY(job_kind,run_id) REFERENCES public.job_frozen_binding(job_kind,run_id),
  CHECK(encode(sha256(convert_to(manifest_payload,'UTF8')),'hex')=publication_fingerprint)
);

CREATE FUNCTION public.job_publication_closure_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE k text; id uuid; b public.job_frozen_binding%ROWTYPE; p public.job_publication%ROWTYPE;
 s text; spec text; admission text; attempt_state text; attempt_worker uuid; attempt_no integer;
 actual_fence bigint; expires timestamptz; ended timestamptz; actual_manifest jsonb;
BEGIN
  id=NEW.run_id;
  IF TG_TABLE_NAME IN ('research_run','research_run_attempt') THEN k='RESEARCH';
  ELSIF TG_TABLE_NAME IN ('backtest_run','backtest_run_attempt') THEN k='BACKTEST';
  ELSE k=NEW.job_kind; END IF;
  SELECT * INTO b FROM public.job_frozen_binding WHERE job_kind=k AND run_id=id;
  IF NOT FOUND THEN RETURN NEW; END IF;
  IF TG_OP='UPDATE' AND TG_TABLE_NAME IN ('research_run','backtest_run','research_run_attempt','backtest_run_attempt') THEN
    IF OLD.state IN ('COMPLETED','FAILED','CANCELLED','SUCCEEDED','EXPIRED') AND to_jsonb(OLD) IS DISTINCT FROM to_jsonb(NEW) THEN
      RAISE EXCEPTION 'JOB_TERMINAL_IMMUTABLE';
    END IF;
  END IF;
  IF k='RESEARCH' THEN
    SELECT state,specification_fingerprint,admission_resolution_fingerprint INTO s,spec,admission FROM public.research_run WHERE run_id=id;
  ELSE
    SELECT state,specification_fingerprint,admission_resolution_fingerprint INTO s,spec,admission FROM public.backtest_run WHERE run_id=id;
  END IF;
  IF s IS NULL OR spec<>b.specification_fingerprint OR admission<>b.admission_fingerprint THEN
    RAISE EXCEPTION 'JOB_RUN_BINDING_MISMATCH';
  END IF;
  SELECT * INTO p FROM public.job_publication WHERE job_kind=k AND run_id=id;
  IF NOT FOUND THEN
    IF s='COMPLETED' OR EXISTS(SELECT 1 FROM public.job_result_member WHERE job_kind=k AND run_id=id) THEN
      RAISE EXCEPTION 'JOB_PUBLICATION_INCOMPLETE';
    END IF;
    RETURN NEW;
  END IF;
  IF s<>'COMPLETED' OR p.binding_fingerprint<>b.binding_fingerprint THEN RAISE EXCEPTION 'JOB_PUBLICATION_STATE_MISMATCH'; END IF;
  IF k='RESEARCH' THEN
    SELECT state,worker_instance_id,attempt_number,attempt_number::bigint,lease_expires_at,finished_at
    INTO attempt_state,attempt_worker,attempt_no,actual_fence,expires,ended FROM public.research_run_attempt
    WHERE run_id=id AND attempt_id=p.attempt_id;
  ELSE
    SELECT a.state,a.worker_instance_id,a.attempt_number,a.fencing_token,a.lease_expires_at,a.finished_at
    INTO attempt_state,attempt_worker,attempt_no,actual_fence,expires,ended FROM public.backtest_run_attempt a
    WHERE a.run_id=id AND a.attempt_id=p.attempt_id;
  END IF;
  IF attempt_state IS DISTINCT FROM 'SUCCEEDED' OR attempt_worker IS DISTINCT FROM p.worker_id
    OR attempt_no IS DISTINCT FROM p.attempt_number OR actual_fence IS DISTINCT FROM p.fence
    OR ended IS NULL OR ended>expires THEN RAISE EXCEPTION 'JOB_ATTEMPT_MISMATCH'; END IF;
  IF (SELECT count(*) FROM public.job_result_member WHERE job_kind=k AND run_id=id)
    <>jsonb_array_length(b.payload::jsonb->'result_plan'->'members') THEN RAISE EXCEPTION 'JOB_MEMBERS_INCOMPLETE'; END IF;
  IF EXISTS (
    SELECT 1 FROM jsonb_array_elements(b.payload::jsonb->'result_plan'->'members') expected
    LEFT JOIN public.job_result_member m ON m.job_kind=k AND m.run_id=id AND m.member_key=expected->>'key'
    WHERE m.member_key IS NULL OR m.descriptor::jsonb->>'kind' IS DISTINCT FROM expected->>'kind'
      OR m.descriptor::jsonb->>'schema' IS DISTINCT FROM expected->>'schema'
      OR m.descriptor::jsonb->'axis_rule' IS DISTINCT FROM expected->'axis_rule'
      OR (expected->>'rows' IS NOT NULL AND m.descriptor::jsonb->>'rows' IS DISTINCT FROM expected->>'rows')
      OR jsonb_typeof(m.descriptor::jsonb->'rows') IS DISTINCT FROM 'number'
      OR m.descriptor::jsonb->>'rows' IS NULL OR (m.descriptor::jsonb->>'rows') !~ '^[0-9]+$'
      OR (expected->>'axis' IS NOT NULL AND m.descriptor::jsonb->>'axis' IS DISTINCT FROM expected->>'axis')
      OR (expected->>'axis' IS NULL AND expected->>'axis_rule' IS NULL AND m.descriptor::jsonb->>'axis' IS NOT NULL)
      OR (expected->>'axis_rule' IS NOT NULL AND COALESCE(m.descriptor::jsonb->>'axis','') !~ '^[0-9a-f]{64}$')
  ) THEN RAISE EXCEPTION 'JOB_MEMBER_BINDING_MISMATCH'; END IF;
  SELECT jsonb_agg(jsonb_build_object('key',member_key,'descriptor_fingerprint',encode(sha256(convert_to(descriptor,'UTF8')),'hex'),'content_fingerprint',content_fingerprint) ORDER BY member_key COLLATE "C")
    INTO actual_manifest FROM public.job_result_member WHERE job_kind=k AND run_id=id;
  IF p.manifest_payload::jsonb IS DISTINCT FROM jsonb_build_object('contract','PG_JOB_RESULT_V1','binding_fingerprint',b.binding_fingerprint,'members',actual_manifest)
    THEN RAISE EXCEPTION 'JOB_MANIFEST_MISMATCH'; END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.job_publication_closure_guard() FROM PUBLIC;
CREATE TRIGGER job_frozen_binding_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON public.job_frozen_binding FOR EACH STATEMENT EXECUTE FUNCTION public.job_content_immutable();
CREATE TRIGGER job_result_member_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON public.job_result_member FOR EACH STATEMENT EXECUTE FUNCTION public.job_content_immutable();
CREATE TRIGGER job_publication_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON public.job_publication FOR EACH STATEMENT EXECUTE FUNCTION public.job_content_immutable();
CREATE CONSTRAINT TRIGGER job_binding_closure AFTER INSERT ON public.job_frozen_binding DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.job_publication_closure_guard();
CREATE CONSTRAINT TRIGGER job_member_closure AFTER INSERT ON public.job_result_member DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.job_publication_closure_guard();
CREATE CONSTRAINT TRIGGER job_publication_closure AFTER INSERT ON public.job_publication DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.job_publication_closure_guard();
CREATE CONSTRAINT TRIGGER job_research_run_closure AFTER INSERT OR UPDATE ON public.research_run DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.job_publication_closure_guard();
CREATE CONSTRAINT TRIGGER job_backtest_run_closure AFTER INSERT OR UPDATE ON public.backtest_run DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.job_publication_closure_guard();
REVOKE ALL ON public.job_frozen_binding,public.job_result_member,public.job_publication FROM PUBLIC;
GRANT SELECT ON public.job_frozen_binding,public.job_result_member,public.job_publication,public.research_run,public.research_run_attempt,public.backtest_run,public.backtest_run_attempt TO onlyalpha_job_reader,onlyalpha_job_publisher;
GRANT INSERT ON public.job_frozen_binding,public.job_result_member,public.job_publication TO onlyalpha_job_publisher;
GRANT UPDATE(revision,state,finished_at,research_result_fingerprint,artifact_content_fingerprint) ON public.research_run TO onlyalpha_job_publisher;
GRANT UPDATE(revision,state,finished_at,evidence_fingerprint,result_fingerprint,determinism_fingerprint) ON public.backtest_run TO onlyalpha_job_publisher;
GRANT UPDATE(state,finished_at) ON public.research_run_attempt,public.backtest_run_attempt TO onlyalpha_job_publisher;

CREATE CONSTRAINT TRIGGER job_research_attempt_closure AFTER UPDATE ON public.research_run_attempt DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.job_publication_closure_guard();
CREATE CONSTRAINT TRIGGER job_backtest_attempt_closure AFTER UPDATE ON public.backtest_run_attempt DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.job_publication_closure_guard();

-- Preserve the original Research control-history transformation without giving
-- the publisher arbitrary INSERT/frontier privileges. Only actual owning rows
-- may enter through these two fixed trigger edges.
CREATE FUNCTION public.job_research_source_capture() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE family text; locator text;
BEGIN
  IF TG_TABLE_SCHEMA<>'public' OR TG_OP NOT IN ('INSERT','UPDATE') THEN RAISE EXCEPTION 'JOB_SOURCE_TRIGGER_INVALID'; END IF;
  IF TG_TABLE_NAME='research_run' THEN family='RESEARCH_RUN'; locator=NEW.run_id::text;
  ELSIF TG_TABLE_NAME='research_run_attempt' THEN family='RESEARCH_ATTEMPT'; locator=NEW.attempt_id::text;
  ELSE RAISE EXCEPTION 'JOB_SOURCE_TRIGGER_INVALID'; END IF;
  PERFORM public.research_source_record(family,locator,to_jsonb(NEW),TG_OP);
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.job_research_source_capture() FROM PUBLIC;
DROP TRIGGER research_run_source_history ON public.research_run;
DROP TRIGGER research_attempt_source_history ON public.research_run_attempt;
CREATE TRIGGER research_run_source_history AFTER INSERT OR UPDATE ON public.research_run FOR EACH ROW EXECUTE FUNCTION public.job_research_source_capture();
CREATE TRIGGER research_attempt_source_history AFTER INSERT OR UPDATE ON public.research_run_attempt FOR EACH ROW EXECUTE FUNCTION public.job_research_source_capture();
