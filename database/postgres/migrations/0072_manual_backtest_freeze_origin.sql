-- Preserve one Freeze owner and immutable Strategy identity. Manual validation
-- is an explicit origin; it never fabricates Research Run/Result evidence.
ALTER TABLE strategy_freeze_record
    ALTER COLUMN candidate_fingerprint DROP NOT NULL,
    ALTER COLUMN research_result_fingerprint DROP NOT NULL,
    ALTER COLUMN admission_evidence_fingerprint DROP NOT NULL,
    ADD COLUMN origin_kind TEXT NOT NULL DEFAULT 'RESEARCH',
    ADD COLUMN preparation_command_id UUID,
    ADD COLUMN strategy_validation_fingerprint TEXT
        CHECK (strategy_validation_fingerprint ~ '^[0-9a-f]{64}$'),
    ADD CONSTRAINT strategy_freeze_validation_origin_fk
        FOREIGN KEY (preparation_command_id, strategy_validation_fingerprint)
        REFERENCES strategy_validation_publication (preparation_command_id, validation_fingerprint);
ALTER TABLE strategy_freeze_record
    DROP CONSTRAINT strategy_freeze_record_schema_version_check;
ALTER TABLE strategy_freeze_record
    ADD CONSTRAINT strategy_freeze_record_schema_version_check CHECK (
        (origin_kind = 'RESEARCH' AND preparation_command_id IS NULL
            AND strategy_validation_fingerprint IS NULL
            AND candidate_fingerprint IS NOT NULL AND research_result_fingerprint IS NOT NULL
            AND admission_evidence_fingerprint IS NOT NULL
            AND (
                (schema_version = 1 AND equivalence_evidence_fingerprints IS NULL
                    AND research_execution_evidence_fingerprints IS NULL)
                OR (schema_version = 2 AND equivalence_evidence_fingerprints IS NOT NULL
                    AND cardinality(equivalence_evidence_fingerprints) > 0
                    AND research_execution_evidence_fingerprints IS NULL)
                OR (schema_version IN (3, 4) AND equivalence_evidence_fingerprints IS NOT NULL
                    AND cardinality(equivalence_evidence_fingerprints) > 0
                    AND research_execution_evidence_fingerprints IS NOT NULL
                    AND cardinality(research_execution_evidence_fingerprints) > 0)
            ))
        OR
        (schema_version = 5 AND origin_kind = 'MANUAL_BACKTEST'
            AND preparation_command_id IS NOT NULL
            AND preparation_command_id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            AND strategy_validation_fingerprint IS NOT NULL
            AND candidate_fingerprint IS NULL AND research_result_fingerprint IS NULL
            AND admission_evidence_fingerprint IS NULL
            AND research_execution_evidence_fingerprints IS NULL
            AND equivalence_evidence_fingerprints IS NULL)
    );
CREATE UNIQUE INDEX strategy_freeze_manual_origin_unique
    ON strategy_freeze_record (preparation_command_id, strategy_validation_fingerprint, strategy_fingerprint)
    WHERE origin_kind = 'MANUAL_BACKTEST';

ALTER TABLE strategy_freeze_command_admission
    ALTER COLUMN research_run_id DROP NOT NULL,
    ALTER COLUMN candidate_fingerprint DROP NOT NULL,
    ADD COLUMN origin_kind TEXT NOT NULL DEFAULT 'RESEARCH',
    ADD COLUMN preparation_command_id UUID,
    ADD COLUMN strategy_validation_fingerprint TEXT
        CHECK (strategy_validation_fingerprint ~ '^[0-9a-f]{64}$'),
    ADD CONSTRAINT strategy_freeze_command_validation_origin_fk
        FOREIGN KEY (preparation_command_id, strategy_validation_fingerprint)
        REFERENCES strategy_validation_publication (preparation_command_id, validation_fingerprint);
ALTER TABLE strategy_freeze_command_admission
    DROP CONSTRAINT strategy_freeze_command_admission_schema_version_check;
ALTER TABLE strategy_freeze_command_admission
    ADD CONSTRAINT strategy_freeze_command_admission_schema_version_check CHECK (
        (schema_version = 1 AND origin_kind = 'RESEARCH'
            AND research_run_id IS NOT NULL AND candidate_fingerprint IS NOT NULL
            AND preparation_command_id IS NULL AND strategy_validation_fingerprint IS NULL)
        OR
        (schema_version = 2 AND origin_kind = 'MANUAL_BACKTEST'
            AND research_run_id IS NULL AND candidate_fingerprint IS NULL
            AND preparation_command_id IS NOT NULL
            AND preparation_command_id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            AND strategy_validation_fingerprint IS NOT NULL)
    );
