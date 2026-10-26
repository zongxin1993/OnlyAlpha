-- One explicit Owner default-workspace configuration; never market values or grants.
-- Additive immutable history and atomic global Command binding.
ALTER TABLE product_command_admission DROP CONSTRAINT product_command_admission_command_kind_check;
ALTER TABLE product_command_admission ADD CONSTRAINT product_command_admission_command_kind_check CHECK (command_kind IN ('CREATE_RESEARCH_RUN', 'CANCEL_RESEARCH_RUN', 'FREEZE_STRATEGY', 'PROMOTE_STRATEGY', 'CREATE_BACKTEST_RUN', 'CANCEL_BACKTEST_RUN', 'EVALUATE_QUALIFICATION', 'CREATE_SYMBOLIC_SEARCH_EXPERIMENT', 'CREATE_PARAMETER_SEARCH_EXPERIMENT', 'ADVANCE_SEARCH_EXPERIMENT', 'CREATE_INTEGRATION', 'UPDATE_INTEGRATION_DRAFT', 'SET_INTEGRATION_SECRET', 'CLEAR_INTEGRATION_SECRET', 'RESET_INTEGRATION_DRAFT_CONTRACT', 'PUBLISH_INTEGRATION_REVISION', 'SET_INTEGRATION_LIFECYCLE', 'CREATE_CHART_CALCULATION', 'SAVE_WATCHLISTS', 'SAVE_WORKSPACE'));
ALTER TABLE product_command_receipt DROP CONSTRAINT product_command_receipt_command_kind_check;
ALTER TABLE product_command_receipt ADD CONSTRAINT product_command_receipt_command_kind_check CHECK (command_kind IN ('CREATE_RESEARCH_RUN', 'CANCEL_RESEARCH_RUN', 'FREEZE_STRATEGY', 'PROMOTE_STRATEGY', 'CREATE_BACKTEST_RUN', 'CANCEL_BACKTEST_RUN', 'EVALUATE_QUALIFICATION', 'CREATE_SYMBOLIC_SEARCH_EXPERIMENT', 'CREATE_PARAMETER_SEARCH_EXPERIMENT', 'ADVANCE_SEARCH_EXPERIMENT', 'CREATE_INTEGRATION', 'UPDATE_INTEGRATION_DRAFT', 'SET_INTEGRATION_SECRET', 'CLEAR_INTEGRATION_SECRET', 'RESET_INTEGRATION_DRAFT_CONTRACT', 'PUBLISH_INTEGRATION_REVISION', 'SET_INTEGRATION_LIFECYCLE', 'CREATE_CHART_CALCULATION', 'SAVE_WATCHLISTS', 'SAVE_WORKSPACE'));
ALTER TABLE product_command_receipt DROP CONSTRAINT product_command_receipt_outcome_kind_check;
ALTER TABLE product_command_receipt ADD CONSTRAINT product_command_receipt_outcome_kind_check CHECK (outcome_kind IN ('RESEARCH_RUN', 'STRATEGY', 'STRATEGY_PROMOTION', 'BACKTEST_RUN', 'QUALIFICATION_DECISION', 'SEARCH_EXPERIMENT', 'INTEGRATION', 'INTEGRATION_REVISION', 'CHART_CALCULATION_OPERATION', 'WATCHLIST_REVISION', 'WORKSPACE_REVISION'));
ALTER TABLE product_command_receipt DROP CONSTRAINT product_command_receipt_outcome_id_check;
ALTER TABLE product_command_receipt ADD CONSTRAINT product_command_receipt_outcome_id_check CHECK (
    (outcome_kind IN ('RESEARCH_RUN', 'BACKTEST_RUN', 'INTEGRATION', 'CHART_CALCULATION_OPERATION')
        AND outcome_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')
    OR (outcome_kind IN ('STRATEGY', 'STRATEGY_PROMOTION', 'QUALIFICATION_DECISION', 'SEARCH_EXPERIMENT', 'INTEGRATION_REVISION', 'WATCHLIST_REVISION', 'WORKSPACE_REVISION')
        AND outcome_id ~ '^[0-9a-f]{64}$')
);
CREATE TABLE workspace_revision (
    namespace_id UUID NOT NULL,
    version BIGINT NOT NULL CHECK (version > 0),
    fingerprint TEXT NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    configuration_json JSONB NOT NULL CHECK (jsonb_typeof(configuration_json) = 'object'),
    command_id UUID NOT NULL UNIQUE REFERENCES product_command_receipt(command_id) DEFERRABLE INITIALLY DEFERRED,
    PRIMARY KEY (namespace_id, version),
    UNIQUE (fingerprint)
);
CREATE TABLE workspace_head (
    namespace_id UUID PRIMARY KEY,
    version BIGINT NOT NULL,
    FOREIGN KEY (namespace_id, version) REFERENCES workspace_revision(namespace_id, version)
);
CREATE TRIGGER workspace_revision_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON workspace_revision
    FOR EACH STATEMENT EXECUTE FUNCTION research_source_history_immutable();
