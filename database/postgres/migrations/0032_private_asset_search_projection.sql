CREATE TABLE private_asset_search_projection_revision (
    projection_fingerprint TEXT PRIMARY KEY CHECK (projection_fingerprint ~ '^[0-9a-f]{64}$'),
    registry_fingerprint TEXT NOT NULL CHECK (registry_fingerprint ~ '^[0-9a-f]{64}$'),
    completeness TEXT NOT NULL CHECK (completeness IN ('CERTIFIED_COMPLETE', 'INCOMPLETE')),
    payload JSONB NOT NULL,
    built_at TIMESTAMPTZ NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1)
);

CREATE TABLE private_asset_search_projection_active (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    projection_fingerprint TEXT NOT NULL REFERENCES private_asset_search_projection_revision(projection_fingerprint)
        ON DELETE CASCADE
);

CREATE FUNCTION private_asset_search_projection_revision_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Private Asset Search Projection Revisions are immutable';
END
$$;

CREATE TRIGGER private_asset_search_projection_revision_immutable_trigger
    BEFORE UPDATE ON private_asset_search_projection_revision
    FOR EACH STATEMENT EXECUTE FUNCTION private_asset_search_projection_revision_immutable();
