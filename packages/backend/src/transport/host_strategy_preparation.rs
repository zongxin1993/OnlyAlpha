//! Bounded Strategy consumer of the existing preparation task and Runtime owners.
//! Parsed values describe selected inputs; only the original submission owner admits a Run.
use super::*;
use crate::{
    application::{
        research_admission::PreparedInputs,
        strategy_research::{Context as ResearchContext, canonical_input_window},
    },
    persistence::{
        research_preparation::{algorithm_inputs, require_current},
        strategy_research::Composer,
    },
    transport::host_research_inputs::DatasetEventWindow,
};
fn ns(v: &Value) -> Result<u64> {
    let value = v
        .as_str()
        .ok_or(INVALID)?
        .parse::<onlyalpha_domain::time::OnlyUtcDateTime>()
        .map_err(|_| INVALID)?;
    OnlyTimestamp::from_datetime(value)
        .unix_nanos()
        .to_string()
        .parse()
        .map_err(|_| INVALID.into())
}
impl Host {
    pub(super) async fn retained_strategy_factor_publication(
        &self,
        o: &Operation,
    ) -> Result<Value> {
        let (_, revision) = algorithm_inputs(o)?;
        let id = text(&revision, "factor_id")?;
        let pin = text(&revision, "revision_fingerprint")?;
        let mut writer = self.writer.lock().await;
        let client = writer
            .as_mut()
            .ok_or("PRODUCT_AUTHORITY_UNAVAILABLE")?
            .client_mut()
            .await
            .map_err(|_| "PRODUCT_AUTHORITY_UNAVAILABLE")?;
        let tx = client
            .transaction()
            .await
            .map_err(|_| "RESEARCH_PREPARATION_UNAVAILABLE")?;
        require_current(&tx, o).await?;
        let rows=tx.query("SELECT command_id::text FROM private_factor_authoring_outcome WHERE factor_id=$1 AND payload->'result'->'revision'->>'revision_fingerprint'=$2 LIMIT 2",&[&id,&pin]).await.map_err(|_|"RESEARCH_PREPARATION_UNAVAILABLE")?;
        if rows.len() != 1 {
            return Err("RESEARCH_FACTOR_REVISION_PROVENANCE_UNAVAILABLE".into());
        }
        let command = CommandId::new(&rows[0].try_get::<_, String>(0).map_err(|_| INVALID)?)
            .map_err(|_| INVALID)?;
        let publication = private_factor_postgres::bound(&tx, id, &command, None)
            .await
            .map_err(|e| e.code())?
            .ok_or(INVALID)?;
        if publication["result"]["revision"] != revision {
            return Err(INVALID.into());
        }
        tx.commit()
            .await
            .map_err(|_| "RESEARCH_PREPARATION_UNAVAILABLE")?;
        Ok(publication)
    }
    pub(super) async fn prepare_strategy_inputs(
        self: &Arc<Self>,
        mut o: Operation,
        human: human_access::Session,
        source_authority: Authority,
        source_session: Session,
        selection: crate::application::source_access::Selection,
        installation: ChartInstallation,
    ) -> Result<()> {
        let config = &self.research_preparation_config;
        let input = o.request.strategy()?.clone();
        let context = input.validate(&o.command)?;
        let future = CommandId::new(o.request.research_command()).map_err(|_| INVALID)?;
        let runtime = RuntimeInputHold::open(
            &config.runtime_root,
            &research_submission::run_id(&future),
            "research",
            text(&o.outputs["environment"], "runtime_generation_fingerprint")?,
        )?;
        installed_proof(config, &o, &runtime)?;
        let resolved = {
            let mut writer = self.writer.lock().await;
            let client = writer
                .as_mut()
                .ok_or("PRODUCT_AUTHORITY_UNAVAILABLE")?
                .client_mut()
                .await
                .map_err(|_| "PRODUCT_AUTHORITY_UNAVAILABLE")?;
            Composer::new(client)
                .resolve(
                    &input.strategy_id,
                    &input.strategy_revision_fingerprint,
                    &context,
                    runtime,
                    &installation,
                )
                .await?
        };
        // This graph was resolved by the selected installed registrations. The
        // whole source dependency closure determines history, never an alias.
        let graph = onlyalpha_calculation::product::Graph::from_record(
            &resolved.record()["decision"]["decision_graph"],
            8 * 1024 * 1024,
        )
        .map_err(|_| INVALID)?;
        let mut sources = Vec::new();
        for target in context.record()["targets"].as_array().ok_or(INVALID)? {
            for binding in target["input_bindings"].as_array().ok_or(INVALID)? {
                sources.push(binding["source"].as_str().ok_or(INVALID)?);
            }
        }
        let window = canonical_input_window(
            &graph,
            ns(&context.record()["start"])?,
            ns(&context.record()["end"])?,
            60_000_000_000,
            sources,
        )?;
        let bounds = DatasetEventWindow::new(
            window["dataset_event_start_ns"]
                .as_str()
                .ok_or(INVALID)?
                .parse()
                .map_err(|_| INVALID)?,
            window["dataset_event_end_ns"]
                .as_str()
                .ok_or(INVALID)?
                .parse()
                .map_err(|_| INVALID)?,
            60_000_000_000,
        )?;
        let strategy = &o.accepted["strategy_revision"]["definition"];
        let definition = json!({"schema_version":2,"dataset_type":"HISTORICAL_BAR","instruments":strategy["universe"]["instruments"],"bar_semantic":strategy["market_input"]["bar_semantic"],"time_range":{"start":timestamp(window["dataset_event_start_ns"].as_str().ok_or(INVALID)?.parse().map_err(|_|INVALID)?)?,"end":timestamp(window["dataset_event_end_ns"].as_str().ok_or(INVALID)?.parse().map_err(|_|INVALID)?)?},"quality_policy":"STRICT","closed_only":true});
        let datasets = Datasets::open(
            &config.research_root.join("datasets"),
            8192,
            8 * 1024 * 1024,
        )?;
        let acquired = self
            .research_inputs(ResearchInputRequest {
                human: human.clone(),
                session: &source_session,
                source: &input.source,
                window: bounds,
                definition: &definition,
                command: &o.command,
                datasets: &datasets,
                deadline: Instant::now() + Duration::from_secs(10),
            })
            .await
            .map_err(|e| e.code())?;
        let materialized = match acquired {
            ResearchInputOutcome::Pending(receipt) => {
                self.preparation_progress(
                    &o,
                    State::InputPending,
                    "ACQUISITION",
                    &o.outputs,
                    &receipt,
                )
                .await?;
                return Ok(());
            }
            ResearchInputOutcome::Unavailable(receipt) => {
                self.preparation_progress(&o, State::Blocked, "ACQUISITION", &o.outputs, &receipt)
                    .await?;
                return Ok(());
            }
            ResearchInputOutcome::Prepared(value) => value,
        };
        o = self.preparation_checkpoint(&o, &human).await?;
        let (prepared, specification) = {
            let mut writer = self.writer.lock().await;
            let client = writer
                .as_mut()
                .ok_or("PRODUCT_AUTHORITY_UNAVAILABLE")?
                .client_mut()
                .await
                .map_err(|_| "PRODUCT_AUTHORITY_UNAVAILABLE")?;
            PreparedInputs::prepare_strategy(
                &mut Composer::new(client),
                resolved,
                &context,
                &installation,
                &datasets,
                &materialized.materialized,
            )
            .await?
        };
        let policy = crate::bootstrap::research_namespace::policy();
        let novelty = crate::bootstrap::research_namespace::novelty(
            config.research_root.parent().ok_or(INVALID)?,
        )?;
        let context = Context {
            human_authority: &self.human_access,
            human: &human,
            source_authority: &source_authority,
            source: &source_session,
            selection: &selection,
        };
        o = self.preparation_checkpoint(&o, &human).await?;
        let (study, actionable) = {
            let mut writer = self.writer.lock().await;
            let session = writer.as_mut().ok_or("PRODUCT_AUTHORITY_UNAVAILABLE")?;
            let request = research_submission::strategy::Request::new(
                specification,
                None,
                text(&policy, "policy_id")?,
                text(&policy, "policy_version")?,
            )?;
            research_submission::strategy::prepare_study(
                session, &novelty, &context, future, request, &prepared, &datasets,
            )
            .await?
            .into_parts()
        };
        let mut outputs = o.outputs.clone();
        outputs["ready"] = json!({"preparation_command_id":o.command.value(),"strategy_revision_fingerprint":input.strategy_revision_fingerprint,"factor_confirmation_command_id":o.accepted["factor_confirmation"]["confirmation_command_id"],"runtime_generation_fingerprint":outputs["environment"]["runtime_generation_fingerprint"],"installed_proof_fingerprint":outputs["environment"]["installed_proof_fingerprint"],"dataset_materialization_id":materialized.materialized.lineage()["materialization_id"],"source_selection":materialized.selection,"prepared_study":study.record()?,"prepared_study_fingerprint":study.fingerprint()?,"prepared_inputs":prepared.record()});
        if actionable {
            self.preparation_progress(
                &o,
                State::Ready,
                "READY_FOR_HUMAN_CONFIRMATION",
                &outputs,
                &Value::Null,
            )
            .await?;
        } else {
            self.preparation_progress(
                &o,
                State::Blocked,
                "NOVELTY",
                &outputs,
                &json!({"code":"NOVELTY_DECISION_NOT_ADMIT"}),
            )
            .await?;
        }
        Ok(())
    }
    pub(super) async fn strategy_preparation_view(
        &self,
        o: &Operation,
        human: &human_access::Session,
    ) -> Result<Value> {
        let mut view = o.view();
        let future = CommandId::new(o.request.research_command()).map_err(|_| INVALID)?;
        let mut reader = self.reader.lock().await;
        let client = reader.as_mut().ok_or("PRODUCT_READ_DRIVER_UNAVAILABLE")?;
        if o.outputs.get("ready").is_none() {
            let tx = client
                .build_transaction()
                .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
                .read_only(true)
                .start()
                .await
                .map_err(|_| "RESEARCH_PREPARATION_UNAVAILABLE")?;
            match crate::persistence::postgres::Commands::verify_binding_in_transaction(
                &tx, &future,
            )
            .await
            .map_err(|_| "RESEARCH_PREPARATION_UNAVAILABLE")?
            {
                crate::application::command::Binding::None => {
                    if tx
                        .query_opt(
                            "SELECT 1 FROM research_run WHERE run_id=$1::text::uuid",
                            &[&research_submission::run_id(&future)],
                        )
                        .await
                        .map_err(|_| "RESEARCH_PREPARATION_UNAVAILABLE")?
                        .is_some()
                    {
                        return Err(INVALID.into());
                    }
                    view["research_outcome"] = json!("NOT_SUBMITTED");
                }
                crate::application::command::Binding::Admitted(a)
                    if a.kind() == crate::application::command::CommandKind::CreateResearchRun =>
                {
                    view["research_outcome"] = json!("OUTCOME_UNKNOWN")
                }
                _ => return Err(INVALID.into()),
            }
            tx.commit()
                .await
                .map_err(|_| "RESEARCH_PREPARATION_UNAVAILABLE")?;
            return Ok(view);
        }
        let source = o.source()?;
        let (a, s, selection) = self.preparation_sources(human, &source, false).await?;
        let context = Context {
            human_authority: &self.human_access,
            human,
            source_authority: &a,
            source: &s,
            selection: &selection,
        };
        let record = &o.outputs["ready"]["prepared_study"];
        let pin = text(&o.outputs["ready"], "prepared_study_fingerprint")?;
        let study = research_submission::strategy::restore_study(&context, record, pin)?;
        match research_submission::strategy::submission_outcome_readonly(client, &context, &study)
            .await?
        {
            SubmissionOutcome::Accepted(run) => {
                view["research_outcome"] = json!("ACCEPTED");
                view["run_id"] = json!(run.run_id());
                return Ok(view);
            }
            SubmissionOutcome::Pending => {
                view["research_outcome"] = json!("OUTCOME_UNKNOWN");
                return Ok(view);
            }
            SubmissionOutcome::NotSubmitted => view["research_outcome"] = json!("NOT_SUBMITTED"),
        }
        let readiness = async {
            let novelty = crate::bootstrap::research_namespace::novelty(
                self.research_preparation_config
                    .research_root
                    .parent()
                    .ok_or(INVALID)?,
            )?;
            let spec = study.request().specification();
            let (policy, version) = study.request().policy();
            let group = novelty
                .retained_group(client, &future, &[spec.subject()?], policy, version)
                .await?;
            if group["group_fingerprint"] != record["decision_group_fingerprint"]
                || group["disposition"] != "ACTIONABLE"
            {
                return Err(INVALID.into());
            }
            retained_ready(&self.research_preparation_config, o)?;
            Ok::<(), PreparationError>(())
        }
        .await;
        view["readiness"] = match readiness {
            Ok(()) => json!({"state":"VERIFIED","code":null}),
            Err(e) => json!({"state":"UNAVAILABLE","code":e.code()}),
        };
        Ok(view)
    }
    async fn strategy_ready_inputs(&self, o: &Operation) -> Result<PreparedInputs> {
        let config = &self.research_preparation_config;
        pinned_release(config, o)?;
        retained_ready(config, o)?;
        let datasets = Datasets::open(
            &config.research_root.join("datasets"),
            8192,
            8 * 1024 * 1024,
        )?;
        let materialized = crate::application::research_dataset::MaterializedDataset::load(
            &datasets,
            text(&o.outputs["ready"], "dataset_materialization_id")?,
        )?;
        let future = CommandId::new(o.request.research_command()).map_err(|_| INVALID)?;
        let runtime = RuntimeInputHold::open(
            &config.runtime_root,
            &research_submission::run_id(&future),
            "research",
            text(&o.outputs["environment"], "runtime_generation_fingerprint")?,
        )?;
        installed_proof(config, o, &runtime)?;
        let selected = release(config)?;
        let installation = ChartInstallation::open(
            &config.algorithms_root,
            text(&selected, "algorithm_artifact")?,
        )
        .map_err(|_| "RESEARCH_ALGORITHM_INSTALLATION_CHANGED")?;
        let original = &o.outputs["ready"]["prepared_inputs"];
        let mut writer = self.writer.lock().await;
        let client = writer
            .as_mut()
            .ok_or("PRODUCT_AUTHORITY_UNAVAILABLE")?
            .client_mut()
            .await
            .map_err(|_| "PRODUCT_AUTHORITY_UNAVAILABLE")?;
        let mut composer = Composer::new(client);
        let (resolved, context) = composer
            .resolve_retained(&original["composition"], runtime, &installation)
            .await?;
        if context.record() != ResearchContext::new(o.request.strategy()?.context.clone())?.record()
        {
            return Err(INVALID.into());
        }
        let (prepared, specification) = PreparedInputs::prepare_strategy(
            &mut composer,
            resolved,
            &context,
            &installation,
            &datasets,
            &materialized,
        )
        .await?;
        if prepared.record() != original
            || specification.record()
                != &o.outputs["ready"]["prepared_study"]["request"]["specification"]
        {
            return Err(INVALID.into());
        }
        Ok(prepared)
    }
    pub(super) async fn confirm_strategy_preparation_body(
        self: &Arc<Self>,
        o: Operation,
        human: human_access::Session,
        expected: &str,
    ) -> Result<Value> {
        let source = o.source()?;
        let (a, s, selection) = self.preparation_sources(&human, &source, true).await?;
        let prepared = self.strategy_ready_inputs(&o).await?;
        let context = Context {
            human_authority: &self.human_access,
            human: &human,
            source_authority: &a,
            source: &s,
            selection: &selection,
        };
        let study = research_submission::strategy::restore_study(
            &context,
            &o.outputs["ready"]["prepared_study"],
            expected,
        )?;
        let datasets = Datasets::open(
            &self
                .research_preparation_config
                .research_root
                .join("datasets"),
            8192,
            8 * 1024 * 1024,
        )?;
        let novelty = crate::bootstrap::research_namespace::novelty(
            self.research_preparation_config
                .research_root
                .parent()
                .ok_or(INVALID)?,
        )?;
        let run = {
            let mut writer = self.writer.lock().await;
            let session = writer.as_mut().ok_or("PRODUCT_AUTHORITY_UNAVAILABLE")?;
            research_submission::strategy::submit_prepared(
                session,
                &novelty,
                &context,
                (&study, expected, &o),
                &prepared,
                &datasets,
                now().map_err(|e| e.code())?,
            )
            .await?
        };
        if !self.wake_research_after_commit() {
            return Ok(json!({"run_id":run.run_id(),"worker_state":"UNAVAILABLE"}));
        }
        Ok(json!({"run_id":run.run_id()}))
    }
}
