CREATE TABLE public.trading_fact_stream (
    scope_key text PRIMARY KEY CHECK (scope_key ~ '^[0-9a-f]{64}$'),
    binding_fingerprint text NOT NULL CHECK (binding_fingerprint ~ '^[0-9a-f]{64}$'),
    kernel_artifact text NOT NULL CHECK (kernel_artifact ~ '^[0-9a-f]{64}$'),
    configuration text NOT NULL,
    configuration_fingerprint text NOT NULL CHECK (configuration_fingerprint = encode(sha256(convert_to(configuration, 'UTF8')), 'hex')),
    head bigint NOT NULL DEFAULT 0 CHECK (head >= 0),
    UNIQUE (scope_key, configuration_fingerprint),
    CHECK (((configuration::jsonb ->> 'runtime_kind') IN ('SIM', 'LIVE')) IS TRUE)
);

-- The canonical Prepared contains the ordered outbox and all original economic projections.
CREATE TABLE public.trading_fact (
    scope_key text NOT NULL,
    sequence bigint NOT NULL CHECK (sequence > 0),
    transaction_id text NOT NULL,
    input_id text NOT NULL,
    configuration_fingerprint text NOT NULL,
    payload_fingerprint text NOT NULL CHECK (payload_fingerprint ~ '^[0-9a-f]{64}$'),
    prepared text NOT NULL,
    written_in xid8 NOT NULL DEFAULT pg_current_xact_id(),
    PRIMARY KEY (scope_key, sequence),
    UNIQUE (scope_key, transaction_id),
    UNIQUE (scope_key, input_id),
    FOREIGN KEY (scope_key, configuration_fingerprint) REFERENCES public.trading_fact_stream (scope_key, configuration_fingerprint),
    CHECK (prepared::jsonb ->> 'transaction_id' IS NOT DISTINCT FROM transaction_id
        AND prepared::jsonb #>> '{input,input_id}' IS NOT DISTINCT FROM input_id
        AND prepared::jsonb ->> 'sequence' IS NOT DISTINCT FROM sequence::text
        AND prepared::jsonb ->> 'predecessor' IS NOT DISTINCT FROM (sequence - 1)::text
        AND prepared::jsonb ->> 'config_hash' IS NOT DISTINCT FROM configuration_fingerprint
        AND prepared::jsonb ->> 'payload_hash' IS NOT DISTINCT FROM payload_fingerprint)
);
CREATE TABLE public.trading_fact_ready (
    scope_key text NOT NULL,
    sequence bigint NOT NULL,
    result_hashes text[] NOT NULL CHECK (cardinality(result_hashes) = 6),
    PRIMARY KEY (scope_key, sequence),
    FOREIGN KEY (scope_key, sequence) REFERENCES public.trading_fact (scope_key, sequence)
);

CREATE FUNCTION public.trading_fact_require_authority() RETURNS void
LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_locks
        WHERE locktype = 'advisory' AND database = (SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database())
          AND pid = pg_backend_pid() AND classid = 1329199301::oid AND objid = 5::oid AND objsubid = 2
          AND granted AND mode = 'ExclusiveLock') THEN
        RAISE EXCEPTION 'TRADING_AUTHORITY_REQUIRED' USING ERRCODE = '42501';
    END IF;
END;
$$;
REVOKE ALL ON FUNCTION public.trading_fact_require_authority() FROM PUBLIC;

CREATE FUNCTION public.trading_fact_guard_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    PERFORM public.trading_fact_require_authority();
    RETURN NULL;
END;
$$;
REVOKE ALL ON FUNCTION public.trading_fact_guard_insert() FROM PUBLIC;
CREATE TRIGGER trading_fact_stream_guard BEFORE INSERT ON public.trading_fact_stream
    FOR EACH STATEMENT EXECUTE FUNCTION public.trading_fact_guard_insert();
CREATE TRIGGER trading_fact_guard BEFORE INSERT ON public.trading_fact
    FOR EACH STATEMENT EXECUTE FUNCTION public.trading_fact_guard_insert();

-- 仅安装已提交计划的持久化投影索引。内存 owner 的状态由内核按原输入重建并对账。
CREATE FUNCTION public.trading_fact_install_projection(stream_key text, plan_sequence bigint) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    components CONSTANT text[] := ARRAY['ORDER','POSITION','ACCOUNT','LEDGER','RISK','EXECUTION'];
    projections json;
    previous_hashes text[];
    installed_hashes text[] := '{}';
    projection json;
    result_hash text;
