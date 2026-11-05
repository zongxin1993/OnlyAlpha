//! Actual installed arithmetic through the native NodePort, no Runtime admission.
use onlyalpha_backend::{
    application::{private_strategy::Definition as Strategy, strategy_research::DecisionGraph},
    workers::{algorithm::describe_native_runtime, trading_nodes::InstalledTradingNodes},
};
use onlyalpha_calculation::{Definition, product::Definition as ProductDefinition};
use onlyalpha_calculation_bridge::{Cancellation, ChartInstallation, ProcessState};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    market::OnlyBar,
    time::{OnlyTimestamp, OnlyUtcDateTime},
};
use onlyalpha_strategy::{
    Executor, NodeDescriptor, NodePort, Program, Revision, Scope, SourceRevision, record_fingerprint,
};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    error::Error,
    path::Path,
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
    time::Duration,
};
const WORK: usize = 8 * 1024 * 1024;
const DEADLINE: Duration = Duration::from_secs(10);
// Compile the same owning port with its private cfg(test) fault points. The
// installed interpreter, process control and positive join are the real owners.
mod algorithm {
    pub use onlyalpha_backend::workers::algorithm::{AlgorithmProcess,describe_research_runtime};
}
#[path = "../../src/workers/trading_nodes.rs"]
mod constructor_port;
struct Completion(Arc<AtomicUsize>);
impl Drop for Completion {
    fn drop(&mut self) {
        self.0.fetch_sub(1, Ordering::SeqCst);
    }
}
fn fixture() -> Result<Value, Box<dyn Error>> {
    Ok(serde_json::from_slice(&std::fs::read(std::env::var(
        "ONLYALPHA_TRADING_TEST_INPUT",
    )?)?)?)
}
fn bar(base: &Value, index: i64) -> Result<OnlyBar, Box<dyn Error>> {
    let mut row = base.clone();
    let close = if index == 21 { 99 } else { 100 + index };
    for field in ["open", "high", "low", "close"] {
        row[field]["value"] = json!(format!("{close}.00"));
    }
    row["volume"]["value"] = json!(if index == 20 { "21" } else { "1" });
    let start: OnlyUtcDateTime = "2025-01-02T11:40:00Z".parse()?;
    for (field, delta) in [
        ("bar_start", 0),
        ("bar_end", 1),
        ("ts_event", 1),
        ("ts_init", 1),
    ] {
        row[field] = json!(
            OnlyTimestamp::from_unix_nanos(
                OnlyTimestamp::from_datetime(start).unix_nanos() + (index + delta) * 60_000_000_000
            )
            .to_datetime_exact()?
            .to_string()
        );
    }
    Ok(OnlyBar::from_record(&row)?)
}
fn setup(case: &Value, artifact: &str) -> Result<(Program, BTreeMap<String, ProductDefinition>), Box<dyn Error>> {
    let (_,program,definitions)=product_setup(case,artifact)?;
    Ok((program,definitions))
}
// One shared component projection; a public value here is not an authenticated Freeze publication.
pub(super) fn product_setup(case: &Value, artifact: &str) -> Result<(SourceRevision,Program,BTreeMap<String,ProductDefinition>),Box<dyn Error>> {
    let mut strategy = case["strategy"].clone();
    strategy["universe"]["instruments"] = json!(["BTCUSDT.BINANCE"]);
    strategy["calculations"] = case["calculations"]["instances"].clone();
    strategy["factor_revision_dependencies"] =
        case["calculations"]["factor_revision_dependencies"].clone();
    strategy["signals"]["entry"]["operator"] = json!(">=");
    strategy["signals"]["entry"]["right"]["value"]["value"] = json!("0.001");
    let strategy = Strategy::from_record(&strategy)?;
    let decision = DecisionGraph::derive(&strategy, &case["calculations"]["nodes"])?;
    let native = describe_native_runtime(env!("CARGO_PKG_VERSION"))?;
    let mut implementations = BTreeMap::new();
    let mut research = BTreeMap::new();
    for row in case["registrations"].as_array().ok_or("registrations")? {
        if row["backend"] == "RESEARCH" {
            research.insert(row["type"]["type_id"].as_str().ok_or("type")?.to_owned(), row["implementation_fingerprint"].clone());
        }
        if row["backend"] == "TRADING" {
            implementations.insert(
                row["type"]["type_id"].as_str().ok_or("type")?.to_owned(),
                (
                    row["implementation_fingerprint"].clone(),
                    row["state_capability"].clone(),
                    row["checkpoint_schema_version"].clone(),
                ),
            );
        }
    }
    for row in native["implementations"]
        .as_array()
        .ok_or("native manifests")?
    {
        if row["backend_kind"] == "RESEARCH" {
            research.insert(row["calculation_type_reference"]["type_id"].as_str().ok_or("native type")?.to_owned(), row["implementation_fingerprint"].clone());
        }
        if row["backend_kind"] != "TRADING" {
            continue;
        }
        implementations.insert(
            row["calculation_type_reference"]["type_id"]
                .as_str()
                .ok_or("native type")?
                .to_owned(),
            (
                row["implementation_fingerprint"].clone(),
                json!("STATELESS"),
                Value::Null,
            ),
        );
    }
    // Explicit component projection, retaining each native Definition2 digest.
    // Original Product Graph1/Science2 identities are never rewritten or equated.
    let mut mapping = BTreeMap::new();
    let mut definitions = BTreeMap::new();
    let mut descriptors = vec![];
    for product in decision.graph().ordered_nodes() {
        let original = product.fingerprint();
        let mut row = product.to_record();
        for reference in row["input_bindings"]
            .as_object_mut()
            .ok_or("inputs")?
            .values_mut()
        {
            if let Some(parent) = reference["node_fingerprint"].as_str() {
                reference["node_fingerprint"] = json!(mapping.get(parent).ok_or("parent")?);
            }
        }
        let native = ProductDefinition::from_record(&row, WORK)?;
        row["schema_version"] = json!(3);
        let definition = Definition::from_record(&row)?;
        mapping.insert(original, definition.fingerprint());
        let implementation = implementations
            .get(row["type_id"].as_str().ok_or("type")?)
            .ok_or("implementation")?;
        definitions.insert(definition.fingerprint(), native.clone());
        descriptors.push(NodeDescriptor {
            definition,
            native_definition: native.fingerprint(),
            implementation: implementation.0.as_str().ok_or("digest")?.into(),
            state_capability: implementation.1.as_str().ok_or("state capability")?.into(),
            checkpoint_schema: implementation.2.as_u64(),
        });
    }
    let mut bindings=decision.graph().ordered_nodes().map(|node| {
        let row=node.to_record();let key=row["type_id"].as_str().ok_or("node type")?;
        Ok(json!({"node_fingerprint":node.fingerprint(),"research_implementation_fingerprint":research.get(key).ok_or("research implementation")?,"trading_implementation_fingerprint":implementations.get(key).ok_or("trading implementation")?.0}))
    }).collect::<Result<Vec<_>,Box<dyn Error>>>()?;
    bindings.sort_by_key(|row|row["node_fingerprint"].as_str().unwrap().to_owned());
    let mut source=json!({"schema_version":1,"universe":strategy.to_record()["universe"],"market_input_contract":strategy.to_record()["market_input"],"decision_graph_fingerprint":decision.graph().fingerprint(),"implementation_bindings":bindings,"signal_semantics":decision.record()["signal_semantics"]});
    let mut identity=source.clone();identity["domain"]=json!("onlyalpha.strategy.revision");
    source["strategy_fingerprint"]=json!(record_fingerprint(&identity));source["decision_graph"]=decision.graph().to_record();
    let source=SourceRevision::from_json(&source.to_string(),WORK)?;
    let revision=Revision::from_product(source.to_record(),descriptors,mapping)?;
    assert!(revision.is_product_materialization());assert_eq!(revision.fingerprint(),source.fingerprint());
    let program = Program::new(
        revision,
        Scope {
            engine: "technical-engine".parse()?,
            runtime: "technical-runtime".parse()?,
            cluster: "technical-cluster".parse()?,
        },
        &"a".repeat(64),
        &"c".repeat(64),
        artifact,
    )?;
    Ok((source, program, definitions))
}
#[path = "next_open_trading.rs"]
mod next_open_trading;
#[test]
fn actual_installed_nodes_keep_native_predicates_and_restore_factory_state()
-> Result<(), Box<dyn Error>> {
    let case = fixture()?;
    let artifact = std::env::var("ONLYALPHA_TRADING_TEST_ARTIFACT")?;
    let installation = Arc::new(ChartInstallation::open(
        Path::new(&std::env::var("ONLYALPHA_TRADING_TEST_INSTALLATION")?),
        &artifact,
    )?);
    let (program, definitions) = setup(&case, &artifact)?;
    let count = Arc::new(AtomicUsize::new(1));
    let port = InstalledTradingNodes::new(
        installation.clone(),
        program.clone(),
        definitions,
        case["sources"].as_array().ok_or("sources")?.clone(),
        Arc::new(Completion(count.clone())),
        DEADLINE,
    )?;
    let mut executor = Executor::new(program, port)?;
    for index in 0..20 {
        let observation = bar(&case["base"], index)?;
        let outcome = executor.process(
            &observation,
            &OnlyTimestamp::from_datetime(*observation.bar_end()),
            &"d".repeat(64),
        )?;
        assert_eq!(outcome.to_record()["status"], "BLOCKED");
    }
    let checkpoint = executor.capture_checkpoint()?;
    let mut restored = executor.restored_candidate(
        checkpoint.to_string().as_bytes(),
        &record_fingerprint(&checkpoint),
    )?;
    assert_eq!(restored.capture_checkpoint()?, checkpoint);
    let observation = bar(&case["base"], 20)?;
    let time = OnlyTimestamp::from_datetime(*observation.bar_end());
    let outcome = executor.process(&observation, &time, &"d".repeat(64))?;
    assert_eq!(outcome.to_record()["status"], "READY");
    assert_eq!(outcome.to_record()["decision"]["entry"], true);
    assert_eq!(outcome.to_record()["decision"]["exit"], false);
    assert_eq!(
        restored
            .process(&observation, &time, &"d".repeat(64))?
            .to_record(),
        outcome.to_record()
    );
    let after = executor.capture_checkpoint()?;
    assert_eq!(
        executor
            .process(&observation, &time, &"d".repeat(64))?
            .to_record(),
        outcome.to_record()
    );
    assert_eq!(executor.capture_checkpoint()?, after);
    // Canonical receipts and cursors are native; Python returns only math state.
    let port_rows = after["port"]["nodes"].as_array().ok_or("port nodes")?;
    assert_eq!(port_rows.len(), executor.program().bindings().len());
    assert!(
        port_rows
            .iter()
            .all(|r| r[1]["cursor"]["revision"].as_u64().is_some())
    );
    let mut damaged = after["port"].clone();
    let entry = damaged["nodes"]
        .as_array_mut()
        .ok_or("port nodes")?
        .iter_mut()
        .find(|r| r[1]["state_capability"] == "CHECKPOINTABLE")
        .ok_or("stateful node")?;
    entry[1]["plugin_state"]["unrecognized"] = json!(true);
    assert!(executor.port().restore_candidate(&damaged).is_err());
    assert_eq!(executor.capture_checkpoint()?, after);
    let observation = bar(&case["base"], 21)?;
    let time = OnlyTimestamp::from_datetime(*observation.bar_end());
    let original = executor.process(&observation, &time, &"d".repeat(64))?;
    assert_eq!(original.to_record()["decision"]["exit"], true);
    assert_eq!(
        restored
            .process(&observation, &time, &"d".repeat(64))?
            .to_record(),
        original.to_record()
    );
    let before_cancel = executor.capture_checkpoint()?;
    let control = executor.port().cancellation()?.ok_or("installed math child")?;
    assert_eq!(control.state(), ProcessState::Running);
    control.cancel()?;
    assert_eq!(control.state(), ProcessState::Joined);
    let next = bar(&case["base"], 22)?;
    let next_time = OnlyTimestamp::from_datetime(*next.bar_end());
    assert!(executor.process(&next, &next_time, &"d".repeat(64)).is_err());
    assert!(executor.is_failed());
    assert!(executor.capture_checkpoint().is_err());

    let mut resumed = executor.restored_candidate(
        before_cancel.to_string().as_bytes(),
        &record_fingerprint(&before_cancel),
    )?;
    let resumed_control = resumed.port().cancellation()?.ok_or("fresh math child")?;
    assert!(!control.same_owner(&resumed_control));
    assert_eq!(resumed_control.state(), ProcessState::Running);
    assert_eq!(resumed.capture_checkpoint()?, before_cancel);
    assert_eq!(
        resumed.process(&next, &next_time, &"d".repeat(64))?.to_record(),
        restored.process(&next, &next_time, &"d".repeat(64))?.to_record()
    );
    assert_eq!(resumed.capture_checkpoint()?, restored.capture_checkpoint()?);
    drop(resumed);
    assert_eq!(resumed_control.state(), ProcessState::Joined);
    eprintln!("Strategy execution, original child cancellation and fresh continuation verified");
    drop(executor);
    drop(restored);
    assert_eq!(
        count.load(Ordering::SeqCst),
        0,
        "all exact child owners must positively join before releasing completion"
    );
    Ok(())
}

