ALTER TABLE market_raw_event
    ADD COLUMN IF NOT EXISTS integration_binding_fingerprint Nullable(String) AFTER provider_schema;
