CREATE TABLE product_command_receipt (
    command_id UUID PRIMARY KEY CHECK (
        command_id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    ),
    command_kind TEXT NOT NULL CHECK (
        command_kind IN ('CREATE_RESEARCH_RUN', 'CANCEL_RESEARCH_RUN')
    ),
    command_fingerprint TEXT NOT NULL CHECK (command_fingerprint ~ '^[0-9a-f]{64}$'),
    outcome_kind TEXT NOT NULL CHECK (outcome_kind = 'RESEARCH_RUN'),
    outcome_id TEXT NOT NULL CHECK (
        outcome_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    ),
    accepted_at TIMESTAMPTZ NOT NULL,
    schema_version SMALLINT NOT NULL CHECK (schema_version = 1)
);

INSERT INTO product_command_receipt (
    command_id,
    command_kind,
    command_fingerprint,
    outcome_kind,
    outcome_id,
    accepted_at,
    schema_version
)
SELECT
    submission.submission_key,
    'CREATE_RESEARCH_RUN',
    submission.command_fingerprint,
    'RESEARCH_RUN',
    submission.run_id::text,
    run.queued_at,
    1
FROM research_run_submission AS submission
JOIN research_run AS run ON run.run_id = submission.run_id
ORDER BY submission.submission_key;

DO $$
BEGIN
    IF (SELECT count(*) FROM product_command_receipt)
        <> (SELECT count(*) FROM research_run_submission) THEN
        RAISE EXCEPTION 'Product Command Receipt backfill is incomplete';
    END IF;
END
$$;

DROP TABLE research_run_submission;
