-- Precondition: checksummed 0049; operator owns the schema and can create roles,
-- transfer function ownership and inspect pg_authid. No existing fact is changed.
-- DDL, role/ACL changes and ledger commit atomically under the migration lock.
-- The entry points have NO runtime EXECUTE grant. Consumer closure must precede
-- deployment provisioning; there is no GUC/token/flag enabling this boundary.
-- Rollback: stop admissions, retain facts/readers and snapshot or forward-fix.
LOCK TABLE public.research_run, public.research_run_attempt IN SHARE ROW EXCLUSIVE MODE;

DO $$
DECLARE executor_oid OID;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'onlyalpha_chart_sql_executor') THEN
        CREATE ROLE onlyalpha_chart_sql_executor NOLOGIN NOSUPERUSER NOCREATEDB
            NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
    END IF;
    SELECT oid INTO executor_oid FROM pg_catalog.pg_authid
    WHERE rolname = 'onlyalpha_chart_sql_executor' AND NOT rolcanlogin AND NOT rolsuper
      AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls
      AND NOT rolinherit AND rolconnlimit = -1 AND rolpassword IS NULL
      AND (rolvaliduntil IS NULL OR rolvaliduntil = 'infinity'::timestamptz);
    IF executor_oid IS NULL
       OR EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members WHERE roleid = executor_oid OR member = executor_oid)
       OR EXISTS (SELECT 1 FROM pg_catalog.pg_db_role_setting WHERE setrole = executor_oid)
       OR EXISTS (
           SELECT 1 FROM pg_catalog.pg_shdepend WHERE refclassid = 'pg_catalog.pg_authid'::regclass
             AND refobjid = executor_oid AND (dbid = 0 OR dbid = (
                 SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database()))
       ) THEN
        RAISE EXCEPTION 'CHART_NATIVE_SQL_EXECUTOR_UNSAFE';
    END IF;
    IF EXISTS (SELECT 1 FROM public.research_run_attempt a JOIN public.research_run r USING (run_id)
               WHERE r.origin_kind = 'CHART_CALCULATION') THEN
        RAISE EXCEPTION 'CHART_NATIVE_EXISTING_ATTEMPT_UNSUPPORTED';
    END IF;
END;
$$;

-- Only function ownership confers this effective identity. Nobody is a member.
-- CREATE and membership are temporary operator privileges for ownership transfer,
-- removed in the same transaction before any runtime can observe the schema.
GRANT onlyalpha_chart_sql_executor TO CURRENT_USER;
GRANT USAGE, CREATE ON SCHEMA public TO onlyalpha_chart_sql_executor;
GRANT SELECT ON public.research_run, public.research_run_attempt,
    public.chart_calculation_operation, public.chart_calculation_compilation,
    public.chart_calculation_run_admission, public.chart_calculation_preparation_fact,
    public.product_command_admission, public.product_command_receipt,
    public.research_run_id_reservation TO onlyalpha_chart_sql_executor;
GRANT UPDATE (state, revision, started_at) ON public.research_run TO onlyalpha_chart_sql_executor;
GRANT INSERT ON public.research_run_attempt TO onlyalpha_chart_sql_executor;
GRANT UPDATE (last_heartbeat_at, lease_expires_at) ON public.research_run_attempt TO onlyalpha_chart_sql_executor;
-- Existing owning source-history triggers execute inside the same transaction.
GRANT SELECT, UPDATE ON public.research_source_history_frontier TO onlyalpha_chart_sql_executor;
GRANT INSERT ON public.research_source_history TO onlyalpha_chart_sql_executor;

-- These owning trigger callees previously relied on the caller's search_path.
-- Qualify their unchanged journal transformation: neither public nor pg_temp
-- may redirect history written by a definer entry into a caller's shadow table.
CREATE OR REPLACE FUNCTION public.research_source_record(
    p_family TEXT, p_locator TEXT, p_row JSONB, p_operation TEXT
) RETURNS void LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog AS $$
DECLARE v_index BIGINT;
BEGIN
    UPDATE public.research_source_history_frontier SET last_index = last_index + 1
    WHERE singleton = TRUE RETURNING last_index INTO v_index;
    IF v_index IS NULL THEN
        RAISE EXCEPTION 'Research source history frontier missing';
    END IF;
    INSERT INTO public.research_source_history (event_index, source_family, native_locator, source_row, operation)
    VALUES (v_index, p_family, p_locator, p_row, p_operation);
