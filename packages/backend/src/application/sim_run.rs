use super::{command::CommandId, source_access};
use crate::{
    bootstrap::deployment::SemanticStoreId,
    persistence::{
        authority_session::AuthoritySession, postgres,
        research_runtime::{Registry, RuntimeInputHold},
        sim_run::{self, Reservation, StartIntent},
    },
    security::human_access::{Access, Session},
};
use onlyalpha_domain::time::OnlyUtcDateTime;
use onlyalpha_runtime::durability::TradingBinding;
use crate::application::frozen_strategy::FrozenStore;
use crate::persistence::{build_fact_read::BuildFactRead, qualification_decision, strategy_promotion};
use serde::{Deserialize, Serialize};
use std::{path::Path, sync::Arc};
use tokio_postgres::{IsolationLevel, Transaction};

#[derive(Deserialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub(crate) struct StartSelection {
    strategy_fingerprint: String,
    backtest_run_id: String,
    policy_fingerprint: String,
    decision_fingerprint: String,
    promotion_fingerprint: String,
    account_id: String,
    account_revision_fingerprint: String,
    broker_revision_fingerprint: String,
}

#[derive(Debug)]
pub(crate) enum StartError {
    Access(source_access::Error),
    Storage(sim_run::Error),
    Proof(&'static str),
}

#[derive(Serialize, Deserialize, utoipa::ToSchema)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub(crate) enum StartState { Reserved, Accepted }

#[derive(Serialize, Deserialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub(crate) struct StartObservation {
    schema_version: u8,
    command_id: String,
    run_id: String,
    state: StartState,
}

impl StartObservation {
    fn new(original: &Reservation, state: StartState) -> Self {
        Self { schema_version: 1, command_id: original.command_id.value().to_owned(),
            run_id: original.run_id.clone(), state }
    }
}

pub(crate) struct StartContext<'a> {
    pub deployment: &'a SemanticStoreId,
    pub runtime_root: &'a Path,
    pub research_root: &'a Path,
    pub frozen: Arc<FrozenStore>,
    pub decisions: Arc<qualification_decision::Store>,
}

impl StartContext<'_> {
    pub(crate) async fn promotion(&self, tx: &BuildFactRead<'_, '_>, intent: &StartIntent)
        -> Result<strategy_promotion::VerifiedSimPromotion, StartError>
    {
        let selected = strategy_promotion::SelectedSimPromotion {
            strategy: &intent.strategy_fingerprint, backtest_run_id: &intent.backtest_run_id,
            owner: &intent.subject_id, policy: &intent.policy_fingerprint,
            decision: &intent.decision_fingerprint, promotion: &intent.promotion_fingerprint,
            max_work: 64 * 1024 * 1024,
        };
        strategy_promotion::read_selected_sim_promotion_in_transaction(tx, self.deployment,
            self.frozen.clone(), self.decisions.clone(), self.research_root, selected)
            .await.map_err(StartError::Proof)
    }
}

impl From<source_access::Error> for StartError {
    fn from(error: source_access::Error) -> Self {
        Self::Access(error)
    }
}

impl From<sim_run::Error> for StartError {
    fn from(error: sim_run::Error) -> Self {
        Self::Storage(error)
    }
}

async fn authorize_resources(
    tx: &Transaction<'_>, access: &Access, session: &Session, intent: &StartIntent,
) -> Result<(crate::persistence::sim_account::SimAccountRevision, String), StartError> {
    access.check_sim_selection(session, &intent.strategy_fingerprint, &intent.account_id)?;
    let (account, broker) = sim_run::read_intent_resources(tx, intent).await?;
    let fingerprint = &broker.record().runtime_configuration_fingerprint;
    access.authorize_sim_start(session, &intent.strategy_fingerprint, account.account_id().value(), fingerprint)?;
    Ok((account, fingerprint.clone()))
}

pub(crate) async fn observe_human_start(authority: &mut AuthoritySession, access: &Access,
    session: &Session, deployment: &SemanticStoreId, command: &CommandId,
) -> Result<StartObservation, StartError> {
    access.check_session(session)?;
    let tx = authority.client_mut().await.map_err(|_| sim_run::Error::Unavailable)?
        .transaction().await.map_err(|_| sim_run::Error::Unavailable)?;
    postgres::bounds(&tx).await.map_err(|_| sim_run::Error::Unavailable)?;
    let original = sim_run::lookup_in_transaction(&tx, deployment.value(), "HUMAN", session.subject_id()?, command)
        .await?.ok_or(sim_run::Error::Missing)?;
    authorize_resources(&tx, access, session, &original.intent).await?;
    let state = if original.accepted.is_some() { StartState::Accepted } else { StartState::Reserved };
    tx.commit().await.map_err(|_| sim_run::Error::Unavailable)?;
    access.check_session(session)?;
    Ok(StartObservation::new(&original, state))
}

