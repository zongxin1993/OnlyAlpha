//! Actual original connections and admitted Ready/Run3 are supplied by the
//! existing owner fixture. No Runtime, joined-product or completion factory.
use super::*;
use crate::{
    application::{
        backtest_run::{CancelRequest, Context, VerifiedRun},
        command::CommandId,
    },
    bootstrap::workstation_startup::ResearchConnection,
    persistence::{
        backtest_run::{Backtests, RunState},
        research_runtime::Registry,
    },
    workers::{backtest_service, research::SharedAuthority},
};
use onlyalpha_domain::time::OnlyUtcDateTime;
use std::{
    collections::BTreeMap,
    path::Path,
    sync::{
        Arc, Condvar, Mutex,
        atomic::{AtomicBool, Ordering},
    },
};
use tokio::sync::Notify;

#[test]
fn scheduler_uses_original_infrastructure_owners_and_concrete_producer() {
    type Clock = fn() -> std::result::Result<
        OnlyUtcDateTime,
        crate::application::research_admission::PreparationError,
    >;
    type Start = fn(
        ResearchConnection,
        SharedAuthority,
        Configuration,
        Clock,
    ) -> std::result::Result<Service, &'static str>;
    let _: Start = Service::start;
    let _: fn(&Service) -> Wake = Service::wake;
    let _: fn(&Wake) -> bool = Wake::notify;
    let _: fn(&Wake) = Wake::stop;
    let _: fn(&Service) -> Status = Service::status;
    let _ = Service::drain;
    let _: fn(
        &crate::persistence::backtest_evidence::Store,
        &crate::persistence::backtest_evidence::BacktestReadContext,
    ) -> std::result::Result<
        Option<crate::persistence::backtest_evidence::CompletionProof>,
        &'static str,
    > = crate::persistence::backtest_evidence::Store::load_completion;
    let _: fn(
        &crate::persistence::backtest_evidence::Store,
        backtest_service::JoinedBacktest,
    ) -> std::result::Result<
        crate::persistence::backtest_evidence::CompletionProof,
        &'static str,
    > = crate::persistence::backtest_evidence::Store::commit;
}

// Deterministic barriers at real blocking phases. They never return a Run,
// observation, completion or joined grant and are absent from production.
#[derive(Default)]
pub(super) struct Gate {
    entered: AtomicBool,
    changed: Notify,
    released: Mutex<bool>,
    resume: Condvar,
}
impl Gate {
    async fn entered(&self) {
        loop {
            let notified = self.changed.notified();
            if self.entered.load(Ordering::Acquire) {
                return;
            }
            notified.await;
        }
    }
    fn hit(&self) {
        self.entered.store(true, Ordering::Release);
        self.changed.notify_waiters();
        let mut released = self.released.lock().unwrap();
        while !*released {
            released = self.resume.wait(released).unwrap();
        }
    }
    fn release(&self) {
        *self.released.lock().unwrap() = true;
        self.resume.notify_all();
    }
}
type Gates = Mutex<BTreeMap<(String, String), Arc<Gate>>>;
static GATES: std::sync::OnceLock<Gates> = std::sync::OnceLock::new();
fn gate(run: &str, phase: &str) -> Arc<Gate> {
    let value = Arc::new(Gate::default());
    assert!(
        GATES
            .get_or_init(Default::default)
            .lock()
            .unwrap()
            .insert((run.into(), phase.into()), value.clone())
            .is_none()
    );
    value
}
/// Called only by the actual blocking job, after restore and after Store.commit.
pub(super) fn blocking_phase(run: &str, phase: &str) {
    let gate = GATES
        .get_or_init(Default::default)
        .lock()
        .unwrap()
        .get(&(run.into(), phase.into()))
        .cloned();
    if let Some(gate) = gate {
        gate.hit();
    }
}
/// Async control observations never block the executor or retain a SQL guard.
pub(super) fn observed_phase(run: &str, phase: &str) {
    let gate = GATES
        .get_or_init(Default::default)
        .lock()
        .unwrap()
        .get(&(run.into(), phase.into()))
        .cloned();
    if let Some(gate) = gate {
        gate.entered.store(true, Ordering::Release);
        gate.changed.notify_waiters();
    }
}
fn remove_gate(run: &str, phase: &str) {
    GATES
        .get_or_init(Default::default)
        .lock()
        .unwrap()
        .remove(&(run.into(), phase.into()));
}