#[test]
fn algorithm_process_owns_the_installed_math_child_until_positive_join()
-> Result<(), Box<dyn Error>> {
    use onlyalpha_backend::workers::algorithm::AlgorithmProcess;
    use onlyalpha_calculation_bridge::ProcessState;
    let case = fixture()?;
    let artifact = std::env::var("ONLYALPHA_TRADING_TEST_ARTIFACT")?;
    let installation = ChartInstallation::open(
        Path::new(&std::env::var("ONLYALPHA_TRADING_TEST_INSTALLATION")?),
        &artifact,
    )?;
    let count = Arc::new(AtomicUsize::new(1));
    let mut worker = AlgorithmProcess::trading(
        &installation,
        &"a".repeat(64),
        Box::new(Completion(count.clone())),
    )?;
    let control = worker.cancellation()?;
    assert_eq!(control.state(), ProcessState::Running);
    let handshake = worker.handshake_trading_numerics(DEADLINE)?;
    assert_eq!(
        handshake,
        json!({"schema_version":1,"contract":"ONLYALPHA_TRADING_NUMERICS_V1","max_nodes":128,"max_frame":8388608,"isolation":"LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1"})
    );
    let nodes = case["calculations"]["nodes"]
        .as_array()
        .ok_or("nodes")?
        .iter()
        .enumerate()
        .map(|(index, row)| (index.to_string(), row["definition"].clone()))
        .collect::<serde_json::Map<_, _>>();
    let initialize =
        json!({"schema_version":1,"op":"INITIALIZE","sources":case["sources"],"nodes":nodes});
    let state = worker.exchange_trading_numerics(initialize, DEADLINE)?;
    assert_eq!(state["schema_version"], 1);
    assert_eq!(state["nodes"].as_object().ok_or("nodes")?.len(), 3);
    assert!(state.get("cursor").is_none() && state.get("receipt").is_none());
    assert_eq!(count.load(Ordering::SeqCst), 1);
    control.cancel()?;
    assert_eq!(control.state(), ProcessState::Joined);
    assert_eq!(count.load(Ordering::SeqCst), 0);
    drop(worker);
    assert_eq!(count.load(Ordering::SeqCst), 0);
    Ok(())
}

