//! Explicit Human preparation of one exact Study; no Agent execution permission.
use crate::{
    application::{
        command::CommandId,
        factor_content::hash,
        factor_studies::{PrepareInput, Source},
        research_admission::{self, PreparationError},
        research_run::Specification,
        source_access::{Authority, Permission, Session},
    },
    persistence::{
        private_factor_postgres,
        research_dataset::Store as Datasets,
        research_preparation::{Operation, Preparations, State, child_command, validated_inputs},
        research_runtime::{Registry, RuntimeInputHold},
        research_submission::{self, Context, Request, SubmissionOutcome},
    },
    security::{
        human_access,
        protected_files::{self, FilePolicy},
    },
    transport::{
        host::{Failure, Host, now},
        host_research_inputs::{ResearchInputOutcome, ResearchInputRequest},
    },
    workers::research_environment,
};
use onlyalpha_calculation_bridge::ChartInstallation;
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBarSemantic, time::OnlyTimestamp};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    path::PathBuf,
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::sync::Notify;
type Result<T> = std::result::Result<T, PreparationError>;
const INVALID: &str = "RESEARCH_PREPARATION_INPUT_MISMATCH";
const CANCELLED: &str = "RESEARCH_PREPARATION_CANCEL_REQUESTED";
#[derive(Clone)]
pub(crate) struct PreparationConfig {
    pub runtime_root: PathBuf,
    pub research_root: PathBuf,
    pub release_root: PathBuf,
    pub algorithms_root: PathBuf,
    pub release_manifest_fingerprint: String,
    pub native_version: String,
}
struct PreparationReservation {
    host: Arc<Host>,
    key: String,
    wake: Arc<Notify>,
    transferred: bool,
}
impl Drop for PreparationReservation {
    fn drop(&mut self) {
        if !self.transferred {
            let mut owners = self
                .host
                .research_preparation_running
                .lock()
                .unwrap_or_else(|e| e.into_inner());
            if owners
                .get(&self.key)
                .is_some_and(|current| Arc::ptr_eq(current, &self.wake))
            {
                owners.remove(&self.key);
            }
        }
    }
}
fn failure(error: PreparationError) -> Failure {
    Failure::unavailable(error.code())
}
fn text<'a>(v: &'a Value, k: &str) -> Result<&'a str> {
    v[k].as_str().ok_or_else(|| INVALID.into())
}
fn timestamp(ns: u64) -> Result<String> {
    OnlyTimestamp::from_unix_nanos(ns.into())
        .to_datetime_exact()
        .map(|t| t.to_string())
        .map_err(|_| INVALID.into())
}
fn release(config: &PreparationConfig) -> Result<Value> {
    let directory = protected_files::open_directory(&config.release_root)
        .map_err(|_| "RESEARCH_RELEASE_UNAVAILABLE")?;
    let raw = protected_files::read_file_at(
        &directory,
        "manifest.json".as_ref(),
        FilePolicy::HistoryDocument,
        8 * 1024 * 1024,
    )
    .map_err(|_| "RESEARCH_RELEASE_UNAVAILABLE")?;
    let digest = Sha256::digest(&raw)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect::<String>();
    if digest != config.release_manifest_fingerprint {
        return Err("RESEARCH_RELEASE_CHANGED".into());
    }
    let value: Value = serde_json::from_slice(&raw).map_err(|_| INVALID)?;
    if value["schema_version"] != 2
        || value["runtime_root"] != config.release_root.to_str().ok_or(INVALID)?
        || value["version"] != config.native_version
    {
        return Err(INVALID.into());
    }
    Ok(value)
}
impl Host {
    fn preparation_owner<'a>(&self, human: &'a human_access::Session) -> Result<&'a str> {
        self.human_access
            .check_session(human)
            .map_err(|_| "RESEARCH_HUMAN_AUTHORIZATION_REQUIRED")?;
        human
            .subject_id()
            .map_err(|_| "RESEARCH_HUMAN_AUTHORIZATION_REQUIRED".into())
    }
    async fn preparation_query(&self, command: &CommandId, owner: &str) -> Result<Operation> {
        let mut writer = self.writer.lock().await;
        let client = writer
            .as_mut()
            .ok_or("PRODUCT_AUTHORITY_UNAVAILABLE")?
            .client_mut()
            .await
            .map_err(|_| "PRODUCT_AUTHORITY_UNAVAILABLE")?;
        Preparations::new(client)
            .query(command, owner)
            .await
            .map_err(Into::into)
    }
    async fn preparation_progress(
        &self,
        o: &Operation,
        state: State,
        phase: &str,
        outputs: &Value,
        detail: &Value,
    ) -> Result<Operation> {
        let mut writer = self.writer.lock().await;
        let client = writer
            .as_mut()
            .ok_or("PRODUCT_AUTHORITY_UNAVAILABLE")?
            .client_mut()
            .await
            .map_err(|_| "PRODUCT_AUTHORITY_UNAVAILABLE")?;
        Preparations::new(client)
            .progress(o, state, phase, outputs, detail)
            .await
            .map_err(Into::into)
    }
    pub(crate) async fn research_preparation(
        self: &Arc<Self>,
        human: human_access::Session,
        command: &CommandId,
    ) -> std::result::Result<Value, Failure> {
        let owner = self.preparation_owner(&human).map_err(failure)?;
        // Observation must not queue behind the producer's physical input work.
        // Keep internal checkpoints on their original writer and use the retained
        // read-only Product connection for this public owning query.
        let o = {
            let mut reader = self.reader.lock().await;
            let client = reader
                .as_mut()
                .ok_or_else(|| failure("PRODUCT_READ_DRIVER_UNAVAILABLE".into()))?;
            Preparations::new(client)
                .query(command, owner)
                .await
                .map_err(|e| failure(e.into()))?
        };
        self.preparation_view(&o, &human).await.map_err(failure)
    }
    async fn preparation_view(
        &self,
        o: &Operation,
        human: &human_access::Session,
    ) -> Result<Value> {
        let mut view = o.view();
        let future = CommandId::new(&o.request.research_command_id).map_err(|_| INVALID)?;
        if o.outputs.get("ready").is_some() {
            let advice: crate::application::factor_studies::Advice =
                serde_json::from_value(o.accepted["study"]["advice"].clone())
                    .map_err(|_| INVALID)?;
            let (a, s, selection) = self
                .preparation_sources(human, &advice.source, false)
                .await?;
            let context = Context {
                human_authority: &self.human_access,
                human,
                source_authority: &a,
                source: &s,
                selection: &selection,
            };
            let record = &o.outputs["ready"]["prepared_study"];
            let expected = text(&o.outputs["ready"], "prepared_study_fingerprint")?;
            let proposal = research_submission::restore_study(&context, record, expected)?;
            let mut reader = self.reader.lock().await;
            let client = reader.as_mut().ok_or("PRODUCT_READ_DRIVER_UNAVAILABLE")?;
            let outcome =
                research_submission::submission_outcome(client, &context, &proposal).await?;
            match outcome {
                SubmissionOutcome::NotSubmitted => {
                    view["research_outcome"] = json!("NOT_SUBMITTED")
                }
                SubmissionOutcome::Pending => {
                    view["research_outcome"] = json!("OUTCOME_UNKNOWN");
                    return Ok(view);
                }
                SubmissionOutcome::Accepted(run) => {
                    view["research_outcome"] = json!("ACCEPTED");
                    view["run_id"] = json!(run.run_id());
                    return Ok(view);
                }
            }
            let readiness = async {
                let authority = crate::bootstrap::research_namespace::novelty(
                    self.research_preparation_config
                        .research_root
                        .parent()
                        .ok_or(INVALID)?,
                )?;
                let spec: Specification =
                    serde_json::from_value(record["request"]["specification"].clone())
                        .map_err(|_| INVALID)?;
                let group = authority
                    .retained_group(
                        client,
                        &future,
                        &[spec.subject()?],
                        text(&record["request"], "policy_id")?,
                        text(&record["request"], "policy_version")?,
                    )
                    .await?;
                if group["group_fingerprint"] != record["decision_group_fingerprint"] {
                    return Err(INVALID.into());
                }
                retained_ready(&self.research_preparation_config, o)?;
                Ok::<(), PreparationError>(())
            }
            .await;
            view["readiness"] = match readiness {
                Ok(()) => json!({"state":"VERIFIED","code":null}),
                Err(error) => json!({"state":"UNAVAILABLE","code":error.code()}),
            };
        } else {
            use crate::application::command::{Binding, CommandKind};
            let mut reader = self.reader.lock().await;
            let client = reader.as_mut().ok_or("PRODUCT_READ_DRIVER_UNAVAILABLE")?;
            let tx = client
                .transaction()
                .await
                .map_err(|_| "RESEARCH_PREPARATION_UNAVAILABLE")?;
            crate::persistence::postgres::bounds(&tx)
                .await
                .map_err(|_| "RESEARCH_PREPARATION_UNAVAILABLE")?;
            crate::persistence::postgres::Commands::lock_command(&tx, &future)
                .await
                .map_err(|_| "RESEARCH_PREPARATION_UNAVAILABLE")?;
            match crate::persistence::postgres::Commands::verify_binding_in_transaction(
                &tx, &future,
            )
            .await
            .map_err(|_| "RESEARCH_PREPARATION_UNAVAILABLE")?
            {
                Binding::None => {
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
                Binding::Admitted(a) if a.kind() == CommandKind::CreateResearchRun => {
                    view["research_outcome"] = json!("OUTCOME_UNKNOWN")
                }
                _ => return Err("RESEARCH_PREPARATION_CORRUPT".into()),
            }
            tx.commit()
                .await
                .map_err(|_| "RESEARCH_PREPARATION_UNAVAILABLE")?;
        }
        Ok(view)
    }
    pub(crate) async fn accept_research_preparation(
        self: &Arc<Self>,
        command: CommandId,
        human: human_access::Session,
        input: PrepareInput,
    ) -> std::result::Result<Value, Failure> {
        let owner = self.preparation_owner(&human).map_err(failure)?.to_owned();
        let original = {
            let mut writer = self.writer.lock().await;
            let client = writer
                .as_mut()
                .ok_or_else(|| failure("PRODUCT_AUTHORITY_UNAVAILABLE".into()))?
                .client_mut()
                .await
                .map_err(|_| failure("PRODUCT_AUTHORITY_UNAVAILABLE".into()))?;
            Preparations::new(client)
                .existing(&command, &owner, &input)
                .await
                .map_err(|e| failure(e.into()))?
        };
        if let Some(original) = original {
            return Ok(original.view());
        }
        if input.release_manifest_fingerprint
            != self
                .research_preparation_config
                .release_manifest_fingerprint
        {
            return Err(failure("RESEARCH_RELEASE_CHANGED".into()));
        }
        release(&self.research_preparation_config).map_err(failure)?;
        let o = {
            let mut writer = self.writer.lock().await;
            let client = writer
                .as_mut()
                .ok_or_else(|| failure("PRODUCT_AUTHORITY_UNAVAILABLE".into()))?
                .client_mut()
                .await
                .map_err(|_| failure("PRODUCT_AUTHORITY_UNAVAILABLE".into()))?;
            Preparations::new(client)
                .accept(&command, &owner, input, now()?)
                .await
                .map_err(|e| failure(e.into()))?
        };
        if o.state == State::Accepted {
            self.start_preparation(o, human).await.map_err(failure)
        } else {
            Ok(o.view())
        }
    }
    pub(crate) async fn resume_research_preparation(
        self: &Arc<Self>,
        human: human_access::Session,
        command: &CommandId,
        revision: i64,
    ) -> std::result::Result<Value, Failure> {
        let owner = self.preparation_owner(&human).map_err(failure)?.to_owned();
        let accepted = self
            .preparation_query(command, &owner)
            .await
            .map_err(failure)?;
        let existing = {
            self.research_preparation_running
                .lock()
                .map_err(|_| failure("RESEARCH_PREPARATION_OWNER_UNKNOWN".into()))?
                .get(command.value())
                .cloned()
        };
        if let Some(wake) = existing {
            wake.notify_one();
            return Ok(self
                .preparation_query(command, &owner)
                .await
                .map_err(failure)?
                .view());
        }
        pinned_release(&self.research_preparation_config, &accepted).map_err(failure)?;
        let o = {
            let mut writer = self.writer.lock().await;
            let client = writer
                .as_mut()
                .ok_or_else(|| failure("PRODUCT_AUTHORITY_UNAVAILABLE".into()))?
                .client_mut()
                .await
                .map_err(|_| failure("PRODUCT_AUTHORITY_UNAVAILABLE".into()))?;
            Preparations::new(client)
                .resume(command, &owner, revision)
                .await
                .map_err(|e| failure(e.into()))?
        };
        if matches!(
            o.state,
            State::Ready | State::Cancelled | State::CancelRequested
        ) {
            return Ok(o.view());
        }
        self.start_preparation(o, human).await.map_err(failure)
    }
    pub(crate) async fn cancel_research_preparation(
        self: &Arc<Self>,
        human: human_access::Session,
        cancel: CommandId,
        command: &CommandId,
        revision: i64,
    ) -> std::result::Result<Value, Failure> {
        let owner = self.preparation_owner(&human).map_err(failure)?.to_owned();
        let o = {
            let mut writer = self.writer.lock().await;
            let client = writer
                .as_mut()
                .ok_or_else(|| failure("PRODUCT_AUTHORITY_UNAVAILABLE".into()))?
                .client_mut()
                .await
                .map_err(|_| failure("PRODUCT_AUTHORITY_UNAVAILABLE".into()))?;
            Preparations::new(client)
                .cancel(&cancel, command, &owner, revision, now()?)
                .await
                .map_err(|e| failure(e.into()))?
        };
        if let Some(wake) = self
            .research_preparation_running
            .lock()
            .map_err(|_| failure("RESEARCH_PREPARATION_OWNER_UNKNOWN".into()))?
            .get(command.value())
        {
            wake.notify_one();
        }
        Ok(o.view())
    }
    async fn start_preparation(
        self: &Arc<Self>,
        o: Operation,
        human: human_access::Session,
    ) -> Result<Value> {
        let wake = Arc::new(Notify::new());
        let key = o.command.value().to_owned();
        {
            let mut owned = self
                .research_preparation_running
                .lock()
                .map_err(|_| "RESEARCH_PREPARATION_OWNER_UNKNOWN")?;
            if let Some(original) = owned.get(&key) {
                original.notify_one();
                return Ok(o.view());
            }
            owned.insert(key.clone(), wake.clone());
        }
        let mut reservation = PreparationReservation {
            host: Arc::clone(self),
            key: key.clone(),
            wake: wake.clone(),
            transferred: false,
        };
        let host = Arc::clone(self);
        let view = o.view();
        self.stream_tasks.lock().await.spawn(async move {
            let result = match host.preparation_body(o.clone(), human).await {
                Ok(()) => Ok(()),
                Err(error) => host.finish_preparation_error(&o, error, &wake).await,
            };
            host.research_preparation_running
                .lock()
                .unwrap_or_else(|e| e.into_inner())
                .remove(&key);
            result
        });
        reservation.transferred = true;
        Ok(view)
    }
    async fn finish_preparation_error(
        &self,
        o: &Operation,
        error: PreparationError,
        wake: &Notify,
    ) -> std::result::Result<(), Failure> {
        let code = error.code();
        let must_drain = error.recovery_owner().is_some()
            || code == "RESEARCH_PREPARATION_PROCESS_OUTCOME_UNKNOWN";
        let unknown = code.contains("UNKNOWN") || must_drain;
        let current = self.preparation_query(&o.command, &o.owner).await;
        let recorded = match current {
            Ok(current) if matches!(current.state, State::Ready | State::Cancelled) => Ok(current),
            Ok(current) => {
                let state = if unknown {
                    State::Unknown
                } else if current.outputs.get("cancellation").is_some() {
                    State::Cancelled
                } else {
                    State::Blocked
                };
                let phase = if state == State::Cancelled {
                    "OWNER_DRAINED"
                } else {
                    "STOPPED"
                };
                self.preparation_progress(
                    &current,
                    state,
                    phase,
                    &current.outputs,
                    &json!({"code":code}),
                )
                .await
            }
            Err(e) => Err(e),
        };
        if must_drain {
            self.drain_preparation_owner(error, wake).await;
        }
        let current = recorded.map_err(failure)?;
        if current.outputs.get("cancellation").is_some() && current.state != State::Cancelled {
            let fresh = self
                .preparation_query(&o.command, &o.owner)
                .await
                .map_err(failure)?;
            self.preparation_progress(
                &fresh,
                State::Cancelled,
                "OWNER_DRAINED",
                &fresh.outputs,
                &json!({"code":code}),
            )
            .await
            .map_err(failure)?;
        }
        Ok(())
    }
    async fn drain_preparation_owner(&self, error: PreparationError, wake: &Notify) {
        loop {
            if let Some(owner) = error.recovery_owner() {
                let owner = owner.clone();
                if matches!(
                    tokio::task::spawn_blocking(move || owner.drain()).await,
                    Ok(Ok(()))
                ) {
                    return;
                }
            }
            // No child replacement or automatic retry after uncertainty. Retain original owner.
            wake.notified().await;
        }
    }
    async fn preparation_checkpoint(
        &self,
        o: &Operation,
        human: &human_access::Session,
    ) -> Result<Operation> {
        self.preparation_owner(human)?;
        let current = self.preparation_query(&o.command, &o.owner).await?;
        if matches!(current.state, State::CancelRequested | State::Cancelled)
            || current.outputs.get("cancellation").is_some()
        {
            return Err(CANCELLED.into());
        }
        if current.accepted != o.accepted {
            return Err(INVALID.into());
        }
        {
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
            let study = crate::persistence::factor_studies::current(
                &tx,
                &current.request.study_proposal_fingerprint,
                &current.owner,
            )
            .await?;
            if study != current.accepted["study"] {
                return Err("RESEARCH_PREPARATION_STUDY_STALE".into());
            }
            tx.commit()
                .await
                .map_err(|_| "RESEARCH_PREPARATION_UNAVAILABLE")?;
        }
        Ok(current)
    }
}

