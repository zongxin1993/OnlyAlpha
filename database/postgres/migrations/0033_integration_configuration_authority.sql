DO $$
BEGIN
    IF EXISTS (SELECT FROM product_credential LIMIT 1) THEN
        RAISE EXCEPTION 'Credential identity migration requires an empty development credential table';
    END IF;
END
$$;

ALTER TABLE product_credential RENAME COLUMN provider_id TO subject_id;
ALTER TABLE product_credential
    RENAME CONSTRAINT product_credential_provider_id_check TO product_credential_subject_id_check;
ALTER TABLE product_credential
    DROP CONSTRAINT product_credential_credential_kind_provider_id_key;
ALTER TABLE product_credential
    ADD COLUMN secret_name TEXT NOT NULL CHECK (secret_name ~ '^[a-z][a-z0-9_]*$'),
    ADD COLUMN generation INTEGER NOT NULL CHECK (generation >= 1),
    ADD CONSTRAINT product_credential_updated_at_order CHECK (updated_at >= created_at),
    ADD CONSTRAINT product_credential_slot_key UNIQUE (credential_kind, subject_id, secret_name);

CREATE TABLE integration (
    integration_id UUID PRIMARY KEY,
    type_id TEXT NOT NULL CHECK (
        type_id ~ '^[a-z0-9]+(?:[._][a-z0-9]+)*$'
        AND type_id !~ '(^|[._])latest($|[._])'
    ),
    display_name TEXT NOT NULL CHECK (btrim(display_name) <> ''),
    lifecycle_state TEXT NOT NULL CHECK (lifecycle_state IN ('ACTIVE', 'DISABLED', 'ARCHIVED')),
    current_revision_fingerprint TEXT NULL CHECK (
        current_revision_fingerprint IS NULL OR current_revision_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL CHECK (updated_at >= created_at),
    UNIQUE (integration_id, current_revision_fingerprint)
);

CREATE TABLE integration_revision (
    revision_fingerprint TEXT PRIMARY KEY CHECK (revision_fingerprint ~ '^[0-9a-f]{64}$'),
    integration_id UUID NOT NULL REFERENCES integration(integration_id),
    revision_sequence INTEGER NOT NULL CHECK (revision_sequence > 0),
    type_id TEXT NOT NULL CHECK (type_id ~ '^[a-z0-9]+(?:[._][a-z0-9]+)*$'),
    type_descriptor_fingerprint TEXT NOT NULL CHECK (type_descriptor_fingerprint ~ '^[0-9a-f]{64}$'),
    type_descriptor_document JSON NOT NULL CHECK (json_typeof(type_descriptor_document) = 'object'),
    configuration_fingerprint TEXT NOT NULL CHECK (configuration_fingerprint ~ '^[0-9a-f]{64}$'),
    configuration_document JSON NOT NULL CHECK (json_typeof(configuration_document) = 'object'),
    runtime_configuration_fingerprint TEXT NOT NULL CHECK (runtime_configuration_fingerprint ~ '^[0-9a-f]{64}$'),
    probe_configuration_fingerprint TEXT NULL CHECK (
        probe_configuration_fingerprint IS NULL OR probe_configuration_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    probe_configuration_document JSON NULL CHECK (
        probe_configuration_document IS NULL OR json_typeof(probe_configuration_document) = 'object'
    ),
    secret_binding_fingerprint TEXT NOT NULL CHECK (secret_binding_fingerprint ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (integration_id, revision_sequence),
    UNIQUE (integration_id, revision_fingerprint),
    CHECK ((probe_configuration_fingerprint IS NULL) = (probe_configuration_document IS NULL))
);

ALTER TABLE integration
    ADD CONSTRAINT integration_current_revision_fk
    FOREIGN KEY (integration_id, current_revision_fingerprint)
    REFERENCES integration_revision(integration_id, revision_fingerprint);

CREATE TABLE integration_draft (
    integration_id UUID PRIMARY KEY REFERENCES integration(integration_id),
    base_revision_fingerprint TEXT NULL CHECK (
        base_revision_fingerprint IS NULL OR base_revision_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    type_descriptor_fingerprint TEXT NOT NULL CHECK (type_descriptor_fingerprint ~ '^[0-9a-f]{64}$'),
    type_descriptor_document JSON NOT NULL CHECK (json_typeof(type_descriptor_document) = 'object'),
    public_configuration_document JSON NOT NULL CHECK (json_typeof(public_configuration_document) = 'object'),
    probe_configuration_document JSON NULL CHECK (
        probe_configuration_document IS NULL OR json_typeof(probe_configuration_document) = 'object'
    ),
    draft_version INTEGER NOT NULL CHECK (draft_version >= 1),
    draft_fingerprint TEXT NOT NULL CHECK (draft_fingerprint ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL CHECK (updated_at >= created_at),
    FOREIGN KEY (integration_id, base_revision_fingerprint)
        REFERENCES integration_revision(integration_id, revision_fingerprint)
);

CREATE TABLE integration_draft_secret_binding (
    integration_id UUID NOT NULL REFERENCES integration_draft(integration_id),
    field_id TEXT NOT NULL CHECK (field_id ~ '^[a-z][a-z0-9_]*$'),
    credential_id UUID NOT NULL REFERENCES product_credential(credential_id),
    credential_generation INTEGER NOT NULL CHECK (credential_generation >= 1),
    PRIMARY KEY (integration_id, field_id)
);

CREATE TABLE integration_revision_secret_binding (
    revision_fingerprint TEXT NOT NULL REFERENCES integration_revision(revision_fingerprint),
    field_id TEXT NOT NULL CHECK (field_id ~ '^[a-z][a-z0-9_]*$'),
    credential_id UUID NOT NULL REFERENCES product_credential(credential_id),
    credential_generation INTEGER NOT NULL CHECK (credential_generation >= 1),
    PRIMARY KEY (revision_fingerprint, field_id)
);

CREATE FUNCTION integration_type_id_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.type_id <> OLD.type_id THEN
        RAISE EXCEPTION 'Integration type_id is immutable';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER integration_type_id_immutable_trigger
    BEFORE UPDATE ON integration
    FOR EACH ROW EXECUTE FUNCTION integration_type_id_immutable();

CREATE FUNCTION integration_revision_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Integration Revisions and published secret bindings are immutable';
END
$$;

CREATE TRIGGER integration_revision_immutable_trigger
    BEFORE UPDATE OR DELETE OR TRUNCATE ON integration_revision
    FOR EACH STATEMENT EXECUTE FUNCTION integration_revision_immutable();

CREATE TRIGGER integration_revision_secret_binding_immutable_trigger
    BEFORE UPDATE OR DELETE OR TRUNCATE ON integration_revision_secret_binding
    FOR EACH STATEMENT EXECUTE FUNCTION integration_revision_immutable();
