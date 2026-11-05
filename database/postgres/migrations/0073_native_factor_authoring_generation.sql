-- Admit the new exact Authoring Generation specification through the existing Run relation.
ALTER TABLE research_run DROP CONSTRAINT research_run_specification_schema_version_check;
ALTER TABLE research_run ADD CONSTRAINT research_run_specification_schema_version_check
    CHECK (specification_schema_version IN (1,2,3,4,5,6));
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
    OR (origin_kind = 'GENERAL' AND specification_schema_version = 6 AND authoring_provenance IS NULL
        AND strategy_research_composition_fingerprint IS NULL
        AND COALESCE((specification_payload::jsonb)->>'kind', '') = 'TIME_SERIES_FACTOR_RESEARCH'
        AND ((specification_payload::jsonb)->'schema_version' = '6'::jsonb) IS TRUE
        AND COALESCE((specification_payload::jsonb)->>'authoring_generation_fingerprint', '') ~ '^[0-9a-f]{64}$')
    OR (origin_kind = 'PRIVATE_STRATEGY' AND specification_schema_version = 5 AND authoring_provenance IS NULL
        AND strategy_research_composition_fingerprint IS NOT NULL
        AND (specification_payload::jsonb)->>'kind' = 'PRIVATE_STRATEGY_RESEARCH')
);

CREATE OR REPLACE FUNCTION native_factor_research_relation_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE target UUID;
BEGIN
    target := NEW.run_id;
    IF EXISTS (SELECT 1 FROM public.research_run WHERE run_id=target AND specification_schema_version IN (4,6))
       OR EXISTS (SELECT 1 FROM public.research_factor_study_authorization WHERE run_id=target) THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.research_run r
            JOIN public.research_factor_study_authorization a ON a.run_id=r.run_id
            JOIN public.product_command_receipt c ON c.command_id=a.command_id
            JOIN public.product_command_admission d ON d.command_id=c.command_id
            JOIN public.research_novelty_admission n ON n.run_id=r.run_id AND n.command_id=c.command_id
            JOIN public.factor_proposal_confirmation f
              ON f.proposal_fingerprint=(a.payload::jsonb)->>'factor_proposal_fingerprint'
             AND f.command_id=((a.payload::jsonb)->>'factor_confirmation_command_id')::uuid
            JOIN public.private_factor_revision v
              ON v.revision_fingerprint=(a.payload::jsonb)->>'factor_revision_fingerprint'
            WHERE r.run_id=target AND r.specification_schema_version IN (4,6) AND r.origin_kind='GENERAL'
              AND d.command_kind='CREATE_RESEARCH_RUN' AND c.command_kind=d.command_kind
              AND c.command_fingerprint=d.command_fingerprint AND c.outcome_kind='RESEARCH_RUN'
              AND c.outcome_id=r.run_id::text AND c.accepted_at=r.queued_at
              AND (a.payload::jsonb)->>'run_id'=r.run_id::text
              AND (a.payload::jsonb)->>'command_id'=c.command_id::text
              AND (a.payload::jsonb)->>'specification_fingerprint'=r.specification_fingerprint
              AND (r.specification_schema_version=4 OR
                   ((a.payload::jsonb)->'prepared_inputs'->>'authoring_generation_fingerprint'
                    = (r.specification_payload::jsonb)->>'authoring_generation_fingerprint'))
              AND n.admission_fingerprint=r.admission_resolution_fingerprint
              AND (a.payload::jsonb)->>'novelty_admission_fingerprint'=n.admission_fingerprint
        ) THEN RAISE EXCEPTION 'NATIVE_FACTOR_RESEARCH_RELATION_CORRUPT'; END IF;
    END IF;
    RETURN NEW;
END;
$$;
