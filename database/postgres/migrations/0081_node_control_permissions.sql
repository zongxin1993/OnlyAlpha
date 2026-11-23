-- Node lifecycle/admission capabilities, separate from build and publication.
-- Login provisioning is an explicit operator action, never ordinary startup.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='onlyalpha_node_control') THEN
    CREATE ROLE onlyalpha_node_control NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_authid WHERE rolname='onlyalpha_node_control'
      AND NOT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole
      AND NOT rolreplication AND NOT rolbypassrls AND NOT rolinherit AND rolpassword IS NULL
      AND rolconnlimit=-1 AND (rolvaliduntil IS NULL OR rolvaliduntil='infinity'::timestamptz))
    OR EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members m JOIN pg_catalog.pg_roles p ON p.oid=m.member WHERE p.rolname='onlyalpha_node_control')
    OR EXISTS (SELECT 1 FROM pg_catalog.pg_shdepend d JOIN pg_catalog.pg_roles p ON p.oid=d.refobjid
      WHERE d.refclassid='pg_catalog.pg_authid'::regclass AND p.rolname='onlyalpha_node_control'
      AND (d.dbid=0 OR d.dbid=(SELECT oid FROM pg_catalog.pg_database WHERE datname=current_database()))) THEN
    RAISE EXCEPTION 'NODE_DATABASE_ROLE_UNSAFE';
  END IF;
END $$;

GRANT USAGE ON SCHEMA public TO onlyalpha_node_control;
GRANT SELECT ON public.onlyalpha_schema_migration,
  public.research_deployment_semantic_store_binding,
  public.market_latest_sealed_revision,
  public.research_source_history,public.research_source_history_frontier,
  public.research_run,public.research_run_attempt,
  public.backtest_run,public.backtest_run_attempt TO onlyalpha_node_control;

GRANT SELECT,INSERT ON
  public.product_command_admission,public.product_command_receipt,
  public.research_preparation,public.research_novelty_admission,
  public.research_novelty_admission_subject,public.research_source_closed_cut,
  public.research_factor_study_authorization,public.research_strategy_study_authorization,
  public.private_strategy_research_composition,
  public.strategy_catalog,public.strategy_freeze_record,public.strategy_promotion_record,
  public.strategy_validation_publication,public.qualification_command_admission,
  public.strategy_freeze_command_admission,
  public.private_factor_asset,public.private_factor_draft,public.private_factor_revision,
  public.private_factor_authoring_outcome,public.private_factor_display,
  public.private_strategy_asset,public.private_strategy_draft,public.private_strategy_revision,
  public.private_strategy_authoring_outcome,
  public.integration,public.integration_draft,public.integration_draft_secret_binding,
  public.integration_revision,public.integration_revision_secret_binding,
  public.integration_probe_attempt,public.product_credential,
  public.factor_proposal_grant,public.factor_proposal_revocation,public.factor_proposal_snapshot,
  public.factor_proposal_head,public.factor_proposal_operation,public.factor_proposal_confirmation,
  public.factor_proposal_withdrawal,
  public.factor_study_grant,public.factor_study_snapshot,public.factor_study_head,
  public.factor_study_operation,public.factor_study_withdrawal,
  public.watchlist_revision,public.watchlist_head,
  public.workspace_library_revision,public.workspace_library_head,
  public.market_source,public.market_capture_session,public.market_ingest_segment,
  public.market_segment_state_event,public.market_segment_physical_proof,
  public.market_coverage_manifest,public.market_coverage_manifest_segment,
  public.market_data_revision,public.market_revision_segment,public.market_revision_seal,
  public.market_recovery_event,public.market_acquisition_intent,
  public.market_acquisition_execution_lock_key,public.market_data_acquisition_attempt,
  public.market_data_acquisition_attempt_outcome,
  public.market_history_prepared_scope,public.market_history_preparation_input
TO onlyalpha_node_control;