// This copies no semantic work into the fixture. The source is an actual
// completed Research/Freeze/Qualified/Ready/Run3 chain from the shared fixture.
fn files(root: &Path) -> BTreeMap<String, (u64, Vec<u8>)> {
    use std::os::unix::fs::MetadataExt;
    fn visit(root: &Path, path: &Path, out: &mut BTreeMap<String, (u64, Vec<u8>)>) {
        if !path.exists() {
            return;
        }
        for entry in std::fs::read_dir(path).unwrap() {
            let entry = entry.unwrap();
            let at = entry.path();
            let metadata = std::fs::symlink_metadata(&at).unwrap();
            assert!(!metadata.file_type().is_symlink());
            if metadata.is_dir() {
                visit(root, &at, out);
            } else {
                out.insert(
                    at.strip_prefix(root).unwrap().to_str().unwrap().into(),
                    (metadata.ino(), std::fs::read(at).unwrap()),
                );
            }
        }
    }
    let mut output = BTreeMap::new();
    visit(root, root, &mut output);
    output
}
async fn writer_row(
    writer: &SharedAuthority,
    run: &str,
) -> (String, Option<String>, Option<String>, Option<String>) {
    let mut held = writer.lock().await;
    let client = held.as_mut().unwrap().client_mut().await.unwrap();
    let row=client.query_one("SELECT state,evidence_fingerprint,result_fingerprint,determinism_fingerprint FROM backtest_run WHERE run_id=$1::text::uuid",&[&run]).await.unwrap();
    (row.get(0), row.get(1), row.get(2), row.get(3))
}
async fn expire_original(writer: &SharedAuthority, run: &str) {
    let mut held = writer.lock().await;
    held.as_mut().unwrap().client_mut().await.unwrap().execute(
        "UPDATE backtest_run_attempt SET claimed_at=clock_timestamp()-interval '3 seconds',last_heartbeat_at=clock_timestamp()-interval '2 seconds',lease_expires_at=clock_timestamp()-interval '1 second' WHERE run_id=$1::text::uuid AND state='ACTIVE'",&[&run]).await.unwrap();
}
async fn idle(service: &mut Service) {
    let mut observed = service.test_observations();
    loop {
        match observed.borrow().clone() {
            Status::Idle => return,
            Status::Uncertain(code) | Status::Unavailable(code) => panic!("{code}"),
            _ => {}
        }
        observed.changed().await.unwrap();
    }
}
async fn assert_terminal(writer: &SharedAuthority, run: &VerifiedRun, status: &str) {
    let actual = writer_row(writer, run.run_id()).await;
    assert_eq!(actual.0, status);
    assert!(actual.1.is_some() && actual.2.is_some() && actual.3.is_some());
    let mut held = writer.lock().await;
    let original = held.as_mut().unwrap();
    original.verify().await.unwrap();
    let current = Backtests::new(original, run.namespace())
        .load(run.run_id())
        .await
        .unwrap();
    assert_eq!(current.run_id(), run.run_id());
    assert_eq!(
        current.specification_fingerprint(),
        run.specification_fingerprint()
    );
    assert_eq!(
        current.admission_resolution_fingerprint(),
        run.admission_resolution_fingerprint()
    );
    assert_eq!(current.record(), run.record());
}

/// The caller commits queued cancellation with the original Human Command first.
pub(crate) async fn queued_cancel(
    connection: ResearchConnection,
    writer: SharedAuthority,
    configuration: Configuration,
    run: VerifiedRun,
    clock: fn() -> std::result::Result<
        OnlyUtcDateTime,
        crate::application::research_admission::PreparationError,
    >,
) {
    assert_eq!(run.state(), RunState::Cancelled);
    assert!(!run.was_started());
    assert_eq!(run.completion_fingerprints(), None);
    let runtime = configuration
        .backtest_root
        .join("runtime")
        .join(run.run_id());
    assert!(!runtime.exists());
    let before = files(&configuration.backtest_root);
    let mut service = Service::start(connection, writer.clone(), configuration, clock).unwrap();
    idle(&mut service).await;
    assert_eq!(
        files(runtime.parent().unwrap().parent().unwrap()),
        before,
        "queued cancellation cannot create a Runtime, SDK child, journal or Evidence"
    );
    let mut held = writer.lock().await;
    assert_eq!(
        held.as_mut()
            .unwrap()
            .client_mut()
            .await
            .unwrap()
            .query_one(
                "SELECT count(*) FROM backtest_run_attempt WHERE run_id=$1::text::uuid",
                &[&run.run_id()]
            )
            .await
            .unwrap()
            .get::<_, i64>(0),
        0
    );
    drop(held);
    service.drain().await.unwrap();
}

