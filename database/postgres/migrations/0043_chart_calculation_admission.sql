-- Precondition: the canonical history through 0042 is applied; existing facts remain untouched.
-- The migration runner commits this additive DDL and its checksum in one transaction.
-- Failure rolls back all DDL; restart repeats through the checksummed migration authority.
-- Admission-unaware binaries must not write chart facts. Disable new admission for rollback;
-- after chart facts exist, retain a compatible reader or forward-fix, never delete history.
ALTER TABLE product_command_admission
    DROP CONSTRAINT product_command_admission_command_kind_check;
ALTER TABLE product_command_admission
    ADD CONSTRAINT product_command_admission_command_kind_check CHECK (
        command_kind IN (
            'CREATE_CHART_CALCULATION',
            'CREATE_RESEARCH_RUN',
            'CANCEL_RESEARCH_RUN',
            'FREEZE_STRATEGY',
            'PROMOTE_STRATEGY',
            'CREATE_BACKTEST_RUN',
            'CANCEL_BACKTEST_RUN',
            'EVALUATE_QUALIFICATION',
            'CREATE_SYMBOLIC_SEARCH_EXPERIMENT',
            'CREATE_PARAMETER_SEARCH_EXPERIMENT',
            'ADVANCE_SEARCH_EXPERIMENT',
            'CREATE_INTEGRATION',
            'UPDATE_INTEGRATION_DRAFT',
            'SET_INTEGRATION_SECRET',
            'CLEAR_INTEGRATION_SECRET',
            'RESET_INTEGRATION_DRAFT_CONTRACT',
            'PUBLISH_INTEGRATION_REVISION',
            'SET_INTEGRATION_LIFECYCLE'
        )
    );

ALTER TABLE product_command_receipt
    DROP CONSTRAINT product_command_receipt_command_kind_check;
ALTER TABLE product_command_receipt
    ADD CONSTRAINT product_command_receipt_command_kind_check CHECK (
        command_kind IN (
            'CREATE_CHART_CALCULATION',
            'CREATE_RESEARCH_RUN',
            'CANCEL_RESEARCH_RUN',
            'FREEZE_STRATEGY',
            'PROMOTE_STRATEGY',
            'CREATE_BACKTEST_RUN',
            'CANCEL_BACKTEST_RUN',
            'EVALUATE_QUALIFICATION',
            'CREATE_SYMBOLIC_SEARCH_EXPERIMENT',
            'CREATE_PARAMETER_SEARCH_EXPERIMENT',
            'ADVANCE_SEARCH_EXPERIMENT',
            'CREATE_INTEGRATION',
            'UPDATE_INTEGRATION_DRAFT',
            'SET_INTEGRATION_SECRET',
            'CLEAR_INTEGRATION_SECRET',
            'RESET_INTEGRATION_DRAFT_CONTRACT',
            'PUBLISH_INTEGRATION_REVISION',
            'SET_INTEGRATION_LIFECYCLE'
        )
    );

ALTER TABLE product_command_receipt
    DROP CONSTRAINT product_command_receipt_outcome_kind_check;
ALTER TABLE product_command_receipt
    ADD CONSTRAINT product_command_receipt_outcome_kind_check CHECK (
        outcome_kind IN (
            'CHART_CALCULATION_OPERATION',
            'RESEARCH_RUN',
            'STRATEGY',
            'STRATEGY_PROMOTION',
            'BACKTEST_RUN',
            'QUALIFICATION_DECISION',
            'SEARCH_EXPERIMENT',
            'INTEGRATION',
            'INTEGRATION_REVISION'
        )
    );

ALTER TABLE product_command_receipt
    DROP CONSTRAINT product_command_receipt_outcome_id_check;
ALTER TABLE product_command_receipt
    ADD CONSTRAINT product_command_receipt_outcome_id_check CHECK (
        (
            outcome_kind IN ('RESEARCH_RUN', 'BACKTEST_RUN', 'INTEGRATION', 'CHART_CALCULATION_OPERATION')
            AND outcome_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
        )
        OR
        (
            outcome_kind IN (
                'STRATEGY',
                'STRATEGY_PROMOTION',
                'QUALIFICATION_DECISION',
                'SEARCH_EXPERIMENT',
                'INTEGRATION_REVISION'
            )
            AND outcome_id ~ '^[0-9a-f]{64}$'
        )
    );

CREATE TABLE chart_calculation_operation (
    operation_id UUID PRIMARY KEY CHECK (operation_id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'),
    product_command_id UUID UNIQUE NOT NULL CHECK (operation_id = product_command_id),
    reserved_run_id UUID UNIQUE NOT NULL CHECK (reserved_run_id <> operation_id AND reserved_run_id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'),
    command_fingerprint TEXT NOT NULL CHECK (command_fingerprint ~ '^[0-9a-f]{64}$'),
    intent_fingerprint TEXT NOT NULL CHECK (intent_fingerprint ~ '^[0-9a-f]{64}$'),
    intent_json TEXT NOT NULL CHECK (jsonb_typeof(intent_json::jsonb) = 'object'),
    catalog_witness_json TEXT NOT NULL CHECK (jsonb_typeof(catalog_witness_json::jsonb) = 'object'),
    catalog_witness_fingerprint TEXT NOT NULL CHECK (catalog_witness_fingerprint ~ '^[0-9a-f]{64}$'),
    operation_fingerprint TEXT NOT NULL CHECK (operation_fingerprint ~ '^[0-9a-f]{64}$'),
    accepted_at TIMESTAMPTZ NOT NULL,
    schema_version SMALLINT NOT NULL CHECK (schema_version = 1),
    state TEXT NOT NULL CHECK (state = 'ADMITTED'),
    preparation_revision BIGINT NOT NULL CHECK (preparation_revision = 0)
);
-- Canonical JSON bytes and cross-authority binding are verified by the owning adapter.
CREATE TRIGGER chart_calculation_operation_immutable
    BEFORE UPDATE OR DELETE OR TRUNCATE ON chart_calculation_operation
    FOR EACH STATEMENT EXECUTE FUNCTION research_source_history_immutable();