END;
$$;
CREATE OR REPLACE FUNCTION public.research_source_capture_change() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog AS $$
DECLARE v_locator TEXT;
BEGIN
    IF TG_TABLE_NAME = 'research_run' THEN v_locator := NEW.run_id::text;
    ELSIF TG_TABLE_NAME = 'research_run_attempt' THEN v_locator := NEW.attempt_id::text;
    ELSE v_locator := NEW.command_id::text;
    END IF;
    PERFORM public.research_source_record(TG_ARGV[0], v_locator, to_jsonb(NEW), TG_OP);
    RETURN NEW;
END;
$$;

ALTER TABLE public.research_run DROP CONSTRAINT research_run_chart_capability_check;
ALTER TABLE public.research_run ADD CONSTRAINT research_run_chart_capability_check CHECK (
    (origin_kind = 'CHART_CALCULATION' AND specification_schema_version = 3 AND authoring_provenance IS NULL
        AND research_result_fingerprint IS NULL AND artifact_content_fingerprint IS NULL
        AND calculation_execution_evidence_fingerprints IS NOT NULL
        AND cardinality(calculation_execution_evidence_fingerprints) = 0
        AND failure_phase IS NULL AND failure_code IS NULL AND failure_detail IS NULL
        AND ((state = 'QUEUED' AND revision = 0 AND started_at IS NULL AND cancel_requested_at IS NULL)
          OR (state = 'CANCELLED' AND revision = 1 AND started_at IS NULL AND cancel_requested_at IS NULL)
          OR (state = 'RUNNING' AND revision = 1 AND started_at IS NOT NULL AND cancel_requested_at IS NULL)
          OR (state = 'CANCEL_REQUESTED' AND revision = 2 AND started_at IS NOT NULL
              AND cancel_requested_at IS NOT NULL AND cancel_requested_at >= started_at))
        AND (started_at IS NULL OR started_at >= queued_at)
        AND (finished_at IS NULL OR finished_at >= queued_at))
    OR (origin_kind IN ('GENERAL', 'PRIVATE_STRATEGY') AND specification_schema_version IN (1, 2))
);

-- SECURITY INVOKER is essential: a definer guard would see its own owner rather
-- than the narrow entry's executor and could authorize raw DML accidentally.
CREATE FUNCTION public.chart_native_run_mutation_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.origin_kind = 'CHART_CALCULATION' AND (NEW.state <> 'QUEUED' OR NEW.revision <> 0) THEN
            RAISE EXCEPTION 'CHART_NATIVE_EXECUTION_NOT_ENABLED';
        END IF;
    ELSIF OLD.origin_kind = 'CHART_CALCULATION' OR NEW.origin_kind = 'CHART_CALCULATION' THEN
        IF (to_jsonb(NEW) - ARRAY['state','revision','started_at','cancel_requested_at','finished_at'])
           IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['state','revision','started_at','cancel_requested_at','finished_at'])
           OR NEW.revision <> OLD.revision + 1 THEN
            RAISE EXCEPTION 'CHART_NATIVE_RUN_MUTATION_INVALID';
        END IF;
        IF OLD.state = 'QUEUED' AND NEW.state = 'RUNNING' THEN
            IF current_user <> 'onlyalpha_chart_sql_executor' THEN
                RAISE EXCEPTION 'CHART_NATIVE_EXECUTION_NOT_ENABLED';
            END IF;
        ELSIF OLD.state = 'QUEUED' AND NEW.state = 'CANCELLED' THEN
            NULL; -- Existing Human cancellation, not execution Authority.
        ELSIF OLD.state = 'RUNNING' AND NEW.state = 'CANCEL_REQUESTED'
              AND NEW.started_at IS NOT DISTINCT FROM OLD.started_at THEN
            NULL;
        ELSE
            RAISE EXCEPTION 'CHART_NATIVE_RUN_MUTATION_INVALID';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.chart_native_run_mutation_guard() FROM PUBLIC;
CREATE TRIGGER chart_native_run_mutation
    BEFORE INSERT OR UPDATE ON public.research_run
    FOR EACH ROW EXECUTE FUNCTION public.chart_native_run_mutation_guard();