/// Real pause occurs after original claim+opaque restore. The blocking barrier
/// lets shutdown win deterministically while the physical owners remain retained.
pub(crate) async fn shutdown_pause(
    connection: ResearchConnection,
    writer: SharedAuthority,
    configuration: Configuration,
    run: VerifiedRun,
    clock: fn() -> std::result::Result<
        OnlyUtcDateTime,
        crate::application::research_admission::PreparationError,
    >,
) {
    let barrier = gate(run.run_id(), "before_produce");
    let paused = gate(run.run_id(), "pause_requested");
    let mut service =
        Service::start(connection, writer.clone(), configuration.clone(), clock).unwrap();
    barrier.entered().await;
    assert_eq!(writer_row(&writer, run.run_id()).await.0, "RUNNING");
    let wake = service.wake();
    wake.stop();
    assert!(!wake.notify());
    let mut drain = Box::pin(service.drain());
    tokio::select! {biased;result=&mut drain=>panic!("shutdown dropped a live blocking owner: {result:?}"),_ = tokio::task::yield_now()=>{}}
    drop(drain);
    paused.entered().await;
    barrier.release();
    service.drain().await.unwrap();
    remove_gate(run.run_id(), "before_produce");
    remove_gate(run.run_id(), "pause_requested");
    let current = writer_row(&writer, run.run_id()).await;
    assert_eq!(current, ("RUNNING".into(), None, None, None));
    let mut held = writer.lock().await;
    let client = held.as_mut().unwrap().client_mut().await.unwrap();
    let rows=client.query("SELECT state,failure_code,failure_detail FROM backtest_run_attempt WHERE run_id=$1::text::uuid ORDER BY attempt_number",&[&run.run_id()]).await.unwrap();
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].get::<_, &str>(0), "ACTIVE");
    assert!(
        rows[0].get::<_, Option<String>>(1).is_none()
            && rows[0].get::<_, Option<String>>(2).is_none()
    );
    drop(held);
    assert!(
        configuration
            .backtest_root
            .join("runtime")
            .join(run.run_id())
            .join("runtime.sqlite3")
            .is_file()
    );
    assert!(
        Registry::inspect_work(
            &configuration.runtime_root,
            run.run_id(),
            run.runtime_generation_fingerprint(),
            run.resolution()["runtime_work_binding"]["reason"]
                .as_str()
                .unwrap()
        )
        .unwrap()["closed"]
            != true,
        "pause never releases an unfinished original work"
    );
}

/// A new original readonly session is supplied by Infrastructure after restart;
/// this function neither reconnects nor changes the immutable Run/READY identity.
pub(crate) async fn resume_expired(
    connection: ResearchConnection,
    writer: SharedAuthority,
    configuration: Configuration,
    run: VerifiedRun,
    clock: fn() -> std::result::Result<
        OnlyUtcDateTime,
        crate::application::research_admission::PreparationError,
    >,
) {
    let journal = configuration
        .backtest_root
        .join("runtime")
        .join(run.run_id())
        .join("runtime.sqlite3");
    use std::os::unix::fs::MetadataExt;
    let inode = std::fs::metadata(&journal).unwrap().ino();
    expire_original(&writer, run.run_id()).await;
    let mut service = Service::start(connection, writer.clone(), configuration, clock).unwrap();
    idle(&mut service).await;
    assert_terminal(&writer, &run, "COMPLETED").await;
    assert_eq!(std::fs::metadata(journal).unwrap().ino(), inode);
    let mut held = writer.lock().await;
    let rows=held.as_mut().unwrap().client_mut().await.unwrap().query("SELECT attempt_number,fencing_token,state FROM backtest_run_attempt WHERE run_id=$1::text::uuid ORDER BY attempt_number",&[&run.run_id()]).await.unwrap();
    assert_eq!(rows.len(), 2);
    assert_eq!(rows[0].get::<_, &str>(2), "EXPIRED");
    assert_eq!(rows[1].get::<_, &str>(2), "SUCCEEDED");
    assert!(rows[1].get::<_, i32>(0) > rows[0].get::<_, i32>(0));
    assert!(rows[1].get::<_, i64>(1) > rows[0].get::<_, i64>(1));
    drop(held);
    service.drain().await.unwrap();
}

