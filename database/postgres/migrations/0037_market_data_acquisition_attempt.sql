-- Durable execution observations for an admitted market-data acquisition.
-- The admitted intent stays the single acquisition truth; attempts only record
-- what execution produced, and never replace canonical Coverage proof.

CREATE TABLE market_data_acquisition_attempt (
    attempt_id TEXT PRIMARY KEY,
    acquisition_id TEXT NOT NULL REFERENCES market_acquisition_intent(acquisition_id),
    outcome TEXT NOT NULL CHECK (outcome IN ('COMPLETE','FAILED')),
    revision_id TEXT REFERENCES market_data_revision(revision_id),
    detail TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    CHECK ((outcome = 'COMPLETE') = (revision_id IS NOT NULL))
);

CREATE TRIGGER market_data_acquisition_attempt_reject_mutation
BEFORE UPDATE OR DELETE ON market_data_acquisition_attempt
FOR EACH ROW EXECUTE FUNCTION onlyalpha_market_data_reject_mutation();
