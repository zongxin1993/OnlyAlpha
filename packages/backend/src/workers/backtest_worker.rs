//! Host scheduling over the original Backtest Run/Attempt and physical owners.
//! Wake-ups are observations, never another queue or execution authority.
pub(crate) use super::backtest_service::Configuration;
use crate::{
    application::{
        backtest_run::{VerifiedCompletion, VerifiedRun},
        research_admission::PreparationError,
    },
    bootstrap::{
        deployment::{self, SemanticStoreId},
        workstation_startup::ResearchConnection,
    },
    persistence::{
        backtest_evidence::{self, CompletionProof, Store},
        backtest_run::{self, Backtests, Claim, RunState, RunStatus},
        research_runtime::Registry,
    },
    security::protected_files,
    workers::{
        backtest_service::{self, Control, Produced, StartMode, Work},
        research::SharedAuthority,
    },
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
use tracing::{Instrument, instrument::WithSubscriber};
const UNAVAILABLE: &str = "BACKTEST_SERVICE_UNAVAILABLE";
const UNKNOWN: &str = "BACKTEST_SERVICE_OUTCOME_UNKNOWN";
const LOST: &str = "BACKTEST_EXECUTION_OWNERSHIP_UNCERTAIN";
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
        writer: SharedAuthority,
        configuration: Configuration,
        clock: impl Fn() -> std::result::Result<OnlyUtcDateTime, PreparationError>
        + Send
        + Sync
        + 'static,
    ) -> Result<Self> {
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
                    let uncertain = matches!(status.borrow().clone(), Status::Uncertain(_));
                    if uncertain {
                        status.send_replace(Status::Uncertain(code));
                    } else {
                        status.send_replace(Status::Unavailable(code));
                    }
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
    #[cfg(test)]
    fn test_observations(&self) -> watch::Receiver<Status> {
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
    connection: &mut Option<ResearchConnection>,
    writer: &SharedAuthority,
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
            if !connection.as_ref().is_some_and(ResearchConnection::active) {
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
    let mut store = Backtests::new(held.as_mut().ok_or(UNAVAILABLE)?, run.namespace());
    let current = store.observe(run).await?;
    store.heartbeat(claim).await?;
    #[cfg(test)]
    tests::observed_phase(run.run_id(), "heartbeat_committed");
    Ok(current)
}
enum CompletedJob {
    Published(CompletionProof),
    Paused,
}
enum JobFailure {
    Native(backtest_service::Error),
    Known(&'static str),
}
struct WorkerSignals<'a> {
    wake: &'a Wake,
    status: &'a watch::Sender<Status>,
}
async fn run_one(
    connection: &mut Option<ResearchConnection>,
    writer: &SharedAuthority,
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
        let WorkerSignals { wake, status } = signals;
        let mut current = observe(writer, run.namespace(), run).await?;
        if current.state.terminal() {
            return terminal(connection, writer, config, wake, status, clock, run).await;
        }
        if matches!(current.state, RunState::Running | RunState::CancelRequested) {
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
            let expired = Backtests::new(held.as_mut().ok_or(UNAVAILABLE)?, run.namespace())
                .expire(run, clock().map_err(|e| e.code())?)
                .await?;
            if let Some(expired) = expired {
                current = expired;
            }
        }
        let claim = {
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
            Backtests::new(held.as_mut().ok_or(UNAVAILABLE)?, run.namespace())
                .claim(run, worker, &uuid4()?, clock().map_err(|e| e.code())?)
                .await?
        };
        let Some(mut claim) = claim else {
            return Ok(());
        };
        let trace_attempt = Operation::start("backend","backtest.attempt",Correlation {
            attempt:u64::try_from(claim.attempt_number()).ok(),
            links:Some(format!("attempt:{}",claim.attempt_id())),
            ..Default::default()
        });
        let attempted:Result<()> = async {
            tracing::info!(target:"onlyalpha.observability",event_kind="summary",module="backend",operation="backtest.run.claimed",outcome="claimed");
        let control = Control::default();
        if current.state == RunState::CancelRequested {
            control.request_cancel();
        }
        if wake.stopped() {
            control.request_pause();
        }
        let child = control.clone();
        let configuration = config.clone();
        let selected = run.clone();
        let mode = if claim.attempt_number() == 1 {
            StartMode::Create
        } else {
            StartMode::Resume
        };
        let handle = tokio::runtime::Handle::current();
        let mut original = connection.take().ok_or(UNKNOWN)?;
        let producer_span = tracing::Span::current();
        let producer_dispatch = tracing::dispatcher::get_default(Clone::clone);
        let mut job = tokio::task::spawn_blocking(move || {
            let result = handle.block_on(
                async {
                    let client = original
                        .client_mut()
                        .await
                        .map_err(|_| JobFailure::Known(UNAVAILABLE))?;
                    let context = backtest_evidence::read_context(
                        client,
                        selected.namespace(),
                        &configuration.research_root,
                        &configuration.runtime_root,
                        selected.run_id(),
                        Some(selected.owner()),
                    )
                    .await
                    .map_err(JobFailure::Known)?;

                    let store = Store::open(
                        &configuration.backtest_root,
                        &configuration.research_root,
                        &configuration.runtime_root,
                    )
                    .map_err(JobFailure::Known)?;
                    if let Some(proof) =
                        store.load_completion(&context).map_err(JobFailure::Known)?
                    {
                        return Ok(CompletedJob::Published(proof));
                    }

                    let operation = context.original_operation().clone();
                    let work = super::backtest_profile::measure(
                        selected.run_id(),
                        "job.work.restore",
                        || Work::restore(context, &selected, &operation, &configuration),
                    )
                    .map_err(JobFailure::Native)?;

                    #[cfg(test)]
                    tests::blocking_phase(selected.run_id(), "before_produce");
                    match super::backtest_profile::measure(selected.run_id(), "job.produce", || {
                        backtest_service::produce(work, mode, &child)
                    })
                    .map_err(JobFailure::Native)?
                    {
                        Produced::Paused(paused) => {
                            paused.verify_cut().map_err(JobFailure::Known)?;
                            drop(paused);
                            Ok(CompletedJob::Paused)
                        }
                        Produced::Terminal(joined) => {
                            let proof = super::backtest_profile::measure(
                                selected.run_id(),
                                "job.evidence.commit",
                                || store.commit(joined),
                            )
                            .map_err(JobFailure::Known)?;

                            #[cfg(test)]
                            tests::blocking_phase(selected.run_id(), "after_publish");
                            Ok(CompletedJob::Published(proof))
                        }
                    }
                }
                .instrument(producer_span)
                .with_subscriber(producer_dispatch),
            );
            (original, result)
        });
        let mut timer = tokio::time::interval(Duration::from_secs(30));
        timer.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        let mut uncertain = None;
        let mut stopping = wake.stopped();
        let result = loop {
            tokio::select! {
                finished=&mut job=>break finished.map_err(|_|UNKNOWN)?,
                _=wake.0.changed.notified()=>{},
                _=timer.tick()=>{},
            }
            if wake.stopped() {
                stopping = true;
                control.request_pause();
                #[cfg(test)]
                tests::observed_phase(run.run_id(), "pause_requested");
            }
            if uncertain.is_none() {
                match heartbeat(writer, run, &mut claim).await {
                    Ok(observed) => {
                        if observed.state == RunState::CancelRequested {
                            control.request_cancel();
                            #[cfg(test)]
                            tests::observed_phase(run.run_id(), "cancel_observed");
                        }
                    }
                    Err(_) => {
                        uncertain = Some(LOST);
                        control.request_pause();
                        status.send_replace(Status::Uncertain(LOST));
                        #[cfg(test)]
                        tests::observed_phase(run.run_id(), "ownership_uncertain");
                    }
                }
            }
        };
        *connection = Some(result.0);
        let outcome = match result.1 {
            Err(JobFailure::Native(error)) => {
                let code = error.code();
                drain_native(error, wake, status).await?;
                return Err(uncertain.unwrap_or(code));
            }
            Err(JobFailure::Known(code)) => return Err(uncertain.unwrap_or(code)),
            Ok(outcome) => outcome,
        };
        if let Some(code) = uncertain {
            drop(outcome);
            return Err(code);
        }
        match outcome {
            CompletedJob::Paused => {
                if !stopping {
                    return Err("BACKTEST_PAUSE_UNREQUESTED");
                }
                Ok(())
            }
            CompletedJob::Published(proof) => {
                let completion = super::backtest_profile::measure(
                    run.run_id(),
                    "job.completion.from_proof",
                    || VerifiedCompletion::from_proof(proof),
                )?;
                {
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
                    let mut store =
                        Backtests::new(held.as_mut().ok_or(UNAVAILABLE)?, run.namespace());
                    if completion.proof().status() == "CANCELLED" {
                        store
                            .cancel(&mut claim, &completion, clock().map_err(|e| e.code())?)
                            .await?;
                    } else {
                        store
                            .complete(&mut claim, &completion, clock().map_err(|e| e.code())?)
                            .await?;
                    }
                }
                drop(completion);
                terminal(connection, writer, config, wake, status, clock, run).await
            }
        }
        }.instrument(trace_attempt.span().clone()).await;
        trace_attempt.finish(if attempted.is_ok() {"ok"} else {"failed"},1,0);
        attempted
    }
    .instrument(trace_job.span().clone())
    .await;
    trace_job.finish(if observed.is_ok() { "ok" } else { "failed" }, 1, 0);
    observed
}
async fn drain_native(
    mut error: backtest_service::Error,
    wake: &Wake,
    status: &watch::Sender<Status>,
) -> Result<()> {
    let code = error.code();
    if code.contains("UNKNOWN") || code.contains("UNCERTAIN") {
        status.send_replace(Status::Uncertain(code));
    }
    let mut retry = tokio::time::interval_at(
        tokio::time::Instant::now() + Duration::from_secs(5),
        Duration::from_secs(5),
    );
    retry.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    loop {
        let (returned, drained) = super::backtest_profile::spawn_blocking(move || {
            let result = error.drain();
            (error, result)
        })
        .await
        .map_err(|_| UNKNOWN)?;
        error = returned;
        if drained.is_ok() {
            drop(error);
            return Ok(());
        }
        status.send_replace(Status::Uncertain(code));
        wait_cleanup(wake, &mut retry).await;
    }
}
/// A terminal binding is released only after actual owning evidence verification
/// and after every returned proof/context/input hold has been dropped.
async fn terminal(
    connection: &mut Option<ResearchConnection>,
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
        let current = {
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
            Backtests::new(held.as_mut().ok_or(UNAVAILABLE)?, run.namespace())
                .load(run.run_id())
                .await?
        };
        if !current.state().terminal() {
            return Err("BACKTEST_TERMINAL_CLEANUP_CONFLICT");
        }
        if current.state() == RunState::Completed
            || (current.state() == RunState::Cancelled && current.was_started())
        {
            let mut original = connection.take().ok_or(UNKNOWN)?;
            let selected = current.clone();
            let cfg = config.clone();
            let handle = tokio::runtime::Handle::current();
            let cleanup_span = tracing::Span::current();
            let cleanup_dispatch = tracing::dispatcher::get_default(Clone::clone);
            let (returned, checked) = tokio::task::spawn_blocking(move || {
                let result = handle.block_on(
                    async {
                        let client = original.client_mut().await.map_err(|_| UNAVAILABLE)?;
                        let context = backtest_evidence::read_context(
                            client,
                            selected.namespace(),
                            &cfg.research_root,
                            &cfg.runtime_root,
                            selected.run_id(),
                            Some(selected.owner()),
                        )
                        .await?;
                        let store =
                            Store::open(&cfg.backtest_root, &cfg.research_root, &cfg.runtime_root)?;
                        let proof = store
                            .load_completion(&context)?
                            .ok_or("BACKTEST_COMPLETION_PROOF_UNAVAILABLE")?;
                        proof.verify_cut()?;
                        if proof.status() != selected.state().as_str() {
                            return Err("BACKTEST_TERMINAL_CLEANUP_CONFLICT");
                        }
                        drop(proof);
                        drop(context);
                        Ok(())
                    }
                    .instrument(cleanup_span)
                    .with_subscriber(cleanup_dispatch),
                );
                (original, result)
            })
            .await
            .map_err(|_| UNKNOWN)?;
            *connection = Some(returned);
            checked?;
        } else if current.state() != RunState::Cancelled
            || current.was_started()
            || current.completion_fingerprints().is_some()
        {
            // No known producer drain proof exists for an arbitrary FAILED row.
            return Err("BACKTEST_TERMINAL_CLEANUP_UNPROVEN");
        }
        let work = current.run_id().to_owned();
        let generation = current.runtime_generation_fingerprint().to_owned();
        let owner = current.resolution()["runtime_work_binding"]["reason"]
            .as_str()
            .ok_or("BACKTEST_RUNTIME_BINDING_INVALID")?
            .to_owned();
        let mut retry = tokio::time::interval_at(
            tokio::time::Instant::now() + Duration::from_secs(5),
            Duration::from_secs(5),
        );
        retry.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        loop {
            let root = config.runtime_root.clone();
            let work = work.clone();
            let generation = generation.clone();
            let owner = owner.clone();
            let at = clock().map_err(|e| e.code())?;
            let result = super::backtest_profile::spawn_blocking(move || {
                Registry::open_existing(&root)?
                    .release_work_exact(&work, &generation, &owner, "backtest-service", at)
                    .map(drop)
            })
            .await
            .map_err(|_| UNKNOWN)?;
            match result {
                Ok(()) => return Ok(()),
                Err("RESEARCH_RUNTIME_UNAVAILABLE") => {
                    status.send_replace(Status::Uncertain("BACKTEST_RUNTIME_CLEANUP_PENDING"));
                    wait_cleanup(wake, &mut retry).await;
                }
                Err(code) => return Err(code),
            }
        }
    }
    .instrument(trace_cleanup.span().clone())
    .await;
    trace_cleanup.finish(if cleaned.is_ok() { "ok" } else { "failed" }, 1, 0);
    cleaned
}
async fn cleanup_terminal(
    connection: &mut Option<ResearchConnection>,
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
                        let root = config.runtime_root.clone();
                        let work = work.clone();
                        let generation = generation.clone();
                        let owner = owner.clone();
                        let at = clock().map_err(|e| e.code())?;
                        let released = super::backtest_profile::spawn_blocking(move || {
                            Registry::open_existing(&root)?
                                .release_work_exact(
                                    &work,
                                    &generation,
                                    &owner,
                                    "backtest-service",
                                    at,
                                )
                                .map(drop)
                        })
                        .await
                        .map_err(|_| UNKNOWN)?;
                        match released {
                            Ok(()) | Err("RESEARCH_RUNTIME_UNAVAILABLE") => {}
                            Err(code) => return Err(code),
                        }
                    }
                    // Busy physical readers retain the same exact binding. The
                    // existing five-second scan observes it again; no new job/Run.
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
            terminal(connection, writer, config, wake, status, clock, &run),
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