/// Heartbeat/cancellation is explicitly woken while the actual blocking job is
/// retained. The caller owns the same accepted Human source context.
pub(crate) async fn cancel_running(
    connection: ResearchConnection,
    writer: SharedAuthority,
    configuration: Configuration,
    run: VerifiedRun,
    context: &Context<'_>,
    cancel: CommandId,
    clock: fn() -> std::result::Result<
        OnlyUtcDateTime,
        crate::application::research_admission::PreparationError,
    >,
) {
    let barrier = gate(run.run_id(), "before_produce");
    let cancelled = gate(run.run_id(), "cancel_observed");
    let renewed = gate(run.run_id(), "heartbeat_committed");
    let mut service = Service::start(connection, writer.clone(), configuration, clock).unwrap();
    barrier.entered().await;
    {
        let mut held = writer.lock().await;
        held.as_mut().unwrap().client_mut().await.unwrap().execute("UPDATE backtest_run_attempt SET claimed_at=clock_timestamp()-interval '3 seconds',last_heartbeat_at=clock_timestamp()-interval '2 seconds' WHERE run_id=$1::text::uuid AND state='ACTIVE'",&[&run.run_id()]).await.unwrap();
    }
    assert!(service.wake().notify());
    renewed.entered().await;
    {
        let mut held = writer.lock().await;
        let row=held.as_mut().unwrap().client_mut().await.unwrap().query_one("SELECT lease_expires_at>clock_timestamp(),state FROM backtest_run_attempt WHERE run_id=$1::text::uuid AND state='ACTIVE'",&[&run.run_id()]).await.unwrap();
        assert!(row.get::<_, bool>(0));
        assert_eq!(row.get::<_, &str>(1), "ACTIVE");
    }
    let request = CancelRequest::new(cancel, run.run_id()).unwrap();
    {
        let mut held = writer.lock().await;
        Backtests::new(held.as_mut().unwrap(), run.namespace())
            .request_cancel(&request, context, clock().unwrap())
            .await
            .unwrap();
    }
    assert!(service.wake().notify());
    cancelled.entered().await;
    barrier.release();
    remove_gate(run.run_id(), "before_produce");
    remove_gate(run.run_id(), "cancel_observed");
    remove_gate(run.run_id(), "heartbeat_committed");
    idle(&mut service).await;
    assert_terminal(&writer, &run, "CANCELLED").await;
    service.drain().await.unwrap();
}

/// The harness runs this in its existing isolated owner process, then observes
/// exit86/original DB lease with the canonical driver-drain barrier.
pub(crate) async fn crash_after_publication(
    connection: ResearchConnection,
    writer: SharedAuthority,
    configuration: Configuration,
    run: VerifiedRun,
    clock: fn() -> std::result::Result<
        OnlyUtcDateTime,
        crate::application::research_admission::PreparationError,
    >,
) -> ! {
    let barrier = gate(run.run_id(), "after_publish");
    let _service =
        Service::start(connection, writer.clone(), configuration.clone(), clock).unwrap();
    barrier.entered().await;
    assert_eq!(
        writer_row(&writer, run.run_id()).await,
        ("RUNNING".into(), None, None, None)
    );
    assert!(configuration.backtest_root.join("evidence/sha256").is_dir());
    std::io::Write::flush(&mut std::io::stdout()).unwrap();
    std::process::exit(86)
}

/// Actual FS publication precedes the rejected SQL reply. Recovery must load
/// the same owning bundle/journal and finalize with a new fence, without SDKs.
pub(crate) async fn recover_published(
    connection: ResearchConnection,
    writer: SharedAuthority,
    configuration: Configuration,
    run: VerifiedRun,
    clock: fn() -> std::result::Result<
        OnlyUtcDateTime,
        crate::application::research_admission::PreparationError,
    >,
) {
    let before = files(&configuration.backtest_root);
    let no_producer = gate(run.run_id(), "before_produce");
    expire_original(&writer, run.run_id()).await;
    let mut service =
        Service::start(connection, writer.clone(), configuration.clone(), clock).unwrap();
    idle(&mut service).await;
    assert!(
        !no_producer.entered.load(Ordering::Acquire),
        "original published recovery cannot rerun numerical children"
    );
    assert_terminal(&writer, &run, "COMPLETED").await;
    assert_eq!(
        files(&configuration.backtest_root),
        before,
        "owning completion recovery must preserve all original runtime/bundle bytes and inodes"
    );
    remove_gate(run.run_id(), "before_produce");
    service.drain().await.unwrap();
}

