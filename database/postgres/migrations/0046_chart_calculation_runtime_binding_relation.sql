-- Precondition: canonical checksummed history through 0045. Existing facts are unchanged.
-- Failure decisions are durable fences against semantic progress during Runtime closure.
-- DDL + migration ledger commit atomically; interruption rolls back and retry is deterministic.
-- Rollback: disable new preparation writers, retain history and a compatible reader, or forward-fix.
ALTER TABLE chart_calculation_preparation_fact
    DROP CONSTRAINT chart_calculation_preparation_fact_kind_check;
ALTER TABLE chart_calculation_preparation_fact
    ADD CONSTRAINT chart_calculation_preparation_fact_kind_check
    CHECK (kind IN ('CLAIM', 'HEARTBEAT', 'RUNTIME_BOUND', 'FAILURE_DECIDED', 'PIN', 'INPUT_READY', 'FAILED'));
