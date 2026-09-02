ALTER TABLE product_command_receipt
    DROP CONSTRAINT product_command_receipt_command_kind_check;
ALTER TABLE product_command_receipt
    ADD CONSTRAINT product_command_receipt_command_kind_check CHECK (
        command_kind IN (
            'CREATE_RESEARCH_RUN',
            'CANCEL_RESEARCH_RUN',
            'FREEZE_STRATEGY',
            'PROMOTE_STRATEGY',
            'CREATE_BACKTEST_RUN',
            'CANCEL_BACKTEST_RUN'
        )
    );

ALTER TABLE product_command_receipt
    DROP CONSTRAINT product_command_receipt_outcome_kind_check;
ALTER TABLE product_command_receipt
    ADD CONSTRAINT product_command_receipt_outcome_kind_check CHECK (
        outcome_kind IN ('RESEARCH_RUN', 'STRATEGY', 'STRATEGY_PROMOTION', 'BACKTEST_RUN')
    );

ALTER TABLE product_command_receipt
    DROP CONSTRAINT product_command_receipt_outcome_id_check;
ALTER TABLE product_command_receipt
    ADD CONSTRAINT product_command_receipt_outcome_id_check CHECK (
        (
            outcome_kind IN ('RESEARCH_RUN', 'BACKTEST_RUN')
            AND outcome_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
        )
        OR
        (
            outcome_kind IN ('STRATEGY', 'STRATEGY_PROMOTION')
            AND outcome_id ~ '^[0-9a-f]{64}$'
        )
    );

CREATE TABLE strategy_freeze_command_admission (
    command_id UUID PRIMARY KEY CHECK (
        command_id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    ),
    command_fingerprint TEXT NOT NULL CHECK (command_fingerprint ~ '^[0-9a-f]{64}$'),
    research_run_id UUID NOT NULL REFERENCES research_run (run_id),
    candidate_fingerprint TEXT NOT NULL CHECK (candidate_fingerprint ~ '^[0-9a-f]{64}$'),
    actor TEXT NOT NULL CHECK (btrim(actor) <> ''),
    comment TEXT,
    state TEXT NOT NULL CHECK (state IN ('PREPARED', 'PUBLISHED', 'COMPLETED')),
    strategy_fingerprint TEXT REFERENCES strategy_catalog (strategy_fingerprint),
    freeze_relation_fingerprint TEXT CHECK (freeze_relation_fingerprint ~ '^[0-9a-f]{64}$'),
    prepared_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    schema_version SMALLINT NOT NULL CHECK (schema_version = 1),
    CHECK (
        (state = 'PREPARED' AND strategy_fingerprint IS NULL AND freeze_relation_fingerprint IS NULL
            AND published_at IS NULL AND completed_at IS NULL)
        OR
        (state = 'PUBLISHED' AND strategy_fingerprint IS NOT NULL AND freeze_relation_fingerprint IS NOT NULL
            AND published_at IS NOT NULL AND completed_at IS NULL)
        OR
        (state = 'COMPLETED' AND strategy_fingerprint IS NOT NULL AND freeze_relation_fingerprint IS NOT NULL
            AND published_at IS NOT NULL AND completed_at IS NOT NULL)
    )
);

CREATE TABLE backtest_run (
    run_id UUID PRIMARY KEY CHECK (
        run_id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    ),
    revision BIGINT NOT NULL CHECK (revision >= 0),
    state TEXT NOT NULL CHECK (state IN ('QUEUED', 'RUNNING', 'CANCEL_REQUESTED', 'COMPLETED', 'FAILED', 'CANCELLED')),
    specification_schema_version SMALLINT NOT NULL CHECK (specification_schema_version = 1),
    specification_fingerprint TEXT NOT NULL CHECK (specification_fingerprint ~ '^[0-9a-f]{64}$'),
    specification_payload JSONB NOT NULL,
    admission_resolution_fingerprint TEXT NOT NULL CHECK (admission_resolution_fingerprint ~ '^[0-9a-f]{64}$'),
    queued_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    cancel_requested_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    evidence_fingerprint TEXT CHECK (evidence_fingerprint ~ '^[0-9a-f]{64}$'),
    result_fingerprint TEXT CHECK (result_fingerprint ~ '^[0-9a-f]{64}$'),
    determinism_fingerprint TEXT CHECK (determinism_fingerprint ~ '^[0-9a-f]{64}$'),
    failure_phase TEXT CHECK (failure_phase IN ('ADMISSION', 'EXECUTION', 'EVIDENCE_COMMIT', 'OPERATIONAL')),
    failure_code TEXT,
    failure_detail TEXT,
    CHECK (
        (state = 'QUEUED' AND revision = 0 AND started_at IS NULL AND cancel_requested_at IS NULL
            AND finished_at IS NULL AND evidence_fingerprint IS NULL AND result_fingerprint IS NULL
            AND determinism_fingerprint IS NULL AND failure_phase IS NULL AND failure_code IS NULL AND failure_detail IS NULL)
        OR state <> 'QUEUED'
    ),
    CHECK (
        (
            state IN ('RUNNING', 'CANCEL_REQUESTED', 'COMPLETED', 'FAILED')
            OR (state = 'CANCELLED' AND started_at IS NOT NULL)
        ) = (started_at IS NOT NULL)
    ),
    CHECK ((state = 'CANCEL_REQUESTED') = (cancel_requested_at IS NOT NULL AND finished_at IS NULL)),
    CHECK ((state IN ('COMPLETED', 'FAILED', 'CANCELLED')) = (finished_at IS NOT NULL)),
    CHECK (
        (state = 'COMPLETED' AND evidence_fingerprint IS NOT NULL AND result_fingerprint IS NOT NULL
            AND determinism_fingerprint IS NOT NULL AND failure_phase IS NULL AND failure_code IS NULL AND failure_detail IS NULL)
        OR
        (state = 'FAILED' AND failure_phase IS NOT NULL AND failure_code IS NOT NULL AND failure_detail IS NOT NULL)
        OR
        (state NOT IN ('COMPLETED', 'FAILED') AND evidence_fingerprint IS NULL AND result_fingerprint IS NULL
            AND determinism_fingerprint IS NULL AND failure_phase IS NULL AND failure_code IS NULL AND failure_detail IS NULL)
    )
);

CREATE INDEX backtest_run_queue_idx ON backtest_run (queued_at, run_id) WHERE state = 'QUEUED';