/// Read-only inspector is supplied by the canonical test harness. It carries
/// no mutation guard and is never adopted as a replacement AuthoritySession.
pub(crate) async fn lost_original_guard(
    connection: ResearchConnection,
    writer: SharedAuthority,
    configuration: Configuration,
    run: VerifiedRun,
    inspector: &mut tokio_postgres::Client,
    clock: fn() -> std::result::Result<
        OnlyUtcDateTime,
        crate::application::research_admission::PreparationError,
    >,
) {
    let barrier = gate(run.run_id(), "before_produce");
    let uncertain = gate(run.run_id(), "ownership_uncertain");
    let mut service =
        Service::start(connection, writer.clone(), configuration.clone(), clock).unwrap();
    barrier.entered().await;
    {
        let mut held = writer.lock().await;
        assert!(
            held.as_mut()
                .unwrap()
                .client_mut()
                .await
                .unwrap()
                .query_one("SELECT pg_advisory_unlock(1329199301,5)", &[])
                .await
                .unwrap()
                .get::<_, bool>(0)
        );
    }
    assert!(service.wake().notify());
    uncertain.entered().await;
    assert!(
        !service.task.as_ref().unwrap().is_finished(),
        "the actual job and cleanup owner remain retained before the blocking gate is released"
    );
    barrier.release();
    let _ = service.drain().await;
    let row=inspector.query_one("SELECT state,evidence_fingerprint,result_fingerprint,determinism_fingerprint FROM backtest_run WHERE run_id=$1::text::uuid",&[&run.run_id()]).await.unwrap();
    assert_eq!(row.get::<_, &str>(0), "RUNNING");
    for index in 1..4 {
        assert!(row.get::<_, Option<String>>(index).is_none());
    }
    let attempts = inspector
        .query(
            "SELECT state,failure_code FROM backtest_run_attempt WHERE run_id=$1::text::uuid",
            &[&run.run_id()],
        )
        .await
        .unwrap();
    assert_eq!(attempts.len(), 1);
    assert_eq!(attempts[0].get::<_, &str>(0), "ACTIVE");
    assert!(attempts[0].get::<_, Option<String>>(1).is_none());
    assert!(
        Registry::inspect_work(
            &configuration.runtime_root,
            run.run_id(),
            run.runtime_generation_fingerprint(),
            run.resolution()["runtime_work_binding"]["reason"]
                .as_str()
                .unwrap()
        )
        .unwrap()["closed"]
            != true,
        "uncertain original outcome cannot release work"
    );
    remove_gate(run.run_id(), "before_produce");
    remove_gate(run.run_id(), "ownership_uncertain");
}

#[tokio::test]
async fn registry_contention_does_not_fail_the_terminal_cleanup_scan() {
    let parent = std::env::temp_dir()
        .canonicalize()
        .unwrap()
        .join(uuid4().unwrap());
    std::fs::create_dir(&parent).unwrap();
    let configuration = Configuration {
        backtest_root: parent.join("backtest"),
        research_root: parent.join("research"),
        runtime_root: parent.join("runtime"),
        algorithms_root: parent.join("algorithms"),
        native_version: env!("CARGO_PKG_VERSION").into(),
    };
    let exclusive = Registry::initialize_fresh(&configuration.runtime_root).unwrap();
    assert_eq!(
        Registry::unreleased_work_bindings(&configuration.runtime_root),
        Err("RESEARCH_RUNTIME_UNAVAILABLE")
    );
    assert_eq!(
        Registry::try_unreleased_work_bindings(&configuration.runtime_root),
        Ok(None)
    );
    let wake = Wake(Arc::new(Admission {
        state: AtomicU8::new(0),
        changed: Notify::new(),
    }));
    let (status, _) = watch::channel(Status::Idle);
    let writer = Arc::new(tokio::sync::Mutex::new(None));
    let namespace = SemanticStoreId::new(&uuid4().unwrap()).unwrap();
    let clock = || panic!("empty cleanup must not release or create work");
    // Hold the exact writer guard across the real cleanup scan, then release
    // that guard explicitly. Neither scan is ordered by a timer.
    let blocked = cleanup_terminal(
        &mut None,
        &writer,
        &configuration,
        &wake,
        &status,
        &clock,
        &namespace,
    )
    .await;
    drop(exclusive);
    assert_eq!(
        Registry::try_unreleased_work_bindings(&configuration.runtime_root),
        Ok(Some(Vec::new()))
    );
    let released = cleanup_terminal(
        &mut None,
        &writer,
        &configuration,
        &wake,
        &status,
        &clock,
        &namespace,
    )
    .await;
    use std::os::unix::fs::PermissionsExt;
    let lock = configuration
        .runtime_root
        .join(".generation-authority.lock");
    std::fs::set_permissions(&lock, std::fs::Permissions::from_mode(0o644)).unwrap();
    let corrupt = cleanup_terminal(
        &mut None,
        &writer,
        &configuration,
        &wake,
        &status,
        &clock,
        &namespace,
    )
    .await;
    std::fs::remove_file(lock).unwrap();
    let missing = cleanup_terminal(
        &mut None,
        &writer,
        &configuration,
        &wake,
        &status,
        &clock,
        &namespace,
    )
    .await;
    std::fs::remove_dir_all(&parent).unwrap();
    assert_eq!(corrupt, Err("RESEARCH_RUNTIME_PROOF_INVALID"));
    assert_eq!(missing, Err("RESEARCH_RUNTIME_UNAVAILABLE"));
    assert_eq!(released, Ok(()));
    assert_eq!(blocked, Ok(()));
}