-- Replace, never disable, the published closed trigger. Raw Chart DML continues
-- to reject even when a login has broad legacy table grants or a caller GUC.
CREATE OR REPLACE FUNCTION public.chart_native_publication_attempt_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.research_run
               WHERE run_id = NEW.run_id AND origin_kind = 'CHART_CALCULATION')
       OR (TG_OP = 'UPDATE' AND EXISTS (SELECT 1 FROM public.research_run
               WHERE run_id = OLD.run_id AND origin_kind = 'CHART_CALCULATION')) THEN
        IF current_user <> 'onlyalpha_chart_sql_executor' THEN
            RAISE EXCEPTION 'CHART_NATIVE_EXECUTION_NOT_ENABLED';
        END IF;
        IF TG_OP = 'INSERT' THEN
            IF NEW.state <> 'ACTIVE' THEN
                RAISE EXCEPTION 'CHART_NATIVE_ATTEMPT_MUTATION_INVALID';
            END IF;
        ELSIF OLD.state <> 'ACTIVE' OR NEW.state <> 'ACTIVE'
              OR (to_jsonb(NEW) - ARRAY['last_heartbeat_at','lease_expires_at'])
                 IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['last_heartbeat_at','lease_expires_at'])
              OR NEW.last_heartbeat_at < OLD.last_heartbeat_at OR NEW.lease_expires_at < OLD.lease_expires_at THEN
            RAISE EXCEPTION 'CHART_NATIVE_ATTEMPT_MUTATION_INVALID';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

-- This is SQL relation proof only; not Source/installed-byte/Work/file proof.
-- The trusted Controller independently verifies those owners before entering.
CREATE FUNCTION public.chart_native_context_v1(
    p_operation UUID, p_run UUID, p_compilation TEXT, p_generation TEXT, p_frozen TEXT
) RETURNS public.research_run
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog AS $$
DECLARE r public.research_run;
BEGIN
    SELECT run.* INTO r FROM public.research_run run
    JOIN public.chart_calculation_run_admission a ON a.run_id = run.run_id
    JOIN public.chart_calculation_operation o ON o.operation_id = a.operation_id
    JOIN public.chart_calculation_compilation c ON c.operation_id = o.operation_id
    JOIN public.product_command_admission d ON d.command_id = o.product_command_id
    JOIN public.product_command_receipt receipt ON receipt.command_id = o.product_command_id
    JOIN public.chart_calculation_preparation_fact ready ON ready.operation_id = o.operation_id
        AND ready.revision = c.input_preparation_revision AND ready.fence = c.input_preparation_fence
    WHERE o.operation_id = p_operation AND o.reserved_run_id = p_run AND a.run_id = p_run
      AND o.state = 'ADMITTED' AND o.schema_version = 1 AND a.schema_version = 1 AND c.schema_version = 1
      AND d.command_kind = 'CREATE_CHART_CALCULATION' AND d.command_fingerprint = o.command_fingerprint
      AND receipt.command_kind = d.command_kind AND receipt.command_fingerprint = d.command_fingerprint
      AND receipt.outcome_kind = 'CHART_CALCULATION_OPERATION' AND receipt.outcome_id = o.operation_id::text
      AND receipt.accepted_at = o.accepted_at AND d.schema_version = 1 AND receipt.schema_version = 1
      AND run.origin_kind = 'CHART_CALCULATION' AND run.specification_schema_version = 3
      AND run.admission_resolution_fingerprint = c.compilation_fingerprint
      AND run.specification_fingerprint = c.specification_fingerprint
      AND run.queued_at = a.queued_at AND a.queued_at >= o.accepted_at
      AND a.compilation_fingerprint = c.compilation_fingerprint AND c.compilation_fingerprint = p_compilation
      AND c.runtime_generation_fingerprint = p_generation AND c.runtime_work_id = p_run
      AND c.compilation_json = p_frozen
      AND ready.kind = 'INPUT_READY'
      AND ready.revision = (SELECT max(revision) FROM public.chart_calculation_preparation_fact
                            WHERE operation_id = o.operation_id)
      AND NOT EXISTS (SELECT 1 FROM public.research_run_id_reservation
                      WHERE run_id = p_run OR owner_id = p_operation);
    IF NOT FOUND THEN
        RAISE EXCEPTION 'CHART_NATIVE_OPERATIONAL_RELATION_INVALID';
    END IF;
    RETURN r;
