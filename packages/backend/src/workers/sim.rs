use super::sim_orders::recover_verified_orders;
use crate::{
    application::{frozen_strategy::FrozenStore, sim_run::open_reserved_generation_with_artifact},
    bootstrap::deployment::SemanticStoreId,
    persistence::{
        authority_session::AuthoritySession, build_fact_read::BuildFactRead,
        qualification_decision, research_runtime::Registry, sim_run, sim_venue,
        trading_facts::TradingFactRepository,
    },
};
use std::{os::fd::AsFd, path::Path, sync::Arc};
use onlyalpha_runtime::durability::{DurabilityError, DurableFactPort, RecoveryFacts, TradingBinding};

/// 从已核验准入的 SIM 绑定恢复经济事实。提交状态未知时须换连接按同一绑定重新观察。
pub async fn recover_economic_state(
    repository: &mut TradingFactRepository<'_>,
    binding: &TradingBinding,
) -> Result<RecoveryFacts, DurabilityError> {
    if binding.configuration().record()["runtime_kind"] != "SIM" {
        return Err(DurabilityError::Rejected("SIM_RECOVERY_SCOPE_INVALID".into()));
    }
    let original = repository.load_recovery(binding).await?;
    let Some((pending, original_prefix)) = original.records().split_last().filter(|(last, _)| !last.ready()) else {
        return Ok(original);
    };
    repository.mark_projected(&original).await?;
    let observed = repository.load_recovery(binding).await?;
    let verified = observed.records().split_last().is_some_and(|(last, prefix)| {
        last.ready()
            && last.prepared() == pending.prepared()
            && prefix == original_prefix
    });
    if !verified {
        return Err(DurabilityError::Rejected("SIM_RECOVERY_PROJECTION_CONFLICT".into()));
    }
    Ok(observed)
}

#[derive(Debug, PartialEq, Eq)]
enum RecoveryError {
    Run(&'static str),
    StorageUnavailable,
    UnknownCommit,
}

impl RecoveryError {
    fn code(&self) -> &'static str {
        match self {
            Self::Run(code) => code,
            Self::StorageUnavailable => "SIM_RECOVERY_STORAGE_UNAVAILABLE",
            Self::UnknownCommit => "SIM_RECOVERY_COMMIT_UNKNOWN",
        }
    }
}

impl From<sim_run::Error> for RecoveryError {
    fn from(error: sim_run::Error) -> Self {
        match error {
            sim_run::Error::Unavailable => Self::StorageUnavailable,
            sim_run::Error::UnknownCommit => Self::UnknownCommit,
            sim_run::Error::Missing => Self::Run("SIM_RECOVERY_RESOURCE_MISSING"),
            _ => Self::Run("SIM_RECOVERY_ADMISSION_CONFLICT"),
        }
    }
}

impl From<DurabilityError> for RecoveryError {
    fn from(error: DurabilityError) -> Self {
        match error {
            DurabilityError::Unavailable => Self::StorageUnavailable,
            DurabilityError::UnknownCommit => Self::UnknownCommit,
            DurabilityError::Rejected(code) => {
                tracing::error!(%code, "SIM 经济事实恢复失败");
                Self::Run("SIM_RECOVERY_ECONOMIC_CONFLICT")
            }
        }
    }
}

impl From<onlyalpha_broker::Error> for RecoveryError {
    fn from(error: onlyalpha_broker::Error) -> Self {
        if error == onlyalpha_broker::Error::new("SIM_VENUE_COMMIT_UNKNOWN") {
            Self::UnknownCommit
        } else if error == onlyalpha_broker::Error::new("SIM_VENUE_UNAVAILABLE") {
            Self::StorageUnavailable
        } else {
            tracing::error!(%error, "SIM 原单恢复失败");
            Self::Run("SIM_ORDER_RECOVERY_FAILED")
        }
    }
}

