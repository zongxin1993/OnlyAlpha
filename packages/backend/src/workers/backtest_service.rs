//! Concrete admitted Backtest producer. SQL fencing/lifecycle belongs to its caller.
//! Only a terminal native replay followed by positive joins can mint JoinedBacktest.
use crate::{
    application::{
        backtest_run::VerifiedRun, private_strategy::exact, research_admission::PreparationError,
    },
    persistence::{
        backtest_evidence::BacktestReadContext, research_preparation::Operation,
        research_runtime::RuntimeInputHold,
    },
    security::immutable_json::{self, Directory},
    workers::{
        algorithm::AlgorithmProcess, backtest_result::ObservedBacktest,
        trading_nodes::InstalledTradingNodes, trading_program,
    },
};
use onlyalpha_backtest::{RunLoop, RunSpec, Trading};
use onlyalpha_calculation::product::Graph;
use onlyalpha_calculation_bridge::{
    Cancellation, ChartInstallation, ProcessState, StrategyPreparation,
};
use onlyalpha_data_source_binance::spot_source::spot_calendar;
use onlyalpha_market_data::{construction::*, delivery::*, state::*, *};
use onlyalpha_strategy::{Executor, NodeFailure, Scope};
use rustix::fs;
use serde_json::{Value, json};
use std::{
    fmt,
    path::PathBuf,
    sync::{
        Arc, Mutex,
        atomic::{AtomicU8, Ordering},
    },
    time::Duration,
};
const INVALID: &str = "BACKTEST_PRODUCER_INPUT_MISMATCH";
const UNAVAILABLE: &str = "BACKTEST_PRODUCER_UNAVAILABLE";
const UNKNOWN: &str = "BACKTEST_ALGORITHM_OUTCOME_UNKNOWN";
const DEADLINE: Duration = Duration::from_secs(10);
const WORK: usize = 8 * 1024 * 1024;
const CAPS: &str = "ONLYALPHA_TRADING_NODE_CAPABILITIES_V1";
type Result<T> = std::result::Result<T, &'static str>;
type NativeRun = RunLoop<Trading<InstalledTradingNodes>>;
fn text<'a>(value: &'a Value, key: &str) -> Result<&'a str> {
    value[key].as_str().filter(|s| !s.is_empty()).ok_or(INVALID)
}
#[derive(Clone)]
pub(crate) struct Configuration {
    pub backtest_root: PathBuf,
    pub research_root: PathBuf,
    pub runtime_root: PathBuf,
    pub algorithms_root: PathBuf,
    pub native_version: String,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum StartMode {
    Create,
    Resume,
}
/// Operational requests only; the caller observes actual SQL cancellation/fencing.
#[derive(Clone, Default)]
pub(crate) struct Control(Arc<AtomicU8>);
impl Control {
    pub(crate) fn request_cancel(&self) {
        self.0.store(2, Ordering::SeqCst);
    }
    pub(crate) fn request_pause(&self) {
        let _ = self
            .0
            .compare_exchange(0, 1, Ordering::SeqCst, Ordering::SeqCst);
    }
    fn requested(&self) -> u8 {
        self.0.load(Ordering::SeqCst)
    }
}
#[derive(Default)]
struct Children {
    frozen: bool,
    owners: Vec<Cancellation>,
}
#[derive(Clone, Default)]
struct ChildGroup(Arc<Mutex<Children>>);
impl ChildGroup {
    fn observe(&self, owner: Cancellation) -> std::result::Result<(), NodeFailure> {
        let (mut children, poisoned) = match self.0.lock() {
            Ok(v) => (v, false),
            Err(p) => (p.into_inner(), true),
        };
        if !children.owners.iter().any(|old| old.same_owner(&owner)) {
            children.owners.push(owner);
        }
        if poisoned || children.frozen {
            Err(NodeFailure::Unknown)
        } else {
            Ok(())
        }
    }
    fn join(&self) -> Result<()> {
        let owners = {
            let mut children = self.0.lock().unwrap_or_else(|p| p.into_inner());
            children.frozen = true;
            children.owners.clone()
        };
        let mut failed = false;
        // Every owner is visited even if an earlier child has an uncertain join.
        for owner in owners {
            if owner.state() != ProcessState::Joined && owner.drain().is_err() {
                failed = true;
            }
            if owner.state() != ProcessState::Joined {
                failed = true;
            }
        }
        if failed {
            return Err(UNKNOWN);
        }
        self.0.clear_poison();
        self.verify()
    }
    fn verify(&self) -> Result<()> {
        let children = self.0.lock().map_err(|_| UNKNOWN)?;
        if !children.frozen
            || children
                .owners
                .iter()
                .any(|o| o.state() != ProcessState::Joined)
        {
            return Err(UNKNOWN);
        }
        Ok(())
    }
}
struct Lifetime {
    context: Arc<BacktestReadContext>,
    runtime: Arc<RuntimeInputHold>,
    installation: Arc<ChartInstallation>,
}
impl Lifetime {
    fn verify(&self) -> Result<()> {
        self.context.verify_cut()?;
        self.runtime.verify()?;
        self.installation.verify().map_err(|_| UNAVAILABLE)
    }
}
/// Errors retain the complete child set and original physical holds. Joining
/// these children never changes the uncertain operational outcome into success.
/// The original directory descriptor stays held until the error and children are dropped.
pub(crate) struct Error {
    code: &'static str,
    children: ChildGroup,
    hold: Option<Arc<Lifetime>>,
    context: Option<Arc<BacktestReadContext>>,
    _directory: Option<Arc<Directory>>,
    installation: Option<Arc<ChartInstallation>>,
}
impl Error {
    fn bare(code: &'static str) -> Self {
        Self {
            code,
            children: ChildGroup::default(),
            hold: None,
            context: None,
            _directory: None,
            installation: None,
        }
    }
    pub(crate) fn code(&self) -> &'static str {
        self.code
    }
    pub(crate) fn drain(&mut self) -> Result<()> {
        self.children.join()
    }
}
impl fmt::Debug for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.code)
    }
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.code)
    }
}
impl std::error::Error for Error {}
/// No parsed READY, observation value or history context alone grants work:
/// restoration must also acquire the current exact Runtime execution hold.
pub(crate) struct Work {
    hold: Arc<Lifetime>,
    configuration: Configuration,
    request: Value,
}
impl Work {
    /// Consume the original job's already verified history cut; never reopen a
    /// second transaction for the same immutable Run. Current execution holds
    /// and installed capabilities remain independently required below.
    pub(crate) fn restore(
        context: Arc<BacktestReadContext>,
        run: &VerifiedRun,
        original: &Operation,
        configuration: &Configuration,
    ) -> std::result::Result<Self, Error> {
        let started = std::time::Instant::now();
        let phase = |name: &str| {
            eprintln!(
                "BACKTEST_WORK_RESTORE_PHASE phase={name} elapsed_ms={}",
                started.elapsed().as_millis()
            )
        };
        phase("begin");
        let mut error = Error::bare(INVALID);
        error.context = Some(context.clone());
        let restored: std::result::Result<Self, PreparationError> = (|| {
            context.roots_match(&configuration.research_root, &configuration.runtime_root)?;
            context.verify_cut()?;
            if context.run().specification_fingerprint() != run.specification_fingerprint()
                || context.run().admission_resolution_fingerprint()
                    != run.admission_resolution_fingerprint()
                || context.run().namespace() != run.namespace()
                || context.run().owner() != run.owner()
                || context.original_operation().command.value() != original.command.value()
                || context.original_operation().owner != original.owner
                || context.original_operation().accepted != original.accepted
                || context.original_operation().outputs["ready"] != original.outputs["ready"]
            {
                return Err(INVALID.into());
            }
            let operation = context.original_operation();
            let input = operation.request.backtest()?;
            let ready = &operation.outputs["ready"];
            if input.backtest_command_id != run.resolution()["runtime_work_binding"]["reason"]
                || operation.request.reserved_run_id() != run.run_id()
            {
                return Err(INVALID.into());
            }
            phase("context");
            let mut runtime = RuntimeInputHold::open(
                &configuration.runtime_root,
                run.run_id(),
                &input.backtest_command_id,
                run.runtime_generation_fingerprint(),
            )?;
            if runtime.binding() != &run.resolution()["runtime_work_binding"]
                || runtime.binding() != &operation.outputs["environment"]["binding"]
                || runtime.backtest_execution_binding()? != run.resolution()["backtest_binding"]
                || ready["backtest_binding"] != run.resolution()["backtest_binding"]
            {
                return Err(INVALID.into());
            }
            runtime.verify_artifacts()?;
            phase("runtime-artifacts");
            let installation = Arc::new(
                ChartInstallation::open(
                    &configuration.algorithms_root,
                    text(&ready["algorithm_resolution"], "algorithm_artifact")?,
                )
                .map_err(|_| UNAVAILABLE)?,
            );
            error.installation = Some(installation.clone());
            // Backtest is not a Research composition. Restore the exact
            // calculation evidence already sealed by the original Run owner;
            // the native producer below still resolves actual installed CAPS.
            let resolution = context.validated_calculations()?;
            phase("calculations");
            let request = resolution["algorithm_resolution_request"].clone();
            if resolution["algorithm_resolution"]["algorithm_artifact"]
                != installation.artifact_fingerprint()
            {
                return Err(INVALID.into());
            }
            let runtime = Arc::new(runtime);
            // Retain the real hold before any further comparison can fail.
            let hold = Arc::new(Lifetime {
                context: context.clone(),
                runtime,
                installation,
            });
            error.hold = Some(hold.clone());
            let source = context.source_revision().to_record();
            if resolution["algorithm_resolution"] != ready["algorithm_resolution"]
                || request != ready["algorithm_resolution_request"]
                || resolution["decision"]["decision_graph"] != source["decision_graph"]
                || resolution["decision"]["signal_semantics"] != source["signal_semantics"]
                || context.prepared().record() != run.resolution()["preparation"]
                || context.prepared().record() != ready["preparation"]
                || context.prepared().inputs().record() != ready["input_sources"]
                || configuration.native_version != env!("CARGO_PKG_VERSION")
            {
                return Err(INVALID.into());
            }
            hold.verify()?;
            phase("complete");
            Ok(Self {
                hold,
                configuration: configuration.clone(),
                request,
            })
        })();
        match restored {
            Ok(work) => Ok(work),
            Err(failure) => {
                error.code = failure.code();
                if let Some(owner) = failure.recovery_owner() {
                    let _ = error.children.observe(owner.clone());
                }
                Err(error)
            }
        }
    }
}
pub(crate) struct JoinedBacktest {
    hold: Arc<Lifetime>,
    children: ChildGroup,
    directory: Arc<Directory>,
    observation: ObservedBacktest,
}
impl JoinedBacktest {
    pub(crate) fn run(&self) -> &VerifiedRun {
        self.hold.context.run()
    }
    pub(crate) fn observation(&self) -> &ObservedBacktest {
        &self.observation
    }
    pub(crate) fn read_context(&self) -> &BacktestReadContext {
        &self.hold.context
    }
    pub(crate) fn verify_cut(&self) -> Result<()> {
        self.hold.verify()?;
        self.directory.verify()?;
        self.children.verify()?;
        if Arc::strong_count(&self.hold) != 1 {
            return Err(UNKNOWN);
        }
        Ok(())
    }
}
pub(crate) struct PausedBacktest {
    hold: Arc<Lifetime>,
    children: ChildGroup,
    directory: Arc<Directory>,
    #[cfg(test)]
    trace: Value,
}
impl PausedBacktest {
    #[cfg(test)]
    pub(crate) fn run(&self) -> &VerifiedRun {
        self.hold.context.run()
    }
    pub(crate) fn verify_cut(&self) -> Result<()> {
        self.hold.verify()?;
        self.directory.verify()?;
        self.children.verify()?;
        if Arc::strong_count(&self.hold) != 1 {
            return Err(UNKNOWN);
        }
        Ok(())
    }
}
pub(crate) enum Produced {
    Terminal(JoinedBacktest),
    Paused(PausedBacktest),
}
fn runtime_directory(work: &Work, mode: StartMode) -> Result<Arc<Directory>> {
    let root = Directory::open(&work.configuration.backtest_root)?;
    let runs = root.child("runtime", mode == StartMode::Create)?;
    let id = work.hold.context.run().run_id();
    if mode == StartMode::Create {
        fs::mkdirat(&runs.fd, id, fs::Mode::from_raw_mode(0o700))
            .map_err(|_| "BACKTEST_RUNTIME_CREATE_REFUSED")?;
        fs::fsync(&runs.fd).map_err(|_| UNAVAILABLE)?;
    }
    let directory = runs
        .child(id, false)
        .map_err(|_| "BACKTEST_RUNTIME_RESUME_REQUIRED")?;
    Ok(Arc::new(directory))
}
fn accept(
    directory: &Directory,
    event: &Value,
) -> std::result::Result<(), onlyalpha_backtest::Error> {
    let receive = || -> Result<()> {
        let id = text(event, "event_id")?;
        if id.len() > 256
            || !id
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || c == b'-' || c == b'_')
        {
            return Err(INVALID);
        }
        // This existing put-once owner returns only after exact readback/fsync.
        immutable_json::put(directory, &["events", id], "event.json", event)
    };
    receive().map_err(|code| onlyalpha_backtest::Error(code.into()))
}
fn native(work: &Work, children: &ChildGroup) -> Result<(RunSpec, Trading<InstalledTradingNodes>)> {
    let hold = &work.hold;
    hold.verify()?;
    let prepared = hold.context.prepared();
    let graph = Graph::from_record(
        &hold.context.source_revision().to_record()["decision_graph"],
        WORK,
    )
    .map_err(|_| INVALID)?;
    let definitions = graph
        .ordered_nodes()
        .filter(|d| d.to_record()["kind"] != "PREDICATE")
        .map(|d| d.to_record())
        .collect::<Vec<_>>();
    let sources = work.request["sources"].as_array().ok_or(INVALID)?.clone();
    let mut worker = AlgorithmProcess::research_resolution(
        &hold.installation,
        hold.context.run().runtime_generation_fingerprint(),
        Box::new(hold.clone()),
    )
    .map_err(|_| UNAVAILABLE)?;
    children
        .observe(worker.cancellation().map_err(|_| UNKNOWN)?)
        .map_err(|_| UNKNOWN)?;
    worker.handshake_research(DEADLINE).map_err(|_| UNKNOWN)?;
    let observed = worker
        .resolve_research(
            json!({"schema_version":1,"contract":CAPS,"sources":sources,"definitions":definitions}),
            DEADLINE,
        )
        .map_err(|_| UNKNOWN)?;
    worker.terminate().map_err(|_| UNKNOWN)?;
    exact(
        &observed,
        &["schema_version", "contract", "nodes", "isolation"],
    )
    .map_err(|_| INVALID)?;
    if observed["schema_version"] != 1
        || observed["contract"] != CAPS
        || observed["isolation"] != "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1"
    {
        return Err(INVALID);
    }
    let cfg = prepared.configuration();
    let profiles = cfg["profiles"]
        .as_object()
        .filter(|p| p.len() == 1)
        .ok_or(INVALID)?;
    let scope = Scope {
        engine: text(cfg, "engine")?.parse().map_err(|_| INVALID)?,
        runtime: text(cfg, "runtime")?.parse().map_err(|_| INVALID)?,
        cluster: profiles
            .keys()
            .next()
            .ok_or(INVALID)?
            .parse()
            .map_err(|_| INVALID)?,
    };
    let market_source = prepared.inputs().records().first().ok_or(INVALID)?.source();
    let (program, definitions, _) = trading_program::materialize(
        hold.context.source_revision(),
        scope.clone(),
        hold.context.run().runtime_generation_fingerprint(),
        market_source,
        hold.installation.artifact_fingerprint(),
        &observed["nodes"],
    )?;
    let artifact = text(
        &hold.context.run().resolution()["backtest_binding"],
        "executor_artifact_sha256",
    )?
    .to_owned();
    let kind = prepared
        .inputs()
        .records()
        .first()
        .ok_or(INVALID)?
        .bar()
        .bar_type()
        .clone();
    let construction =
        OnlyConstructionGraph::new(vec![OnlyConstructionInput::Bar(kind.clone())], vec![])
            .map_err(|_| INVALID)?;
    // This profile delivers only LATEST_CLOSED and has no construction or
    // Pipeline calculation slots. Historical lookback belongs to the actual
    // incremental numerical nodes, whose complete checkpoints remain retained.
    let pipeline = PipelineProgram::new(
        OnlyMarketDataStateScope::new(scope.engine, scope.runtime),
        program.generation(),
        1,
        vec![
            SourceProgram::new(
                market_source,
                Arc::new(spot_calendar().map_err(|_| INVALID)?),
                Arc::new(OnlyConstructionRegistry::default()),
                &artifact,
                construction.clone(),
            )
            .map_err(|_| INVALID)?,
        ],
        vec![ClusterProgram {
            cluster: scope.cluster,
            subscription: OnlyBarSubscription::new(
                "native-next-open-strategy",
                vec![kind.clone()],
                construction,
                Some(kind),
                OnlyBarFreshness::LatestClosed,
            )
            .map_err(|_| INVALID)?,
        }],
        vec![],
        &artifact,
    )
    .map_err(|_| INVALID)?;
    let group = children.clone();
    let observe = Arc::new(move |owner| group.observe(owner));
    let port = InstalledTradingNodes::new_owned(
        hold.installation.clone(),
        program.clone(),
        definitions,
        sources,
        hold.clone(),
        DEADLINE,
        observe,
    )
    .map_err(|error| {
        if matches!(error, NodeFailure::Unknown) {
            UNKNOWN
        } else {
            UNAVAILABLE
        }
    })?;
    let preparation =
        StrategyPreparation::new(pipeline, Executor::new(program, port).map_err(|_| INVALID)?)
            .map_err(|_| INVALID)?;
    let participants = prepared
        .clone()
        .into_participants(preparation)
        .map_err(|_| INVALID)?;
    Ok((
        RunSpec {
            work_id: hold.context.run().run_id().into(),
            configuration: cfg.clone(),
            kernel_artifact: artifact.clone(),
            driver_artifact: artifact,
            initial_ns: prepared.initial_ns().clone(),
        },
        participants,
    ))
}
pub(crate) fn produce(
    work: Work,
    mode: StartMode,
    control: &Control,
) -> std::result::Result<Produced, Error> {
    let children = ChildGroup::default();
    let mut directory = None;
    let result = (|| -> Result<Produced> {
        work.hold.verify()?;
        let selected = runtime_directory(&work, mode)?;
        directory = Some(selected.clone());
        let (spec, participants) = native(&work, &children)?;
        let inputs = work.hold.context.prepared().inputs().clone();
        let mut run: NativeRun = match mode {
            StartMode::Create => RunLoop::create(&selected.path, spec, inputs, participants),
            StartMode::Resume => RunLoop::open(&selected.path, spec, inputs, participants),
        }
        .map_err(|_| UNAVAILABLE)?;
        let restored = run.trace_metadata().map_err(|_| UNAVAILABLE)?;
        let mut paused = false;
        if restored["state"]["status"] != "TERMINATED" {
            if restored["state"]["input_cancelled"] == true {
                run.deliver(|event| accept(&selected, event))
                    .map_err(|_| UNAVAILABLE)?;
                run.terminate("CANCELLED", Some("USER_CANCELLED"))
                    .map_err(|_| UNAVAILABLE)?;
            } else if restored["state"]["input_finished"] == true {
                run.deliver(|event| accept(&selected, event))
                    .map_err(|_| UNAVAILABLE)?;
                run.finish_input().map_err(|_| UNAVAILABLE)?;
            } else {
                if restored["state"]["status"] == "PAUSED" && control.requested() != 1 {
                    run.resume().map_err(|_| UNAVAILABLE)?;
                }
                let mut processing_time = Duration::ZERO;
                let mut step_count = 0_u64;
                loop {
                    match control.requested() {
                        1 => {
                            if run.progress().map_err(|_| UNAVAILABLE)?["status"] != "PAUSED" {
                                run.pause().map_err(|_| UNAVAILABLE)?;
                            }
                            paused = true;
                            break;
                        }
                        2 => {
                            run.cancel_input().map_err(|_| UNAVAILABLE)?;
                            run.deliver(|event| accept(&selected, event))
                                .map_err(|_| UNAVAILABLE)?;
                            run.terminate("CANCELLED", Some("USER_CANCELLED"))
                                .map_err(|_| UNAVAILABLE)?;
                            break;
                        }
                        _ => {}
                    }
                    let started = std::time::Instant::now();
                    #[cfg(test)]
                    let advanced = {
                        let advanced = run
                            .step_observed(&mut |phase, index, _| {
                                test_after_step(phase, index, control);
                                Ok(())
                            })
                            .map_err(|_| UNKNOWN)?;
                        run.deliver(|event| accept(&selected, event))
                            .map_err(|_| UNAVAILABLE)?;
                        advanced
                    };
                    #[cfg(not(test))]
                    let (advanced, _) = run
                        .step_and_deliver(|event| accept(&selected, event))
                        .map_err(|error| {
                            eprintln!("BACKTEST_NATIVE_STEP_FAILURE error={error:?}");
                            match error {
                                onlyalpha_backtest::StepAndDeliverError::Step(_) => UNKNOWN,
                                onlyalpha_backtest::StepAndDeliverError::Delivery(_) => UNAVAILABLE,
                            }
                        })?;
                    processing_time += started.elapsed();
                    step_count += 1;
                    if step_count.is_multiple_of(128) || !advanced {
                        eprintln!(
                            "BACKTEST_NATIVE_PROGRESS steps={step_count} processing_ms={}",
                            processing_time.as_millis()
                        );
                    }
                    if !advanced {
                        run.close_input().map_err(|_| UNAVAILABLE)?;
                        run.deliver(|event| accept(&selected, event))
                            .map_err(|_| UNAVAILABLE)?;
                        run.finish_input().map_err(|_| UNAVAILABLE)?;
                        break;
                    }
                }
            }
        }
        let observation = if paused {
            None
        } else {
            Some(
                ObservedBacktest::observe(work.hold.context.prepared(), &run)
                    .map_err(|_| INVALID)?,
            )
        };
        #[cfg(test)]
        let paused_trace = if paused {
            Some(run.trace().map_err(|_| UNAVAILABLE)?)
        } else {
            None
        };
        drop(run);
        children.join()?;
        work.hold.verify()?;
        selected.verify()?;
        // No child or abandoned candidate may retain the lifetime after join.
        if Arc::strong_count(&work.hold) != 1 {
            return Err(UNKNOWN);
        }
        let hold = work.hold.clone();
        if let Some(observation) = observation {
            if !matches!(
                observation.proof()["status"].as_str(),
                Some("COMPLETED" | "CANCELLED")
            ) || observation.proof()["drained"] != true
            {
                return Err(INVALID);
            }
            Ok(Produced::Terminal(JoinedBacktest {
                hold,
                children: children.clone(),
                directory: selected,
                observation,
            }))
        } else {
            Ok(Produced::Paused(PausedBacktest {
                hold,
                children: children.clone(),
                directory: selected,
                #[cfg(test)]
                trace: paused_trace.ok_or(INVALID)?,
            }))
        }
    })();
    match result {
        Ok(value) => Ok(value),
        Err(code) => Err(Error {
            code,
            children,
            hold: Some(work.hold),
            context: None,
            _directory: directory,
            installation: None,
        }),
    }
}
#[cfg(test)]
thread_local! {static STOP:std::cell::Cell<Option<(u64,u8)>>=const{std::cell::Cell::new(None)};}
#[cfg(test)]
pub(crate) fn test_pause_after_step(step: u64) {
    STOP.with(|stop| stop.set(Some((step, 1))));
}
#[cfg(test)]
pub(crate) fn test_cancel_after_step(step: u64) {
    STOP.with(|stop| stop.set(Some((step, 2))));
}
#[cfg(test)]
fn test_after_step(phase: &str, index: u64, control: &Control) {
    if phase == "STEP_READY" {
        STOP.with(|stop| {
            if stop.get().is_some_and(|(step, _)| step == index) {
                let (_, kind) = stop.take().unwrap();
                if kind == 1 {
                    control.request_pause();
                } else {
                    control.request_cancel();
                }
            }
        });
    }
}
#[cfg(test)]
pub(crate) fn test_child_states(joined: &JoinedBacktest) -> Vec<ProcessState> {
    joined
        .children
        .0
        .lock()
        .unwrap()
        .owners
        .iter()
        .map(Cancellation::state)
        .collect()
}
#[cfg(test)]
pub(crate) fn test_paused_trace(paused: &PausedBacktest) -> Value {
    paused.trace.clone()
}