pub(crate) async fn start_human_run(
    authority: &mut AuthoritySession, access: &Access, session: &Session,
    context: &StartContext<'_>, command: &CommandId, selection: StartSelection, at: OnlyUtcDateTime,
) -> Result<StartObservation, StartError> {
    access.check_session(session)?;
    let intent = StartIntent {
        deployment_id: context.deployment.value().to_owned(),
        subject_kind: "HUMAN".into(),
        subject_id: session.subject_id()?.to_owned(),
        strategy_fingerprint: selection.strategy_fingerprint,
        backtest_run_id: selection.backtest_run_id,
        policy_fingerprint: selection.policy_fingerprint,
        decision_fingerprint: selection.decision_fingerprint,
        promotion_fingerprint: selection.promotion_fingerprint,
        account_id: selection.account_id,
        account_revision_fingerprint: selection.account_revision_fingerprint,
        broker_revision_fingerprint: selection.broker_revision_fingerprint,
    };
    intent.fingerprint()?;
    let roles = authority.control_roles().map_err(|_| sim_run::Error::Unavailable)?;
    let client = authority.client_mut().await.map_err(|_| sim_run::Error::Unavailable)?;
    let tx = client.build_transaction().isolation_level(IsolationLevel::RepeatableRead)
        .start().await.map_err(|_| sim_run::Error::Unavailable)?;
    postgres::bounds(&tx).await.map_err(|_| sim_run::Error::Unavailable)?;
    authorize_resources(&tx, access, session, &intent).await?;
    let saved = sim_run::lookup_in_transaction(&tx, context.deployment.value(), "HUMAN", session.subject_id()?, command).await?;
    let (original, initial_promotion, loaded_artifact) = if let Some(saved) = saved {
        if saved.intent != intent { return Err(sim_run::Error::Conflict.into()); }
        let loaded = tokio::task::spawn_blocking(crate::workers::algorithm::loaded_native_image_sha256)
            .await.map_err(|_| sim_run::Error::Unavailable)?
            .map_err(|_| StartError::Proof("SIM_KERNEL_ARTIFACT_UNAVAILABLE"))?;
        (saved, None, loaded)
    } else {
        // Missing or rejected qualification must not consume a new command or Generation.
        let promotion = context.promotion(&BuildFactRead::control(&tx, &roles), &intent).await?;
        let root = context.runtime_root.to_owned();
        let (generation, artifact) = tokio::task::spawn_blocking(move || {
            let snapshot = Registry::inspect(&root)?;
            let generation = snapshot["active_for_new_work"].as_str().ok_or("SIM_ACTIVE_GENERATION_REQUIRED")?;
            let artifact = crate::workers::algorithm::loaded_native_image_sha256().map_err(|_| "SIM_KERNEL_ARTIFACT_UNAVAILABLE")?;
            Ok((generation.to_owned(), artifact))
        }).await.map_err(|_| sim_run::Error::Unavailable)?.map_err(StartError::Proof)?;
        let reserved = sim_run::reserve_in_transaction(&tx, command, &intent, &generation, &artifact).await?;
        (reserved, Some(promotion), artifact)
    };
    access.check_session(session)?;
    tx.commit().await.map_err(|_| sim_run::Error::UnknownCommit)?;

    let root = context.runtime_root.to_owned();
    let loaded_for_bind = loaded_artifact.clone();
    let (original, mut generation) = tokio::task::spawn_blocking(move || {
        let held = if original.accepted.is_some() {
            open_reserved_generation_with_artifact(&root, &original, &loaded_for_bind)?
        } else {
            bind_reserved_generation_with_artifact(&root, &original, at, &loaded_for_bind)?
        };
        Ok((original, held))
    }).await.map_err(|_| sim_run::Error::Unavailable)?.map_err(StartError::Proof)?;
    let client = authority.client_mut().await.map_err(|_| sim_run::Error::Unavailable)?;
    let tx = client.build_transaction().isolation_level(IsolationLevel::RepeatableRead)
        .start().await.map_err(|_| sim_run::Error::Unavailable)?;
    postgres::bounds(&tx).await.map_err(|_| sim_run::Error::Unavailable)?;
    let (account, broker_runtime_fingerprint) = authorize_resources(&tx, access, session, &intent).await?;
    let promotion = match initial_promotion {
        Some(promotion) => {
            crate::bootstrap::deployment::verify_binding_in_transaction(&tx, context.deployment)
                .await.map_err(|error| StartError::Proof(error.code()))?;
            promotion.verify_cut().map_err(StartError::Proof)?;
            promotion
        }
        None => context.promotion(&BuildFactRead::control(&tx, &roles), &intent).await?,
    };
    let source = promotion.source_revision();
    let record = source.to_record();
    let universe = record["universe"]["instruments"].as_array().ok_or(sim_run::Error::Integrity)?
        .iter().map(|id| id.as_str().map(str::to_owned).ok_or(sim_run::Error::Integrity)).collect::<Result<Vec<_>, _>>()?;
    let trading_binding = account.trading_binding(&original.run_id, &original.generation, &original.kernel_artifact,
        source.fingerprint(), &universe).map_err(|_| sim_run::Error::Mismatch)?;
    let certified = promotion.validated_calculations().map_err(StartError::Proof)?;
    let algorithm = certified["algorithm_resolution"]["algorithm_artifact"].as_str().ok_or(sim_run::Error::Integrity)?;
    let installed = generation.installed_proof_data(algorithm).map_err(StartError::Proof)?;
    let native = generation.native_predicate_implementations_for_loaded(&loaded_artifact).map_err(StartError::Proof)?;
    if installed["native_descriptor"]["implementations"] != native ||
        installed["native_descriptor"]["image"]["artifact"].as_str() != Some(original.kernel_artifact.as_str()) {
        return Err(sim_run::Error::Mismatch.into());
    }
    crate::persistence::backtest_evidence::implementation_records(source, certified, generation.manifest(), &installed, Some(certified))
        .map_err(StartError::Proof)?;
    let proof = VerifiedSimAdmission { command: command.clone(), run_id: original.run_id.clone(),
        intent_fingerprint: original.intent_fingerprint.clone(), generation: original.generation.clone(),
        trading_binding, broker_runtime_fingerprint };
    sim_run::accept_in_transaction_with_artifact(&tx, &proof, &at.to_string(), &loaded_artifact).await?;
    promotion.verify_cut().map_err(StartError::Proof)?;
    generation.verify().map_err(StartError::Proof)?;
    access.check_session(session)?;
    tx.commit().await.map_err(|_| sim_run::Error::UnknownCommit)?;
    drop(generation);
    drop(promotion);
    crate::workers::sim::resume_admitted_command_with_artifact(
        authority, context.deployment, context.runtime_root, context.research_root, command.value(), &loaded_artifact,
    ).await.map_err(StartError::Proof)?;
    Ok(StartObservation::new(&original, StartState::Accepted))
}

