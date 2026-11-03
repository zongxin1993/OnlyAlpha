-- Forward-only native Strategy Research authorization on the existing Run owner.
-- The pinned migration history is verified before this DDL/ledger transaction.
-- Preserve every Factor4 and historical public specification byte and reader.
ALTER TABLE research_run DROP CONSTRAINT research_run_specification_schema_version_check;
ALTER TABLE research_run ADD CONSTRAINT research_run_specification_schema_version_check
    CHECK (specification_schema_version IN (1,2,3,4,5));
ALTER TABLE research_run DROP CONSTRAINT research_run_chart_capability_check;
ALTER TABLE research_run ADD CONSTRAINT research_run_chart_capability_check CHECK (
    (origin_kind = 'CHART_CALCULATION' AND specification_schema_version = 3 AND authoring_provenance IS NULL
        AND research_result_fingerprint IS NULL AND artifact_content_fingerprint IS NULL
        AND calculation_execution_evidence_fingerprints IS NOT NULL
        AND cardinality(calculation_execution_evidence_fingerprints) = 0
        AND failure_phase IS NULL AND failure_code IS NULL AND failure_detail IS NULL
        AND ((state = 'QUEUED' AND revision = 0 AND started_at IS NULL AND cancel_requested_at IS NULL)
          OR (state = 'CANCELLED' AND revision = 1 AND started_at IS NULL AND cancel_requested_at IS NULL)
          OR (state = 'RUNNING' AND revision = 1 AND started_at IS NOT NULL AND cancel_requested_at IS NULL)
          OR (state = 'CANCEL_REQUESTED' AND revision = 2 AND started_at IS NOT NULL
              AND cancel_requested_at IS NOT NULL AND cancel_requested_at >= started_at))
        AND (started_at IS NULL OR started_at >= queued_at)
        AND (finished_at IS NULL OR finished_at >= queued_at))
    OR (origin_kind IN ('GENERAL','PRIVATE_STRATEGY') AND specification_schema_version IN (1,2))
    OR (origin_kind = 'GENERAL' AND specification_schema_version = 4 AND authoring_provenance IS NULL
        AND strategy_research_composition_fingerprint IS NULL
        AND (specification_payload::jsonb)->>'kind' = 'TIME_SERIES_FACTOR_RESEARCH')
    OR (origin_kind = 'PRIVATE_STRATEGY' AND specification_schema_version = 5 AND authoring_provenance IS NULL
        AND strategy_research_composition_fingerprint IS NOT NULL
        AND (specification_payload::jsonb)->>'kind' = 'PRIVATE_STRATEGY_RESEARCH')
);

-- One immutable Human authorization is provenance of an existing Research Run;
-- it owns no queue, second Run identity, scientific result or current permission.
CREATE TABLE research_strategy_study_authorization (
    run_id UUID PRIMARY KEY REFERENCES research_run(run_id),
    command_id UUID UNIQUE NOT NULL REFERENCES product_command_receipt(command_id) DEFERRABLE INITIALLY DEFERRED,
    fingerprint TEXT UNIQUE NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    payload TEXT NOT NULL CHECK (octet_length(payload) <= 8388608),
    CHECK (encode(sha256(convert_to(payload,'UTF8')),'hex') = fingerprint)
);
CREATE TRIGGER research_strategy_study_authorization_immutable
    BEFORE UPDATE OR DELETE OR TRUNCATE ON research_strategy_study_authorization
    FOR EACH STATEMENT EXECUTE FUNCTION research_source_history_immutable();

