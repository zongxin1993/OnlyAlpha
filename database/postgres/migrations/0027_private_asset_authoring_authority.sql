CREATE TABLE private_l3_asset (
    factor_id TEXT PRIMARY KEY CHECK (factor_id ~ '^private\.factor\.[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$'),
    current_revision_fingerprint TEXT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1)
);

CREATE TABLE private_l3_revision (
    revision_fingerprint TEXT PRIMARY KEY CHECK (revision_fingerprint ~ '^[0-9a-f]{64}$'),
    factor_id TEXT NOT NULL REFERENCES private_l3_asset(factor_id),
    parent_revision_fingerprint TEXT NULL,
    source_text TEXT NOT NULL CHECK (source_text <> ''),
    source_sha256 TEXT NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    payload JSONB NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    UNIQUE (factor_id, revision_fingerprint),
    FOREIGN KEY (factor_id, parent_revision_fingerprint)
        REFERENCES private_l3_revision(factor_id, revision_fingerprint)
);

ALTER TABLE private_l3_asset
    ADD CONSTRAINT private_l3_asset_current_revision_fk
    FOREIGN KEY (factor_id, current_revision_fingerprint)
    REFERENCES private_l3_revision(factor_id, revision_fingerprint);

CREATE TABLE private_l3_draft (
    factor_id TEXT PRIMARY KEY REFERENCES private_l3_asset(factor_id),
    base_revision_fingerprint TEXT NULL,
    payload JSONB NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    FOREIGN KEY (factor_id, base_revision_fingerprint)
        REFERENCES private_l3_revision(factor_id, revision_fingerprint)
);

CREATE TABLE private_l4_asset (
    strategy_id TEXT PRIMARY KEY CHECK (strategy_id ~ '^private\.strategy\.[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$'),
    current_revision_fingerprint TEXT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1)
);

CREATE TABLE private_l4_revision (
    revision_fingerprint TEXT PRIMARY KEY CHECK (revision_fingerprint ~ '^[0-9a-f]{64}$'),
    strategy_id TEXT NOT NULL REFERENCES private_l4_asset(strategy_id),
    parent_revision_fingerprint TEXT NULL,
    definition_fingerprint TEXT NOT NULL CHECK (definition_fingerprint ~ '^[0-9a-f]{64}$'),
    payload JSONB NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    UNIQUE (strategy_id, revision_fingerprint),
    FOREIGN KEY (strategy_id, parent_revision_fingerprint)
        REFERENCES private_l4_revision(strategy_id, revision_fingerprint)
);

ALTER TABLE private_l4_asset
    ADD CONSTRAINT private_l4_asset_current_revision_fk
    FOREIGN KEY (strategy_id, current_revision_fingerprint)
    REFERENCES private_l4_revision(strategy_id, revision_fingerprint);

CREATE TABLE private_l4_draft (
    strategy_id TEXT PRIMARY KEY REFERENCES private_l4_asset(strategy_id),
    base_revision_fingerprint TEXT NULL,
    payload JSONB NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    FOREIGN KEY (strategy_id, base_revision_fingerprint)
        REFERENCES private_l4_revision(strategy_id, revision_fingerprint)
);

CREATE FUNCTION private_asset_revision_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Private Asset Revisions are immutable';
END
$$;
CREATE TRIGGER private_l3_revision_immutable_trigger
    BEFORE UPDATE OR DELETE OR TRUNCATE ON private_l3_revision
    FOR EACH STATEMENT EXECUTE FUNCTION private_asset_revision_immutable();
CREATE TRIGGER private_l4_revision_immutable_trigger
    BEFORE UPDATE OR DELETE OR TRUNCATE ON private_l4_revision
    FOR EACH STATEMENT EXECUTE FUNCTION private_asset_revision_immutable();
