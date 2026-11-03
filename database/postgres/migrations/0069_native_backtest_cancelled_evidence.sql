-- Preserve every existing Run and its original Evidence interpretation. Only
-- native Specification3/Resolution2 may retain a published CANCELLED prefix.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.backtest_run'::regclass
          AND conname = 'backtest_run_check4'
          AND contype = 'c'
          AND pg_get_constraintdef(oid) = $expected$CHECK ((((state = 'COMPLETED'::text) AND (evidence_fingerprint IS NOT NULL) AND (result_fingerprint IS NOT NULL) AND (determinism_fingerprint IS NOT NULL) AND (failure_phase IS NULL) AND (failure_code IS NULL) AND (failure_detail IS NULL)) OR ((state = 'FAILED'::text) AND (failure_phase IS NOT NULL) AND (failure_code IS NOT NULL) AND (failure_detail IS NOT NULL)) OR ((state <> ALL (ARRAY['COMPLETED'::text, 'FAILED'::text])) AND (evidence_fingerprint IS NULL) AND (result_fingerprint IS NULL) AND (determinism_fingerprint IS NULL) AND (failure_phase IS NULL) AND (failure_code IS NULL) AND (failure_detail IS NULL))))$expected$
    ) THEN
        RAISE EXCEPTION 'NATIVE_BACKTEST_CANCELLED_EVIDENCE_MIGRATION_PRECONDITION';
    END IF;
END $$;

ALTER TABLE public.backtest_run
    DROP CONSTRAINT backtest_run_check4,
    ADD CONSTRAINT backtest_run_check4 CHECK (
        (state = 'COMPLETED' AND evidence_fingerprint IS NOT NULL AND result_fingerprint IS NOT NULL
            AND determinism_fingerprint IS NOT NULL AND failure_phase IS NULL AND failure_code IS NULL AND failure_detail IS NULL)
        OR
        (state = 'FAILED' AND failure_phase IS NOT NULL AND failure_code IS NOT NULL AND failure_detail IS NOT NULL)
        OR
        (state NOT IN ('COMPLETED', 'FAILED') AND failure_phase IS NULL AND failure_code IS NULL AND failure_detail IS NULL
            AND (
                (evidence_fingerprint IS NULL AND result_fingerprint IS NULL AND determinism_fingerprint IS NULL)
                OR
                (state = 'CANCELLED' AND specification_schema_version = 3 AND admission_resolution_schema_version = 2
                    AND started_at IS NOT NULL AND evidence_fingerprint IS NOT NULL AND result_fingerprint IS NOT NULL
                    AND determinism_fingerprint IS NOT NULL)
            ))
    );
