CREATE TABLE private_strategy_research_composition (
    composition_fingerprint TEXT PRIMARY KEY CHECK (composition_fingerprint ~ '^[0-9a-f]{64}$'),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    private_strategy_id TEXT NOT NULL CHECK (private_strategy_id ~ '^private\.strategy\.[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$'),
    private_strategy_revision_fingerprint TEXT NOT NULL CHECK (private_strategy_revision_fingerprint ~ '^[0-9a-f]{64}$'),
    private_strategy_definition_fingerprint TEXT NOT NULL CHECK (private_strategy_definition_fingerprint ~ '^[0-9a-f]{64}$'),
    research_context_fingerprint TEXT NOT NULL CHECK (research_context_fingerprint ~ '^[0-9a-f]{64}$'),
    factor_revision_bindings JSONB NOT NULL CHECK (jsonb_typeof(factor_revision_bindings) = 'array'),
    catalog_generation_fingerprint TEXT NOT NULL CHECK (catalog_generation_fingerprint ~ '^[0-9a-f]{64}$'),
    research_definition_fingerprint TEXT NOT NULL CHECK (research_definition_fingerprint ~ '^[0-9a-f]{64}$'),
    research_context_payload JSONB NOT NULL CHECK (jsonb_typeof(research_context_payload) = 'object'),
    FOREIGN KEY (private_strategy_id, private_strategy_revision_fingerprint)
        REFERENCES private_strategy_revision(strategy_id, revision_fingerprint)
);

CREATE TRIGGER private_strategy_research_composition_immutable_trigger
    BEFORE UPDATE OR DELETE OR TRUNCATE ON private_strategy_research_composition
    FOR EACH STATEMENT EXECUTE FUNCTION private_asset_revision_immutable();

ALTER TABLE research_run
    ADD COLUMN strategy_research_composition_fingerprint TEXT NULL
        REFERENCES private_strategy_research_composition(composition_fingerprint),
    ADD CONSTRAINT research_run_strategy_composition_fingerprint_check CHECK (
        strategy_research_composition_fingerprint IS NULL
        OR strategy_research_composition_fingerprint ~ '^[0-9a-f]{64}$'
    );