#[test]
fn constructor_handshake_failure_reports_the_new_original_child_after_an_old_join() -> Result<(),Box<dyn Error>> {
    use onlyalpha_backend::workers::algorithm::AlgorithmProcess;
    use onlyalpha_strategy::NodeFailure;
    let case=fixture()?;let artifact=std::env::var("ONLYALPHA_TRADING_TEST_ARTIFACT")?;
    let installation=Arc::new(ChartInstallation::open(Path::new(&std::env::var("ONLYALPHA_TRADING_TEST_INSTALLATION")?),&artifact)?);
    let (program,definitions)=setup(&case,&artifact)?;
    let old=AlgorithmProcess::trading(&installation,program.generation(),Box::new(Arc::new(())))?;
    let previous=old.cancellation()?;old.terminate()?;drop(old);
    assert_eq!(previous.state(),ProcessState::Joined);
    let observed=Arc::new(std::sync::Mutex::new(Vec::<Cancellation>::new()));
    let captured=observed.clone();let prior=previous.clone();
    let count=Arc::new(AtomicUsize::new(1));let hold:Arc<dyn Send+Sync>=Arc::new(Completion(count.clone()));
    let result=constructor_port::InstalledTradingNodes::new_owned(installation,program,definitions,case["sources"].as_array().unwrap().clone(),hold.clone(),DEADLINE,Arc::new(move |child:Cancellation| {
        assert_eq!(child.state(),ProcessState::Running);
        assert!(!child.same_owner(&prior));
        captured.lock().unwrap().push(child.clone());
        // A real shutdown before the handshake produces deterministic UNKNOWN.
        child.cancel().map_err(|_|NodeFailure::Unknown)
    }));
    assert!(matches!(result,Err(NodeFailure::Unknown)));
    let children=observed.lock().unwrap();assert_eq!(children.len(),1);
    assert!(!children[0].same_owner(&previous));children[0].drain()?;
    assert_eq!(children[0].state(),ProcessState::Joined);
    drop(children);drop(hold);assert_eq!(count.load(Ordering::SeqCst),0);
    Ok(())
}