#[tokio::test]
async fn stopped_admission_never_polls_a_new_restore_or_revives_on_wake() {
    let wake = Wake(Arc::new(Admission {
        state: std::sync::atomic::AtomicU8::new(0),
        changed: Notify::new(),
    }));
    wake.stop();
    assert!(!wake.notify());
    let entered = AtomicBool::new(false);
    assert!(
        handoff(&wake, async {
            entered.store(true, Ordering::Release);
            Ok(())
        })
        .await
        .is_none()
    );
    assert!(!entered.load(Ordering::Acquire));
}

#[tokio::test(start_paused = true)]
async fn stopped_cleanup_retries_after_its_stop_notification_was_already_consumed() {
    let wake = Wake(Arc::new(Admission {
        state: std::sync::atomic::AtomicU8::new(0),
        changed: Notify::new(),
    }));
    wake.stop();
    wake.0.changed.notified().await;
    assert!(!wake.notify());
    let mut retry = tokio::time::interval_at(
        tokio::time::Instant::now() + std::time::Duration::from_secs(5),
        std::time::Duration::from_secs(5),
    );
    retry.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    let mut pending = Box::pin(wait_cleanup(&wake, &mut retry));
    tokio::select! {biased;_=&mut pending=>panic!("no cleanup retry was requested yet"),_=std::future::ready(())=>{}}
    tokio::time::advance(std::time::Duration::from_secs(5)).await;
    tokio::select! {biased;_=&mut pending=>{},_=std::future::ready(())=>panic!("stopped cleanup lost its only future retry")}
}

/// The external hold is a real archived Runtime owning reader, never a fake
/// busy callback. Releasing it sends no HTTP wake or new work permission.
pub(crate) async fn cleanup_busy_then_stop(
    connection: ResearchConnection,
    writer: SharedAuthority,
    configuration: Configuration,
    run: VerifiedRun,
    clock: fn() -> std::result::Result<
        OnlyUtcDateTime,
        crate::application::research_admission::PreparationError,
    >,
) {
    let external = crate::persistence::research_runtime::RuntimeEvidenceHold::open(
        &configuration.runtime_root,
        run.run_id(),
        run.resolution()["runtime_work_binding"]["reason"]
            .as_str()
            .unwrap(),
        run.runtime_generation_fingerprint(),
    )
    .unwrap();
    let mut service =
        Service::start(connection, writer.clone(), configuration.clone(), clock).unwrap();
    let mut observed = service.test_observations();
    loop {
        let current = observed.borrow().clone();
        match current {
            Status::Uncertain("BACKTEST_RUNTIME_CLEANUP_PENDING") => break,
            Status::Unavailable(code) => panic!("{code}"),
            _ => {}
        }
        observed.changed().await.unwrap();
    }
    assert_terminal(&writer, &run, "COMPLETED").await;
    external.verify().unwrap();
    service.wake().stop();
    assert!(!service.wake().notify());
    let mut drain = Box::pin(service.drain());
    tokio::select! {biased;result=&mut drain=>panic!("external actual read cut is still held: {result:?}"),_=std::future::ready(())=>{}}
    drop(drain);
    drop(external);
    // Await the actual service/Registry completion. The separate paused-time
    // unit proves its retry trigger; elapsed time never proves release here.
    service.drain().await.unwrap();
    assert_eq!(
        Registry::inspect_work(
            &configuration.runtime_root,
            run.run_id(),
            run.runtime_generation_fingerprint(),
            run.resolution()["runtime_work_binding"]["reason"]
                .as_str()
                .unwrap()
        )
        .unwrap()["closed"],
        true
    );
    let mut held = writer.lock().await;
    let rows = held
        .as_mut()
        .unwrap()
        .client_mut()
        .await
        .unwrap()
        .query(
            "SELECT state FROM backtest_run_attempt WHERE run_id=$1::text::uuid",
            &[&run.run_id()],
        )
        .await
        .unwrap();
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].get::<_, &str>(0), "SUCCEEDED");
}

