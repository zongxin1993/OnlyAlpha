-- Allow the current native Product specification without changing stored facts.
-- Migration authority applies DDL and its checksum ledger in one transaction.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.backtest_run'::regclass
          AND conname = 'backtest_run_specification_schema_version_check'
          AND pg_get_constraintdef(oid) = 'CHECK ((specification_schema_version = 1))'
    ) THEN
        RAISE EXCEPTION 'BACKTEST_SPECIFICATION_MIGRATION_PRECONDITION';
    END IF;
END $$;
ALTER TABLE backtest_run
    DROP CONSTRAINT backtest_run_specification_schema_version_check,
    ADD CONSTRAINT backtest_run_specification_schema_version_check
        CHECK (specification_schema_version IN (1, 2));