#[test]
fn constructor_initialize_failure_keeps_the_fresh_child_handle_available_for_drain() -> Result<(),Box<dyn Error>> {
    use onlyalpha_strategy::NodeFailure;
    let case=fixture()?;let artifact=std::env::var("ONLYALPHA_TRADING_TEST_ARTIFACT")?;
    let installation=Arc::new(ChartInstallation::open(Path::new(&std::env::var("ONLYALPHA_TRADING_TEST_INSTALLATION")?),&artifact)?);
    let (program,definitions)=setup(&case,&artifact)?;
    let observed=Arc::new(std::sync::Mutex::new(Vec::<Cancellation>::new()));let captured=observed.clone();
    let count=Arc::new(AtomicUsize::new(1));let hold:Arc<dyn Send+Sync>=Arc::new(Completion(count.clone()));
    constructor_port::test_fail_before_initialize();
    let result=constructor_port::InstalledTradingNodes::new_owned(installation,program,definitions,case["sources"].as_array().unwrap().clone(),hold.clone(),DEADLINE,Arc::new(move |child:Cancellation| {
        assert_eq!(child.state(),ProcessState::Running);captured.lock().unwrap().push(child);Ok(())
    }));
    assert!(matches!(result,Err(NodeFailure::Unknown)));
    let children=observed.lock().unwrap();assert_eq!(children.len(),1);
    assert!(children[0].same_owner(&children[0].clone()));children[0].drain()?;
    assert_eq!(children[0].state(),ProcessState::Joined);
    drop(children);drop(hold);assert_eq!(count.load(Ordering::SeqCst),0);
    Ok(())
}

