//! Host-owned recovery/execution of accepted native Research Runs.
//! Durable authorization is loaded from the original Run; no Human/Agent session is recreated.
use crate::{
    application::{
        research_admission::{self, PreparationError},
        research_run::VerifiedRun,
    },
    bootstrap::workstation_startup::ResearchConnection,
    persistence::{
        research_dataset::Store as Datasets, research_runtime::RuntimeInputHold,
        research_submission,
    },
    workers::research::{self, Work},
};
use onlyalpha_calculation_bridge::ChartInstallation;
use onlyalpha_domain::time::OnlyUtcDateTime;
use std::{
    path::PathBuf,
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
const UNAVAILABLE: &str = "RESEARCH_SERVICE_UNAVAILABLE";
const UNKNOWN: &str = "RESEARCH_SERVICE_OUTCOME_UNKNOWN";
const ROWS: usize = 10_000;
#[derive(Clone)]
pub(crate) struct Configuration {
    pub runtime_root: PathBuf,
    pub research_root: PathBuf,
    pub algorithms: PathBuf,
    pub native_version: String,
}
/// Observations only: the DB Run/Attempt and immutable stores remain authoritative.
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
    /// Call only after the original submission transaction commits. Coalescing is safe:
    /// each wake scans the durable owner, rather than carrying a second in-memory queue.
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
pub(crate) struct Service {
    wake: Wake,
    status: watch::Receiver<Status>,
    task: Option<JoinHandle<Result<(), &'static str>>>,
    drained: Option<Result<(), &'static str>>,
}
impl Service {
    pub(crate) fn start(
        connection: ResearchConnection,
        writer: research::SharedAuthority,
        configuration: Configuration,
        clock: impl Fn() -> Result<OnlyUtcDateTime, PreparationError> + Send + Sync + 'static,
    ) -> Result<Self, &'static str> {
        if !connection.active() {
            return Err(UNAVAILABLE);
        }
        let worker = uuid4()?;
        let wake = Wake(Arc::new(Admission {
            state: AtomicU8::new(0),
            changed: Notify::new(),
        }));
        let (status, observed) = watch::channel(Status::Starting);
        let selected = wake.clone();
        let task = tokio::spawn(async move {
            let mut connection = connection;
            let result = serve(
                &mut connection,
                &writer,
                &configuration,
                &selected,
                &status,
                &clock,
                &worker,
            )
            .await;
            let closed = connection.close().await.map_err(|_| UNAVAILABLE);
            match result.and(closed) {
                Ok(()) => {
                    status.send_replace(Status::Stopped);
                    Ok(())
                }
                Err(code) => {
                    status.send_replace(Status::Unavailable(code));
                    // Work and its original child are already joined; the read-only
                    // driver has completed close. Preserve the operational error above,
                    // independently of physical ownership drain success.
                    Ok(())
                }
            }
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
            return Status::Uncertain(code);
        }
        self.status.borrow().clone()
    }
    /// Stops new work atomically, then retains and joins all already-started work.
    /// Cancelling this await does not take/drop the retained task handle or process owner.
    pub(crate) async fn drain(&mut self) -> Result<(), &'static str> {
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
        // Never abort an executing/preparing child. The retained task drains before exit.
        self.wake.stop();
    }
}
async fn serve(
    connection: &mut ResearchConnection,
    writer: &research::SharedAuthority,
    config: &Configuration,
    wake: &Wake,
    status: &watch::Sender<Status>,
    clock: &(impl Fn() -> Result<OnlyUtcDateTime, PreparationError> + Send + Sync),
    worker: &str,
) -> Result<(), &'static str> {
    let mut poll = tokio::time::interval(Duration::from_secs(5));
    poll.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    // The initial interval tick performs startup recovery, independent of a submitting Agent.
    loop {
        if !next_scan(wake, &mut poll).await {
            return Ok(());
        }
        let client = connection.client_mut().await.map_err(|_| UNAVAILABLE)?;
        let tx = client.transaction().await.map_err(|_| UNAVAILABLE)?;
        crate::persistence::postgres::bounds(&tx)
            .await
            .map_err(|_| UNAVAILABLE)?;
        let rows=tx.query("SELECT r.run_id::text FROM research_run r WHERE r.specification_schema_version=4 AND r.origin_kind='GENERAL' AND r.state IN ('QUEUED','RUNNING','CANCEL_REQUESTED') AND NOT EXISTS(SELECT 1 FROM research_run_attempt a WHERE a.run_id=r.run_id AND a.state='ACTIVE' AND a.lease_expires_at>clock_timestamp()) ORDER BY r.queued_at,r.run_id LIMIT 10001",&[]).await.map_err(|_|UNAVAILABLE)?;
        tx.commit().await.map_err(|_| UNAVAILABLE)?;
        if rows.len() > ROWS {
            return Err("RESEARCH_RECOVERY_INVENTORY_BUDGET_EXCEEDED");
        }
        let ids = rows
            .iter()
            .map(|r| r.try_get::<_, String>(0).map_err(|_| UNAVAILABLE))
            .collect::<Result<Vec<_>, _>>()?;
        for id in ids {
            if wake.stopped() {
                return Ok(());
            }
            let run = research_submission::load(
                connection.client_mut().await.map_err(|_| UNAVAILABLE)?,
                &id,
                None,
            )
            .await?;
            status.send_replace(Status::Running(id));
            // All cancellation, expiry and terminal projections use the same canonical
            // protocol and original writer as run_owned, before any executable preparation.
            // Admission covers the entire retained restoration + execution handoff.
            // Shutdown cannot pass this CAS then start a fresh preflight later.
            let result = handoff(wake, async {
                clock()?;
                if research::recover_owned(writer, &run, &config.research_root, clock)
                    .await?
                    .is_some()
                {
                    return Ok(());
                }
                let configuration = config.clone();
                let worker = worker.to_owned();
                let attempt = uuid4()?;
                let work = tokio::task::spawn_blocking(move || {
                    restore_work(run, &configuration, worker, attempt)
                })
                .await
                .map_err(|_| PreparationError::from(UNKNOWN))?;
                match work {
                    Ok(work) => research::run_owned(writer, work, clock).await.map(|_| ()),
                    Err(error) => Err(error),
                }
            })
            .await;
            let Some(result) = result else { return Ok(()) };
            if let Err(error) = result {
                // Stop the service rather than create a replacement Attempt after uncertainty.
                // The same original process owner is retained until its explicit drain succeeds.
                let code = error.code();
                if code.contains("UNKNOWN") || error.recovery_owner().is_some() {
                    status.send_replace(Status::Uncertain(code));
                    drain_original(error, wake, status).await?;
                }
                return Err(code);
            }
            if !connection.active() {
                return Err("RESEARCH_NODE_AUTHORITY_UNAVAILABLE");
            }
        }
        status.send_replace(Status::Idle);
    }
}
/// One scheduling gate for initial recovery, post-commit wake and lease-expiry observation.
/// It carries no Run or permission and cannot restart stopped admission.
async fn next_scan(wake: &Wake, poll: &mut tokio::time::Interval) -> bool {
    if wake.stopped() {
        return false;
    }
    tokio::select! { _ = wake.0.changed.notified() => {}, _ = poll.tick() => {} }
    !wake.stopped()
}

