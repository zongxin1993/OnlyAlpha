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
            'CANCEL_BACKTEST_RUN',
            'EVALUATE_QUALIFICATION'
        )
    );

ALTER TABLE product_command_receipt
    DROP CONSTRAINT product_command_receipt_outcome_kind_check;
ALTER TABLE product_command_receipt
    ADD CONSTRAINT product_command_receipt_outcome_kind_check CHECK (
        outcome_kind IN (
            'RESEARCH_RUN',
            'STRATEGY',
            'STRATEGY_PROMOTION',
            'BACKTEST_RUN',
            'QUALIFICATION_DECISION'
        )
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
            outcome_kind IN ('STRATEGY', 'STRATEGY_PROMOTION', 'QUALIFICATION_DECISION')
            AND outcome_id ~ '^[0-9a-f]{64}$'
        )
    );

ALTER TABLE strategy_promotion_record
    ADD COLUMN qualification_decision_fingerprint TEXT
        CHECK (qualification_decision_fingerprint ~ '^[0-9a-f]{64}$');
ALTER TABLE strategy_promotion_record
    DROP CONSTRAINT strategy_promotion_record_schema_version_check;
ALTER TABLE strategy_promotion_record
    ADD CONSTRAINT strategy_promotion_record_schema_version_check CHECK (
        (schema_version = 1 AND qualification_decision_fingerprint IS NULL)
        OR
        (schema_version = 2 AND qualification_decision_fingerprint IS NOT NULL)
    );
ALTER TABLE strategy_promotion_record
    ADD CONSTRAINT strategy_promotion_qualification_evidence_check CHECK (
        qualification_decision_fingerprint IS NULL
        OR qualification_decision_fingerprint = ANY (evidence_fingerprints)
    );

CREATE TABLE qualification_command_admission (
    command_id UUID PRIMARY KEY CHECK (
        command_id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    ),
    command_fingerprint TEXT NOT NULL CHECK (command_fingerprint ~ '^[0-9a-f]{64}$'),
    subject_strategy_fingerprint TEXT NOT NULL REFERENCES strategy_catalog (strategy_fingerprint),
    policy_id TEXT NOT NULL CHECK (btrim(policy_id) <> ''),
    policy_version TEXT NOT NULL CHECK (policy_version ~ '^[1-9][0-9]*$'),
    evidence_payload JSONB NOT NULL CHECK (jsonb_typeof(evidence_payload) = 'array'),
    state TEXT NOT NULL CHECK (state IN ('PREPARED', 'COMPLETED')),
    decision_fingerprint TEXT CHECK (decision_fingerprint ~ '^[0-9a-f]{64}$'),
    prepared_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    schema_version SMALLINT NOT NULL CHECK (schema_version = 1),
    CHECK (
        (state = 'PREPARED' AND decision_fingerprint IS NULL AND completed_at IS NULL)
        OR
        (state = 'COMPLETED' AND decision_fingerprint IS NOT NULL AND completed_at IS NOT NULL)
    )
);

CREATE INDEX qualification_command_subject_idx
    ON qualification_command_admission (subject_strategy_fingerprint);
