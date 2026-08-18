CREATE TABLE research_run_attempt (
    attempt_id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES research_run(run_id),
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    state TEXT NOT NULL CHECK (state IN ('ACTIVE', 'SUCCEEDED', 'FAILED', 'EXPIRED', 'CANCELLED')),
    worker_instance_id UUID NOT NULL,
    claimed_at TIMESTAMPTZ NOT NULL,
    last_heartbeat_at TIMESTAMPTZ NOT NULL,
    lease_expires_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    failure_phase TEXT CHECK (failure_phase IN ('ADMISSION', 'EXECUTION', 'RESULT_COMMIT', 'ARTIFACT_COMMIT', 'OPERATIONAL')),
    failure_code TEXT,
    failure_detail TEXT,
    CONSTRAINT research_run_attempt_number_unique UNIQUE (run_id, attempt_number),
    CONSTRAINT research_run_attempt_time_order CHECK (
        last_heartbeat_at >= claimed_at
        AND lease_expires_at >= last_heartbeat_at
        AND (finished_at IS NULL OR finished_at >= claimed_at)
    ),
    CONSTRAINT research_run_attempt_failure_complete CHECK (
        (failure_phase IS NULL AND failure_code IS NULL AND failure_detail IS NULL)
        OR (failure_phase IS NOT NULL AND failure_code IS NOT NULL AND failure_detail IS NOT NULL)
    ),
    CONSTRAINT research_run_attempt_state_facts CHECK (
        (state = 'ACTIVE' AND finished_at IS NULL AND failure_phase IS NULL)
        OR (state IN ('SUCCEEDED', 'CANCELLED') AND finished_at IS NOT NULL AND failure_phase IS NULL)
        OR (state IN ('FAILED', 'EXPIRED') AND finished_at IS NOT NULL AND failure_phase IS NOT NULL)
    )
);

CREATE UNIQUE INDEX research_run_attempt_one_active
    ON research_run_attempt (run_id)
    WHERE state = 'ACTIVE';

CREATE INDEX research_run_attempt_expiry
    ON research_run_attempt (lease_expires_at, run_id, attempt_id)
    WHERE state = 'ACTIVE';

CREATE INDEX research_run_attempt_history
    ON research_run_attempt (run_id, attempt_number);

CREATE INDEX research_run_execution_order
    ON research_run (queued_at, run_id)
    WHERE state IN ('QUEUED', 'RUNNING');