GRANT UPDATE(lifecycle_state,current_revision_fingerprint,updated_at) ON public.integration TO onlyalpha_node_control;
GRANT UPDATE(base_revision_fingerprint,type_descriptor_fingerprint,type_descriptor_document,public_configuration_document,probe_configuration_document,draft_version,draft_fingerprint,updated_at) ON public.integration_draft TO onlyalpha_node_control;
GRANT UPDATE(credential_id,credential_generation),DELETE ON public.integration_draft_secret_binding TO onlyalpha_node_control;
GRANT UPDATE(generation,ciphertext,updated_at) ON public.product_credential TO onlyalpha_node_control;
GRANT UPDATE(current_revision_fingerprint) ON public.private_factor_asset,public.private_strategy_asset TO onlyalpha_node_control;
GRANT UPDATE(base_revision_fingerprint,payload) ON public.private_factor_draft,public.private_strategy_draft TO onlyalpha_node_control;
GRANT UPDATE(payload,fingerprint) ON public.private_factor_display TO onlyalpha_node_control;
GRANT UPDATE(fingerprint) ON public.factor_proposal_head,public.factor_study_head TO onlyalpha_node_control;
GRANT UPDATE(version) ON public.watchlist_head,public.workspace_library_head TO onlyalpha_node_control;
GRANT UPDATE(revision,state,phase,outputs_payload,detail_payload) ON public.research_preparation TO onlyalpha_node_control;
GRANT UPDATE(state,decision_fingerprint,completed_at) ON public.qualification_command_admission TO onlyalpha_node_control;
GRANT UPDATE(state,strategy_fingerprint,freeze_relation_fingerprint,published_at,completed_at) ON public.strategy_freeze_command_admission TO onlyalpha_node_control;

-- FOR UPDATE requires an UPDATE capability. Grant only an immutable identity
-- column, with its guard, rather than mutable display metadata or whole tables.
CREATE TRIGGER strategy_catalog_identity_immutable
  BEFORE UPDATE OF strategy_fingerprint ON public.strategy_catalog
  FOR EACH ROW EXECUTE FUNCTION public.job_content_immutable();
GRANT UPDATE(strategy_fingerprint) ON public.strategy_catalog TO onlyalpha_node_control;
GRANT UPDATE(grant_id) ON public.factor_proposal_grant TO onlyalpha_node_control;
GRANT UPDATE(acquisition_id) ON public.market_acquisition_intent TO onlyalpha_node_control;

GRANT INSERT(run_id,revision,state,specification_schema_version,specification_fingerprint,specification_payload,admission_resolution_fingerprint,queued_at,calculation_execution_evidence_fingerprints,origin_kind,strategy_research_composition_fingerprint)
  ON public.research_run TO onlyalpha_node_control;
GRANT INSERT(run_id,revision,state,specification_schema_version,specification_fingerprint,specification_payload,admission_resolution_schema_version,admission_resolution_fingerprint,admission_resolution_payload,queued_at)
  ON public.backtest_run TO onlyalpha_node_control;
GRANT INSERT(attempt_id,run_id,attempt_number,state,worker_instance_id,claimed_at,last_heartbeat_at,lease_expires_at)
  ON public.research_run_attempt TO onlyalpha_node_control;
GRANT INSERT(attempt_id,run_id,attempt_number,state,worker_instance_id,fencing_token,claimed_at,last_heartbeat_at,lease_expires_at)
  ON public.backtest_run_attempt TO onlyalpha_node_control;
GRANT UPDATE(revision,state,started_at,cancel_requested_at,finished_at,failure_phase,failure_code,failure_detail)
  ON public.research_run TO onlyalpha_node_control;
GRANT UPDATE(revision,state,started_at,cancel_requested_at,finished_at)
  ON public.backtest_run TO onlyalpha_node_control;
GRANT UPDATE(last_heartbeat_at,lease_expires_at,state,finished_at,failure_phase,failure_code,failure_detail)
  ON public.research_run_attempt TO onlyalpha_node_control;
GRANT UPDATE(last_heartbeat_at,lease_expires_at,state,finished_at,failure_code,failure_detail)
  ON public.backtest_run_attempt TO onlyalpha_node_control;

-- Existing invoker Product Command capture chain (Run capture is already a
-- fixed SECURITY DEFINER trigger). No job publisher source-history grant.
GRANT INSERT ON public.research_source_history TO onlyalpha_node_control;
GRANT UPDATE(last_index) ON public.research_source_history_frontier TO onlyalpha_node_control;
GRANT EXECUTE ON FUNCTION public.research_source_record(text,text,jsonb,text) TO onlyalpha_node_control;
