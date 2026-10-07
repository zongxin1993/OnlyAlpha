-- Precondition: canonical history through 0044. No T1 facts are rewritten.
-- Additive, transactionally checksummed DDL; any failure rolls back the whole migration.
-- Restart/retry uses the existing migration ledger. No legacy data translation is needed.
-- Rollback: disable preparation writers; preserve facts and a compatible reader, or forward-fix.
CREATE TABLE chart_calculation_preparation_fact (
    operation_id UUID NOT NULL REFERENCES chart_calculation_operation(operation_id),
    revision BIGINT NOT NULL CHECK (revision > 0),
    fence BIGINT NOT NULL CHECK (fence > 0 AND fence <= revision),
    kind TEXT NOT NULL CHECK (kind IN ('CLAIM', 'HEARTBEAT', 'PIN', 'INPUT_READY', 'FAILED')),
    fact_json TEXT NOT NULL CHECK (jsonb_typeof(fact_json::jsonb) = 'object'),
    fact_fingerprint TEXT NOT NULL CHECK (fact_fingerprint ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY (operation_id, revision)
);
CREATE TRIGGER chart_calculation_preparation_fact_immutable
    BEFORE UPDATE OR DELETE OR TRUNCATE ON chart_calculation_preparation_fact
    FOR EACH STATEMENT EXECUTE FUNCTION research_source_history_immutable();