impl Host {
    async fn preparation_sources(
        &self,
        human: &human_access::Session,
        source: &Source,
        check: bool,
    ) -> Result<(
        Authority,
        Session,
        crate::application::source_access::Selection,
    )> {
        let owner = self.preparation_owner(human)?;
        let (authority, session) = {
            let issuer = self.issuer.lock().await;
            (issuer.authority.clone(), issuer.session.clone())
        };
        let selection = source.selection()?;
        if check {
            authority
                .check_session(&session)
                .map_err(|_| "RESEARCH_SOURCE_ACCESS_DENIED")?;
            if session
                .subject_id()
                .map_err(|_| "RESEARCH_SOURCE_ACCESS_DENIED")?
                != owner
            {
                return Err("RESEARCH_SOURCE_ACCESS_DENIED".into());
            }
            session
                .require_selection(&selection, Permission::ClosedHistory)
                .map_err(|_| "RESEARCH_SOURCE_ACCESS_DENIED")?;
        }
        Ok((authority, session, selection))
    }
    async fn publish_preparation_revision(&self, o: &Operation) -> Result<Value> {
        let expected = validated_inputs(&o.accepted["study"], &o.accepted["factor_confirmation"])?;
        let id = expected.draft.factor_id();
        let child = child_command(&o.command, "PUBLISH_CONFIRMED_FACTOR")?;
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
        crate::persistence::postgres::bounds(&tx)
            .await
            .map_err(|_| "RESEARCH_PREPARATION_UNAVAILABLE")?;
        let current = crate::persistence::factor_studies::current(
            &tx,
            &o.request.study_proposal_fingerprint,
            &o.owner,
        )
        .await?;
        if current != o.accepted["study"] {
            return Err(INVALID.into());
        }
        let state = private_factor_postgres::state(&tx, id)
            .await
            .map_err(|e| e.code())?;
        if state["draft"] != *expected.draft.record() {
            return Err("RESEARCH_FACTOR_CONFIRMATION_MISMATCH".into());
        }
        let target = expected.revision["revision_fingerprint"]
            .as_str()
            .ok_or(INVALID)?;
        let retained = state["revisions"]
            .as_array()
            .ok_or(INVALID)?
            .iter()
            .any(|r| r["revision"] == expected.revision);
        let result = if retained {
            let rows=tx.query("SELECT command_id::text FROM private_factor_authoring_outcome WHERE factor_id=$1 AND payload->'result'->'revision'->>'revision_fingerprint'=$2 LIMIT 2",&[&id,&target]).await.map_err(|_|"RESEARCH_PREPARATION_UNAVAILABLE")?;
            if rows.len() != 1 {
                return Err("RESEARCH_FACTOR_REVISION_PROVENANCE_UNAVAILABLE".into());
            }
            let original = CommandId::new(&rows[0].try_get::<_, String>(0).map_err(|_| INVALID)?)
                .map_err(|_| INVALID)?;
            private_factor_postgres::bound(&tx, id, &original, None)
                .await
                .map_err(|e| e.code())?
                .ok_or(INVALID)?
        } else {
            private_factor_postgres::apply_in_transaction(&tx,&child,id,json!({"operation":"PUBLISH","factor_id":id,"expected_draft_fingerprint":expected.draft.fingerprint().map_err(|e|e.code())?}),None,&now().map_err(|e|e.code())?.to_string()).await.map_err(|e|e.code())?
        };
        if result["result"]["revision"] != expected.revision {
            return Err(INVALID.into());
        }
        tx.commit()
            .await
            .map_err(|_| "RESEARCH_PREPARATION_OUTCOME_UNKNOWN")?;
        Ok(result)
    }
    async fn preparation_body(
        self: &Arc<Self>,
        original: Operation,
        human: human_access::Session,
    ) -> Result<()> {
        let config = self.research_preparation_config.clone();
        pinned_release(&config, &original)?;
        let mut o = self.preparation_checkpoint(&original, &human).await?;
        o = self
            .preparation_progress(&o, State::Running, "VALIDATING", &o.outputs, &Value::Null)
            .await?;
        let inputs = validated_inputs(&o.accepted["study"], &o.accepted["factor_confirmation"])?;
        let (source_authority, source_session, selection) = self
            .preparation_sources(&human, &inputs.advice.source, true)
            .await?;
        let reference = crate::application::source_access::Reference::new(
            &inputs.advice.source.integration_id,
            &inputs.advice.source.integration_revision_fingerprint,
            Some(&inputs.advice.source.expected_type_id),
        )
        .map_err(|e| e.code())?;
        let (resolved, _) = self.resolve(&reference).await.map_err(|e| e.code())?;
        if resolved.selection() != &selection {
            return Err("RESEARCH_SOURCE_ACCESS_DENIED".into());
        }
        let manifest = release(&config)?;
        let installation = ChartInstallation::open(
            &config.algorithms_root,
            text(&manifest, "algorithm_artifact")?,
        )
        .map_err(|_| "RESEARCH_ALGORITHM_INSTALLATION_CHANGED")?;
        if o.outputs.get("environment").is_none() {
            let publication = self.publish_preparation_revision(&o).await?;
            o = self.preparation_checkpoint(&o, &human).await?;
            let background = config.clone();
            let study = o.accepted["study"].clone();
            let confirmed = o.accepted["factor_confirmation"].clone();
            let generation = tokio::task::spawn_blocking(move || {
                let prepared = validated_inputs(&study, &confirmed)?;
                let selected = release(&background)?;
                let installation = ChartInstallation::open(
                    &background.algorithms_root,
                    text(&selected, "algorithm_artifact")?,
                )
                .map_err(|_| "RESEARCH_ALGORITHM_INSTALLATION_CHANGED")?;
                research_environment::prepare(
                    &installation,
                    &background.release_root,
                    &prepared.factor,
                    &prepared.revision,
                    &background.native_version,
                )
            })
            .await
            .map_err(|_| "RESEARCH_PREPARATION_PROCESS_OUTCOME_UNKNOWN")??;
            o = self.preparation_checkpoint(&o, &human).await?;
            let generation_id =
                text(generation.manifest(), "runtime_generation_fingerprint")?.to_owned();
            let installed = generation.proof().clone();
            let root = config.runtime_root.clone();
            let command = o.command.clone();
            let actor = o.owner.clone();
            let expected = o.request.expected_active_generation.clone();
            let initialize = o.request.initialize_fresh_runtime;
            let future = CommandId::new(&o.request.research_command_id).map_err(|_| INVALID)?;
            let work = research_submission::run_id(&future);
            let at = now().map_err(|e| e.code())?;
            let generation_for_publication = generation_id.clone();
            let publication_for_install = publication.clone();
            let (activation, binding, activation_disposition) = {
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
                let current = crate::persistence::factor_studies::current(
                    &tx,
                    &o.request.study_proposal_fingerprint,
                    &o.owner,
                )
                .await?;
                if current != o.accepted["study"] {
                    return Err("RESEARCH_PREPARATION_STUDY_STALE".into());
                }
                let known_runtime =
                    crate::persistence::research_preparation::runtime_history_exists(&tx).await?;
                let result =
                    tokio::task::spawn_blocking(move || -> Result<(Value, Value, String)> {
                        let mut registry = match protected_files::open_directory(&root) {
                            Ok(_) => Registry::open_existing(&root)?,
                            Err(protected_files::ReadError::Missing) if initialize => {
                                crate::persistence::research_preparation::guard_fresh_runtime(
                                    known_runtime,
                                )?;
                                Registry::initialize_fresh(&root)?
                            }
                            Err(_) => return Err("RESEARCH_RUNTIME_UNAVAILABLE".into()),
                        };
                        let prior = original_activation(&root, &command)?;
                        if prior.is_none()
                            && registry.snapshot()["active_for_new_work"] != json!(expected)
                        {
                            return Err("GENERATION_ACTIVATION_CONFLICT".into());
                        }
                        generation.publish(
                            &mut registry,
                            prepared_source(&publication_for_install)?,
                            &actor,
                            at,
                        )?;
                        let (activation, disposition) = if prior.is_some() {
                            // Exact command replay stays original even if a later command changed current.
                            (
                                registry.activate(
                                    &command,
                                    &generation_for_publication,
                                    expected.as_deref(),
                                    &actor,
                                    at,
                                )?,
                                "ACTIVATED",
                            )
                        } else if expected.as_deref() == Some(&generation_for_publication)
                            && registry.snapshot()["active_for_new_work"]
                                == generation_for_publication
                        {
                            let event = last_activation(&root)?
                                .ok_or("RESEARCH_ACTIVATION_PROOF_UNAVAILABLE")?;
                            if event["generation_fingerprint"] != generation_for_publication {
                                return Err(INVALID.into());
                            }
                            (event, "REUSED_CURRENT")
                        } else {
                            (
                                registry.activate(
                                    &command,
                                    &generation_for_publication,
                                    expected.as_deref(),
                                    &actor,
                                    at,
                                )?,
                                "ACTIVATED",
                            )
                        };
                        let binding = registry.bind_new_work_exact(
                            &work,
                            &generation_for_publication,
                            "research",
                            &actor,
                            at,
                        )?;
                        Ok((activation, binding, disposition.into()))
                    })
                    .await
                    .map_err(|_| "RESEARCH_PREPARATION_OUTCOME_UNKNOWN")??;
                tx.commit()
                    .await
                    .map_err(|_| "RESEARCH_PREPARATION_OUTCOME_UNKNOWN")?;
                result
            };
            let mut outputs = o.outputs.clone();
            outputs["environment"] = json!({"runtime_generation_fingerprint":generation_id,"installed_proof_fingerprint":installed["installed_proof_fingerprint"],"installed_proof":installed,"publication":publication,"activation":activation,"activation_disposition":activation_disposition,"binding":binding});
            o = self
                .preparation_progress(&o, State::Running, "INPUTS", &outputs, &Value::Null)
                .await?;
        }
        let current = validated_inputs(&o.accepted["study"], &o.accepted["factor_confirmation"])?;
        let datasets = Datasets::open(
            &config.research_root.join("datasets"),
            8192,
            8 * 1024 * 1024,
        )?;
        let semantic =
            OnlyBarSemantic::fixed_duration(current.advice.timeframe_minutes.into(), None)
                .map_err(|_| INVALID)?;
        let definition = json!({"schema_version":2,"dataset_type":"HISTORICAL_BAR","instruments":[current.advice.source.instrument_id],"bar_semantic":semantic.to_record(),"time_range":{"start":timestamp(current.window.dataset_start_ns())?,"end":timestamp(current.window.dataset_end_ns())?},"quality_policy":"STRICT","closed_only":true});
        let acquired = self
            .research_inputs(ResearchInputRequest {
                human: human.clone(),
                session: &source_session,
                source: &current.advice.source,
                window: &current.window,
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
        let root = config.runtime_root.clone();
        let o_for_preflight = o.clone();
        let background = config.clone();
        let materialization = materialized.materialized.lineage()["materialization_id"]
            .as_str()
            .ok_or(INVALID)?
            .to_owned();
        let prepared = tokio::task::spawn_blocking(
            move || -> Result<crate::application::research_admission::PreparedInputs> {
                let original = validated_inputs(
                    &o_for_preflight.accepted["study"],
                    &o_for_preflight.accepted["factor_confirmation"],
                )?;
                let datasets = Datasets::open(
                    &background.research_root.join("datasets"),
                    8192,
                    8 * 1024 * 1024,
                )?;
                let materialized = crate::application::research_dataset::MaterializedDataset::load(
                    &datasets,
                    &materialization,
                )?;
                let runtime = RuntimeInputHold::open(
                    &root,
                    &research_submission::run_id(
                        &CommandId::new(&o_for_preflight.request.research_command_id)
                            .map_err(|_| INVALID)?,
                    ),
                    "research",
                    text(
                        &o_for_preflight.outputs["environment"],
                        "runtime_generation_fingerprint",
                    )?,
                )?;
                let selected = release(&background)?;
                let installation = ChartInstallation::open(
                    &background.algorithms_root,
                    text(&selected, "algorithm_artifact")?,
                )
                .map_err(|_| "RESEARCH_ALGORITHM_INSTALLATION_CHANGED")?;
                research_admission::prepare(
                    runtime,
                    &installation,
                    &original.factor,
                    &original.revision,
                    &original.window,
                    &datasets,
                    &materialized,
                )
            },
        )
        .await
        .map_err(|_| "RESEARCH_PREPARATION_PROCESS_OUTCOME_UNKNOWN")??;
        let spec = Specification {
            schema_version: 4,
            kind: "TIME_SERIES_FACTOR_RESEARCH".into(),
            candidate: json!({"hypothesis":o.accepted["factor_confirmation"]["snapshot"]["preview"]["hypothesis"],"expression":o.accepted["factor_confirmation"]["snapshot"]["preview"]["expression"]}),
            draft: current.draft.record().clone(),
            revision: current.revision,
            study: current.advice.study()?,
            dataset_snapshot_fingerprint: materialized
                .materialized
                .verified()
                .dataset()
                .snapshot_fingerprint()
                .into(),
            runtime_generation_fingerprint: text(
                &o.outputs["environment"],
                "runtime_generation_fingerprint",
            )?
            .into(),
            catalog_generation_fingerprint: text(
                prepared.runtime_manifest(),
                "catalog_generation_fingerprint",
            )?
            .into(),
            algorithm_artifact_fingerprint: installation.artifact_fingerprint().into(),
            execution_binding: prepared.record()["execution_binding"].clone(),
        };
        let policy = crate::bootstrap::research_namespace::policy();
        let authority = crate::bootstrap::research_namespace::novelty(
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
        let (proposal, actionable) = {
            let mut writer = self.writer.lock().await;
            let client = writer
                .as_mut()
                .ok_or("PRODUCT_AUTHORITY_UNAVAILABLE")?
                .client_mut()
                .await
                .map_err(|_| "PRODUCT_AUTHORITY_UNAVAILABLE")?;
            let proposal = research_submission::prepare_study(
                client,
                &authority,
                &context,
                CommandId::new(&o.request.research_command_id).map_err(|_| INVALID)?,
                Request {
                    schema_version: 1,
                    factor_proposal_fingerprint: text(
                        &o.accepted["study"],
                        "factor_proposal_fingerprint",
                    )?
                    .into(),
                    parent_run_id: None,
                    policy_id: text(&policy, "policy_id")?.into(),
                    policy_version: text(&policy, "policy_version")?.into(),
                    specification: spec,
                },
                &prepared,
                &datasets,
            )
            .await?;
            proposal.into_parts()
        };
        let mut outputs = o.outputs.clone();
        outputs["ready"] = json!({"preparation_command_id":o.command.value(),"study_proposal_fingerprint":o.request.study_proposal_fingerprint,"factor_confirmation_command_id":o.accepted["factor_confirmation"]["confirmation_command_id"],"revision_fingerprint":proposal.record()?["request"]["specification"]["revision"]["revision_fingerprint"],"runtime_generation_fingerprint":o.outputs["environment"]["runtime_generation_fingerprint"],"installed_proof_fingerprint":o.outputs["environment"]["installed_proof_fingerprint"],"dataset_materialization_id":materialized.materialized.lineage()["materialization_id"],"source_selection":materialized.selection,"prepared_study":proposal.record()?,"prepared_study_fingerprint":proposal.fingerprint()?,"prepared_inputs":prepared.record()});
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
}
fn prepared_source(publication: &Value) -> Result<&[u8]> {
    publication["result"]["revision"]["source_text"]
        .as_str()
        .map(str::as_bytes)
        .ok_or_else(|| INVALID.into())
}

fn installed_proof(
    config: &PreparationConfig,
    o: &Operation,
    hold: &RuntimeInputHold,
) -> Result<()> {
    if hold.binding() != &o.outputs["environment"]["binding"] {
        return Err(INVALID.into());
    }
    retained_environment(config, o)?;
    hold.verify()?;
    Ok(())
}
fn retained_environment(config: &PreparationConfig, o: &Operation) -> Result<()> {
    Registry::inspect(&config.runtime_root)?;
    let environment = &o.outputs["environment"];
    let generation = text(environment, "runtime_generation_fingerprint")?;
    let proof = text(environment, "installed_proof_fingerprint")?;
    if !crate::is_sha256_hex(generation) || !crate::is_sha256_hex(proof) {
        return Err(INVALID.into());
    }
    let root = crate::security::immutable_json::Directory::open(&config.runtime_root)?;
    let parent = root.path(&["runtime-generation-installed-proof", generation], false)?;
    let bytes = protected_files::read_file_at(
        &parent.fd,
        format!("{proof}.json").as_ref(),
        FilePolicy::HistoryDocument,
        8 * 1024 * 1024,
    )
    .map_err(|_| "RESEARCH_INSTALLED_PROOF_UNAVAILABLE")?;
    let actual: Value = serde_json::from_slice(&bytes).map_err(|_| INVALID)?;
    let mut identity = actual.clone();
    identity
        .as_object_mut()
        .ok_or(INVALID)?
        .remove("installed_proof_fingerprint");
    if actual != environment["installed_proof"]
        || hash(&identity)? != proof
        || actual["runtime_generation_fingerprint"] != generation
        || actual["contract"] != "ONLYALPHA_INSTALLED_RESEARCH_ENVIRONMENT_V1"
    {
        return Err(INVALID.into());
    }
    let ledger = protected_files::read_file_at(
        &root.fd,
        "generation-events.jsonl".as_ref(),
        FilePolicy::HistoryDocument,
        8 * 1024 * 1024,
    )
    .map_err(|_| "RESEARCH_RUNTIME_UNAVAILABLE")?;
    let mut found = 0;
    let mut work_found = 0;
    for line in std::str::from_utf8(&ledger).map_err(|_| INVALID)?.lines() {
        let event: Value = serde_json::from_str(line).map_err(|_| INVALID)?;
        if event == environment["activation"] {
            found += 1;
        }
        if event == environment["binding"] {
            work_found += 1;
        }
    }
    if found != 1 || work_found != 1 {
        return Err(INVALID.into());
    }
    crate::persistence::research_preparation::validate_activation(o, environment)?;
    Ok(())
}
fn retained_ready(config: &PreparationConfig, o: &Operation) -> Result<()> {
    retained_environment(config, o)?;
    let ready = &o.outputs["ready"];
    let original = &ready["prepared_inputs"];
    let datasets = Datasets::open(
        &config.research_root.join("datasets"),
        8192,
        8 * 1024 * 1024,
    )?;
    let materialized = crate::application::research_dataset::MaterializedDataset::load(
        &datasets,
        text(ready, "dataset_materialization_id")?,
    )?;
    let sealed =
        &materialized.verified().manifest()["provenance"][0]["source_metadata"]["sealed_input"];
    let selection = &ready["source_selection"];
    if materialized.lineage() != &original["dataset_materialization"]
        || materialized.verified().dataset().snapshot_fingerprint()
            != text(original, "dataset_snapshot_fingerprint")?
        || materialized.verified().dataset().construction_fingerprint()
            != text(original, "dataset_construction_fingerprint")?
        || selection["scope"] != sealed["scope"]
        || selection["revision"] != sealed["evidence"]["revision"]
        || selection["seal"] != sealed["evidence"]["seal"]
    {
        return Err(INVALID.into());
    }
    Ok(())
}
fn ready_preflight(
    config: &PreparationConfig,
    o: &Operation,
) -> Result<crate::application::research_admission::PreparedInputs> {
    pinned_release(config, o)?;
    let ready = &o.outputs["ready"];
    let original = validated_inputs(&o.accepted["study"], &o.accepted["factor_confirmation"])?;
    let datasets = Datasets::open(
        &config.research_root.join("datasets"),
        8192,
        8 * 1024 * 1024,
    )?;
    let materialized = crate::application::research_dataset::MaterializedDataset::load(
        &datasets,
        text(ready, "dataset_materialization_id")?,
    )?;
    let work = research_submission::run_id(
        &CommandId::new(&o.request.research_command_id).map_err(|_| INVALID)?,
    );
    let runtime = RuntimeInputHold::open(
        &config.runtime_root,
        &work,
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
    let inputs = research_admission::prepare(
        runtime,
        &installation,
        &original.factor,
        &original.revision,
        &original.window,
        &datasets,
        &materialized,
    )?;
    if inputs.record() != &ready["prepared_inputs"] {
        return Err(INVALID.into());
    }
    Ok(inputs)
}
impl Host {
    pub(crate) async fn confirm_research_preparation(
        self: &Arc<Self>,
        human: human_access::Session,
        command: &CommandId,
        expected: &str,
        original_research_command: &CommandId,
    ) -> std::result::Result<Value, Failure> {
        let owner = self.preparation_owner(&human).map_err(failure)?.to_owned();
        let o = self
            .preparation_query(command, &owner)
            .await
            .map_err(failure)?;
        if o.request.research_command_id != original_research_command.value() {
            return Err(failure("RESEARCH_PREPARATION_COMMAND_CONFLICT".into()));
        }
        let advice = validated_inputs(&o.accepted["study"], &o.accepted["factor_confirmation"])
            .map_err(|e| failure(e.into()))?
            .advice;
        // This original issuer/session tuple is only read for outcome recovery here;
        // no current Source permission or replacement selection is manufactured.
        let (source_authority, source_session, selection) = self
            .preparation_sources(&human, &advice.source, false)
            .await
            .map_err(failure)?;
        let context = Context {
            human_authority: &self.human_access,
            human: &human,
            source_authority: &source_authority,
            source: &source_session,
            selection: &selection,
        };
        let prepared = research_submission::restore_study(
            &context,
            &o.outputs["ready"]["prepared_study"],
            expected,
        )
        .map_err(|e| failure(e.into()))?;
        let outcome = {
            let mut writer = self.writer.lock().await;
            let client = writer
                .as_mut()
                .ok_or_else(|| failure("PRODUCT_AUTHORITY_UNAVAILABLE".into()))?
                .client_mut()
                .await
                .map_err(|_| failure("PRODUCT_AUTHORITY_UNAVAILABLE".into()))?;
            research_submission::submission_outcome(client, &context, &prepared)
                .await
                .map_err(|e| failure(e.into()))?
        };
        match outcome {
            SubmissionOutcome::Accepted(run) => return Ok(json!({"run_id":run.run_id()})),
            SubmissionOutcome::Pending => {
                return Ok(
                    json!({"state":"SUBMISSION_PENDING","research_command_id":o.request.research_command_id}),
                );
            }
            SubmissionOutcome::NotSubmitted => {}
        }
        if o.state != State::Ready {
            return Err(failure("RESEARCH_PREPARATION_NOT_READY".into()));
        }
        let wake = Arc::new(Notify::new());
        let key = command.value().to_owned();
        {
            let mut owners = self
                .research_preparation_running
                .lock()
                .map_err(|_| failure("RESEARCH_PREPARATION_OWNER_UNKNOWN".into()))?;
            if owners.contains_key(&key) {
                return Ok(
                    json!({"state":"SUBMISSION_PENDING","research_command_id":o.request.research_command_id}),
                );
            }
            owners.insert(key.clone(), wake.clone());
        }
        let mut reservation = PreparationReservation {
            host: Arc::clone(self),
            key: key.clone(),
            wake: wake.clone(),
            transferred: false,
        };
        let host = Arc::clone(self);
        let (send, receive) = tokio::sync::oneshot::channel();
        let expected = expected.to_owned();
        self.stream_tasks.lock().await.spawn(async move {
            let result = host
                .confirm_preparation_body(o.clone(), human, &expected)
                .await;
            match result {
                Ok(value) => {
                    let _ = send.send(Ok(value));
                }
                Err(error) => {
                    let code = error.code();
                    let durable_stale = error.recovery_owner().is_none()
                        && matches!(
                            code,
                            "FACTOR_STUDY_PROPOSAL_STALE" | "RESEARCH_PREPARATION_STUDY_STALE"
                        );
                    let deferred = if durable_stale {
                        Some(send)
                    } else {
                        let _ = send.send(Err(code));
                        None
                    };
                    let finished = host.finish_preparation_error(&o, error, &wake).await;
                    host.research_preparation_running
                        .lock()
                        .unwrap_or_else(|e| e.into_inner())
                        .remove(&key);
                    if let Some(send) = deferred {
                        let response = if finished.is_ok() {
                            code
                        } else {
                            "RESEARCH_PREPARATION_OUTCOME_UNKNOWN"
                        };
                        let _ = send.send(Err(response));
                    }
                    return finished;
                }
            }
            host.research_preparation_running
                .lock()
                .unwrap_or_else(|e| e.into_inner())
                .remove(&key);
            Ok(())
        });
        reservation.transferred = true;
        receive
            .await
            .map_err(|_| failure("RESEARCH_PREPARATION_OUTCOME_UNKNOWN".into()))?
            .map_err(|e| failure(e.into()))
    }
    async fn confirm_preparation_body(
        self: &Arc<Self>,
        o: Operation,
        human: human_access::Session,
        expected: &str,
    ) -> Result<Value> {
        self.preparation_owner(&human)?;
        pinned_release(&self.research_preparation_config, &o)?;
        let o = self
            .preparation_progress(&o, State::Running, "CONFIRMING", &o.outputs, &Value::Null)
            .await?;
        let current = validated_inputs(&o.accepted["study"], &o.accepted["factor_confirmation"])?;
        let (source_authority, source_session, selection) = self
            .preparation_sources(&human, &current.advice.source, true)
            .await?;
        {
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
            let accepted = crate::persistence::factor_studies::current(
                &tx,
                &o.request.study_proposal_fingerprint,
                &o.owner,
            )
            .await?;
            if accepted != o.accepted["study"] {
                return Err(INVALID.into());
            }
            tx.commit()
                .await
                .map_err(|_| "RESEARCH_PREPARATION_UNAVAILABLE")?;
        }
        let selected = self.research_preparation_config.clone();
        let original = o.clone();
        let inputs = tokio::task::spawn_blocking(move || ready_preflight(&selected, &original))
            .await
            .map_err(|_| "RESEARCH_PREPARATION_PROCESS_OUTCOME_UNKNOWN")??;
        let datasets = Datasets::open(
            &self
                .research_preparation_config
                .research_root
                .join("datasets"),
            8192,
            8 * 1024 * 1024,
        )?;
        let context = Context {
            human_authority: &self.human_access,
            human: &human,
            source_authority: &source_authority,
            source: &source_session,
            selection: &selection,
        };
        let proposal = research_submission::restore_study(
            &context,
            &o.outputs["ready"]["prepared_study"],
            expected,
        )?;
        let authority = crate::bootstrap::research_namespace::novelty(
            self.research_preparation_config
                .research_root
                .parent()
                .ok_or(INVALID)?,
        )?;
        let run = {
            let mut writer = self.writer.lock().await;
            let client = writer
                .as_mut()
                .ok_or("PRODUCT_AUTHORITY_UNAVAILABLE")?
                .client_mut()
                .await
                .map_err(|_| "PRODUCT_AUTHORITY_UNAVAILABLE")?;
            research_submission::submit_prepared(
                client,
                &authority,
                &context,
                (&proposal, expected, &o),
                &inputs,
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

fn pinned_release(config: &PreparationConfig, o: &Operation) -> Result<()> {
    if config.release_manifest_fingerprint != o.request.release_manifest_fingerprint {
        return Err("RESEARCH_PREPARATION_RELEASE_PIN_UNAVAILABLE".into());
    }
    release(config)?;
    Ok(())
}
fn generation_events(root: &std::path::Path) -> Result<Vec<Value>> {
    let dir = protected_files::open_directory(root).map_err(|_| "RESEARCH_RUNTIME_UNAVAILABLE")?;
    let raw = protected_files::read_file_at(
        &dir,
        "generation-events.jsonl".as_ref(),
        FilePolicy::HistoryDocument,
        8 * 1024 * 1024,
    )
    .map_err(|_| "RESEARCH_RUNTIME_UNAVAILABLE")?;
    std::str::from_utf8(&raw)
        .map_err(|_| INVALID)?
        .lines()
        .map(|line| serde_json::from_str(line).map_err(|_| INVALID.into()))
        .collect()
}
fn original_activation(root: &std::path::Path, command: &CommandId) -> Result<Option<Value>> {
    let mut selected = None;
    for event in generation_events(root)? {
        if event["kind"] == "GenerationActivated" {
            let reason = event["reason"]
                .as_str()
                .and_then(|r| serde_json::from_str::<Value>(r).ok());
            if reason
                .as_ref()
                .is_some_and(|r| r["command_id"] == command.value())
                && selected.replace(event).is_some()
            {
                return Err(INVALID.into());
            }
        }
    }
    Ok(selected)
}
fn last_activation(root: &std::path::Path) -> Result<Option<Value>> {
    Ok(generation_events(root)?
        .into_iter()
        .rfind(|e| e["kind"] == "GenerationActivated"))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn accepted(release: &str) -> Operation {
        Operation {
            command: CommandId::new("00000000-0000-4000-8000-000000000001").unwrap(),
            owner: "owner".into(),
            request: PrepareInput {
                schema_version: 1,
                study_proposal_fingerprint: "a".repeat(64),
                release_manifest_fingerprint: release.into(),
                expected_active_generation: None,
                initialize_fresh_runtime: false,
                research_command_id: "00000000-0000-4000-8000-000000000002".into(),
            },
            accepted: Value::Null,
            revision: 9_007_199_254_740_993,
            state: State::Unknown,
            phase: "STOPPED".into(),
            outputs: json!({}),
            detail: Value::Null,
        }
    }
    #[test]
    fn reuse_current_keeps_original_freeform_activation_reason_without_new_command_authority() {
        let generation = "c".repeat(64);
        let mut o = accepted(&"a".repeat(64));
        o.request.expected_active_generation = Some(generation.clone());
        let mut environment = json!({"runtime_generation_fingerprint":generation,"activation_disposition":"REUSED_CURRENT","activation":{"kind":"GenerationActivated","generation_fingerprint":generation,"reason":"Human selected the verified release","actor":"original-human","expected_current":null}});
        crate::persistence::research_preparation::validate_activation(&o, &environment).unwrap();
        environment["activation_disposition"] = json!("ACTIVATED");
        assert!(
            crate::persistence::research_preparation::validate_activation(&o, &environment)
                .is_err()
        );
        environment["activation"]["reason"] = json!(
            json!({"contract":"ONLYALPHA_GENERATION_COMMAND_V1","command_id":o.command.value()})
                .to_string()
        );
        environment["activation"]["actor"] = json!(o.owner);
        environment["activation"]["expected_current"] = json!(o.request.expected_active_generation);
        crate::persistence::research_preparation::validate_activation(&o, &environment).unwrap();
        environment["activation_disposition"] = json!("REUSED_CURRENT");
        o.request.expected_active_generation = None;
        assert!(
            crate::persistence::research_preparation::validate_activation(&o, &environment)
                .is_err()
        );
    }
    #[test]
    fn resumed_original_release_never_substitutes_current_installation() {
        let o = accepted(&"a".repeat(64));
        let config = PreparationConfig {
            runtime_root: "/missing-runtime".into(),
            research_root: "/missing-research".into(),
            release_root: "/missing-release".into(),
            algorithms_root: "/missing-algorithms".into(),
            release_manifest_fingerprint: "b".repeat(64),
            native_version: "version".into(),
        };
        assert_eq!(
            pinned_release(&config, &o).unwrap_err().code(),
            "RESEARCH_PREPARATION_RELEASE_PIN_UNAVAILABLE"
        );
        assert_eq!(o.view()["research_outcome"], "UNOBSERVED");
        assert_eq!(
            o.view()["readiness"],
            json!({"state":"NOT_APPLICABLE","code":null})
        );
        assert_eq!(o.view()["revision"], "9007199254740993");
        assert!(o.view()["run_id"].is_null());
    }
}
