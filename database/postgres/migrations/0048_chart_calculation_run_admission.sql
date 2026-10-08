-- Precondition: checksummed history through 0047. Existing Run and Chart bytes are unchanged.
-- DDL and ledger commit atomically; any constraint/ledger failure rolls back. Retry is deterministic.
-- No compatibility shim: older writers cannot consume Chart reservations. Disable new admissions
-- before rollback; retain admitted facts and compatible readers, restore a snapshot or forward-fix.
ALTER TABLE research_run DROP CONSTRAINT research_run_origin_kind_check;
ALTER TABLE research_run DROP CONSTRAINT research_run_origin_composition_check;
ALTER TABLE research_run DROP CONSTRAINT research_run_specification_schema_version_check;
ALTER TABLE research_run ADD CONSTRAINT research_run_specification_schema_version_check
    CHECK (specification_schema_version IN (1, 2, 3));
ALTER TABLE research_run ADD CONSTRAINT research_run_origin_kind_check
    CHECK (origin_kind IN ('GENERAL', 'PRIVATE_STRATEGY', 'CHART_CALCULATION'));
ALTER TABLE research_run ADD CONSTRAINT research_run_origin_composition_check CHECK (
    (origin_kind = 'PRIVATE_STRATEGY' AND strategy_research_composition_fingerprint IS NOT NULL)
    OR (origin_kind IN ('GENERAL', 'CHART_CALCULATION') AND strategy_research_composition_fingerprint IS NULL)
);
ALTER TABLE research_run ADD CONSTRAINT research_run_chart_capability_check CHECK (
    (origin_kind = 'CHART_CALCULATION' AND specification_schema_version = 3 AND authoring_provenance IS NULL
        AND started_at IS NULL AND cancel_requested_at IS NULL
        AND research_result_fingerprint IS NULL AND artifact_content_fingerprint IS NULL
        AND calculation_execution_evidence_fingerprints IS NOT NULL
        AND cardinality(calculation_execution_evidence_fingerprints) = 0
        AND failure_phase IS NULL AND failure_code IS NULL AND failure_detail IS NULL
        AND ((state = 'QUEUED' AND revision = 0) OR (state = 'CANCELLED' AND revision = 1)))
    OR (origin_kind IN ('GENERAL', 'PRIVATE_STRATEGY') AND specification_schema_version IN (1, 2))
);

CREATE TABLE chart_calculation_run_admission (
    operation_id UUID PRIMARY KEY REFERENCES chart_calculation_compilation(operation_id),
    run_id UUID UNIQUE NOT NULL REFERENCES research_run(run_id),
    compilation_fingerprint TEXT NOT NULL CHECK (compilation_fingerprint ~ '^[0-9a-f]{64}$'),
    queued_at TIMESTAMPTZ NOT NULL,
    schema_version SMALLINT NOT NULL CHECK (schema_version = 1),
    CHECK (operation_id <> run_id)
);
CREATE TRIGGER chart_calculation_run_admission_immutable
    BEFORE UPDATE OR DELETE OR TRUNCATE ON chart_calculation_run_admission
    FOR EACH STATEMENT EXECUTE FUNCTION research_source_history_immutable();

-- Deferred closure: a typed Run cannot commit without its exact immutable relation,
-- and consumption cannot leave a reservation, orphan relation, wrong origin or queue reference.
-- Existing reserved-ID unique-index probe is retained unchanged: delete the verified reservation
-- before inserting the same-ID Run; rollback restores exclusion, commit transfers it to the Run PK.
CREATE FUNCTION chart_calculation_run_admission_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    target UUID;
BEGIN
    target := NEW.run_id;
    IF EXISTS (SELECT 1 FROM public.research_run WHERE run_id = target AND origin_kind = 'CHART_CALCULATION')
       OR EXISTS (SELECT 1 FROM public.chart_calculation_run_admission WHERE run_id = target) THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.chart_calculation_run_admission a
            JOIN public.chart_calculation_operation o ON o.operation_id = a.operation_id
            JOIN public.chart_calculation_compilation c ON c.operation_id = o.operation_id
            JOIN public.research_run r ON r.run_id = a.run_id
            WHERE a.run_id = target AND o.reserved_run_id = r.run_id
              AND r.origin_kind = 'CHART_CALCULATION'
              AND a.compilation_fingerprint = c.compilation_fingerprint
              AND r.admission_resolution_fingerprint = c.compilation_fingerprint
              AND r.specification_fingerprint = c.specification_fingerprint
              AND r.queued_at = a.queued_at AND r.queued_at >= o.accepted_at
              AND NOT EXISTS (SELECT 1 FROM public.research_run_id_reservation q
                              WHERE q.run_id = target OR q.owner_id = o.operation_id)
        ) THEN
            RAISE EXCEPTION 'CHART_RUN_ADMISSION_RELATION_CORRUPT';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE CONSTRAINT TRIGGER chart_run_admission_run_guard
    AFTER INSERT OR UPDATE ON research_run DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION chart_calculation_run_admission_guard();
CREATE CONSTRAINT TRIGGER chart_run_admission_relation_guard
    AFTER INSERT ON chart_calculation_run_admission DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION chart_calculation_run_admission_guard();
CREATE CONSTRAINT TRIGGER chart_run_admission_reservation_guard
    AFTER INSERT OR UPDATE ON research_run_id_reservation DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION chart_calculation_run_admission_guard();
