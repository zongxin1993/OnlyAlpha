CREATE TABLE product_command_admission (
    command_id UUID PRIMARY KEY CHECK (
        command_id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    ),
    command_kind TEXT NOT NULL CHECK (
        command_kind IN (
            'CREATE_RESEARCH_RUN',
            'CANCEL_RESEARCH_RUN',
            'FREEZE_STRATEGY',
            'PROMOTE_STRATEGY',
            'CREATE_BACKTEST_RUN',
            'CANCEL_BACKTEST_RUN',
            'EVALUATE_QUALIFICATION',
            'CREATE_SYMBOLIC_SEARCH_EXPERIMENT',
            'CREATE_PARAMETER_SEARCH_EXPERIMENT',
            'ADVANCE_SEARCH_EXPERIMENT'
        )
    ),
    command_fingerprint TEXT NOT NULL CHECK (command_fingerprint ~ '^[0-9a-f]{64}$'),
    schema_version SMALLINT NOT NULL CHECK (schema_version = 1),
    CONSTRAINT product_command_admission_exact_identity_key UNIQUE (
        command_id,
        command_kind,
        command_fingerprint
    )
);

INSERT INTO product_command_admission (
    command_id,
    command_kind,
    command_fingerprint,
    schema_version
)
SELECT
    command_id,
    command_kind,
    command_fingerprint,
    1
FROM product_command_receipt
ORDER BY command_id;

DO $$
BEGIN
    IF (SELECT count(*) FROM product_command_admission)
        <> (SELECT count(*) FROM product_command_receipt) THEN
        RAISE EXCEPTION 'Product Command Admission backfill count is incomplete';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM product_command_receipt AS receipt
        LEFT JOIN product_command_admission AS admission
          ON admission.command_id = receipt.command_id
         AND admission.command_kind = receipt.command_kind
         AND admission.command_fingerprint = receipt.command_fingerprint
        WHERE admission.command_id IS NULL
    ) THEN
        RAISE EXCEPTION 'Product Command Admission backfill integrity verification failed';
    END IF;
END
$$;

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
            'EVALUATE_QUALIFICATION',
            'CREATE_SYMBOLIC_SEARCH_EXPERIMENT',
            'CREATE_PARAMETER_SEARCH_EXPERIMENT',
            'ADVANCE_SEARCH_EXPERIMENT'
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
            'QUALIFICATION_DECISION',
            'SEARCH_EXPERIMENT'
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
            outcome_kind IN ('STRATEGY', 'STRATEGY_PROMOTION', 'QUALIFICATION_DECISION', 'SEARCH_EXPERIMENT')
            AND outcome_id ~ '^[0-9a-f]{64}$'
        )
    );
