-- 正式 Research 发布身份与科学结果身份分列（Constitution §4.1）：
-- artifact_content_fingerprint 继续等于本 Run 的 publication_fingerprint（发布身份）；
-- research_result_fingerprint 改为生产方在发布成员同一表示上由科学域公式推导的科学结果身份，
-- 与文件证据轨道同一定义，守卫只确认其为完整 SHA-256，与成员内容的一致性由读取方
-- （research_evidence::publication）在同一快照内重算核对。Backtest 轨道不受影响。
CREATE OR REPLACE FUNCTION public.research_publication_causal_reference_guard() RETURNS trigger
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
  IF publication IS NULL OR artifact IS DISTINCT FROM publication
      OR result IS NULL OR result !~ '^[0-9a-f]{64}$' THEN
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
