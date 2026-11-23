//! Host scheduling over the original Backtest Run/Attempt and physical owners.
//! Wake-ups are observations, never another queue or execution authority.
pub(crate) use super::backtest_service::Configuration;
use super::source_sessions::SourceSessions;
use crate::{
    application::{
        backtest_run::VerifiedRun,
        finite_job::{AbortedPreparation, FiniteOutcome, PreparationTask, PreparedExecution},
        job_input::MemoryBudget,
        job_recovery::{JobRecovery, RecoveryDecision, RecoveryRefusal, RetryBudget},
        research_admission::PreparationError,
    },
    bootstrap::{
        deployment::{self, SemanticStoreId},
        workstation_startup::{ResearchConnection,JobReadConnections as InputConnections},
    },
    persistence::{
        backtest_run::{self, Backtests, Claim, RunState, RunStatus},
        job_publication::{AttemptClaim, AttemptExecutionBinding, PublicationError, PublicationObservation, PublicationRepository},
        research_runtime::Registry,
    },
    security::protected_files,
    workers::research::SharedAuthority,
};
use onlyalpha_domain::time::OnlyUtcDateTime;
use onlyalpha_observability::{Correlation, Operation};
use std::{
    sync::{
        Arc,
        atomic::{AtomicU8, Ordering},
    },
    time::Duration,
};
use tokio::{
    sync::{Notify, watch},
    task::JoinHandle,
};
use tracing::Instrument;
const UNAVAILABLE: &str = "BACKTEST_SERVICE_UNAVAILABLE";
const UNKNOWN: &str = "BACKTEST_SERVICE_OUTCOME_UNKNOWN";
const LOST: &str = "BACKTEST_EXECUTION_OWNERSHIP_UNCERTAIN";
const CLEANUP_PENDING: &str = "BACKTEST_RUNTIME_CLEANUP_PENDING";
type Result<T> = std::result::Result<T, &'static str>;

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum Status {
    Starting,
    Idle,
    Running(String),
    Uncertain(&'static str),
    Unavailable(&'static str),
    Stopped,
}
impl Status {
    fn after_error(&self, code: &'static str) -> Self {
        if code.contains("UNKNOWN")
            || code.contains("UNCERTAIN")
            || matches!(self, Self::Uncertain(prior) if *prior != CLEANUP_PENDING)
        {
            Self::Uncertain(code)
        } else {
            Self::Unavailable(code)
        }
    }
}
struct Admission {
    state: AtomicU8,
    changed: Notify,
}
#[derive(Clone)]
pub(crate) struct Wake(Arc<Admission>);
impl Wake {
    pub(crate) fn notify(&self) -> bool {
        if self.stopped() {
            return false;
        }
        self.0.changed.notify_one();
        true
    }
    pub(crate) fn stop(&self) {
        self.0.state.swap(2, Ordering::AcqRel);
        self.0.changed.notify_one();
    }
    fn stopped(&self) -> bool {
        self.0.state.load(Ordering::Acquire) == 2
    }
    fn begin(&self) -> bool {
        self.0
            .state
            .compare_exchange(0, 1, Ordering::AcqRel, Ordering::Acquire)
            .is_ok()
    }
    fn finish(&self) {
        let _ = self
            .0
            .state
            .compare_exchange(1, 0, Ordering::AcqRel, Ordering::Acquire);
    }
}
// This guard exists before the task is first polled. Exit closes operational
// admission; it never proves that original children or connections drained.
struct TaskExit {
    wake: Wake,
    status: watch::Sender<Status>,
}
impl Drop for TaskExit {
    fn drop(&mut self) {
        self.wake.stop();
        let current = self.status.borrow().clone();
        if matches!(
            current,
            Status::Starting | Status::Idle | Status::Running(_)
        ) {
            self.status.send_replace(Status::Uncertain(UNKNOWN));
        }
    }
}
pub(crate) struct Service {
    wake: Wake,
    status: watch::Receiver<Status>,
    task: Option<JoinHandle<Result<()>>>,
    drained: Option<Result<()>>,
}
impl Service {
    pub(crate) fn start(
        connection: ResearchConnection,
        facts: ResearchConnection,
        writer: SharedAuthority,
        sources: SourceSessions,
        physical: Arc<crate::persistence::market_data::ClickHouse>,
        configuration: Configuration,
        clock: impl Fn() -> std::result::Result<OnlyUtcDateTime, PreparationError>
        + Send
        + Sync
        + 'static,
    ) -> Result<Self> {
        let connection=InputConnections::new(connection,facts,physical).map_err(|_|UNAVAILABLE)?;
        if !connection.active() {
            return Err(UNAVAILABLE);
        }
        let wake = Wake(Arc::new(Admission {
            state: AtomicU8::new(0),
            changed: Notify::new(),
        }));
        let (status, observed) = watch::channel(Status::Starting);
        let selected = wake.clone();
        let exit = TaskExit {
            wake: selected.clone(),
            status: status.clone(),
        };
        let task = tokio::spawn(async move {
            let _exit = exit;
            let mut connection = Some(connection);
            let result = match uuid4() {
                Ok(worker) => {
                    serve(
                        &mut connection,
                        &writer,
                        &sources,
                        &configuration,
                        &selected,
                        &status,
                        &clock,
                        &worker,
                    )
                    .await
                }
                Err(code) => Err(code),
            };
            let closed = match connection.as_mut() {
                Some(connection) => connection.close().await.map_err(|_| UNAVAILABLE),
                None => Err(UNKNOWN),
            };
            if let Err(code) = closed {
                status.send_replace(Status::Uncertain(code));
                return Err(code);
            }
            match result {
                Ok(()) => {
                    status.send_replace(Status::Stopped);
                }
                Err(code) => {
                    eprintln!("BACKTEST_WORKER_EXIT code={code}");
                    let failed = status.borrow().after_error(code);
                    status.send_replace(failed);
                }
            }
            // The operational outcome remains visible above; this Ok proves
            // physical task/child/connection drain only, never semantic success.
            Ok(())
        });
        Ok(Self {
            wake,
            status: observed,
            task: Some(task),
            drained: None,
        })
    }
    pub(crate) fn wake(&self) -> Wake {
        self.wake.clone()
    }
    pub(crate) fn status(&self) -> Status {
        if let Some(Err(code)) = self.drained {
            Status::Uncertain(code)
        } else {
            self.status.borrow().clone()
        }
    }
    pub(crate) fn subscribe(&self) -> watch::Receiver<Status> {
        self.status.clone()
    }
    pub(crate) async fn drain(&mut self) -> Result<()> {
        self.wake.stop();
        if let Some(result) = self.drained {
            return result;
        }
        let Some(task) = self.task.as_mut() else {
            return Err(UNKNOWN);
        };
        let result = task.await.unwrap_or(Err(UNKNOWN));
        self.task.take();
        self.drained = Some(result);
        result
    }
}
impl Drop for Service {
    fn drop(&mut self) {
        self.wake.stop();
    }
}
async fn wait_cleanup(wake: &Wake, retry: &mut tokio::time::Interval) {
    tokio::select! { _=wake.0.changed.notified()=>{}, _=retry.tick()=>{} }
}
async fn handoff(
    wake: &Wake,
    operation: impl std::future::Future<Output = Result<()>>,
) -> Option<Result<()>> {
    if !wake.begin() {
        return None;
    }
    let result = operation.await;
    wake.finish();
    Some(result)
}
fn namespace(config: &Configuration) -> Result<SemanticStoreId> {
    let directory =
        protected_files::open_directory(&config.research_root).map_err(|_| UNAVAILABLE)?;
    deployment::load_semantic_store_id_at(&directory).map_err(|e| e.code())
}
async fn next_scan(wake: &Wake, poll: &mut tokio::time::Interval) -> bool {
    if wake.stopped() {
        return false;
    }
    tokio::select! {_=wake.0.changed.notified()=>{},_=poll.tick()=>{}}
    !wake.stopped()
}
async fn serve(
    connection: &mut Option<InputConnections>,
    writer: &SharedAuthority,
    sources: &SourceSessions,
    config: &Configuration,
    wake: &Wake,
    status: &watch::Sender<Status>,
    clock: &(impl Fn() -> std::result::Result<OnlyUtcDateTime, PreparationError> + Send + Sync),
    worker: &str,
) -> Result<()> {
    let namespace = namespace(config)?;
    let mut poll = tokio::time::interval(Duration::from_secs(5));
    poll.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    while next_scan(wake, &mut poll).await {
        let ids = backtest_run::pending_native_run_ids(
            connection
                .as_mut()
                .ok_or(UNKNOWN)?
                .client_mut()
                .await
                .map_err(|_| UNAVAILABLE)?,
            &namespace,
        )
        .await?;
        for id in ids {
            if wake.stopped() {
                return Ok(());
            }
            let run = {
                let mut writer_hold = crate::workers::backtest_profile::HoldEnd::pending();
                let writer_wait = onlyalpha_observability::Operation::start(
                    "backend",
                    "writer.wait",
                    onlyalpha_observability::Correlation::default(),
                );
                let mut held = writer.lock().instrument(writer_wait.span().clone()).await;
                writer_wait.finish("acquired", 1, 0);
                writer_hold.acquired("writer", "writer.hold");
                let _writer_release_begin = writer_hold.begin_release_marker();
                Backtests::new(held.as_mut().ok_or(UNAVAILABLE)?, &namespace)
                    .load(&id)
                    .await?
            };
            status.send_replace(Status::Running(id));
            let result = handoff(
                wake,
                run_one(
                    connection,
                    writer,
                    sources,
                    config,
                    WorkerSignals { wake, status },
                    clock,
                    worker,
                    &run,
                ),
            )
            .await;
            match result {
                None => return Ok(()),
                Some(result) => result?,
            }
            if !connection.as_ref().is_some_and(InputConnections::active) {
                return Err(UNAVAILABLE);
            }
        }
        if wake.stopped() {
            return Ok(());
        }
        cleanup_terminal(connection, writer, config, wake, status, clock, &namespace)
            .await
            .inspect_err(|code| {
                eprintln!("BACKTEST_WORKER_SCAN_FAILED phase=terminal-cleanup code={code}")
            })?;
        status.send_replace(Status::Idle);
    }
    Ok(())
}
async fn observe(
    writer: &SharedAuthority,
    namespace: &SemanticStoreId,
    run: &VerifiedRun,
) -> Result<RunStatus> {
    let mut writer_hold = crate::workers::backtest_profile::HoldEnd::pending();
    let writer_wait = onlyalpha_observability::Operation::start(
        "backend",
        "writer.wait",
        onlyalpha_observability::Correlation::default(),
    );
    let mut held = writer.lock().instrument(writer_wait.span().clone()).await;
    writer_wait.finish("acquired", 1, 0);
    writer_hold.acquired("writer", "writer.hold");
    let _writer_release_begin = writer_hold.begin_release_marker();
    Backtests::new(held.as_mut().ok_or(UNAVAILABLE)?, namespace)
        .observe(run)
        .await
}
async fn heartbeat(
    writer: &SharedAuthority,
    run: &VerifiedRun,
    claim: &mut Claim,
) -> Result<Option<RunStatus>> {
    let mut writer_hold = crate::workers::backtest_profile::HoldEnd::pending();
    let writer_wait = onlyalpha_observability::Operation::start(
        "backend",
        "writer.wait",
        onlyalpha_observability::Correlation::default(),
    );
    let mut held = writer.lock().instrument(writer_wait.span().clone()).await;
    writer_wait.finish("acquired", 1, 0);
    writer_hold.acquired("writer", "writer.hold");
    let _writer_release_begin = writer_hold.begin_release_marker();
    let mut store = Backtests::new(held.as_mut().ok_or(UNAVAILABLE)?, run.namespace());
    let current = store.heartbeat(claim).await?;
    #[cfg(test)]
    if current.is_some() {
        tests::observed_phase(run.run_id(), "heartbeat_committed");
    }
    Ok(current)
}
struct WorkerSignals<'a> {
    wake: &'a Wake,
    status: &'a watch::Sender<Status>,
}

#[derive(Clone, Copy)]
enum Ownership {
    Retained,
    Expired,
    Unknown(&'static str),
}

async fn wait_owned<T>(
    work: impl std::future::Future<Output = std::result::Result<T, PreparationError>>,
    stop: impl Fn(),
    signals: &WorkerSignals<'_>,
    writer: &SharedAuthority,
    run: &VerifiedRun,
    claim: &mut Claim,
) -> Result<(T, Ownership)> {
    tokio::pin!(work);
    let mut timer = tokio::time::interval(Duration::from_secs(30));
    timer.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    let mut ownership = Ownership::Retained;
    let result = loop {
        tokio::select! {
            joined = &mut work => break joined,
            _ = signals.wake.0.changed.notified(), if matches!(ownership, Ownership::Retained) => {},
            _ = timer.tick(), if matches!(ownership, Ownership::Retained) => {},
        }
        if signals.wake.stopped() {
            stop();
            #[cfg(test)]
            tests::observed_phase(run.run_id(), "pause_requested");
        }
        match heartbeat(writer, run, claim).await {
            Ok(Some(current)) if current.state == RunState::CancelRequested => {
                stop();
                #[cfg(test)]
                tests::observed_phase(run.run_id(), "cancel_observed");
            }
            Ok(Some(_)) => {}
            Ok(None) => {
                ownership = Ownership::Expired;
                stop();
                #[cfg(test)]
                tests::observed_phase(run.run_id(), "attempt_expired");
            }
            Err(code) => {
                ownership = Ownership::Unknown(code);
                stop();
                signals.status.send_replace(Status::Uncertain(code));
                tracing::warn!(run_id = run.run_id(), rejection = code, "Backtest Attempt heartbeat failed");
                #[cfg(test)]
                tests::observed_phase(run.run_id(), "ownership_uncertain");
            }
        }
    };
    result.map(|value| (value, ownership)).map_err(|error| error.code())
}

async fn finish_lost_attempt(
    ownership: Ownership,
    connection: &mut Option<InputConnections>,
    writer: &SharedAuthority,
) -> Result<()> {
    if let Ownership::Unknown(code) = ownership {
        return Err(code);
    }
    let mut held = writer.lock().await;
    held.as_mut().ok_or(UNAVAILABLE)?.verify().await.map_err(|error| error.code())?;
    connection.as_mut().ok_or(UNKNOWN)?.clients_mut().await.map_err(|_| UNAVAILABLE)?;
    Ok(())
}

async fn finish_or_confirm_expiry(
    result: Result<()>,
    claim: &Claim,
    connection: &mut Option<InputConnections>,
    writer: &SharedAuthority,
) -> Result<()> {
    if !matches!(result, Err(LOST | backtest_run::LOST)) {
        return result;
    }
    let expired = {
        let mut held = writer.lock().await;
        Backtests::new(held.as_mut().ok_or(UNAVAILABLE)?, claim.run().namespace())
            .confirm_attempt_expired(claim)
            .await?
    };
    if !expired {
        return result;
    }
    finish_lost_attempt(Ownership::Expired, connection, writer).await
}

async fn run_one(
    connection: &mut Option<InputConnections>,
    writer: &SharedAuthority,
    sources: &SourceSessions,
    config: &Configuration,
    signals: WorkerSignals<'_>,
    clock: &(impl Fn() -> std::result::Result<OnlyUtcDateTime, PreparationError> + Send + Sync),
    worker: &str,
    run: &VerifiedRun,
) -> Result<()> {
    let command = run.resolution()["runtime_work_binding"]["reason"]
        .as_str()
        .map(str::to_owned);
    let trace_job = Operation::root(
        "backend",
        "backtest.run_one",
        Correlation {
            run_id: Some(run.run_id().into()),
            links: command.as_ref().map(|id| format!("command:{id}")),
            command_id: command,
            ..Default::default()
        },
    );
    let observed: Result<()> = async {
        #[cfg(test)]
        tests::wait_at_phase(run.run_id(), "before_claim").await;
        let at = || clock().map_err(|error| error.code());
        let budget = MemoryBudget::new(crate::transport::host::ROWS, crate::transport::host::WORK)
            .map_err(|_| "BACKTEST_INPUT_BUDGET_INVALID")?;
        let (mut claim, binding) = {
            let mut held = writer.lock().await;
            let mut runs = Backtests::new(held.as_mut().ok_or(UNAVAILABLE)?, run.namespace());
            let mut observation = runs.observe_publication(run).await?;
            if matches!(&observation, PublicationObservation::ConfirmedUnpublished(proof) if proof.active_attempts() == 1)
                && runs.expire(run, at()?).await?.is_some()
            {
                observation = runs.observe_publication(run).await?;
            }
            match JobRecovery::decide(observation, RetryBudget::finite_job()).map_err(publication_error)? {
                RecoveryDecision::RecomputeWithNewClaim(proof) => {
                    if signals.wake.stopped() {
                        return Ok(());
                    }
                    let Some(claim) = runs.claim_recompute(run, &proof, worker, &uuid4()?, at()?).await? else {
                        return Ok(());
                    };
                    (claim, proof.binding().clone())
                }
                RecoveryDecision::FinishCancellation(proof) => {
                    runs.finish_cancelled_unpublished(run, &proof, at()?).await?;
                    return Ok(());
                }
                RecoveryDecision::Refused(RecoveryRefusal::RetryExhausted, proof) => {
                    runs.finish_exhausted(run, &proof, at()?).await?;
                    return Ok(());
                }
                RecoveryDecision::AlreadyPublished(_)
                | RecoveryDecision::Refused(RecoveryRefusal::Terminal, _)
                | RecoveryDecision::WaitForResolution => return Ok(()),
            }
        };
        let trace_attempt = Operation::start("backend", "backtest.attempt", Correlation {
            attempt: u64::try_from(claim.attempt_number()).ok(),
            links: Some(format!("attempt:{}", claim.attempt_id())),
            ..Default::default()
        });
        let attempted: Result<()> = async {
            tracing::info!(target: "onlyalpha.observability", event_kind = "summary", module = "backend", operation = "backtest.run.claimed", outcome = "claimed");
            let execution = AttemptExecutionBinding::capture(&AttemptClaim::from_backtest(&claim))
                .map_err(publication_error)?;
            let preparing = PreparationTask::start_backtest(
                connection.take().ok_or(UNKNOWN)?, sources.clone(), run.clone(), binding,
                execution, config.clone(), budget,
            );
            let stop = preparing.cancellation();
            let (prepared, ownership) = wait_owned(
                preparing.join(), || { stop.send_replace(true); }, &signals, writer, run, &mut claim,
            ).await?;
            let outcome = match prepared {
                PreparedExecution::Ready { readers, value } => {
                    *connection = Some(readers);
                    if !matches!(ownership, Ownership::Retained) {
                        drop(value.discard());
                        return finish_lost_attempt(ownership, connection, writer).await;
                    }
                    let Some(current) = heartbeat(writer, run, &mut claim).await? else {
                        drop(value.discard());
                        return finish_lost_attempt(Ownership::Expired, connection, writer).await;
                    };
                    if current.state == RunState::CancelRequested {
                        Err((value.discard(), "BACKTEST_EXECUTION_CANCELLED".into()))
                    } else if signals.wake.stopped() {
                        return Ok(());
                    } else {
                        value.start(&AttemptClaim::from_backtest(&claim))
                    }
                }
                PreparedExecution::Aborted { readers, proof, error } => {
                    *connection = Some(readers);
                    if !matches!(ownership, Ownership::Retained) {
                        verify_preparation_drained(&error)?;
                        drop(proof);
                        return finish_lost_attempt(ownership, connection, writer).await;
                    }
                    Err((proof, error))
                }
            };
            let task = match outcome {
                Ok(task) => task,
                Err((proof, error)) => {
                    if signals.wake.stopped() && error.code() == "BACKTEST_EXECUTION_CANCELLED"
                        && observe(writer, run.namespace(), run).await?.state == RunState::Running
                    {
                        return Ok(());
                    }
                    let result = settle_preparation(writer, run, &mut claim, proof, error).await;
                    return finish_or_confirm_expiry(result, &claim, connection, writer).await;
                }
            };
            let control = task.cancellation();
            let (finished, ownership) = wait_owned(
                task.finish(), || control.request_stop(), &signals, writer, run, &mut claim,
            ).await?;
            if !matches!(ownership, Ownership::Retained) {
                drop(finished.into_drained().map_err(|error| error.code())?);
                return finish_lost_attempt(ownership, connection, writer).await;
            }
            let Some(current) = heartbeat(writer, run, &mut claim).await? else {
                drop(finished.into_drained().map_err(|error| error.code())?);
                return finish_lost_attempt(Ownership::Expired, connection, writer).await;
            };
            #[cfg(test)]
            super::backtest_profile::spawn_blocking({
                let id = run.run_id().to_owned();
                let attempt = claim.attempt_number();
                move || {
                    if attempt == 1 {
                        tests::blocking_phase(&id, "before_first_finalization");
                    }
                    tests::blocking_phase(&id, "before_finalization");
                }
            }).await.map_err(|_| UNKNOWN)?;
            if current.state == RunState::CancelRequested || signals.wake.stopped() {
                let drained = finished.into_drained().map_err(|error| error.code())?;
                if current.state == RunState::CancelRequested {
                    let result = {
                        let mut held = writer.lock().await;
                        Backtests::new(held.as_mut().ok_or(UNAVAILABLE)?, run.namespace())
                            .finish_drained(&mut claim, &drained, None).await.map(drop)
                    };
                    drop(drained);
                    return finish_or_confirm_expiry(result, &claim, connection, writer).await;
                }
                return Ok(());
            }
            let result = match finished.into_outcome().map_err(|error| error.code())? {
                FiniteOutcome::Completed(candidate) => {
                    #[cfg(test)]
                    tests::wait_at_phase(run.run_id(), "candidate_ready").await;
                    #[cfg(test)]
                    let rollback_revision = tests::verify_economic_publication_rollbacks(
                        connection, writer, run, &claim, &candidate,
                    ).await;
                    let result = {
                        let mut held = writer.lock().await;
                        let published = PublicationRepository::publish_guarded(
                            held.as_mut().ok_or(UNAVAILABLE)?, run.namespace(),
                            &AttemptClaim::from_backtest(&claim), &candidate,
                        ).await;
                        #[cfg(test)]
                        tests::record_first_publication(run.run_id(), claim.attempt_number(), &published);
                        published.map(drop).map_err(|error| {
                            tracing::warn!(run_id = run.run_id(), ?error, "Backtest publication refused");
                            publication_error(error)
                        })
                    };
                    #[cfg(test)]
                    if let Some(revision) = rollback_revision {
                        assert!(result.is_ok(), "original candidate after rollbacks: {result:?}");
                        tests::assert_original_economic_publication(connection, &claim, &candidate, revision).await;
                    }
                    drop(candidate);
                    #[cfg(test)]
                    if result.is_ok() {
                        super::backtest_profile::spawn_blocking({
                            let id = run.run_id().to_owned();
                            move || tests::blocking_phase(&id, "after_publish")
                        }).await.map_err(|_| UNKNOWN)?;
                    }
                    result
                }
                FiniteOutcome::Failed { drained, error } => {
                    let mut held = writer.lock().await;
                    Backtests::new(held.as_mut().ok_or(UNAVAILABLE)?, run.namespace())
                        .finish_drained(&mut claim, &drained, Some(error.code())).await.map(drop)
                }
            };
            finish_or_confirm_expiry(result, &claim, connection, writer).await
        }.instrument(trace_attempt.span().clone()).await;
        trace_attempt.finish(if attempted.is_ok() { "ok" } else { "failed" }, 1, 0);
        attempted
    }.instrument(trace_job.span().clone()).await;
    if let Err(code) = observed {
        if code.contains("UNKNOWN") || code.contains("UNCERTAIN") {
            signals.status.send_replace(Status::Uncertain(code));
        }
    }
    trace_job.finish(if observed.is_ok() { "ok" } else { "failed" }, 1, 0);
    observed
}

fn verify_preparation_drained(error: &PreparationError) -> Result<()> {
    let code = error.code();
    if code.contains("UNKNOWN") || code.contains("UNCERTAIN") || error.recovery_owner().is_some() {
        return Err(code);
    }
    Ok(())
}

async fn settle_preparation(
    writer: &SharedAuthority,
    run: &VerifiedRun,
    claim: &mut Claim,
    proof: AbortedPreparation,
    error: PreparationError,
) -> Result<()> {
    verify_preparation_drained(&error)?;
    let mut held = writer.lock().await;
    Backtests::new(held.as_mut().ok_or(UNAVAILABLE)?, run.namespace())
        .finish_aborted(claim, &proof, error.code()).await?;
    Ok(())
}

fn publication_error(error: PublicationError) -> &'static str {
    match error {
        PublicationError::OutcomeUnknown => "BACKTEST_PUBLICATION_OUTCOME_UNKNOWN",
        PublicationError::OwnershipLost => LOST,
        PublicationError::Unavailable => "BACKTEST_PUBLICATION_UNAVAILABLE",
        PublicationError::Denied => "BACKTEST_PUBLICATION_DENIED",
        PublicationError::MissingEvidence => "BACKTEST_PUBLICATION_MISSING_EVIDENCE",
        PublicationError::BudgetExceeded => "BACKTEST_PUBLICATION_BUDGET_EXCEEDED",
        PublicationError::Integrity | PublicationError::Mismatch => "BACKTEST_PUBLICATION_INTEGRITY_MISMATCH",
        PublicationError::Conflict => "BACKTEST_PUBLICATION_CONFLICT",
    }
}

async fn try_release_runtime_work(
    config: &Configuration,
    work: &str,
    generation: &str,
    owner: &str,
    at: OnlyUtcDateTime,
) -> Result<bool> {
    let root = config.runtime_root.clone();
    let work = work.to_owned();
    let generation = generation.to_owned();
    let owner = owner.to_owned();
    super::backtest_profile::spawn_blocking(move || {
        let Some(mut registry) = Registry::try_open_for_release(&root)? else {
            return Ok(false);
        };
        registry.release_work_exact(&work, &generation, &owner, "backtest-service", at)?;
        Ok(true)
    })
    .await
    .map_err(|_| UNKNOWN)?
}

async fn terminal(
    writer: &SharedAuthority,
    config: &Configuration,
    wake: &Wake,
    status: &watch::Sender<Status>,
    clock: &(impl Fn() -> std::result::Result<OnlyUtcDateTime, PreparationError> + Send + Sync),
    run: &VerifiedRun,
) -> Result<()> {
    let trace_cleanup = Operation::start(
        "backend",
        "backtest.terminal.cleanup",
        Correlation {
            run_id: Some(run.run_id().into()),
            ..Default::default()
        },
    );
    let cleaned: Result<()> = async {
        let observation = {
            let mut held = writer.lock().await;
            Backtests::new(held.as_mut().ok_or(UNAVAILABLE)?, run.namespace())
                .observe_publication(run).await?
        };
        match observation {
            PublicationObservation::Published(_) if run.state() == RunState::Completed => {}
            PublicationObservation::ConfirmedUnpublished(proof)
                if matches!(run.state(), RunState::Cancelled | RunState::Failed)
                    && proof.run_state() == run.state().as_str()
                    && proof.active_attempts() == 0
                    && run.completion_fingerprints().is_none() => {}
            PublicationObservation::Unresolved => return Ok(()),
            _ => return Err("BACKTEST_TERMINAL_CLEANUP_UNPROVEN"),
        }
        let work = run.run_id();
        let generation = run.runtime_generation_fingerprint();
        let owner = run.resolution()["runtime_work_binding"]["reason"]
            .as_str()
            .ok_or("BACKTEST_RUNTIME_BINDING_INVALID")?;
        let mut retry = tokio::time::interval_at(
            tokio::time::Instant::now() + Duration::from_secs(5),
            Duration::from_secs(5),
        );
        retry.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        loop {
            let at = clock().map_err(|e| e.code())?;
            if try_release_runtime_work(config, work, generation, owner, at).await? {
                return Ok(());
            }
            status.send_replace(Status::Uncertain(CLEANUP_PENDING));
            wait_cleanup(wake, &mut retry).await;
        }
    }
    .instrument(trace_cleanup.span().clone())
    .await;
    trace_cleanup.finish(if cleaned.is_ok() { "ok" } else { "failed" }, 1, 0);
    cleaned
}
async fn cleanup_terminal(
    connection: &mut Option<InputConnections>,
    writer: &SharedAuthority,
    config: &Configuration,
    wake: &Wake,
    status: &watch::Sender<Status>,
    clock: &(impl Fn() -> std::result::Result<OnlyUtcDateTime, PreparationError> + Send + Sync),
    namespace: &SemanticStoreId,
) -> Result<()> {
    let root = config.runtime_root.clone();
    let Some(bindings) = super::backtest_profile::spawn_blocking(move || {
        Registry::try_unreleased_work_bindings(&root)
    })
    .await
    .map_err(|_| UNKNOWN)?
    .inspect_err(|code| {
        eprintln!("BACKTEST_WORKER_SCAN_FAILED phase=registry-inventory code={code}")
    })?
    else {
        eprintln!(
            "BACKTEST_WORKER_SCAN_DEFERRED phase=registry-inventory code=RESEARCH_RUNTIME_INVENTORY_LOCK_BUSY"
        );
        return Ok(());
    };
    if bindings.len() > 10000 {
        return Err("BACKTEST_RECOVERY_INVENTORY_BUDGET_EXCEEDED");
    }
    for (work, generation, owner) in bindings {
        if wake.stopped() {
            return Ok(());
        }
        if !crate::application::command::uuid4(&owner) || !crate::application::command::uuid4(&work)
        {
            continue;
        }
        let run = {
            let client = connection
                .as_mut()
                .ok_or(UNKNOWN)?
                .client_mut()
                .await
                .map_err(|_| UNAVAILABLE)?;
            match backtest_run::read_snapshot(client, namespace, &work, None).await {
                Ok((run, _)) => run,
                Err("BACKTEST_RUN_NOT_FOUND") => {
                    let tx = client
                        .build_transaction()
                        .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
                        .read_only(true)
                        .start()
                        .await
                        .map_err(|_| UNAVAILABLE)?;
                    let eligible=crate::persistence::research_preparation::cancelled_backtest_cleanup_in_transaction(&tx,namespace,&work,&generation,&owner).await?;
                    tx.commit().await.map_err(|_| UNAVAILABLE)?;
                    if eligible.is_some() {
                        let at = clock().map_err(|e| e.code())?;
                        if !try_release_runtime_work(config, &work, &generation, &owner, at).await? {
                            eprintln!("BACKTEST_WORKER_SCAN_DEFERRED phase=cancelled-preparation-release code=RESEARCH_RUNTIME_INVENTORY_LOCK_BUSY");
                        }
                    }
                    continue;
                }
                Err(code) => return Err(code),
            }
        };
        if run.runtime_generation_fingerprint() != generation
            || run.resolution()["runtime_work_binding"]["reason"] != owner
        {
            return Err("BACKTEST_RUNTIME_BINDING_INVALID");
        }
        if !run.state().terminal() {
            continue;
        }
        match handoff(
            wake,
            terminal(writer, config, wake, status, clock, &run),
        )
        .await
        {
            None => return Ok(()),
            Some(result) => result?,
        }
    }
    Ok(())
}
fn uuid4() -> Result<String> {
    let mut bytes = [0_u8; 16];
    getrandom::fill(&mut bytes).map_err(|_| UNAVAILABLE)?;
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    let s = bytes.iter().map(|b| format!("{b:02x}")).collect::<String>();
    Ok(format!(
        "{}-{}-{}-{}-{}",
        &s[..8],
        &s[8..12],
        &s[12..16],
        &s[16..20],
        &s[20..]
    ))
}

#[cfg(test)]
#[path = "../../tests/application/support/backtest_worker_assertions.rs"]
pub(crate) mod tests;
