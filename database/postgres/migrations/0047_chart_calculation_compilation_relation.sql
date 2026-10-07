-- Precondition: canonical checksummed history through 0046. No T1/T2 facts are rewritten.
-- This is an immutable compilation consequence, not Run admission or numeric publication.
-- DDL + migration ledger commit atomically; failure rolls back and retry is deterministic.
-- Rollback: disable compilation writers, retain facts and a compatible reader, or forward-fix.
CREATE TABLE chart_calculation_compilation (
    operation_id UUID PRIMARY KEY REFERENCES chart_calculation_operation(operation_id),
    input_preparation_revision BIGINT NOT NULL CHECK (input_preparation_revision > 0),
    input_preparation_fence BIGINT NOT NULL CHECK (input_preparation_fence > 0 AND input_preparation_fence <= input_preparation_revision),
    input_selection_fingerprint TEXT NOT NULL CHECK (input_selection_fingerprint ~ '^[0-9a-f]{64}$'),
    dataset_snapshot_fingerprint TEXT NOT NULL CHECK (dataset_snapshot_fingerprint ~ '^[0-9a-f]{64}$'),
    dataset_materialization_id TEXT NOT NULL CHECK (btrim(dataset_materialization_id) <> ''),
    runtime_generation_fingerprint TEXT NOT NULL CHECK (runtime_generation_fingerprint ~ '^[0-9a-f]{64}$'),
    runtime_work_id UUID NOT NULL CHECK (runtime_work_id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'),
    runtime_binding_event_fingerprint TEXT NOT NULL CHECK (runtime_binding_event_fingerprint ~ '^[0-9a-f]{64}$'),
    catalog_witness_fingerprint TEXT NOT NULL CHECK (catalog_witness_fingerprint ~ '^[0-9a-f]{64}$'),
    catalog_implementation_fingerprint TEXT NOT NULL CHECK (catalog_implementation_fingerprint ~ '^[0-9a-f]{64}$'),
    specification_fingerprint TEXT NOT NULL CHECK (specification_fingerprint ~ '^[0-9a-f]{64}$'),
    result_plan_fingerprint TEXT NOT NULL CHECK (result_plan_fingerprint ~ '^[0-9a-f]{64}$'),
    graph_fingerprint TEXT NOT NULL CHECK (graph_fingerprint ~ '^[0-9a-f]{64}$'),
    calculation_fingerprint TEXT NOT NULL CHECK (calculation_fingerprint ~ '^[0-9a-f]{64}$'),
    implementation_fingerprint TEXT NOT NULL CHECK (implementation_fingerprint ~ '^[0-9a-f]{64}$'),
    compilation_json TEXT NOT NULL CHECK (jsonb_typeof(compilation_json::jsonb) = 'object'),
    compilation_fingerprint TEXT NOT NULL CHECK (compilation_fingerprint ~ '^[0-9a-f]{64}$'),
    schema_version SMALLINT NOT NULL CHECK (schema_version = 1)
);
-- Canonical JSON, redundant references and INPUT_READY ownership are verified by the owning adapter.
CREATE TRIGGER chart_calculation_compilation_immutable
    BEFORE UPDATE OR DELETE OR TRUNCATE ON chart_calculation_compilation
    FOR EACH STATEMENT EXECUTE FUNCTION research_source_history_immutable();
