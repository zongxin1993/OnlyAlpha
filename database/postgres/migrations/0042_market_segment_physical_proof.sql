CREATE TABLE market_segment_physical_proof (
    segment_id TEXT PRIMARY KEY REFERENCES market_ingest_segment(segment_id),
    proof_fingerprint TEXT NOT NULL CHECK (proof_fingerprint ~ '^[0-9a-f]{64}$'),
    proof JSONB NOT NULL
);

CREATE TRIGGER market_segment_physical_proof_reject_mutation
BEFORE UPDATE OR DELETE ON market_segment_physical_proof
FOR EACH ROW EXECUTE FUNCTION onlyalpha_market_data_reject_mutation();
