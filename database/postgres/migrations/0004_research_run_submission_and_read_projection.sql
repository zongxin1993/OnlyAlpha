CREATE TABLE research_run_submission (
    submission_key UUID PRIMARY KEY,
    command_fingerprint TEXT NOT NULL CHECK (command_fingerprint ~ '^[0-9a-f]{64}$'),
    run_id UUID NOT NULL UNIQUE REFERENCES research_run(run_id)
);

CREATE INDEX research_run_recent_order
    ON research_run (queued_at DESC, run_id DESC);