// No test calls stop/drain before checking admission. Waiting for the real
// task's final Sender to drop is the deterministic task-exit barrier.
#[tokio::test]
async fn known_task_error_closes_wake_before_any_drain_request() {
    let wake = Wake(Arc::new(Admission {
        state: std::sync::atomic::AtomicU8::new(0),
        changed: Notify::new(),
    }));
    let (status, mut observed) = watch::channel(Status::Starting);
    let exit = TaskExit {
        wake: wake.clone(),
        status: status.clone(),
    };
    let task = tokio::spawn(async move {
        let _exit = exit;
        status.send_replace(Status::Unavailable("BACKTEST_SERVICE_UNAVAILABLE"));
        Err::<(), &'static str>("BACKTEST_SERVICE_UNAVAILABLE")
    });
    while observed.changed().await.is_ok() {}
    assert_eq!(task.await.unwrap(), Err("BACKTEST_SERVICE_UNAVAILABLE"));
    assert_eq!(
        *observed.borrow(),
        Status::Unavailable("BACKTEST_SERVICE_UNAVAILABLE")
    );
    assert!(
        !wake.notify(),
        "an exited task must refuse new work without a Host shutdown request"
    );
    assert!(!wake.begin(), "an exited task cannot admit another restore");
}

#[tokio::test]
async fn task_panic_closes_wake_and_reports_unknown_without_proving_drain() {
    let wake = Wake(Arc::new(Admission {
        state: std::sync::atomic::AtomicU8::new(0),
        changed: Notify::new(),
    }));
    let (status, observed) = watch::channel(Status::Running(
        "12345678-1234-4234-8234-123456789abc".into(),
    ));
    let exit = TaskExit {
        wake: wake.clone(),
        status,
    };
    let task = tokio::spawn(async move {
        let _exit = exit;
        panic!("deterministic task panic");
        #[allow(unreachable_code)]
        Ok(())
    });
    let mut service = Service {
        wake: wake.clone(),
        status: observed,
        task: Some(task),
        drained: None,
    };
    let mut observed = service.test_observations();
    while observed.changed().await.is_ok() {}
    assert!(
        !wake.notify(),
        "panic must stop admission before any caller asks to drain"
    );
    assert_eq!(
        service.status(),
        Status::Uncertain("BACKTEST_SERVICE_OUTCOME_UNKNOWN")
    );
    assert_eq!(
        service.drained, None,
        "a dead task is not positive child/connection drain evidence"
    );
    assert_eq!(
        service.drain().await,
        Err("BACKTEST_SERVICE_OUTCOME_UNKNOWN")
    );
}

#[test]
fn unpolled_task_future_already_owns_its_exit_guard() {
    let wake = Wake(Arc::new(Admission {
        state: std::sync::atomic::AtomicU8::new(0),
        changed: Notify::new(),
    }));
    let (status, observed) = watch::channel(Status::Starting);
    let exit = TaskExit {
        wake: wake.clone(),
        status,
    };
    let unpolled = async move {
        let _exit = exit;
        std::future::pending::<()>().await;
    };
    drop(unpolled);
    assert!(
        !wake.notify(),
        "task ownership starts when its future is constructed"
    );
    assert_eq!(
        *observed.borrow(),
        Status::Uncertain("BACKTEST_SERVICE_OUTCOME_UNKNOWN")
    );
}
