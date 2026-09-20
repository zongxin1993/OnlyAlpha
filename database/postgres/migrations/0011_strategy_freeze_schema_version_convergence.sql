ALTER TABLE strategy_freeze_record
    DROP CONSTRAINT strategy_freeze_record_schema_version_check;

ALTER TABLE strategy_freeze_record
    ADD CONSTRAINT strategy_freeze_record_schema_version_check CHECK (
        (schema_version = 1 AND equivalence_evidence_fingerprints IS NULL
            AND research_execution_evidence_fingerprints IS NULL)
        OR
        (schema_version = 2 AND equivalence_evidence_fingerprints IS NOT NULL
            AND cardinality(equivalence_evidence_fingerprints) > 0
            AND research_execution_evidence_fingerprints IS NULL)
        OR
        (schema_version IN (3, 4) AND equivalence_evidence_fingerprints IS NOT NULL
            AND cardinality(equivalence_evidence_fingerprints) > 0
            AND research_execution_evidence_fingerprints IS NOT NULL
            AND cardinality(research_execution_evidence_fingerprints) > 0)
    );
