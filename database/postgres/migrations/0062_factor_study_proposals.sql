ALTER TABLE product_command_admission DROP CONSTRAINT product_command_admission_command_kind_check;
ALTER TABLE product_command_admission ADD CONSTRAINT product_command_admission_command_kind_check CHECK (command_kind IN ('CREATE_PROPOSAL_GRANT', 'REVOKE_PROPOSAL_GRANT', 'STAGE_FACTOR_PROPOSAL', 'CONFIRM_FACTOR_PROPOSAL', 'WITHDRAW_FACTOR_PROPOSAL', 'CREATE_FACTOR_STUDY_GRANT', 'STAGE_FACTOR_STUDY', 'WITHDRAW_FACTOR_STUDY', 'FACTOR_CHAT', 'CREATE_RESEARCH_RUN', 'CANCEL_RESEARCH_RUN', 'FREEZE_STRATEGY', 'PROMOTE_STRATEGY', 'CREATE_BACKTEST_RUN', 'CANCEL_BACKTEST_RUN', 'EVALUATE_QUALIFICATION', 'CREATE_SYMBOLIC_SEARCH_EXPERIMENT', 'CREATE_PARAMETER_SEARCH_EXPERIMENT', 'ADVANCE_SEARCH_EXPERIMENT', 'CREATE_INTEGRATION', 'UPDATE_INTEGRATION_DRAFT', 'SET_INTEGRATION_SECRET', 'CLEAR_INTEGRATION_SECRET', 'RESET_INTEGRATION_DRAFT_CONTRACT', 'PUBLISH_INTEGRATION_REVISION', 'SET_INTEGRATION_LIFECYCLE', 'CREATE_CHART_CALCULATION', 'SAVE_WATCHLISTS', 'SAVE_WORKSPACE', 'SAVE_PRIVATE_FACTOR_DRAFT', 'PUBLISH_PRIVATE_FACTOR_REVISION', 'UPDATE_PRIVATE_FACTOR_DISPLAY'));
ALTER TABLE product_command_receipt DROP CONSTRAINT product_command_receipt_command_kind_check;
ALTER TABLE product_command_receipt ADD CONSTRAINT product_command_receipt_command_kind_check CHECK (command_kind IN ('CREATE_PROPOSAL_GRANT', 'REVOKE_PROPOSAL_GRANT', 'STAGE_FACTOR_PROPOSAL', 'CONFIRM_FACTOR_PROPOSAL', 'WITHDRAW_FACTOR_PROPOSAL', 'CREATE_FACTOR_STUDY_GRANT', 'STAGE_FACTOR_STUDY', 'WITHDRAW_FACTOR_STUDY', 'FACTOR_CHAT', 'CREATE_RESEARCH_RUN', 'CANCEL_RESEARCH_RUN', 'FREEZE_STRATEGY', 'PROMOTE_STRATEGY', 'CREATE_BACKTEST_RUN', 'CANCEL_BACKTEST_RUN', 'EVALUATE_QUALIFICATION', 'CREATE_SYMBOLIC_SEARCH_EXPERIMENT', 'CREATE_PARAMETER_SEARCH_EXPERIMENT', 'ADVANCE_SEARCH_EXPERIMENT', 'CREATE_INTEGRATION', 'UPDATE_INTEGRATION_DRAFT', 'SET_INTEGRATION_SECRET', 'CLEAR_INTEGRATION_SECRET', 'RESET_INTEGRATION_DRAFT_CONTRACT', 'PUBLISH_INTEGRATION_REVISION', 'SET_INTEGRATION_LIFECYCLE', 'CREATE_CHART_CALCULATION', 'SAVE_WATCHLISTS', 'SAVE_WORKSPACE', 'SAVE_PRIVATE_FACTOR_DRAFT', 'PUBLISH_PRIVATE_FACTOR_REVISION', 'UPDATE_PRIVATE_FACTOR_DISPLAY'));
ALTER TABLE product_command_receipt DROP CONSTRAINT product_command_receipt_outcome_kind_check;
ALTER TABLE product_command_receipt ADD CONSTRAINT product_command_receipt_outcome_kind_check CHECK (outcome_kind IN ('RESEARCH_RUN', 'STRATEGY', 'STRATEGY_PROMOTION', 'BACKTEST_RUN', 'QUALIFICATION_DECISION', 'SEARCH_EXPERIMENT', 'INTEGRATION', 'INTEGRATION_REVISION', 'CHART_CALCULATION_OPERATION', 'WATCHLIST_REVISION', 'WORKSPACE_REVISION', 'PRIVATE_FACTOR_AUTHORING', 'FACTOR_CHAT_EVENT', 'FACTOR_PROPOSAL_OPERATION', 'FACTOR_STUDY_OPERATION'));
ALTER TABLE product_command_receipt DROP CONSTRAINT product_command_receipt_outcome_id_check;
ALTER TABLE product_command_receipt ADD CONSTRAINT product_command_receipt_outcome_id_check CHECK (
    (outcome_kind IN ('RESEARCH_RUN', 'BACKTEST_RUN', 'INTEGRATION', 'CHART_CALCULATION_OPERATION')
        AND outcome_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')
    OR (outcome_kind IN ('STRATEGY', 'STRATEGY_PROMOTION', 'QUALIFICATION_DECISION', 'SEARCH_EXPERIMENT', 'INTEGRATION_REVISION', 'WATCHLIST_REVISION', 'WORKSPACE_REVISION', 'PRIVATE_FACTOR_AUTHORING', 'FACTOR_CHAT_EVENT', 'FACTOR_PROPOSAL_OPERATION', 'FACTOR_STUDY_OPERATION')
        AND outcome_id ~ '^[0-9a-f]{64}$')
);


-- Unadmitted study suggestions only. No Research/Generation/Run grant is created.
CREATE TABLE factor_study_grant (
    grant_id UUID PRIMARY KEY,
    fingerprint TEXT UNIQUE NOT NULL CHECK(fingerprint ~ '^[0-9a-f]{64}$'),
    factor_proposal_fingerprint TEXT NOT NULL REFERENCES factor_proposal_snapshot,
    parent_grant_id UUID NOT NULL REFERENCES factor_proposal_grant,
    command_id UUID UNIQUE NOT NULL REFERENCES product_command_receipt DEFERRABLE INITIALLY DEFERRED,
    payload JSONB NOT NULL,
    UNIQUE(factor_proposal_fingerprint,parent_grant_id),
    UNIQUE(grant_id,factor_proposal_fingerprint)
);
CREATE TABLE factor_study_snapshot (
    fingerprint TEXT PRIMARY KEY CHECK(fingerprint ~ '^[0-9a-f]{64}$'),
    factor_proposal_fingerprint TEXT NOT NULL REFERENCES factor_proposal_snapshot,
    study_grant_id UUID NOT NULL,
    command_id UUID UNIQUE NOT NULL REFERENCES product_command_receipt DEFERRABLE INITIALLY DEFERRED,
    session_id UUID NOT NULL,
    event_fingerprint TEXT NOT NULL CHECK(event_fingerprint ~ '^[0-9a-f]{64}$'),
    payload JSONB NOT NULL,
    FOREIGN KEY(study_grant_id,factor_proposal_fingerprint) REFERENCES factor_study_grant(grant_id,factor_proposal_fingerprint),
    UNIQUE(factor_proposal_fingerprint,event_fingerprint),
    UNIQUE(factor_proposal_fingerprint,fingerprint)
);
-- A rebuildable pointer into immutable suggestions, not an independent Study fact.
CREATE TABLE factor_study_head (
    factor_proposal_fingerprint TEXT PRIMARY KEY REFERENCES factor_proposal_snapshot,
    fingerprint TEXT NOT NULL,
    FOREIGN KEY(factor_proposal_fingerprint,fingerprint) REFERENCES factor_study_snapshot(factor_proposal_fingerprint,fingerprint)
);
CREATE TABLE factor_study_operation (
    command_id UUID PRIMARY KEY REFERENCES product_command_receipt DEFERRABLE INITIALLY DEFERRED,
    fingerprint TEXT UNIQUE NOT NULL CHECK(fingerprint ~ '^[0-9a-f]{64}$'),
    payload JSONB NOT NULL
);
CREATE TRIGGER factor_study_grant_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON factor_study_grant FOR EACH STATEMENT EXECUTE FUNCTION private_asset_revision_immutable();
CREATE TRIGGER factor_study_snapshot_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON factor_study_snapshot FOR EACH STATEMENT EXECUTE FUNCTION private_asset_revision_immutable();
CREATE TRIGGER factor_study_operation_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON factor_study_operation FOR EACH STATEMENT EXECUTE FUNCTION private_asset_revision_immutable();
CREATE TABLE factor_study_withdrawal (
    study_proposal_fingerprint TEXT PRIMARY KEY REFERENCES factor_study_snapshot(fingerprint),
    command_id UUID UNIQUE NOT NULL REFERENCES product_command_receipt DEFERRABLE INITIALLY DEFERRED
);
CREATE TRIGGER factor_study_withdrawal_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON factor_study_withdrawal FOR EACH STATEMENT EXECUTE FUNCTION private_asset_revision_immutable();
