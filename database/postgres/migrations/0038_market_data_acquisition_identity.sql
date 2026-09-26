-- Market Data acquisition execution identity.
--
-- Two separate authorites are tightened here, without rewriting historical rows:
--
-- 1. The admitted acquisition intent owns one execution intent per exact
--    (market source, requested scope, provenance, Integration runtime binding).
--    `admitted_at` is the observation timestamp of the first admission, so an exact
--    re-entry preserves the original value instead of conflicting on a retry time.
--    Intent rows written before the runtime binding became part of that identity keep
--    their historical content; they are not rewritten and are not re-enterable under
--    the new identity domain.
-- 2. Every execution occurrence under one admitted intent is independently
--    append-only, identified by a monotonic `attempt_number` per acquisition.

ALTER TABLE market_acquisition_intent RENAME COLUMN created_at TO admitted_at;

ALTER TABLE market_data_acquisition_attempt
    ADD COLUMN attempt_number INTEGER,
    ADD COLUMN started_at TIMESTAMPTZ,
    ADD COLUMN completed_at TIMESTAMPTZ;

DROP TRIGGER market_data_acquisition_attempt_reject_mutation ON market_data_acquisition_attempt;

UPDATE market_data_acquisition_attempt AS attempt
SET attempt_number = numbered.ordinal,
    started_at = attempt.recorded_at,
    completed_at = attempt.recorded_at
FROM (
    SELECT attempt_id,
           ROW_NUMBER() OVER (PARTITION BY acquisition_id ORDER BY recorded_at, attempt_id) AS ordinal
    FROM market_data_acquisition_attempt
) AS numbered
WHERE attempt.attempt_id = numbered.attempt_id;

ALTER TABLE market_data_acquisition_attempt
    ALTER COLUMN attempt_number SET NOT NULL,
    ALTER COLUMN started_at SET NOT NULL,
    ALTER COLUMN completed_at SET NOT NULL,
    ADD CONSTRAINT market_data_acquisition_attempt_number_check CHECK (attempt_number >= 1),
    ADD CONSTRAINT market_data_acquisition_attempt_occurrence_check CHECK (started_at <= completed_at),
    ADD CONSTRAINT market_data_acquisition_attempt_occurrence_unique UNIQUE (acquisition_id, attempt_number),
    DROP COLUMN recorded_at;

CREATE TRIGGER market_data_acquisition_attempt_reject_mutation
BEFORE UPDATE OR DELETE ON market_data_acquisition_attempt
FOR EACH ROW EXECUTE FUNCTION onlyalpha_market_data_reject_mutation();