/// 预留已提交但接纳未提交时，原 Run 没有交易流。按原命令、Run、Generation 和 owner 释放绑定，
/// 释放失败不得当作已恢复。
fn release_unaccepted_reservation(
    runtime_root: &Path, reservation: &sim_run::Reservation,
) -> Result<(), RecoveryError> {
    let at = crate::transport::host::now().map_err(|_| RecoveryError::Run("SIM_RECOVERY_CLOCK_UNAVAILABLE"))?;
    let root = runtime_root.to_owned();
    let run_id = reservation.run_id.clone();
    let generation = reservation.generation.clone();
    let owner = reservation.command_id.value().to_owned();
    let actor = reservation.intent.subject_id.clone();
    let joined = std::thread::scope(|scope| scope.spawn(move || {
        Registry::open_existing(&root)?.release_work_exact(&run_id, &generation, &owner, &actor, at)
    }).join());
    match joined {
        Ok(Ok(_)) => Ok(()),
        Ok(Err(code)) => Err(RecoveryError::Run(code)),
        Err(_) => Err(RecoveryError::Run("SIM_RECOVERY_GENERATION_UNAVAILABLE")),
    }
}

async fn recover_command_with_artifact(
    authority: &mut AuthoritySession, deployment: &SemanticStoreId, runtime_root: &Path,
    research_root: &Path, command_id: &str, loaded_artifact: &str,
) -> Result<(), RecoveryError> {
    let roles = authority.control_roles().map_err(|_| RecoveryError::StorageUnavailable)?;
    let research = crate::security::protected_files::open_directory(research_root)
        .map_err(|_| RecoveryError::Run("SIM_RECOVERY_PROMOTION_UNAVAILABLE"))?;
    let context = crate::application::sim_run::StartContext {
        deployment, runtime_root, research_root,
        frozen: Arc::new(FrozenStore::open(research.as_fd()).map_err(|_| RecoveryError::Run("SIM_RECOVERY_PROMOTION_UNAVAILABLE"))?),
        decisions: Arc::new(qualification_decision::Store::open(research_root).map_err(|_| RecoveryError::Run("SIM_RECOVERY_PROMOTION_UNAVAILABLE"))?),
    };
    let tx = authority.client_mut().await.map_err(|_| RecoveryError::StorageUnavailable)?
        .transaction().await.map_err(|_| RecoveryError::StorageUnavailable)?;
    let reservation = sim_run::recovery_in_transaction(&tx, deployment.value(), command_id).await?;
    let Some(accepted) = &reservation.accepted else {
        tx.commit().await.map_err(|_| RecoveryError::StorageUnavailable)?;
        release_unaccepted_reservation(runtime_root, &reservation)?;
        return Ok(());
    };
    let (account, _) = sim_run::read_resources_in_transaction(&tx, &reservation).await?;
    let proof = context.promotion(&BuildFactRead::control(&tx, &roles), &reservation.intent)
        .await.map_err(|_| RecoveryError::Run("SIM_RECOVERY_PROMOTION_UNAVAILABLE"))?;
    let source = proof.source_revision();
    let universe = source.to_record()["universe"]["instruments"].as_array()
        .ok_or(RecoveryError::Run("SIM_RECOVERY_ADMISSION_CONFLICT"))?
        .iter().map(|id| id.as_str().map(str::to_owned).ok_or(RecoveryError::Run("SIM_RECOVERY_ADMISSION_CONFLICT")))
        .collect::<Result<Vec<_>, _>>()?;
    let recomputed = account.trading_binding(&reservation.run_id, &reservation.generation,
        &reservation.kernel_artifact, source.fingerprint(), &universe)
        .map_err(|_| RecoveryError::Run("SIM_RECOVERY_BINDING_CONFLICT"))?;
    if recomputed.fingerprint() != accepted.trading_binding.fingerprint() {
        return Err(RecoveryError::Run("SIM_RECOVERY_BINDING_CONFLICT"));
    }
    let binding = accepted.trading_binding.clone();
    let venue = sim_run::read_venue_with_artifact(
        &tx, &reservation, &binding, &accepted.broker_runtime_fingerprint, loaded_artifact,
    ).await?;
    tx.commit().await.map_err(|_| RecoveryError::StorageUnavailable)?;

    let root = runtime_root.to_owned();
    let loaded = loaded_artifact.to_owned();
    let generation = tokio::task::spawn_blocking(move || open_reserved_generation_with_artifact(&root, &reservation, &loaded))
        .await.map_err(|_| RecoveryError::Run("SIM_RECOVERY_GENERATION_UNAVAILABLE"))?
        .map_err(RecoveryError::Run)?;
    let mut repository = TradingFactRepository::new(authority).await?;
    let facts = recover_economic_state(&mut repository, &binding).await?;
    sim_venue::with_recovered(
        authority, &binding, venue.scope, &venue.artifact, venue.cash, &venue.configuration,
        65_536,
        move |broker, journal, venue| {
            let _generation = generation;
            recover_verified_orders(broker, journal, venue, &facts)
        },
    ).await?;
    Ok(())
}

