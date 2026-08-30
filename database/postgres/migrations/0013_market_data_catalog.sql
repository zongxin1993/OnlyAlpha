CREATE TABLE market_source (
    source_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    venue TEXT NOT NULL,
    market TEXT NOT NULL,
    schema_version SMALLINT NOT NULL CHECK (schema_version = 1)
);

CREATE TABLE market_capture_session (
    capture_session_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES market_source(source_id),
    capture_mode TEXT NOT NULL CHECK (capture_mode IN ('REALTIME_STREAM','REST_BACKFILL','REPAIR','REPLAY')),
    provider_schema TEXT NOT NULL,
    codec TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    CHECK (ended_at IS NULL OR ended_at >= started_at)
);

CREATE TABLE market_ingest_segment (
    segment_id TEXT PRIMARY KEY,
    capture_session_id TEXT NOT NULL REFERENCES market_capture_session(capture_session_id),
    source_id TEXT NOT NULL REFERENCES market_source(source_id),
    market TEXT NOT NULL,
    stream TEXT NOT NULL,
    schema_version SMALLINT NOT NULL CHECK (schema_version = 1),
    record_count BIGINT NOT NULL CHECK (record_count > 0),
    raw_count BIGINT NOT NULL CHECK (raw_count > 0),
    canonical_count BIGINT NOT NULL CHECK (canonical_count >= 0),
    content_hash TEXT NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL,
    sealed_at TIMESTAMPTZ NOT NULL,
    UNIQUE (segment_id, content_hash),
    CHECK (sealed_at >= created_at)
);

CREATE TABLE market_segment_state_event (
    event_id TEXT PRIMARY KEY,
    segment_id TEXT NOT NULL REFERENCES market_ingest_segment(segment_id),
    state TEXT NOT NULL CHECK (state IN ('SEALED','STORE_WRITTEN','VERIFIED','COMMITTED','GC_ELIGIBLE')),
    occurred_at TIMESTAMPTZ NOT NULL,
    detail JSONB NOT NULL,
    UNIQUE (segment_id, state)
);

CREATE TABLE market_coverage_manifest (
    manifest_id TEXT PRIMARY KEY,
    manifest_fingerprint TEXT NOT NULL UNIQUE CHECK (manifest_fingerprint ~ '^[0-9a-f]{64}$'),
    scope JSONB NOT NULL,
    complete BOOLEAN NOT NULL,
    proof JSONB NOT NULL,
    issues JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CHECK (complete OR jsonb_array_length(issues) > 0)
);

CREATE TABLE market_coverage_manifest_segment (
    manifest_id TEXT NOT NULL REFERENCES market_coverage_manifest(manifest_id),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    segment_id TEXT NOT NULL,
    segment_content_hash TEXT NOT NULL,
    PRIMARY KEY (manifest_id, ordinal),
    UNIQUE (manifest_id, segment_id),
    FOREIGN KEY (segment_id, segment_content_hash)
        REFERENCES market_ingest_segment(segment_id, content_hash)
);

CREATE TABLE market_data_revision (
    revision_id TEXT PRIMARY KEY,
    revision_fingerprint TEXT NOT NULL UNIQUE CHECK (revision_fingerprint ~ '^[0-9a-f]{64}$'),
    manifest_id TEXT NOT NULL UNIQUE REFERENCES market_coverage_manifest(manifest_id),
    scope JSONB NOT NULL,
    parent_revision_id TEXT REFERENCES market_data_revision(revision_id),
    normalizers JSONB NOT NULL,
    creation_reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE market_revision_segment (
    revision_id TEXT NOT NULL REFERENCES market_data_revision(revision_id),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    segment_id TEXT NOT NULL,
    segment_content_hash TEXT NOT NULL,
    PRIMARY KEY (revision_id, ordinal),
    UNIQUE (revision_id, segment_id),
    FOREIGN KEY (segment_id, segment_content_hash)
        REFERENCES market_ingest_segment(segment_id, content_hash)
);

CREATE TABLE market_revision_seal (
    seal_id TEXT PRIMARY KEY,
    revision_id TEXT NOT NULL UNIQUE REFERENCES market_data_revision(revision_id),
    revision_fingerprint TEXT NOT NULL,
    checks JSONB NOT NULL,
    sealed_at TIMESTAMPTZ NOT NULL,
    CHECK (jsonb_array_length(checks) > 0)
);

ALTER TABLE market_data_revision
    ADD CONSTRAINT market_data_revision_identity_unique UNIQUE (revision_id, revision_fingerprint);

ALTER TABLE market_revision_seal
    ADD CONSTRAINT market_revision_seal_revision_identity_fk
    FOREIGN KEY (revision_id, revision_fingerprint)
    REFERENCES market_data_revision(revision_id, revision_fingerprint);

CREATE TABLE market_recovery_event (
    recovery_event_id TEXT PRIMARY KEY,
    segment_id TEXT REFERENCES market_ingest_segment(segment_id),
    crash_boundary TEXT NOT NULL,
    outcome TEXT NOT NULL,
    detail JSONB NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL
);

CREATE FUNCTION onlyalpha_market_data_reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'market-data catalog history is append-only';
END;
$$;

DO $$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'market_source', 'market_capture_session', 'market_ingest_segment',
        'market_segment_state_event', 'market_coverage_manifest',
        'market_coverage_manifest_segment', 'market_data_revision', 'market_revision_segment',
        'market_revision_seal', 'market_recovery_event'
    ] LOOP
        EXECUTE format(
            'CREATE TRIGGER %I_reject_mutation BEFORE UPDATE OR DELETE ON %I '
            'FOR EACH ROW EXECUTE FUNCTION onlyalpha_market_data_reject_mutation()',
            table_name, table_name
        );
    END LOOP;
END;
$$;

CREATE VIEW market_latest_sealed_revision AS
SELECT DISTINCT ON (revision.scope)
    revision.revision_id,
    revision.revision_fingerprint,
    revision.scope,
    seal.sealed_at
FROM market_data_revision AS revision
JOIN market_revision_seal AS seal ON seal.revision_id = revision.revision_id
ORDER BY revision.scope, seal.sealed_at DESC, revision.revision_id DESC;