#[test]
fn constructor_restore_failure_attaches_fresh_child_and_preserves_the_original_port() -> Result<(),Box<dyn Error>> {
    use onlyalpha_strategy::NodeFailure;
    let case=fixture()?;let artifact=std::env::var("ONLYALPHA_TRADING_TEST_ARTIFACT")?;
    let installation=Arc::new(ChartInstallation::open(Path::new(&std::env::var("ONLYALPHA_TRADING_TEST_INSTALLATION")?),&artifact)?);
    let (program,definitions)=setup(&case,&artifact)?;
    let observed=Arc::new(std::sync::Mutex::new(Vec::<Cancellation>::new()));let captured=observed.clone();
    let count=Arc::new(AtomicUsize::new(1));let hold:Arc<dyn Send+Sync>=Arc::new(Completion(count.clone()));
    let mut port=constructor_port::InstalledTradingNodes::new_owned(installation,program,definitions,case["sources"].as_array().unwrap().clone(),hold.clone(),DEADLINE,Arc::new(move |child:Cancellation| {
        captured.lock().unwrap().push(child);Ok(())
    })).map_err(|_|"actual initialized SDK port")?;
    let original=port.cancellation().map_err(|_|"original child owner")?.ok_or("math child")?;
    let checkpoint=port.capture().map_err(|_|"actual SDK checkpoint")?;
    constructor_port::test_fail_before_initialize();
    assert!(matches!(port.restore_candidate(&checkpoint),Err(NodeFailure::Unknown)));
    let children=observed.lock().unwrap();assert_eq!(children.len(),2);
    assert!(children[0].same_owner(&original));assert!(!children[1].same_owner(&original));
    assert_eq!(original.state(),ProcessState::Running,"a failed fresh candidate cannot kill or replace the old transactional port");
    children[1].drain()?;assert_eq!(children[1].state(),ProcessState::Joined);
    original.cancel()?;drop(children);drop(port);drop(hold);
    assert_eq!(count.load(Ordering::SeqCst),0);
    Ok(())
}