BEGIN
    PERFORM public.trading_fact_require_authority();
    SELECT f.prepared::json -> 'projections' INTO projections
    FROM public.trading_fact_stream s JOIN public.trading_fact f ON f.scope_key = s.scope_key AND f.sequence = s.head
    WHERE s.scope_key = stream_key AND s.head = plan_sequence AND f.written_in <> pg_current_xact_id()
    FOR UPDATE OF s;
    IF json_typeof(projections) IS DISTINCT FROM 'array' OR json_array_length(projections) IS DISTINCT FROM 6 THEN
        RAISE EXCEPTION 'TRADING_FACT_PROJECTION_MISSING' USING ERRCODE = '23514';
    END IF;
    SELECT r.result_hashes INTO previous_hashes FROM public.trading_fact_ready r
    WHERE r.scope_key = stream_key AND r.sequence = plan_sequence - 1;
    FOR i IN 1..6 LOOP
        projection := projections -> (i - 1);
        result_hash := encode(sha256(convert_to((projection -> 'result')::text, 'UTF8')), 'hex');
        IF projection ->> 'component' IS DISTINCT FROM components[i]
            OR json_typeof(projection -> 'result') IS DISTINCT FROM 'object'
            OR projection ->> 'result_hash' IS DISTINCT FROM result_hash
            OR ((projection ->> 'before_hash') ~ '^[0-9a-f]{64}$') IS NOT TRUE
            OR (plan_sequence > 1 AND projection ->> 'before_hash' IS DISTINCT FROM previous_hashes[i]) THEN
            RAISE EXCEPTION 'TRADING_FACT_PROJECTION_CONFLICT' USING ERRCODE = '23514';
        END IF;
        installed_hashes := array_append(installed_hashes, result_hash);
    END LOOP;
    INSERT INTO public.trading_fact_ready(scope_key, sequence, result_hashes)
    VALUES (stream_key, plan_sequence, installed_hashes);
END;
$$;
REVOKE ALL ON FUNCTION public.trading_fact_install_projection(text,bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.trading_fact_install_projection(text,bigint) TO onlyalpha_node_control;

CREATE FUNCTION public.trading_fact_advance() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    UPDATE public.trading_fact_stream SET head = NEW.sequence
    WHERE scope_key = NEW.scope_key AND head = NEW.sequence - 1
        AND (head = 0 OR EXISTS (SELECT 1 FROM public.trading_fact_ready r WHERE r.scope_key = NEW.scope_key AND r.sequence = NEW.sequence - 1));
    IF NOT FOUND THEN
        RAISE EXCEPTION 'TRADING_FACT_PREDECESSOR_CONFLICT' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;
REVOKE ALL ON FUNCTION public.trading_fact_advance() FROM PUBLIC;
CREATE TRIGGER trading_fact_advance AFTER INSERT ON public.trading_fact
    FOR EACH ROW EXECUTE FUNCTION public.trading_fact_advance();
CREATE TRIGGER trading_fact_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON public.trading_fact
    FOR EACH STATEMENT EXECUTE FUNCTION public.job_content_immutable();
CREATE TRIGGER trading_fact_ready_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON public.trading_fact_ready
    FOR EACH STATEMENT EXECUTE FUNCTION public.job_content_immutable();
CREATE TRIGGER trading_fact_stream_retained BEFORE DELETE OR TRUNCATE ON public.trading_fact_stream
    FOR EACH STATEMENT EXECUTE FUNCTION public.job_content_immutable();

REVOKE ALL ON public.trading_fact_stream, public.trading_fact, public.trading_fact_ready FROM PUBLIC;
GRANT SELECT ON public.trading_fact_stream, public.trading_fact, public.trading_fact_ready TO onlyalpha_node_control;
GRANT INSERT (scope_key, binding_fingerprint, kernel_artifact, configuration, configuration_fingerprint) ON public.trading_fact_stream TO onlyalpha_node_control;
GRANT INSERT (scope_key, sequence, transaction_id, input_id, configuration_fingerprint, payload_fingerprint, prepared)
    ON public.trading_fact TO onlyalpha_node_control;
