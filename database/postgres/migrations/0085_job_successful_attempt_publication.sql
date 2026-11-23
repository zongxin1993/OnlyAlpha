-- Both writers change the original Run row version so an older repeatable-read
-- snapshot cannot certify absence after the competing transaction commits.
CREATE FUNCTION public.job_serialize_successful_attempt() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE
    k text;
BEGIN
    IF TG_TABLE_NAME = 'job_frozen_binding' THEN
        k := NEW.job_kind;
    ELSE
        k := TG_ARGV[0];
        IF EXISTS (SELECT 1 FROM public.job_frozen_binding WHERE job_kind=k AND run_id=NEW.run_id) THEN
            RETURN NEW;
        END IF;
    END IF;
    -- The Attempt writer may already hold its row. Fail immediately if a
    -- Run owner is ahead of it, preserving the production Run-first order.
    IF k = 'BACKTEST' THEN
        UPDATE public.backtest_run r SET revision=r.revision
        WHERE r.run_id=(SELECT run_id FROM public.backtest_run WHERE run_id=NEW.run_id FOR NO KEY UPDATE NOWAIT);
    ELSIF k = 'RESEARCH' THEN
        UPDATE public.research_run r SET revision=r.revision
        WHERE r.run_id=(SELECT run_id FROM public.research_run WHERE run_id=NEW.run_id FOR NO KEY UPDATE NOWAIT);
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.job_serialize_successful_attempt() FROM PUBLIC;

CREATE OR REPLACE TRIGGER research_run_source_history
    AFTER INSERT ON public.research_run FOR EACH ROW EXECUTE FUNCTION public.job_research_source_capture();
CREATE TRIGGER research_run_source_history_update
    AFTER UPDATE ON public.research_run FOR EACH ROW WHEN (OLD.* IS DISTINCT FROM NEW.*)
    EXECUTE FUNCTION public.job_research_source_capture();

CREATE TRIGGER job_serialize_frozen_binding
    BEFORE INSERT ON public.job_frozen_binding FOR EACH ROW EXECUTE FUNCTION public.job_serialize_successful_attempt();
CREATE TRIGGER job_serialize_backtest_success
    BEFORE INSERT OR UPDATE ON public.backtest_run_attempt FOR EACH ROW WHEN (NEW.state='SUCCEEDED')
    EXECUTE FUNCTION public.job_serialize_successful_attempt('BACKTEST');
CREATE TRIGGER job_serialize_research_success
    BEFORE INSERT OR UPDATE ON public.research_run_attempt FOR EACH ROW WHEN (NEW.state='SUCCEEDED')
    EXECUTE FUNCTION public.job_serialize_successful_attempt('RESEARCH');

CREATE FUNCTION public.job_successful_attempt_publication_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE
    k text;
    winner uuid;
BEGIN
    IF TG_TABLE_NAME = 'backtest_run_attempt' THEN
        k := 'BACKTEST';
    ELSIF TG_TABLE_NAME = 'research_run_attempt' THEN
        k := 'RESEARCH';
    ELSE
        k := NEW.job_kind;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.job_frozen_binding WHERE job_kind=k AND run_id=NEW.run_id) THEN
        RETURN NEW;
    END IF;
    SELECT attempt_id INTO winner FROM public.job_publication WHERE job_kind=k AND run_id=NEW.run_id;
    IF EXISTS (
        SELECT 1 FROM public.backtest_run_attempt
        WHERE k='BACKTEST' AND run_id=NEW.run_id AND state='SUCCEEDED' AND attempt_id IS DISTINCT FROM winner
        UNION ALL
        SELECT 1 FROM public.research_run_attempt
        WHERE k='RESEARCH' AND run_id=NEW.run_id AND state='SUCCEEDED' AND attempt_id IS DISTINCT FROM winner
    ) THEN
        RAISE EXCEPTION 'JOB_SUCCESSFUL_ATTEMPT_PUBLICATION_MISMATCH';
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.job_successful_attempt_publication_guard() FROM PUBLIC;
CREATE CONSTRAINT TRIGGER job_binding_successful_attempt_publication
    AFTER INSERT ON public.job_frozen_binding DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION public.job_successful_attempt_publication_guard();
CREATE CONSTRAINT TRIGGER job_backtest_successful_attempt_publication
    AFTER INSERT OR UPDATE ON public.backtest_run_attempt DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW WHEN (NEW.state='SUCCEEDED') EXECUTE FUNCTION public.job_successful_attempt_publication_guard();
CREATE CONSTRAINT TRIGGER job_research_successful_attempt_publication
    AFTER INSERT OR UPDATE ON public.research_run_attempt DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW WHEN (NEW.state='SUCCEEDED') EXECUTE FUNCTION public.job_successful_attempt_publication_guard();