pub(crate) async fn resume_admitted_command_with_artifact(
    authority: &mut AuthoritySession, deployment: &SemanticStoreId, runtime_root: &Path,
    research_root: &Path, command: &str, loaded_artifact: &str,
) -> Result<(), &'static str> {
    recover_command_with_artifact(authority, deployment, runtime_root, research_root, command, loaded_artifact)
        .await
        .map_err(|error| error.code())
}

pub(crate) async fn recover_admitted_orders(
    authority: &mut AuthoritySession,
    deployment: &SemanticStoreId,
    runtime_root: &Path,
    research_root: &Path,
) -> Result<(), &'static str> {
    let tx = authority.client_mut().await.map_err(|_| RecoveryError::StorageUnavailable.code())?
        .transaction().await.map_err(|_| RecoveryError::StorageUnavailable.code())?;
    let ids = sim_run::recovery_command_ids(&tx, deployment.value()).await.map_err(|e| RecoveryError::from(e).code())?;
    tx.commit().await.map_err(|_| RecoveryError::StorageUnavailable.code())?;
    if ids.is_empty() {
        return Ok(());
    }
    let loaded = tokio::task::spawn_blocking(crate::workers::algorithm::loaded_native_image_sha256)
        .await
        .map_err(|_| "SIM_KERNEL_ARTIFACT_UNAVAILABLE")?
        .map_err(|_| "SIM_KERNEL_ARTIFACT_UNAVAILABLE")?;
    observe_recovery_commands(&ids, async |id| {
        recover_command_with_artifact(authority, deployment, runtime_root, research_root, id, &loaded).await
    }).await
}

async fn observe_recovery_commands(
    ids: &[String], mut recover: impl AsyncFnMut(&str) -> Result<(), RecoveryError>,
) -> Result<(), &'static str> {
    let mut first_failure = None;
    for id in ids {
        match recover(id).await {
            Ok(()) => {}
            Err(RecoveryError::Run(code)) => {
                tracing::error!(command_id = %id, %code, "SIM 运行恢复失败，继续核验其他运行");
                first_failure.get_or_insert(code);
            }
            Err(error) => return Err(error.code()),
        }
    }
    match first_failure {
        Some(code) => Err(code),
        None => Ok(()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn incomplete_run_blocks_readiness_after_observing_other_runs() {
        let ids = [String::from("damaged"), String::from("healthy")];
        let mut observed = Vec::new();
        let result = observe_recovery_commands(&ids, async |id| {
            observed.push(id.to_owned());
            if id == "damaged" { Err(sim_run::Error::Integrity.into()) } else { Ok(()) }
        }).await;
        assert_eq!(observed, ids);
        assert_eq!(result, Err("SIM_RECOVERY_ADMISSION_CONFLICT"));
    }

    #[tokio::test]
    async fn lost_storage_or_uncertain_append_stops_work_on_the_original_connection() {
        let ids = [String::from("first"), String::from("second"), String::from("third")];
        for (venue_code, expected) in [
            ("SIM_VENUE_COMMIT_UNKNOWN", "SIM_RECOVERY_COMMIT_UNKNOWN"),
            ("SIM_VENUE_UNAVAILABLE", "SIM_RECOVERY_STORAGE_UNAVAILABLE"),
        ] {
            let mut observed = Vec::new();
            let result = observe_recovery_commands(&ids, async |id| {
                observed.push(id.to_owned());
                if id == "first" { return Err(sim_run::Error::Mismatch.into()); }
                Err(onlyalpha_broker::Error::new(venue_code).into())
            }).await;
            assert_eq!(observed, ids[..2]);
            assert_eq!(result, Err(expected));
        }
    }
}