CREATE FUNCTION native_strategy_research_relation_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE target UUID;
BEGIN
    target := NEW.run_id;
    IF EXISTS (SELECT 1 FROM public.research_run WHERE run_id=target AND specification_schema_version=5)
       OR EXISTS (SELECT 1 FROM public.research_strategy_study_authorization WHERE run_id=target) THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.research_run r
            JOIN public.research_strategy_study_authorization a ON a.run_id=r.run_id
            JOIN public.product_command_receipt c ON c.command_id=a.command_id
            JOIN public.product_command_admission d ON d.command_id=c.command_id
            JOIN public.private_strategy_research_composition p
              ON p.composition_fingerprint=r.strategy_research_composition_fingerprint
            JOIN public.private_strategy_revision v
              ON v.strategy_id=p.private_strategy_id
             AND v.revision_fingerprint=p.private_strategy_revision_fingerprint
            JOIN public.research_novelty_admission n ON n.run_id=r.run_id AND n.command_id=c.command_id
            JOIN public.research_novelty_admission_subject s
              ON s.command_id=n.command_id AND s.admission_fingerprint=n.admission_fingerprint AND s.ordinal=0
            WHERE r.run_id=target AND r.specification_schema_version=5 AND r.origin_kind='PRIVATE_STRATEGY'
              AND r.authoring_provenance IS NULL
              AND (r.specification_payload::jsonb)->>'schema_version'='5'
              AND (r.specification_payload::jsonb)->>'kind'='PRIVATE_STRATEGY_RESEARCH'
              AND d.command_kind='CREATE_RESEARCH_RUN' AND c.command_kind=d.command_kind
              AND c.command_fingerprint=d.command_fingerprint AND c.outcome_kind='RESEARCH_RUN'
              AND c.outcome_id=r.run_id::text AND c.accepted_at=r.queued_at
              AND (a.payload::jsonb)->>'schema_version'='1'
              AND (a.payload::jsonb)->>'contract'='ONLYALPHA_STRATEGY_RESEARCH_AUTHORIZATION_V1'
              AND btrim((a.payload::jsonb)->>'actor_id')<>''
              AND (a.payload::jsonb)->>'run_id'=r.run_id::text
              AND (a.payload::jsonb)->>'command_id'=c.command_id::text
              AND (a.payload::jsonb)->>'command_fingerprint'=d.command_fingerprint
              AND (a.payload::jsonb)->>'specification_fingerprint'=r.specification_fingerprint
              AND (a.payload::jsonb)->>'scientific_specification_fingerprint' ~ '^[0-9a-f]{64}$'
              AND (a.payload::jsonb)->'request'->'specification'=r.specification_payload::jsonb
              AND (a.payload::jsonb)->>'accepted_at' IS NOT NULL
              AND ((a.payload::jsonb)->>'accepted_at')::timestamptz=r.queued_at
              AND (a.payload::jsonb)->>'strategy_id'=p.private_strategy_id
              AND (a.payload::jsonb)->>'strategy_revision_fingerprint'=p.private_strategy_revision_fingerprint
              AND (a.payload::jsonb)->>'composition_fingerprint'=p.composition_fingerprint
              AND (a.payload::jsonb)->'prepared_inputs'->'composition'=(to_jsonb(p)-'research_context_payload')
              AND (a.payload::jsonb)->'prepared_inputs'->>'contract'='ONLYALPHA_STRATEGY_RESEARCH_PREPARED_INPUTS_V1'
              AND (a.payload::jsonb)->'prepared_inputs'->>'run_specification_fingerprint'=r.specification_fingerprint
              AND (a.payload::jsonb)->'prepared_inputs'->'runtime_work_binding'->>'work_id'=r.run_id::text
              AND n.schema_version=2 AND n.command_fingerprint=d.command_fingerprint
              AND n.runtime_work_id=r.run_id::text
              AND n.admission_fingerprint=r.admission_resolution_fingerprint
              AND (a.payload::jsonb)->>'novelty_admission_fingerprint'=n.admission_fingerprint
              AND (a.payload::jsonb)->>'decision_group_fingerprint'=n.decision_group_fingerprint
              AND (SELECT count(*) FROM public.research_novelty_admission_subject m WHERE m.command_id=n.command_id)=1
        ) THEN RAISE EXCEPTION 'NATIVE_STRATEGY_RESEARCH_RELATION_CORRUPT'; END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE CONSTRAINT TRIGGER native_strategy_research_run_guard
    AFTER INSERT OR UPDATE ON research_run DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION native_strategy_research_relation_guard();
CREATE CONSTRAINT TRIGGER native_strategy_research_authorization_guard
    AFTER INSERT ON research_strategy_study_authorization DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION native_strategy_research_relation_guard();

-- Native Backtest uses the same operational Run/Attempt and exact admission
-- payload columns. Existing versions remain exact, without history translation.
ALTER TABLE backtest_run
    DROP CONSTRAINT backtest_run_specification_schema_version_check,
    ADD CONSTRAINT backtest_run_specification_schema_version_check CHECK (specification_schema_version IN (1,2,3));
ALTER TABLE backtest_run
    DROP CONSTRAINT backtest_run_admission_resolution_schema_version_check,
    ADD CONSTRAINT backtest_run_admission_resolution_schema_version_check CHECK (admission_resolution_schema_version IN (1,2));
