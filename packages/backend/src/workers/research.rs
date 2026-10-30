//! One admitted finite Run, existing Attempt lease, immutable publication, fenced completion.
//! Shipping mutations always borrow the original Node Authority's physical session briefly.
use crate::{
    application::{
        research_admission::{PreparationError, PreparedInputs},
        research_run::VerifiedRun,
        research_run_execution::{self, Control, verify_inputs},
    },
    persistence::{
        authority_session::AuthoritySession,
        research_dataset::Store as Datasets,
        research_evidence::Store as Evidence,
        research_execution::{
            Claim, Failure, FailurePhase, ResearchExecution, RetryDecision, RunState, RunStatus,
        },
    },
};
use onlyalpha_calculation_bridge::ChartInstallation;
use onlyalpha_domain::time::OnlyUtcDateTime;
use std::{
    path::{Path, PathBuf},
    sync::Arc,
    time::Duration,
};
use tokio::sync::{Mutex, MutexGuard};
use tokio_postgres::Client;
pub type SharedAuthority = Arc<Mutex<Option<AuthoritySession>>>;

pub struct Work {
    pub run: VerifiedRun,
    pub inputs: PreparedInputs,
    pub datasets: Datasets,
    pub installation: ChartInstallation,
    pub evidence_root: PathBuf,
    pub native_version: String,
    pub worker_id: String,
    pub attempt_id: String,
}
// The two actual consumers share one protocol: a directly owned technical session and
// the Shipping Host's original AuthoritySession. Neither opens/reconnects a socket.
enum Access<'a> {
    Direct(&'a mut Client),
    Owned(&'a SharedAuthority),
}
enum Guard<'a> {
    Direct(&'a mut Client),
    Owned(MutexGuard<'a, Option<AuthoritySession>>),
}
impl Access<'_> {
    async fn enter(&mut self) -> Guard<'_> {
        match self {
            Self::Direct(client) => Guard::Direct(client),
            Self::Owned(writer) => Guard::Owned(writer.lock().await),
        }
    }
}
impl Guard<'_> {
    async fn client(&mut self) -> Result<&mut Client, PreparationError> {
        match self {
            Self::Direct(client) => Ok(client),
            Self::Owned(writer) => writer
                .as_mut()
                .ok_or("RESEARCH_NODE_AUTHORITY_UNAVAILABLE")?
                .client_mut()
                .await
                .map_err(|_| PreparationError::from("RESEARCH_NODE_AUTHORITY_UNAVAILABLE")),
        }
    }
}
/// Existing direct technical consumer, with no alternate business or execution semantics.
pub async fn run_once(
    client: &mut Client,
    work: Work,
    now: impl Fn() -> OnlyUtcDateTime,
) -> Result<RunStatus, PreparationError> {
    execute_once(&mut Access::Direct(client), work, &|| Ok(now())).await
}
/// All operational writes use the original guard-owning socket. Losing that socket
/// cannot finalize on an independent Research connection after a prior lock check.
pub async fn run_owned(
    writer: &SharedAuthority,
    work: Work,
    now: impl Fn() -> Result<OnlyUtcDateTime, PreparationError>,
) -> Result<RunStatus, PreparationError> {
    execute_once(&mut Access::Owned(writer), work, &now).await
}
/// Before executable preparation, recover cancellation/terminal facts without an algorithm.
pub(crate) async fn recover_owned(
    writer: &SharedAuthority,
    run: &VerifiedRun,
    root: &Path,
    now: impl Fn() -> Result<OnlyUtcDateTime, PreparationError>,
) -> Result<Option<RunStatus>, PreparationError> {
    recover_existing(&mut Access::Owned(writer), run, root, &now).await
}
async fn recover_existing(
    access: &mut Access<'_>,
    run: &VerifiedRun,
    root: &Path,
    now: &impl Fn() -> Result<OnlyUtcDateTime, PreparationError>,
) -> Result<Option<RunStatus>, PreparationError> {
    let mut status = {
        let mut held = access.enter().await;
        ResearchExecution::new(held.client().await?)
            .observe(run)
            .await?
    };
    if status.state.terminal() {
        if status.state == RunState::Completed {
            let current = {
                let mut held = access.enter().await;
                crate::persistence::research_submission::load(
                    held.client().await?,
                    run.run_id(),
                    None,
                )
                .await?
            };
            Evidence::open(root)?
                .load_verified(&current)?
                .ok_or("RESEARCH_COMPLETION_PROOF_UNAVAILABLE")?;
        }
        return Ok(Some(status));
    }
    if matches!(status.state, RunState::Running | RunState::CancelRequested) {
        let expired = {
            let mut held = access.enter().await;
            ResearchExecution::new(held.client().await?)
                .expire(run, now()?)
                .await?
        };
        if let Some(expired) = expired {
            status = expired;
        }
    }
    if status.state.terminal() {
        return Ok(Some(status));
    }
    if status.state == RunState::CancelRequested {
        let root = root.to_path_buf();
        let run = run.clone();
        let revision = status.revision;
        let inspection =
            tokio::task::spawn_blocking(move || Evidence::open(&root)?.inspect(run, revision))
                .await
                .map_err(|_| "RESEARCH_CANCELLATION_INSPECTION_UNAVAILABLE")??;
        let mut held = access.enter().await;
        return ResearchExecution::new(held.client().await?)
            .reconcile(&inspection, now()?)
            .await
            .map(Some)
            .map_err(Into::into);
    }
    Ok(None)
}
async fn heartbeat(
    access: &mut Access<'_>,
    run: &VerifiedRun,
    claim: &mut Claim,
) -> Result<RunStatus, PreparationError> {
    let mut held = access.enter().await;
    let client = held.client().await?;
    let observed = ResearchExecution::new(client).observe(run).await?;
    ResearchExecution::new(client).heartbeat(claim).await?;
    Ok(observed)
}
async fn execute_once(
    access: &mut Access<'_>,
    work: Work,
    now: &impl Fn() -> Result<OnlyUtcDateTime, PreparationError>,
) -> Result<RunStatus, PreparationError> {
    let run = work.run.clone();
    let root = work.evidence_root.clone();
    if let Some(status) = recover_existing(access, &run, &root, now).await? {
        return Ok(status);
    }
    verify_inputs(&work.run, &work.inputs)?;
    let claim = {
        let mut held = access.enter().await;
        ResearchExecution::new(held.client().await?)
            .claim(&run, &work.worker_id, &work.attempt_id, now()?)
            .await?
    };
    let Some(mut claim) = claim else {
        let mut held = access.enter().await;
        return ResearchExecution::new(held.client().await?)
            .observe(&run)
            .await
            .map_err(Into::into);
    };
    let store = Evidence::open(&root)?;
    if let Some(completed) = store.load_verified(&run)? {
        let mut held = access.enter().await;
        return ResearchExecution::new(held.client().await?)
            .complete(&mut claim, &completed, now()?)
            .await
            .map_err(Into::into);
    }
    let control = Control::default();
    let child_control = control.clone();
    let mut job = tokio::task::spawn_blocking(move || {
        let store = Evidence::open(&work.evidence_root)?;
        let result = research_run_execution::execute(
            work.run,
            work.inputs,
            work.datasets,
            work.installation,
            &work.native_version,
            &child_control,
        )?;
        store
            .commit(result)
            .map_err(|_| PreparationError::from("RESEARCH_EVIDENCE_OUTCOME_UNKNOWN"))
    });
    let mut timer = tokio::time::interval(Duration::from_secs(30));
    timer.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    let result = loop {
        tokio::select! {
            result=&mut job=>match result {Ok(result)=>break result,Err(_)=>{control.stop()?;return Err(control.uncertain("RESEARCH_EXECUTION_OUTCOME_UNKNOWN"));}},
            _=timer.tick()=>{
                // No guard survives this short phase or is held while stopping/joining a child.
                let observation=heartbeat(access,&run,&mut claim).await;
                let observation=match observation {
                    Ok(observed)=>observed,
                    Err(_)=>{
                        let stopped=control.stop();let outcome=job.await;
                        if let Ok(Err(error))=outcome && error.recovery_owner().is_some(){return Err(error);}
                        stopped?;return Err(control.uncertain("RESEARCH_EXECUTION_OWNERSHIP_UNCERTAIN"));
                    },
                };
                if observation.state==RunState::CancelRequested && let Err(error)=control.stop(){let _=job.await;return Err(error);}
            }
        }
    };
    match result {
        Ok(completed) => {
            let mut held = access.enter().await;
            ResearchExecution::new(held.client().await?)
                .complete(&mut claim, &completed, now()?)
                .await
                .map_err(Into::into)
        }
        Err(error) => {
            if error.code().contains("UNKNOWN") {
                return Err(error);
            }
            let state = {
                let mut held = access.enter().await;
                ResearchExecution::new(held.client().await?)
                    .observe(&run)
                    .await?
            };
            if state.state == RunState::CancelRequested {
                let completed = store.load_verified(&run)?;
                let mut held = access.enter().await;
                let client = held.client().await?;
                if let Some(completed) = completed {
                    return ResearchExecution::new(client)
                        .complete(&mut claim, &completed, now()?)
                        .await
                        .map_err(Into::into);
                }
                return ResearchExecution::new(client)
                    .cancel(&mut claim, now()?)
                    .await
                    .map_err(Into::into);
            }
            let failure = Failure::new(
                FailurePhase::Execution,
                error.code(),
                "Selected finite Research execution did not complete",
            )?;
            let mut held = access.enter().await;
            ResearchExecution::new(held.client().await?)
                .fail(&mut claim, &failure, RetryDecision::FinalFail, now()?)
                .await
                .map_err(Into::into)
        }
    }
}