pub(crate) fn bind_reserved_generation_with_artifact(
    root: &Path,
    reservation: &Reservation,
    at: OnlyUtcDateTime,
    loaded_artifact: &str,
) -> Result<RuntimeInputHold, &'static str> {
    let work = &reservation.run_id;
    let generation = &reservation.generation;
    let owner = reservation.command_id.value();
    let actor = reservation.intent.subject_id.as_str();
    let event = Registry::open_existing(root)?.bind_new_work_exact(work, generation, owner, actor, at)?;
    let hold = open_reserved_generation_with_artifact(root, reservation, loaded_artifact)?;
    if hold.binding() != &event {
        return Err("SIM_RUN_GENERATION_BINDING_MISMATCH");
    }
    Ok(hold)
}

pub(crate) fn open_reserved_generation_with_artifact(
    root: &Path,
    reservation: &Reservation,
    loaded_artifact: &str,
) -> Result<RuntimeInputHold, &'static str> {
    let mut hold = RuntimeInputHold::open(
        root, &reservation.run_id, reservation.command_id.value(), &reservation.generation,
    )?;
    if hold.binding()["actor"].as_str() != Some(reservation.intent.subject_id.as_str()) {
        return Err("SIM_RUN_GENERATION_BINDING_MISMATCH");
    }
    hold.verify_artifacts()?;
    if !crate::is_sha256_hex(loaded_artifact)
        || loaded_artifact != reservation.kernel_artifact
        || hold.execution_binding()?["executor_artifact_sha256"].as_str() != Some(loaded_artifact)
    {
        return Err("SIM_KERNEL_ARTIFACT_MISMATCH");
    }
    Ok(hold)
}

pub(crate) struct VerifiedSimAdmission {
    command: CommandId,
    run_id: String,
    intent_fingerprint: String,
    generation: String,
    trading_binding: TradingBinding,
    broker_runtime_fingerprint: String,
}

impl VerifiedSimAdmission {
    pub(crate) fn command_id(&self) -> &str {
        self.command.value()
    }

    pub(crate) fn run_id(&self) -> &str {
        &self.run_id
    }

    pub(crate) fn intent_fingerprint(&self) -> &str {
        &self.intent_fingerprint
    }

    pub(crate) fn generation(&self) -> &str {
        &self.generation
    }

    pub(crate) fn trading_binding(&self) -> &TradingBinding {
        &self.trading_binding
    }

    pub(crate) fn broker_runtime_fingerprint(&self) -> &str {
        &self.broker_runtime_fingerprint
    }
}
