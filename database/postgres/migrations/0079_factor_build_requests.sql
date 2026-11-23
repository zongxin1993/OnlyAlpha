-- Construction intent is distinct from an immutable program/certificate and
-- from a Research/Backtest Run. No execution or LIVE authority is granted.
CREATE UNIQUE INDEX factor_program_build_identity ON public.factor_built_program
(source_sha256,(payload::jsonb->>'interface_fingerprint'),(payload::jsonb->>'builder_artifact'),(payload::jsonb->>'primitive_artifact'));
CREATE UNIQUE INDEX factor_certificate_exact_identity ON public.factor_parameter_certificate
(revision_fingerprint,program_fingerprint,parameters_fingerprint,(payload::jsonb->>'certifier_artifact'),(payload::jsonb->>'case_suite_fingerprint'));
CREATE TABLE public.factor_build_request (
 revision_fingerprint text NOT NULL REFERENCES public.private_factor_revision(revision_fingerprint),
 requested_parameters_fingerprint text NOT NULL CHECK(requested_parameters_fingerprint ~ '^[0-9a-f]{64}$'),
 requested_parameters_payload text NOT NULL CHECK(octet_length(requested_parameters_payload)<=262144 AND jsonb_typeof(requested_parameters_payload::jsonb)='object'),
 request_context text NOT NULL CHECK(request_context='DEFAULT' OR request_context ~ '^[0-9a-f]{64}$'),
 state text NOT NULL CHECK(state IN ('BUILDING','READY','FAILED')),
 build_environment_fingerprint text CHECK(build_environment_fingerprint ~ '^[0-9a-f]{64}$'),
 program_fingerprint text REFERENCES public.factor_built_program(program_fingerprint),
 certificate_fingerprint text REFERENCES public.factor_parameter_certificate(certificate_fingerprint),
 failure_code text CHECK(failure_code ~ '^[A-Z_]{1,96}$'),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 finished_at timestamptz,
 PRIMARY KEY(revision_fingerprint,requested_parameters_fingerprint,request_context),
 CHECK(encode(sha256(convert_to(requested_parameters_payload,'UTF8')),'hex')=requested_parameters_fingerprint),
 CHECK((state='BUILDING' AND build_environment_fingerprint IS NULL AND program_fingerprint IS NULL AND certificate_fingerprint IS NULL AND failure_code IS NULL AND finished_at IS NULL)
 OR (state='READY' AND build_environment_fingerprint IS NOT NULL AND program_fingerprint IS NOT NULL AND certificate_fingerprint IS NOT NULL AND failure_code IS NULL AND finished_at IS NOT NULL)
 OR (state='FAILED' AND build_environment_fingerprint IS NOT NULL AND program_fingerprint IS NULL AND certificate_fingerprint IS NULL AND failure_code IS NOT NULL AND finished_at IS NOT NULL))
);
CREATE FUNCTION public.factor_build_request_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' OR TG_OP='TRUNCATE' THEN RAISE EXCEPTION 'FACTOR_BUILD_CONTROL_IMMUTABLE'; END IF;
 IF TG_OP='UPDATE' AND (OLD.state<>'BUILDING' OR NEW.revision_fingerprint<>OLD.revision_fingerprint
   OR NEW.requested_parameters_fingerprint<>OLD.requested_parameters_fingerprint OR NEW.requested_parameters_payload<>OLD.requested_parameters_payload
   OR NEW.request_context<>OLD.request_context OR NEW.created_at<>OLD.created_at) THEN RAISE EXCEPTION 'FACTOR_BUILD_CONTROL_IMMUTABLE'; END IF;
 IF NEW.state='READY' AND NOT EXISTS(SELECT 1 FROM public.factor_parameter_certificate c WHERE c.certificate_fingerprint=NEW.certificate_fingerprint AND c.revision_fingerprint=NEW.revision_fingerprint AND c.program_fingerprint=NEW.program_fingerprint) THEN RAISE EXCEPTION 'FACTOR_BUILD_CERTIFICATE_MISMATCH'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.factor_build_request_guard() FROM PUBLIC;
CREATE TRIGGER factor_build_request_guard BEFORE INSERT OR UPDATE OR DELETE ON public.factor_build_request FOR EACH ROW EXECUTE FUNCTION public.factor_build_request_guard();
CREATE TRIGGER factor_build_request_no_truncate BEFORE TRUNCATE ON public.factor_build_request FOR EACH STATEMENT EXECUTE FUNCTION public.job_content_immutable();
CREATE FUNCTION public.factor_enqueue_default_build() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF TG_TABLE_SCHEMA<>'public' OR TG_TABLE_NAME<>'private_factor_revision' OR TG_OP<>'INSERT' THEN RAISE EXCEPTION 'FACTOR_BUILD_TRIGGER_INVALID'; END IF;
 INSERT INTO public.factor_build_request(revision_fingerprint,requested_parameters_fingerprint,requested_parameters_payload,request_context,state)
 VALUES(NEW.revision_fingerprint,encode(sha256(convert_to('{}','UTF8')),'hex'),'{}','DEFAULT','BUILDING');
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.factor_enqueue_default_build() FROM PUBLIC;
CREATE TRIGGER factor_enqueue_default_build AFTER INSERT ON public.private_factor_revision FOR EACH ROW EXECUTE FUNCTION public.factor_enqueue_default_build();
REVOKE ALL ON public.factor_build_request FROM PUBLIC;
GRANT SELECT ON public.private_factor_revision TO onlyalpha_factor_builder;
GRANT SELECT ON public.factor_build_request TO onlyalpha_factor_builder,onlyalpha_job_reader;
GRANT INSERT ON public.factor_build_request TO onlyalpha_factor_builder;
GRANT UPDATE(state,build_environment_fingerprint,program_fingerprint,certificate_fingerprint,failure_code,finished_at) ON public.factor_build_request TO onlyalpha_factor_builder;

GRANT SELECT(factor_id) ON public.private_factor_revision TO onlyalpha_job_reader;