#[test]
fn trading_capabilities_metadata_observes_actual_installed_registrations_without_market_rows() -> Result<(),Box<dyn Error>> {
    use onlyalpha_backend::workers::algorithm::AlgorithmProcess;
    use onlyalpha_calculation::product::Graph;
    let case=fixture()?;let artifact=std::env::var("ONLYALPHA_TRADING_TEST_ARTIFACT")?;
    let installation=ChartInstallation::open(Path::new(&std::env::var("ONLYALPHA_TRADING_TEST_INSTALLATION")?),&artifact)?;
    let (source,program,_)=product_setup(&case,&artifact)?;
    let graph=Graph::from_record(&source.to_record()["decision_graph"],WORK)?;
    let definitions=graph.ordered_nodes().map(|definition|definition.to_record()).filter(|record|record["kind"]!="PREDICATE").collect::<Vec<_>>();
    assert!(!definitions.is_empty());
    let mut expected=BTreeMap::new();
    for definition in &definitions {
        let matches=case["registrations"].as_array().unwrap().iter().filter(|row|row["backend"]=="TRADING"&&row["type"]["type_id"]==definition["type_id"]&&row["type"]["semantic_version"]==definition["semantic_version"]).collect::<Vec<_>>();
        assert_eq!(matches.len(),1);let registration=matches[0];
        let id=ProductDefinition::from_record(definition, WORK)?.fingerprint();
        expected.insert(id.clone(),json!({"node_fingerprint":id,"implementation_fingerprint":registration["implementation_fingerprint"],"state_capability":registration["state_capability"],"checkpoint_schema_version":registration["checkpoint_schema_version"]}));
    }
    let mut worker=AlgorithmProcess::research_resolution(&installation,&program.generation(),Box::new(Arc::new(())))?;
    let owner=worker.cancellation()?;
    worker.handshake_research(DEADLINE)?;
    let request=json!({"schema_version":1,"contract":"ONLYALPHA_TRADING_NODE_CAPABILITIES_V1","sources":case["sources"],"definitions":definitions});
    assert!(request.get("rows").is_none()&&request.get("input").is_none());
    let observed=worker.resolve_research(request,DEADLINE)?;
    worker.terminate()?;assert_eq!(owner.state(),ProcessState::Joined);
    assert_eq!(observed,json!({"schema_version":1,"contract":"ONLYALPHA_TRADING_NODE_CAPABILITIES_V1","nodes":expected.into_values().collect::<Vec<_>>(),"isolation":"LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1"}));
    Ok(())
}
#[test]
fn trading_capabilities_metadata_rejects_vector_inputs_and_native_predicates() -> Result<(),Box<dyn Error>> {
    use onlyalpha_backend::workers::algorithm::AlgorithmProcess;
    use onlyalpha_calculation::{product::Graph};
    use onlyalpha_calculation_bridge::WorkerError;
    let case=fixture()?;let artifact=std::env::var("ONLYALPHA_TRADING_TEST_ARTIFACT")?;
    let installation=ChartInstallation::open(Path::new(&std::env::var("ONLYALPHA_TRADING_TEST_INSTALLATION")?),&artifact)?;
    let (source,program,_)=product_setup(&case,&artifact)?;
    let graph=Graph::from_record(&source.to_record()["decision_graph"],WORK)?;
    let arithmetic=graph.ordered_nodes().find(|definition|definition.to_record()["kind"]!="PREDICATE").ok_or("arithmetic")?.to_record();
    let predicate=graph.ordered_nodes().find(|definition|definition.to_record()["kind"]=="PREDICATE").ok_or("native Predicate")?.to_record();
    for request in [
        json!({"schema_version":1,"contract":"ONLYALPHA_TRADING_NODE_CAPABILITIES_V1","sources":case["sources"],"definitions":[arithmetic],"rows":[{"close":"1"}]}),
        json!({"schema_version":1,"contract":"ONLYALPHA_TRADING_NODE_CAPABILITIES_V1","sources":case["sources"],"definitions":[predicate]}),
    ] {
        let mut worker=AlgorithmProcess::research_resolution(&installation,&program.generation(),Box::new(Arc::new(())))?;
        worker.handshake_research(DEADLINE)?;
        assert_eq!(worker.resolve_research(request,DEADLINE),Err(WorkerError::Rejected));
        worker.terminate()?;
    }
    Ok(())
}
