CREATE TABLE backtest_run_attempt (
    attempt_id UUID PRIMARY KEY CHECK (
        attempt_id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    ),
    run_id UUID NOT NULL REFERENCES backtest_run (run_id),
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    state TEXT NOT NULL CHECK (state IN ('ACTIVE', 'SUCCEEDED', 'FAILED', 'EXPIRED', 'CANCELLED')),
    worker_instance_id UUID NOT NULL CHECK (
        worker_instance_id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    ),
    fencing_token BIGINT NOT NULL CHECK (fencing_token > 0),
    claimed_at TIMESTAMPTZ NOT NULL,
    last_heartbeat_at TIMESTAMPTZ NOT NULL,
    lease_expires_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    failure_code TEXT,
    failure_detail TEXT,
    UNIQUE (run_id, attempt_number),
    UNIQUE (run_id, fencing_token),
    CHECK (last_heartbeat_at >= claimed_at),
    CHECK (lease_expires_at >= last_heartbeat_at),
    CHECK (
        (state = 'ACTIVE' AND finished_at IS NULL AND failure_code IS NULL AND failure_detail IS NULL)
        OR
        (state IN ('SUCCEEDED', 'CANCELLED') AND finished_at IS NOT NULL
            AND failure_code IS NULL AND failure_detail IS NULL)
        OR
        (state IN ('FAILED', 'EXPIRED') AND finished_at IS NOT NULL
            AND failure_code IS NOT NULL AND failure_detail IS NOT NULL)
    )
);

CREATE UNIQUE INDEX backtest_one_active_attempt_per_run
    ON backtest_run_attempt (run_id)
    WHERE state = 'ACTIVE';
CREATE INDEX backtest_attempt_expiry_idx
    ON backtest_run_attempt (lease_expires_at, attempt_id)
    WHERE state = 'ACTIVE';
