DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM backtest_run) THEN
        RAISE EXCEPTION USING
            ERRCODE = 'check_violation',
            MESSAGE = 'A0 admission-resolution migration requires an empty pre-product backtest_run table';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM strategy_freeze_command_admission
        WHERE state = 'PUBLISHED'
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = 'check_violation',
            MESSAGE = 'PUBLISHED freeze admissions require explicit reconciliation before migration';
    END IF;
END
$$;

ALTER TABLE backtest_run
    ADD COLUMN admission_resolution_schema_version SMALLINT NOT NULL CHECK (
        admission_resolution_schema_version = 1
    ),
    ADD COLUMN admission_resolution_payload JSONB NOT NULL;

ALTER TABLE strategy_freeze_command_admission
    DROP CONSTRAINT strategy_freeze_command_admission_state_check;
ALTER TABLE strategy_freeze_command_admission
    ADD CONSTRAINT strategy_freeze_command_admission_state_check CHECK (
        state IN ('PREPARED', 'COMPLETED')
    );
ALTER TABLE strategy_freeze_command_admission
    DROP CONSTRAINT strategy_freeze_command_admission_check;
ALTER TABLE strategy_freeze_command_admission
    ADD CONSTRAINT strategy_freeze_command_admission_check CHECK (
        (state = 'PREPARED' AND strategy_fingerprint IS NULL AND freeze_relation_fingerprint IS NULL
            AND published_at IS NULL AND completed_at IS NULL)
        OR
        (state = 'COMPLETED' AND strategy_fingerprint IS NOT NULL AND freeze_relation_fingerprint IS NOT NULL
            AND published_at IS NOT NULL AND completed_at IS NOT NULL)
    );
