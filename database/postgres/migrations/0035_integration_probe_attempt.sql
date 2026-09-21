CREATE TABLE integration_probe_attempt (
    probe_attempt_id UUID PRIMARY KEY,
    integration_id UUID NOT NULL,
    revision_fingerprint TEXT NOT NULL CHECK (revision_fingerprint ~ '^[0-9a-f]{64}$'),
    type_id TEXT NOT NULL CHECK (type_id ~ '^[a-z0-9]+(?:[._][a-z0-9]+)*$'),
    type_descriptor_fingerprint TEXT NOT NULL CHECK (type_descriptor_fingerprint ~ '^[0-9a-f]{64}$'),
    probe_contract_fingerprint TEXT NOT NULL CHECK (probe_contract_fingerprint ~ '^[0-9a-f]{64}$'),
    probe_configuration_fingerprint TEXT NULL CHECK (
        probe_configuration_fingerprint IS NULL OR probe_configuration_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    runtime_configuration_fingerprint TEXT NOT NULL CHECK (
        runtime_configuration_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL CHECK (completed_at >= started_at),
    overall_status TEXT NOT NULL CHECK (overall_status IN ('READY', 'DEGRADED', 'OFFLINE', 'FAILED')),
    result_fingerprint TEXT NOT NULL CHECK (result_fingerprint ~ '^[0-9a-f]{64}$'),
    result_document JSON NOT NULL CHECK (json_typeof(result_document) = 'object'),
    FOREIGN KEY (integration_id, revision_fingerprint)
        REFERENCES integration_revision(integration_id, revision_fingerprint)
);

CREATE INDEX integration_probe_attempt_revision_latest_idx
    ON integration_probe_attempt (integration_id, revision_fingerprint, completed_at DESC, probe_attempt_id DESC);

CREATE FUNCTION integration_probe_attempt_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Integration Probe Attempts are immutable';
END
$$;

CREATE TRIGGER integration_probe_attempt_immutable_trigger
    BEFORE UPDATE OR DELETE OR TRUNCATE ON integration_probe_attempt
    FOR EACH STATEMENT EXECUTE FUNCTION integration_probe_attempt_immutable();
