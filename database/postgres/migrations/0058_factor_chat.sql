ALTER TABLE product_command_admission DROP CONSTRAINT product_command_admission_command_kind_check;
ALTER TABLE product_command_admission ADD CONSTRAINT product_command_admission_command_kind_check CHECK (command_kind IN ('FACTOR_CHAT', 'CREATE_RESEARCH_RUN', 'CANCEL_RESEARCH_RUN', 'FREEZE_STRATEGY', 'PROMOTE_STRATEGY', 'CREATE_BACKTEST_RUN', 'CANCEL_BACKTEST_RUN', 'EVALUATE_QUALIFICATION', 'CREATE_SYMBOLIC_SEARCH_EXPERIMENT', 'CREATE_PARAMETER_SEARCH_EXPERIMENT', 'ADVANCE_SEARCH_EXPERIMENT', 'CREATE_INTEGRATION', 'UPDATE_INTEGRATION_DRAFT', 'SET_INTEGRATION_SECRET', 'CLEAR_INTEGRATION_SECRET', 'RESET_INTEGRATION_DRAFT_CONTRACT', 'PUBLISH_INTEGRATION_REVISION', 'SET_INTEGRATION_LIFECYCLE', 'CREATE_CHART_CALCULATION', 'SAVE_WATCHLISTS', 'SAVE_WORKSPACE', 'SAVE_PRIVATE_FACTOR_DRAFT', 'PUBLISH_PRIVATE_FACTOR_REVISION', 'UPDATE_PRIVATE_FACTOR_DISPLAY'));
ALTER TABLE product_command_receipt DROP CONSTRAINT product_command_receipt_command_kind_check;
ALTER TABLE product_command_receipt ADD CONSTRAINT product_command_receipt_command_kind_check CHECK (command_kind IN ('FACTOR_CHAT', 'CREATE_RESEARCH_RUN', 'CANCEL_RESEARCH_RUN', 'FREEZE_STRATEGY', 'PROMOTE_STRATEGY', 'CREATE_BACKTEST_RUN', 'CANCEL_BACKTEST_RUN', 'EVALUATE_QUALIFICATION', 'CREATE_SYMBOLIC_SEARCH_EXPERIMENT', 'CREATE_PARAMETER_SEARCH_EXPERIMENT', 'ADVANCE_SEARCH_EXPERIMENT', 'CREATE_INTEGRATION', 'UPDATE_INTEGRATION_DRAFT', 'SET_INTEGRATION_SECRET', 'CLEAR_INTEGRATION_SECRET', 'RESET_INTEGRATION_DRAFT_CONTRACT', 'PUBLISH_INTEGRATION_REVISION', 'SET_INTEGRATION_LIFECYCLE', 'CREATE_CHART_CALCULATION', 'SAVE_WATCHLISTS', 'SAVE_WORKSPACE', 'SAVE_PRIVATE_FACTOR_DRAFT', 'PUBLISH_PRIVATE_FACTOR_REVISION', 'UPDATE_PRIVATE_FACTOR_DISPLAY'));
ALTER TABLE product_command_receipt DROP CONSTRAINT product_command_receipt_outcome_kind_check;
ALTER TABLE product_command_receipt ADD CONSTRAINT product_command_receipt_outcome_kind_check CHECK (outcome_kind IN ('RESEARCH_RUN', 'STRATEGY', 'STRATEGY_PROMOTION', 'BACKTEST_RUN', 'QUALIFICATION_DECISION', 'SEARCH_EXPERIMENT', 'INTEGRATION', 'INTEGRATION_REVISION', 'CHART_CALCULATION_OPERATION', 'WATCHLIST_REVISION', 'WORKSPACE_REVISION', 'PRIVATE_FACTOR_AUTHORING', 'FACTOR_CHAT_EVENT'));
ALTER TABLE product_command_receipt DROP CONSTRAINT product_command_receipt_outcome_id_check;
ALTER TABLE product_command_receipt ADD CONSTRAINT product_command_receipt_outcome_id_check CHECK (
    (outcome_kind IN ('RESEARCH_RUN', 'BACKTEST_RUN', 'INTEGRATION', 'CHART_CALCULATION_OPERATION')
        AND outcome_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')
    OR (outcome_kind IN ('STRATEGY', 'STRATEGY_PROMOTION', 'QUALIFICATION_DECISION', 'SEARCH_EXPERIMENT', 'INTEGRATION_REVISION', 'WATCHLIST_REVISION', 'WORKSPACE_REVISION', 'PRIVATE_FACTOR_AUTHORING', 'FACTOR_CHAT_EVENT')
        AND outcome_id ~ '^[0-9a-f]{64}$')
);

-- Conversational authoring provenance; Factor content remains in the existing Authoring Authority.
CREATE TABLE factor_chat_conversation (
 conversation_id UUID PRIMARY KEY,
 owner_id TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE factor_chat_event (
 conversation_id UUID NOT NULL REFERENCES factor_chat_conversation,
 ordinal INTEGER NOT NULL CHECK (ordinal BETWEEN 1 AND 101),
 command_id UUID NOT NULL UNIQUE REFERENCES product_command_receipt(command_id) DEFERRABLE INITIALLY DEFERRED,
 fingerprint TEXT NOT NULL UNIQUE CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
 payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object'),
 PRIMARY KEY(conversation_id,ordinal)
);
CREATE TABLE factor_chat_model_result (
 event_fingerprint TEXT PRIMARY KEY REFERENCES factor_chat_event(fingerprint),
 fingerprint TEXT NOT NULL CHECK(fingerprint ~ '^[0-9a-f]{64}$'),
 payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object')
);
CREATE TRIGGER factor_chat_event_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON factor_chat_event
 FOR EACH STATEMENT EXECUTE FUNCTION private_asset_revision_immutable();
CREATE TRIGGER factor_chat_model_result_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON factor_chat_model_result
 FOR EACH STATEMENT EXECUTE FUNCTION private_asset_revision_immutable();

-- Original Command's explicit no-effect outcome. Does not require a conversation to have been created.
CREATE TABLE factor_chat_abandonment (
 command_id UUID PRIMARY KEY REFERENCES product_command_receipt(command_id) DEFERRABLE INITIALLY DEFERRED,
 fingerprint TEXT NOT NULL UNIQUE CHECK(fingerprint ~ '^[0-9a-f]{64}$'),
 payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object')
);
CREATE TRIGGER factor_chat_abandonment_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON factor_chat_abandonment
 FOR EACH STATEMENT EXECUTE FUNCTION private_asset_revision_immutable();
