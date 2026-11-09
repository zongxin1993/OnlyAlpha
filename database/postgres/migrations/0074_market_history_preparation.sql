-- V3 先接纳历史请求，再将同一 attempt 的不可变准备输入绑定到最终 Scope。
ALTER TABLE market_acquisition_intent
    DROP CONSTRAINT market_acquisition_intent_identity_version_check,
    ADD CONSTRAINT market_acquisition_intent_identity_version_check
        CHECK (identity_version IN (1, 2, 3));

CREATE TABLE market_history_preparation_input (
    attempt_id TEXT NOT NULL REFERENCES market_data_acquisition_attempt(attempt_id),
    query_fingerprint TEXT NOT NULL CHECK (query_fingerprint ~ '^[0-9a-f]{64}$'),
    query_document JSONB NOT NULL,
    segment_id TEXT NOT NULL,
    segment_content_hash TEXT NOT NULL,
    raw_event_id TEXT NOT NULL,
    raw_sha256 TEXT NOT NULL CHECK (raw_sha256 ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY (attempt_id, query_fingerprint),
    UNIQUE (segment_id, raw_event_id),
    FOREIGN KEY (segment_id, segment_content_hash)
        REFERENCES market_ingest_segment(segment_id, content_hash)
);

CREATE TABLE market_history_prepared_scope (
    attempt_id TEXT PRIMARY KEY REFERENCES market_data_acquisition_attempt(attempt_id),
    input_manifest JSONB NOT NULL,
    input_fingerprint TEXT NOT NULL CHECK (input_fingerprint ~ '^[0-9a-f]{64}$'),
    requested_scope JSONB NOT NULL
);

CREATE TRIGGER market_history_preparation_input_reject_mutation
BEFORE UPDATE OR DELETE ON market_history_preparation_input
FOR EACH ROW EXECUTE FUNCTION onlyalpha_market_data_reject_mutation();

CREATE TRIGGER market_history_prepared_scope_reject_mutation
BEFORE UPDATE OR DELETE ON market_history_prepared_scope
FOR EACH ROW EXECUTE FUNCTION onlyalpha_market_data_reject_mutation();
