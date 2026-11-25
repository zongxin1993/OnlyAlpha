CREATE TABLE public.sim_venue_log (
    scope_key text NOT NULL REFERENCES public.sim_run_admission (scope_key),
    sequence bigint NOT NULL CHECK (sequence >= 0),
    previous text NOT NULL CHECK (previous ~ '^[0-9a-f]{64}$'),
    previous_sequence bigint GENERATED ALWAYS AS (NULLIF(sequence, 0) - 1) STORED,
    fingerprint text NOT NULL,
    document text NOT NULL,
    PRIMARY KEY (scope_key, sequence),
    UNIQUE (scope_key, sequence, fingerprint),
    FOREIGN KEY (scope_key, previous_sequence, previous)
        REFERENCES public.sim_venue_log (scope_key, sequence, fingerprint),
    CHECK (fingerprint = encode(sha256(convert_to(document, 'UTF8')), 'hex')),
    CHECK (document::jsonb ->> 'scope_key' IS NOT DISTINCT FROM scope_key
        AND document::jsonb ->> 'sequence' IS NOT DISTINCT FROM sequence::text
        AND document::jsonb ->> 'previous' IS NOT DISTINCT FROM previous),
    CHECK (CASE WHEN sequence = 0 THEN previous = repeat('0', 64) AND document::jsonb ->> 'kind' = 'OPEN'
        ELSE document::jsonb ->> 'kind' IN ('PROTOCOL', 'VENUE') END IS TRUE)
);

ALTER TABLE public.sim_run_admission
    ADD COLUMN open_sequence bigint GENERATED ALWAYS AS (0::bigint) STORED,
    ADD CONSTRAINT sim_run_open_fk FOREIGN KEY (scope_key, open_sequence)
        REFERENCES public.sim_venue_log (scope_key, sequence) DEFERRABLE INITIALLY DEFERRED;

CREATE FUNCTION public.sim_venue_require_ready_intent() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    intent jsonb := NEW.document::jsonb #> '{body,record,event,intent}';
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.trading_fact f
        JOIN public.trading_fact_ready r USING (scope_key, sequence)
        WHERE f.scope_key = NEW.scope_key AND f.transaction_id = (intent ->> 'transaction')
            AND f.payload_fingerprint = (intent ->> 'payload_hash')
    ) THEN
        RAISE EXCEPTION 'SIM_ORIGINAL_INTENT_NOT_READY' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.sim_venue_require_ready_intent() FROM PUBLIC;
CREATE TRIGGER sim_venue_ready_intent BEFORE INSERT ON public.sim_venue_log
    FOR EACH ROW WHEN (NEW.document::jsonb ->> 'kind' = 'PROTOCOL'
        AND jsonb_extract_path_text(NEW.document::jsonb, 'body', 'record', 'event', 'kind') = 'INTENT')
    EXECUTE FUNCTION public.sim_venue_require_ready_intent();

CREATE TRIGGER sim_venue_log_guard BEFORE INSERT ON public.sim_venue_log
    FOR EACH STATEMENT EXECUTE FUNCTION public.trading_fact_guard_insert();
CREATE TRIGGER sim_venue_log_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON public.sim_venue_log
    FOR EACH STATEMENT EXECUTE FUNCTION public.job_content_immutable();
REVOKE ALL ON public.sim_venue_log FROM PUBLIC;
GRANT SELECT ON public.sim_venue_log TO onlyalpha_node_control;
GRANT INSERT (scope_key, sequence, previous, fingerprint, document)
    ON public.sim_venue_log TO onlyalpha_node_control;