/// The future is not polled until atomic admission. This covers preparation itself,
/// rather than opening the gate only after a child might already have started.
async fn handoff(
    wake: &Wake,
    operation: impl std::future::Future<Output = Result<(), PreparationError>>,
) -> Option<Result<(), PreparationError>> {
    if !wake.begin() {
        return None;
    }
    let result = operation.await;
    wake.finish();
    Some(result)
}

fn restore_work(
    run: VerifiedRun,
    config: &Configuration,
    worker_id: String,
    attempt_id: String,
) -> Result<Work, PreparationError> {
    let owner = run.prepared_inputs["runtime_work_binding"]["reason"]
        .as_str()
        .ok_or("RESEARCH_RECOVERY_BINDING_INVALID")?;
    let runtime = RuntimeInputHold::open(
        &config.runtime_root,
        run.run_id(),
        owner,
        run.runtime_generation_fingerprint(),
    )?;
    let installation = ChartInstallation::open(
        &config.algorithms,
        &run.specification().algorithm_artifact_fingerprint,
    )
    .map_err(|_| "RESEARCH_ALGORITHM_INSTALLATION_CHANGED")?;
    let datasets = Datasets::open(
        &config.research_root.join("datasets"),
        8192,
        8 * 1024 * 1024,
    )?;
    let inputs = research_admission::restore(&run, runtime, &installation, &datasets)?;
    Ok(Work {
        run,
        inputs,
        datasets,
        installation,
        evidence_root: config.research_root.clone(),
        native_version: config.native_version.clone(),
        worker_id,
        attempt_id,
    })
}
async fn drain_original(
    error: PreparationError,
    wake: &Wake,
    status: &watch::Sender<Status>,
) -> Result<(), &'static str> {
    let Some(owner) = error.recovery_owner() else {
        return Ok(());
    };
    loop {
        let selected = owner.clone();
        let result = tokio::task::spawn_blocking(move || selected.drain()).await;
        if matches!(result, Ok(Ok(()))) {
            return Ok(());
        }
        status.send_replace(Status::Uncertain(error.code()));
        // No polling retry and no replacement child. The failed original owner stays
        // alive here. Shutdown or an explicit wake may request another original drain.
        wake.0.changed.notified().await;
    }
}
fn uuid4() -> Result<String, &'static str> {
    let mut bytes = [0u8; 16];
    getrandom::fill(&mut bytes).map_err(|_| UNAVAILABLE)?;
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    let text = bytes.iter().map(|b| format!("{b:02x}")).collect::<String>();
    Ok(format!(
        "{}-{}-{}-{}-{}",
        &text[..8],
        &text[8..12],
        &text[12..16],
        &text[16..20],
        &text[20..]
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::AtomicBool;
    #[tokio::test(start_paused = true)]
    async fn startup_scans_without_agent_and_post_commit_wake_survives_processing() {
        let wake = Wake(Arc::new(Admission {
            state: AtomicU8::new(0),
            changed: Notify::new(),
        }));
        let mut poll = tokio::time::interval(Duration::from_secs(5));
        assert!(next_scan(&wake, &mut poll).await);
        // A commit during current processing retains a permit for the next durable scan.
        assert!(wake.notify());
        assert!(next_scan(&wake, &mut poll).await);
        {
            let pending = next_scan(&wake, &mut poll);
            tokio::pin!(pending);
            tokio::select! { biased; _ = &mut pending => panic!("no event or clock advance"), _ = std::future::ready(()) => {} }
            assert!(wake.notify());
            assert!(pending.await);
        }
        wake.stop();
        assert!(!next_scan(&wake, &mut poll).await);
        assert!(!wake.notify());
    }
    #[tokio::test]
    async fn uncertain_join_is_latched_across_repeated_drains() {
        let wake = Wake(Arc::new(Admission {
            state: AtomicU8::new(0),
            changed: Notify::new(),
        }));
        let (_sender, observed) = watch::channel(Status::Starting);
        let (failed, original) = tokio::sync::oneshot::channel::<Result<(), &'static str>>();
        drop(failed);
        let task = tokio::spawn(async { original.await.expect("controlled owner task failure") });
        let mut service = Service {
            wake,
            status: observed,
            task: Some(task),
            drained: None,
        };
        assert_eq!(service.drain().await, Err(UNKNOWN));
        assert_eq!(service.drain().await, Err(UNKNOWN));
        assert_eq!(service.status(), Status::Uncertain(UNKNOWN));
    }
    #[tokio::test]
    async fn stop_before_handoff_cannot_start_preflight() {
        let wake = Wake(Arc::new(Admission {
            state: AtomicU8::new(0),
            changed: Notify::new(),
        }));
        let started = AtomicBool::new(false);
        wake.stop();
        let result = handoff(&wake, async {
            started.store(true, Ordering::Release);
            Ok(())
        })
        .await;
        assert!(result.is_none());
        assert!(!started.load(Ordering::Acquire));
    }
    #[tokio::test]
    async fn stop_during_restore_keeps_the_entire_original_handoff_owned() {
        let wake = Wake(Arc::new(Admission {
            state: AtomicU8::new(0),
            changed: Notify::new(),
        }));
        let (entered, preflight) = tokio::sync::oneshot::channel();
        let (release, wait) = tokio::sync::oneshot::channel();
        let admitted = wake.clone();
        let job = tokio::spawn(async move {
            handoff(&admitted, async {
                entered.send(()).unwrap();
                wait.await.map_err(|_| PreparationError::from(UNKNOWN))?;
                Ok(())
            })
            .await
        });
        preflight.await.unwrap();
        wake.stop();
        assert!(!wake.begin());
        assert!(!job.is_finished());
        release.send(()).unwrap();
        job.await.unwrap().unwrap().unwrap();
        assert!(wake.stopped());
        assert!(!wake.begin());
    }
    #[tokio::test]
    async fn cancelled_shutdown_await_keeps_the_original_work_owned() {
        let wake = Wake(Arc::new(Admission {
            state: AtomicU8::new(0),
            changed: Notify::new(),
        }));
        assert!(wake.begin());
        let (finished, release) = tokio::sync::oneshot::channel();
        let running = wake.clone();
        let task = tokio::spawn(async move {
            release.await.map_err(|_| UNKNOWN)?;
            running.finish();
            Ok(())
        });
        let (_status, observed) = watch::channel(Status::Running("original-work".into()));
        let mut service = Service {
            wake: wake.clone(),
            status: observed,
            task: Some(task),
            drained: None,
        };
        {
            let shutdown = service.drain();
            tokio::pin!(shutdown);
            tokio::select! {biased;_=&mut shutdown=>panic!("unreleased work cannot be drained"),_=std::future::ready(())=>{}}
        }
        assert!(wake.stopped());
        assert!(!wake.begin());
        assert!(
            service
                .task
                .as_ref()
                .is_some_and(|task| !task.is_finished())
        );
        finished.send(()).unwrap();
        service.drain().await.unwrap();
        assert!(!wake.begin());
        assert!(!wake.notify());
        assert!(service.task.is_none());
    }
}
