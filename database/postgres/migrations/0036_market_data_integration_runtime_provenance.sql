-- Exact Integration runtime binding provenance for durable market-data evidence.
-- Nullable on purpose: rows written before this authority existed stay verifiable
-- and are never rewritten. Canonical market facts keep provider/source identity.

ALTER TABLE market_ingest_segment
    ADD COLUMN integration_binding_fingerprint TEXT,
    ADD CONSTRAINT market_ingest_segment_binding_fingerprint_check
        CHECK (
            integration_binding_fingerprint IS NULL
            OR integration_binding_fingerprint ~ '^[0-9a-f]{64}$'
        );

ALTER TABLE market_acquisition_intent
    ADD COLUMN integration_binding_fingerprint TEXT,
    ADD CONSTRAINT market_acquisition_intent_binding_fingerprint_check
        CHECK (
            integration_binding_fingerprint IS NULL
            OR integration_binding_fingerprint ~ '^[0-9a-f]{64}$'
        );
