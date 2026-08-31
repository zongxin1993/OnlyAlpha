ALTER TABLE market_ingest_segment DISABLE TRIGGER market_ingest_segment_reject_mutation;

ALTER TABLE market_ingest_segment
    ADD COLUMN provider TEXT,
    ADD COLUMN venue TEXT,
    ADD COLUMN capture_mode TEXT,
    ADD COLUMN provider_schema TEXT,
    ADD COLUMN codec TEXT,
    ADD COLUMN instrument_id TEXT,
    ADD COLUMN data_kind TEXT,
    ADD COLUMN start_ns BIGINT,
    ADD COLUMN end_ns BIGINT,
    ADD COLUMN data_version TEXT,
    ADD COLUMN bar_type TEXT,
    ADD COLUMN first_sequence BIGINT,
    ADD COLUMN last_sequence BIGINT;

UPDATE market_ingest_segment AS segment
SET provider = source.provider,
    venue = source.venue,
    capture_mode = session.capture_mode,
    provider_schema = session.provider_schema,
    codec = session.codec
FROM market_source AS source, market_capture_session AS session
WHERE source.source_id = segment.source_id
  AND session.capture_session_id = segment.capture_session_id;

UPDATE market_ingest_segment AS segment
SET instrument_id = revision.scope->>'instrument_id',
    data_kind = revision.scope->>'data_kind',
    start_ns = (revision.scope->>'start_ns')::BIGINT,
    end_ns = (revision.scope->>'end_ns')::BIGINT,
    data_version = revision.scope->>'data_version',
    bar_type = revision.scope->>'bar_type',
    first_sequence = (revision.scope->>'first_sequence')::BIGINT,
    last_sequence = (revision.scope->>'last_sequence')::BIGINT
FROM market_revision_segment AS binding
JOIN market_data_revision AS revision ON revision.revision_id = binding.revision_id
WHERE binding.segment_id = segment.segment_id;

ALTER TABLE market_ingest_segment
    ALTER COLUMN provider SET NOT NULL,
    ALTER COLUMN venue SET NOT NULL,
    ALTER COLUMN capture_mode SET NOT NULL,
    ALTER COLUMN provider_schema SET NOT NULL,
    ALTER COLUMN codec SET NOT NULL,
    ADD CONSTRAINT market_ingest_segment_capture_mode_check
        CHECK (capture_mode IN ('REALTIME_STREAM','REST_BACKFILL','REPAIR','REPLAY')),
    ADD CONSTRAINT market_ingest_segment_scope_shape_check CHECK (
        (instrument_id IS NULL AND data_kind IS NULL AND start_ns IS NULL AND end_ns IS NULL AND data_version IS NULL)
        OR
        (instrument_id IS NOT NULL AND data_kind IS NOT NULL AND start_ns IS NOT NULL AND end_ns IS NOT NULL
         AND data_version IS NOT NULL AND start_ns < end_ns)
    ),
    ADD CONSTRAINT market_ingest_segment_sequence_shape_check CHECK (
        (first_sequence IS NULL AND last_sequence IS NULL)
        OR
        (first_sequence IS NOT NULL AND last_sequence IS NOT NULL AND first_sequence <= last_sequence)
    );

ALTER TABLE market_ingest_segment ENABLE TRIGGER market_ingest_segment_reject_mutation;

ALTER TABLE market_segment_state_event DROP CONSTRAINT market_segment_state_event_state_check;
ALTER TABLE market_segment_state_event ADD CONSTRAINT market_segment_state_event_state_check CHECK (
    state IN ('SEALED','STORE_WRITTEN','VERIFIED','COMMITTED','DURABLE_SEGMENT_COMMITTED','GC_ELIGIBLE')
);

ALTER TABLE market_coverage_manifest DISABLE TRIGGER market_coverage_manifest_reject_mutation;
ALTER TABLE market_coverage_manifest
    ADD COLUMN coverage_status TEXT,
    ADD COLUMN gaps JSONB NOT NULL DEFAULT '[]'::JSONB;
UPDATE market_coverage_manifest
SET coverage_status = CASE WHEN complete THEN 'COMPLETE' ELSE 'INCOMPLETE' END;
ALTER TABLE market_coverage_manifest
    ALTER COLUMN coverage_status SET NOT NULL,
    ADD CONSTRAINT market_coverage_manifest_status_check
        CHECK (coverage_status IN ('COMPLETE','INCOMPLETE','UNPROVABLE')),
    ADD CONSTRAINT market_coverage_manifest_complete_projection_check
        CHECK (complete = (coverage_status = 'COMPLETE'));
ALTER TABLE market_coverage_manifest ENABLE TRIGGER market_coverage_manifest_reject_mutation;

CREATE TABLE market_acquisition_intent (
    acquisition_id TEXT PRIMARY KEY,
    request_fingerprint TEXT NOT NULL UNIQUE CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
    source_id TEXT NOT NULL,
    requested_scope JSONB NOT NULL,
    provenance TEXT NOT NULL CHECK (provenance IN ('REALTIME_STREAM','REST_BACKFILL','REPAIR','REPLAY')),
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TRIGGER market_acquisition_intent_reject_mutation
BEFORE UPDATE OR DELETE ON market_acquisition_intent
FOR EACH ROW EXECUTE FUNCTION onlyalpha_market_data_reject_mutation();
