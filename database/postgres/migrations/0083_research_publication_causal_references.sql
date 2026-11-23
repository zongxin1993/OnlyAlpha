-- 正式 Research 的引用绑定当前 PG 因果成员；控制角色仍不能写结果列。
GRANT UPDATE(calculation_execution_evidence_fingerprints) ON public.research_run TO onlyalpha_job_publisher;

CREATE FUNCTION public.research_publication_causal_reference_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE target uuid; status text; actual text[]; expected text[]; result text; artifact text; publication text;
BEGIN
  IF TG_TABLE_NAME='job_publication' THEN
    IF NEW.job_kind<>'RESEARCH' THEN RETURN NEW; END IF;
  END IF;
  target=NEW.run_id;
  SELECT r.state,r.calculation_execution_evidence_fingerprints,r.research_result_fingerprint,r.artifact_content_fingerprint
    INTO status,actual,result,artifact FROM public.research_run r WHERE r.run_id=target;
  IF status IS NULL THEN RAISE EXCEPTION 'RESEARCH_PUBLICATION_RUN_MISSING'; END IF;
  IF status<>'COMPLETED' THEN
    IF actual IS DISTINCT FROM ARRAY[]::text[] THEN RAISE EXCEPTION 'RESEARCH_UNPUBLISHED_CAUSAL_REFERENCES'; END IF;
    RETURN NEW;
  END IF;
  SELECT p.publication_fingerprint INTO publication FROM public.job_publication p WHERE p.job_kind='RESEARCH' AND p.run_id=target;
  IF publication IS NULL OR result IS DISTINCT FROM publication OR artifact IS DISTINCT FROM publication THEN
    RAISE EXCEPTION 'RESEARCH_PUBLICATION_RESULT_BINDING_MISMATCH';
  END IF;
  SELECT COALESCE(array_agg(ref.fingerprint ORDER BY ref.fingerprint COLLATE "C"),ARRAY[]::text[]) INTO expected
    FROM (SELECT DISTINCT m.content_fingerprint AS fingerprint FROM public.job_result_member m
      WHERE m.job_kind='RESEARCH' AND m.run_id=target AND m.descriptor::jsonb->>'kind'='CAUSAL_EVIDENCE') ref;
  IF cardinality(expected)=0 OR actual IS DISTINCT FROM expected THEN
    RAISE EXCEPTION 'RESEARCH_PUBLICATION_CAUSAL_REFERENCE_MISMATCH';
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.research_publication_causal_reference_guard() FROM PUBLIC;
CREATE CONSTRAINT TRIGGER research_run_causal_references AFTER INSERT OR UPDATE ON public.research_run
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.research_publication_causal_reference_guard();
CREATE CONSTRAINT TRIGGER research_publication_causal_references AFTER INSERT ON public.job_publication
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.research_publication_causal_reference_guard();
