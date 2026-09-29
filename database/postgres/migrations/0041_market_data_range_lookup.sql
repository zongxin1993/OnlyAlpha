-- Exact-family-first lookup for current sealed revision range composition.
-- Values remain mechanically derived from immutable scope JSON; no second truth is writable.
CREATE INDEX market_data_revision_range_family_overlap_idx
ON market_data_revision (
    (scope->>'source_id'),
    (scope->>'market'),
    (scope->>'instrument_id'),
    (scope->>'data_kind'),
    (scope->>'data_version'),
    (scope->>'bar_type'),
    (scope#>>'{bar_construction,fingerprint}'),
    ((scope->>'start_ns')::BIGINT),
    ((scope->>'end_ns')::BIGINT)
);

-- PostgreSQL advisory locks are session-owned and disappear with the session.
-- This immutable mapping makes the 64-bit lock namespace collision-safe for the
-- exact acquisition identity instead of treating a hash as authority.
CREATE TABLE market_acquisition_execution_lock_key (
    lock_key BIGINT PRIMARY KEY,
    acquisition_id TEXT NOT NULL UNIQUE REFERENCES market_acquisition_intent(acquisition_id)
);

CREATE TRIGGER market_acquisition_execution_lock_key_append_only
BEFORE UPDATE OR DELETE ON market_acquisition_execution_lock_key
FOR EACH ROW EXECUTE FUNCTION onlyalpha_market_data_reject_mutation();
