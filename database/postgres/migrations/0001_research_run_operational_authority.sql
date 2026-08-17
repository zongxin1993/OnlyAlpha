CREATE TABLE onlyalpha_schema_migration (
    migration_id TEXT PRIMARY KEY,
    checksum_sha256 TEXT NOT NULL CHECK (checksum_sha256 ~ '^[0-9a-f]{64}$'),
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE research_run (
    run_id UUID PRIMARY KEY,
    revision BIGINT NOT NULL CHECK (revision >= 0),
    state TEXT NOT NULL CHECK (state IN ('QUEUED', 'RUNNING', 'CANCEL_REQUESTED', 'COMPLETED', 'FAILED', 'CANCELLED')),
    specification_schema_version INTEGER NOT NULL CHECK (specification_schema_version = 1),
    specification_fingerprint TEXT NOT NULL CHECK (specification_fingerprint ~ '^[0-9a-f]{64}$'),
    specification_payload TEXT NOT NULL,
    admission_resolution_fingerprint TEXT NOT NULL CHECK (admission_resolution_fingerprint ~ '^[0-9a-f]{64}$'),
    queued_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    cancel_requested_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    research_result_fingerprint TEXT CHECK (research_result_fingerprint ~ '^[0-9a-f]{64}$'),
    artifact_content_fingerprint TEXT CHECK (artifact_content_fingerprint ~ '^[0-9a-f]{64}$'),
    failure_phase TEXT CHECK (failure_phase IN ('ADMISSION', 'EXECUTION', 'RESULT_COMMIT', 'ARTIFACT_COMMIT', 'OPERATIONAL')),
    failure_code TEXT,
    failure_detail TEXT,
    CONSTRAINT research_run_failure_complete CHECK (
        (failure_phase IS NULL AND failure_code IS NULL AND failure_detail IS NULL)
        OR (failure_phase IS NOT NULL AND failure_code IS NOT NULL AND failure_detail IS NOT NULL)
    ),
    CONSTRAINT research_run_state_facts CHECK (
        (state = 'QUEUED' AND started_at IS NULL AND cancel_requested_at IS NULL AND finished_at IS NULL
            AND research_result_fingerprint IS NULL AND artifact_content_fingerprint IS NULL AND failure_phase IS NULL)
        OR (state = 'RUNNING' AND started_at IS NOT NULL AND finished_at IS NULL AND failure_phase IS NULL)
        OR (state = 'CANCEL_REQUESTED' AND started_at IS NOT NULL AND cancel_requested_at IS NOT NULL
            AND finished_at IS NULL AND failure_phase IS NULL)
        OR (state = 'COMPLETED' AND finished_at IS NOT NULL AND research_result_fingerprint IS NOT NULL
            AND artifact_content_fingerprint IS NOT NULL AND failure_phase IS NULL)
        OR (state = 'FAILED' AND finished_at IS NOT NULL AND failure_phase IS NOT NULL)
        OR (state = 'CANCELLED' AND finished_at IS NOT NULL AND failure_phase IS NULL)
    )
);

CREATE INDEX research_run_queue_order ON research_run (queued_at, run_id) WHERE state = 'QUEUED';
