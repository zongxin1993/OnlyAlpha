-- The existing ledger remains the sole Promotion authority. Research records
-- retain their original schema and bytes; a manual grant is explicitly tagged.
ALTER TABLE strategy_promotion_record ADD COLUMN origin JSONB;
ALTER TABLE strategy_promotion_record
    DROP CONSTRAINT strategy_promotion_record_from_stage_check;
ALTER TABLE strategy_promotion_record
    ADD CONSTRAINT strategy_promotion_record_from_stage_check
    CHECK (from_stage IN ('FROZEN', 'RESEARCH', 'BACKTEST', 'SIM'));
ALTER TABLE strategy_promotion_record
    DROP CONSTRAINT strategy_promotion_record_schema_version_check;
ALTER TABLE strategy_promotion_record
    ADD CONSTRAINT strategy_promotion_record_schema_version_check CHECK (
        (schema_version = 1 AND qualification_decision_fingerprint IS NULL
            AND origin IS NULL AND from_stage <> 'FROZEN')
        OR
        (schema_version = 2 AND qualification_decision_fingerprint IS NOT NULL
            AND origin IS NULL AND from_stage <> 'FROZEN')
        OR
        (schema_version = 3 AND qualification_decision_fingerprint IS NOT NULL
            AND origin IS NOT NULL AND jsonb_typeof(origin) = 'object'
            AND origin ?& ARRAY['kind', 'strategy_validation_fingerprint']
            AND origin - 'kind' - 'strategy_validation_fingerprint' = '{}'::jsonb
            AND origin->>'kind' = 'MANUAL_BACKTEST'
            AND jsonb_typeof(origin->'strategy_validation_fingerprint') = 'string'
            AND origin->>'strategy_validation_fingerprint' ~ '^[0-9a-f]{64}$'
            AND origin->>'strategy_validation_fingerprint' = ANY (evidence_fingerprints)
            AND from_stage = 'FROZEN' AND to_stage = 'BACKTEST')
    );
