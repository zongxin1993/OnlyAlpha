-- Precondition: canonical 0043 is applied. Backfill exact chart ownership before enabling exclusion.
-- DDL, backfill, guards and migration checksum commit atomically; conflict aborts the migration.
-- Restart/retry uses the canonical checksum authority. No old history is rewritten.
-- After reservations exist, rollback must retain exclusion: stop new admission and forward-fix;
-- do not drop this authority or its guard to run an older writer.
LOCK TABLE research_run IN SHARE MODE;

ALTER TABLE chart_calculation_operation ADD CONSTRAINT chart_calculation_operation_reservation_identity
    UNIQUE (operation_id, reserved_run_id, accepted_at);

CREATE TABLE research_run_id_reservation (
    run_id UUID PRIMARY KEY CHECK (run_id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'),
    owner_kind TEXT NOT NULL CHECK (owner_kind = 'CHART_CALCULATION'),
    owner_id UUID UNIQUE NOT NULL,
    reserved_at TIMESTAMPTZ NOT NULL,
    schema_version SMALLINT NOT NULL CHECK (schema_version = 1),
    CONSTRAINT research_run_id_reservation_operation_fk
        FOREIGN KEY (owner_id, run_id, reserved_at)
        REFERENCES chart_calculation_operation (operation_id, reserved_run_id, accepted_at)
        DEFERRABLE INITIALLY IMMEDIATE
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM chart_calculation_operation c JOIN research_run r ON r.run_id = c.reserved_run_id
    ) THEN
        RAISE EXCEPTION 'RESEARCH_RUN_ID_RESERVATION_CONFLICT' USING ERRCODE = '23505';
    END IF;
END;
$$;

INSERT INTO research_run_id_reservation (run_id, owner_kind, owner_id, reserved_at, schema_version)
SELECT reserved_run_id, 'CHART_CALCULATION', operation_id, accepted_at, 1 FROM chart_calculation_operation;

CREATE TRIGGER research_run_id_reservation_immutable
    BEFORE UPDATE OR TRUNCATE ON research_run_id_reservation
    FOR EACH STATEMENT EXECUTE FUNCTION research_source_history_immutable();

-- Use unique-index arbitration, not snapshot absence: even a pre-existing Repeatable Read
-- snapshot cannot miss a newly committed reservation. The private probe never commits:
-- insert an independently generated probe owner, delete that exact tuple, then validate the
-- one deferred FK before returning. This also works for legacy SET CONSTRAINTS ALL IMMEDIATE.
-- Only owner UUID collisions regenerate; every other constraint/serialization error propagates.
CREATE FUNCTION research_run_reserved_id_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    probe_owner UUID;
    probe_run UUID;
    violated_constraint TEXT;
    removed BIGINT;
BEGIN
    SET CONSTRAINTS public.research_run_id_reservation_operation_fk DEFERRED;
    FOR attempt IN 1..128 LOOP
        probe_owner := gen_random_uuid();
        BEGIN
            INSERT INTO public.research_run_id_reservation
                (run_id, owner_kind, owner_id, reserved_at, schema_version)
            VALUES (NEW.run_id, 'CHART_CALCULATION', probe_owner, NEW.queued_at, 1)
            ON CONFLICT (run_id) DO NOTHING RETURNING run_id INTO probe_run;
            IF probe_run IS NULL THEN
                RAISE EXCEPTION 'RESEARCH_RUN_ID_RESERVED' USING ERRCODE = '23505';
            END IF;
            DELETE FROM public.research_run_id_reservation
                WHERE run_id = NEW.run_id AND owner_id = probe_owner;
            GET DIAGNOSTICS removed = ROW_COUNT;
            IF removed <> 1 THEN
                RAISE EXCEPTION 'RESEARCH_RUN_ID_RESERVATION_PROBE_CORRUPT';
            END IF;
            SET CONSTRAINTS public.research_run_id_reservation_operation_fk IMMEDIATE;
            RETURN NEW;
        EXCEPTION WHEN unique_violation THEN
            GET STACKED DIAGNOSTICS violated_constraint = CONSTRAINT_NAME;
            IF violated_constraint IS DISTINCT FROM 'research_run_id_reservation_owner_id_key' THEN
                RAISE;
            END IF;
        END;
    END LOOP;
    RAISE EXCEPTION 'RESEARCH_RUN_ID_RESERVATION_PROBE_COLLISION_LIMIT';
END;
$$;

CREATE TRIGGER research_run_reserved_id_insert
    BEFORE INSERT ON research_run FOR EACH ROW EXECUTE FUNCTION research_run_reserved_id_guard();
CREATE TRIGGER research_run_reserved_id_update
    BEFORE UPDATE OF run_id ON research_run FOR EACH ROW
    WHEN (OLD.run_id IS DISTINCT FROM NEW.run_id) EXECUTE FUNCTION research_run_reserved_id_guard();

-- Future T4 contract (not implemented here): lock exact operation + reservation; verify
-- owner, UUID and timestamp; delete the exact reservation; insert the same-ID Research Run;
-- insert the immutable operation->Run relation; commit all in one transaction. A competing
-- unique probe waits for the reservation deletion to commit/rollback. On commit the Run PK
-- owns the UUID; on rollback the reservation still excludes it. No generic bypass flag.
