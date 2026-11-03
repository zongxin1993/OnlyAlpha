-- Accepted V2 adds an explicit authoring/qualified origin; historical V1 bytes
-- stay exact and are never reinterpreted as an origin or enrollment capability.
ALTER TABLE research_preparation DROP CONSTRAINT research_preparation_kind_contract_check;
ALTER TABLE research_preparation ADD CONSTRAINT research_preparation_kind_contract_check CHECK ((
    (preparation_kind='FACTOR_RESEARCH' AND accepted_payload::jsonb->>'contract'='ONLYALPHA_ACCEPTED_RESEARCH_PREPARATION_V1')
    OR (preparation_kind='STRATEGY_RESEARCH' AND accepted_payload::jsonb->>'contract'='ONLYALPHA_ACCEPTED_STRATEGY_RESEARCH_PREPARATION_V1')
    OR (preparation_kind='BACKTEST_PREPARATION' AND accepted_payload::jsonb->>'contract' IN ('ONLYALPHA_ACCEPTED_BACKTEST_PREPARATION_V1','ONLYALPHA_ACCEPTED_BACKTEST_PREPARATION_V2'))
) IS TRUE);

-- Authentic original producer membership only. The immutable file is semantic truth.
CREATE TABLE strategy_validation_publication (
    preparation_command_id UUID PRIMARY KEY REFERENCES research_preparation(command_id),
    validation_fingerprint TEXT NOT NULL UNIQUE CHECK(validation_fingerprint ~ '^[0-9a-f]{64}$'),
    accepted_fingerprint TEXT NOT NULL CHECK(accepted_fingerprint ~ '^[0-9a-f]{64}$'),
    private_strategy_id TEXT NOT NULL,
    private_strategy_revision_fingerprint TEXT NOT NULL CHECK(private_strategy_revision_fingerprint ~ '^[0-9a-f]{64}$'),
    recorded_at TIMESTAMPTZ NOT NULL,
    UNIQUE(preparation_command_id,validation_fingerprint),
    FOREIGN KEY(private_strategy_id,private_strategy_revision_fingerprint)
        REFERENCES private_strategy_revision(strategy_id,revision_fingerprint)
);
CREATE TRIGGER strategy_validation_publication_immutable
    BEFORE UPDATE OR DELETE OR TRUNCATE ON strategy_validation_publication
    FOR EACH STATEMENT EXECUTE FUNCTION private_asset_revision_immutable();
CREATE FUNCTION strategy_validation_publication_relation_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.research_preparation p
        JOIN public.product_command_admission a ON a.command_id=p.command_id
        JOIN public.product_command_receipt r ON r.command_id=a.command_id
        JOIN public.private_strategy_revision v ON v.strategy_id=NEW.private_strategy_id
            AND v.revision_fingerprint=NEW.private_strategy_revision_fingerprint
        WHERE p.command_id=NEW.preparation_command_id
            AND p.preparation_kind='BACKTEST_PREPARATION'
            AND p.accepted_payload::jsonb->>'schema_version'='2'
            AND p.accepted_payload::jsonb->>'contract'='ONLYALPHA_ACCEPTED_BACKTEST_PREPARATION_V2'
            AND p.accepted_fingerprint=NEW.accepted_fingerprint
            AND a.command_kind='PREPARE_BACKTEST' AND r.command_kind=a.command_kind
            AND r.command_fingerprint=a.command_fingerprint
            AND r.outcome_kind='RESEARCH_PREPARATION_OPERATION' AND r.outcome_id=p.accepted_fingerprint
            AND p.accepted_payload::jsonb->'input'->'origin'->>'kind'='MANUAL_STRATEGY'
            AND p.accepted_payload::jsonb->'input'->'origin'->>'strategy_id'=NEW.private_strategy_id
            AND p.accepted_payload::jsonb->'input'->'origin'->>'strategy_revision_fingerprint'=NEW.private_strategy_revision_fingerprint
            AND (p.accepted_payload::jsonb->>'accepted_at')::timestamptz=NEW.recorded_at
    ) THEN RAISE EXCEPTION 'STRATEGY_VALIDATION_PUBLICATION_RELATION_CORRUPT'; END IF;
    RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER strategy_validation_publication_relation
    AFTER INSERT ON strategy_validation_publication DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION strategy_validation_publication_relation_guard();
