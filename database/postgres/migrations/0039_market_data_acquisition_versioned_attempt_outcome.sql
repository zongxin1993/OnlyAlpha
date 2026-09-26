-- Version historical acquisition identity and split attempt occurrence from outcome.

ALTER TABLE market_acquisition_intent
    ADD COLUMN identity_version SMALLINT NOT NULL DEFAULT 1,
    ADD CONSTRAINT market_acquisition_intent_identity_version_check
        CHECK (identity_version IN (1, 2)),
    ADD CONSTRAINT market_acquisition_intent_v2_binding_check
        CHECK (identity_version = 1 OR integration_binding_fingerprint IS NOT NULL);

ALTER TABLE market_data_acquisition_attempt
    ADD COLUMN identity_version SMALLINT NOT NULL DEFAULT 1;

CREATE TABLE market_data_acquisition_attempt_outcome (
    attempt_id TEXT PRIMARY KEY REFERENCES market_data_acquisition_attempt(attempt_id),
    completed_at TIMESTAMPTZ NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('COMPLETE','FAILED')),
    revision_id TEXT REFERENCES market_data_revision(revision_id),
    detail TEXT NOT NULL,
    CHECK ((outcome = 'COMPLETE') = (revision_id IS NOT NULL))
);

INSERT INTO market_data_acquisition_attempt_outcome
    (attempt_id, completed_at, outcome, revision_id, detail)
SELECT attempt_id, completed_at, outcome, revision_id, detail
FROM market_data_acquisition_attempt;

ALTER TABLE market_data_acquisition_attempt
    ADD CONSTRAINT market_data_acquisition_attempt_identity_version_check
        CHECK (identity_version IN (1, 2)),
    DROP CONSTRAINT market_data_acquisition_attempt_occurrence_check,
    DROP COLUMN completed_at,
    DROP COLUMN outcome,
    DROP COLUMN revision_id,
    DROP COLUMN detail;

CREATE TRIGGER market_data_acquisition_attempt_outcome_reject_mutation
BEFORE UPDATE OR DELETE ON market_data_acquisition_attempt_outcome
FOR EACH ROW EXECUTE FUNCTION onlyalpha_market_data_reject_mutation();

-- Historical rows were populated as V1 above. Future writers must choose the
-- identity domain explicitly; the current Product persistence path writes V2.
ALTER TABLE market_acquisition_intent
    ALTER COLUMN identity_version DROP DEFAULT;
ALTER TABLE market_data_acquisition_attempt
    ALTER COLUMN identity_version DROP DEFAULT;
