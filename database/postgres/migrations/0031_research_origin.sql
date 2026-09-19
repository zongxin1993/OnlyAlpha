ALTER TABLE research_run
    ADD COLUMN origin_kind TEXT NOT NULL DEFAULT 'GENERAL',
    ADD CONSTRAINT research_run_origin_kind_check CHECK (origin_kind IN ('GENERAL', 'PRIVATE_STRATEGY'));

UPDATE research_run
SET origin_kind = 'PRIVATE_STRATEGY'
WHERE strategy_research_composition_fingerprint IS NOT NULL;

ALTER TABLE research_run
    ADD CONSTRAINT research_run_origin_composition_check CHECK (
        (origin_kind = 'PRIVATE_STRATEGY' AND strategy_research_composition_fingerprint IS NOT NULL)
        OR (origin_kind = 'GENERAL' AND strategy_research_composition_fingerprint IS NULL)
    );
