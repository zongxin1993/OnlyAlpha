-- Current named workspace library, separate from immutable historical default-workspace records.
CREATE TABLE workspace_library_revision (
    namespace_id UUID NOT NULL,
    version BIGINT NOT NULL CHECK (version > 0),
    fingerprint TEXT NOT NULL UNIQUE CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    library_json JSONB NOT NULL CHECK (jsonb_typeof(library_json) = 'object'),
    command_id UUID NOT NULL UNIQUE REFERENCES product_command_receipt(command_id) DEFERRABLE INITIALLY DEFERRED,
    PRIMARY KEY (namespace_id, version)
);
CREATE TABLE workspace_library_head (
    namespace_id UUID PRIMARY KEY,
    version BIGINT NOT NULL,
    FOREIGN KEY (namespace_id, version) REFERENCES workspace_library_revision(namespace_id, version)
);
CREATE TRIGGER workspace_library_revision_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON workspace_library_revision
    FOR EACH STATEMENT EXECUTE FUNCTION research_source_history_immutable();