END;
$$;
REVOKE ALL ON FUNCTION public.chart_native_context_v1(UUID, UUID, TEXT, TEXT, TEXT) FROM PUBLIC;
ALTER FUNCTION public.chart_native_context_v1(UUID, UUID, TEXT, TEXT, TEXT) OWNER TO onlyalpha_chart_sql_executor;

CREATE FUNCTION public.chart_native_claim_v1(
    p_version INTEGER, p_operation UUID, p_run UUID, p_revision BIGINT,
    p_compilation TEXT, p_generation TEXT, p_frozen TEXT,
    p_attempt UUID, p_worker UUID, p_lease INTERVAL, p_max_attempts INTEGER, p_started TIMESTAMPTZ
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE r public.research_run; a public.research_run_attempt; n INTEGER; count_attempts INTEGER; now_at TIMESTAMPTZ;
BEGIN
    IF p_version IS DISTINCT FROM 1 OR p_revision IS NULL OR p_revision NOT IN (0, 1)
       OR p_attempt IS NULL OR p_worker IS NULL
       OR p_attempt::text !~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
       OR p_worker::text !~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
       OR p_lease IS NULL OR NOT isfinite(p_lease) OR p_lease <= interval '0 seconds'
       OR p_max_attempts IS NULL OR p_max_attempts < 1 OR p_started IS NULL OR NOT isfinite(p_started) THEN
        RAISE EXCEPTION 'CHART_NATIVE_SQL_REQUEST_INVALID';
    END IF;
    -- Write intent before Run row/frontier: T1's SHARE cannot wait on a frontier
    -- already held by this transaction while this writer waits to upgrade.
    -- A zero-row UPDATE takes ROW EXCLUSIVE using the column UPDATE privilege.
    -- LOCK TABLE would require a broader table-level grant; no row/history changes.
    UPDATE public.research_run SET state = state WHERE FALSE;
    LOCK TABLE public.research_run_attempt IN ROW EXCLUSIVE MODE;
    PERFORM public.chart_native_context_v1(p_operation, p_run, p_compilation, p_generation, p_frozen);
    SELECT * INTO r FROM public.research_run WHERE run_id = p_run FOR UPDATE SKIP LOCKED;
    IF NOT FOUND THEN RETURN NULL; END IF; -- busy; not absence proof
    r := public.chart_native_context_v1(p_operation, p_run, p_compilation, p_generation, p_frozen);
    IF r.revision <> p_revision OR r.state NOT IN ('QUEUED', 'RUNNING')
       OR EXISTS (SELECT 1 FROM public.research_run_attempt WHERE run_id = p_run AND state = 'ACTIVE') THEN
        RETURN NULL;
    END IF;
    SELECT count(*), coalesce(max(attempt_number), 0) INTO count_attempts, n
    FROM public.research_run_attempt WHERE run_id = p_run;
    IF count_attempts <> n OR (r.state = 'QUEUED' AND n <> 0)
       OR (r.state = 'RUNNING' AND n = 0)
       OR EXISTS (SELECT 1 FROM public.research_run_attempt WHERE run_id = p_run AND state NOT IN ('FAILED', 'EXPIRED')) THEN
        RAISE EXCEPTION 'CHART_NATIVE_ATTEMPT_HISTORY_INVALID';
    END IF;
    IF n >= p_max_attempts THEN RETURN NULL; END IF;
    IF r.state = 'QUEUED' THEN
        UPDATE public.research_run SET state = 'RUNNING', revision = revision + 1, started_at = p_started
        WHERE run_id = p_run RETURNING * INTO r;
    END IF;
    now_at := clock_timestamp();
    INSERT INTO public.research_run_attempt (
        attempt_id, run_id, attempt_number, state, worker_instance_id, claimed_at, last_heartbeat_at, lease_expires_at
    ) VALUES (p_attempt, p_run, n + 1, 'ACTIVE', p_worker, now_at, now_at, now_at + p_lease) RETURNING * INTO a;
    RETURN jsonb_build_object('schema_version', 1, 'run', to_jsonb(r), 'attempt', to_jsonb(a));
END;
$$;
REVOKE ALL ON FUNCTION public.chart_native_claim_v1(INTEGER, UUID, UUID, BIGINT, TEXT, TEXT, TEXT, UUID, UUID, INTERVAL, INTEGER, TIMESTAMPTZ) FROM PUBLIC;
ALTER FUNCTION public.chart_native_claim_v1(INTEGER, UUID, UUID, BIGINT, TEXT, TEXT, TEXT, UUID, UUID, INTERVAL, INTEGER, TIMESTAMPTZ) OWNER TO onlyalpha_chart_sql_executor;

CREATE FUNCTION public.chart_native_heartbeat_v1(
    p_version INTEGER, p_operation UUID, p_run UUID, p_revision BIGINT,
    p_compilation TEXT, p_generation TEXT, p_frozen TEXT,
    p_attempt UUID, p_worker UUID, p_number INTEGER, p_lease INTERVAL
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE r public.research_run; a public.research_run_attempt; now_at TIMESTAMPTZ;
BEGIN
    IF p_version IS DISTINCT FROM 1 OR p_number IS NULL OR p_number < 1
       OR p_lease IS NULL OR NOT isfinite(p_lease) OR p_lease <= interval '0 seconds' THEN
        RAISE EXCEPTION 'CHART_NATIVE_SQL_REQUEST_INVALID';
    END IF;
    UPDATE public.research_run SET state = state WHERE FALSE;
    LOCK TABLE public.research_run_attempt IN ROW EXCLUSIVE MODE;
    SELECT * INTO r FROM public.research_run WHERE run_id = p_run FOR UPDATE;
    r := public.chart_native_context_v1(p_operation, p_run, p_compilation, p_generation, p_frozen);
    IF p_revision IS NULL OR r.revision <> p_revision OR r.state NOT IN ('RUNNING', 'CANCEL_REQUESTED') THEN
        RAISE EXCEPTION 'CHART_NATIVE_OWNERSHIP_LOST';
    END IF;
    SELECT * INTO a FROM public.research_run_attempt
    WHERE attempt_id = p_attempt AND run_id = p_run AND worker_instance_id = p_worker
      AND attempt_number = p_number AND state = 'ACTIVE' FOR UPDATE;
    -- Sample server time AFTER waiting on both rows; an earlier predicate cannot
    -- permit renewal of a lease which expired during row-lock contention.
    now_at := clock_timestamp();
    IF NOT FOUND OR a.lease_expires_at <= now_at THEN
        RAISE EXCEPTION 'CHART_NATIVE_OWNERSHIP_LOST';
    END IF;
    UPDATE public.research_run_attempt
    SET last_heartbeat_at = now_at, lease_expires_at = greatest(a.lease_expires_at, now_at + p_lease)
    WHERE attempt_id = p_attempt RETURNING * INTO a;
    RETURN jsonb_build_object('schema_version', 1, 'run', to_jsonb(r), 'attempt', to_jsonb(a));
END;
$$;
REVOKE ALL ON FUNCTION public.chart_native_heartbeat_v1(INTEGER, UUID, UUID, BIGINT, TEXT, TEXT, TEXT, UUID, UUID, INTEGER, INTERVAL) FROM PUBLIC;
ALTER FUNCTION public.chart_native_heartbeat_v1(INTEGER, UUID, UUID, BIGINT, TEXT, TEXT, TEXT, UUID, UUID, INTEGER, INTERVAL) OWNER TO onlyalpha_chart_sql_executor;

REVOKE CREATE ON SCHEMA public FROM onlyalpha_chart_sql_executor;
REVOKE onlyalpha_chart_sql_executor FROM CURRENT_USER;
-- Creator defaults can grant named roles even after PUBLIC is revoked and
-- ownership transferred. Reject, rather than change unrelated operator defaults.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_proc p
        JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(coalesce(p.proacl, pg_catalog.acldefault('f', p.proowner))) a
        WHERE n.nspname = 'public'
          AND p.proname IN ('chart_native_context_v1', 'chart_native_claim_v1', 'chart_native_heartbeat_v1')
          AND a.privilege_type = 'EXECUTE' AND a.grantee <> p.proowner
    ) THEN
        RAISE EXCEPTION 'CHART_NATIVE_SQL_ENTRY_ACL_UNSAFE';
    END IF;
END;
$$;
-- No GRANT to controller/reader/PUBLIC. No finalization/recovery/release permission.
