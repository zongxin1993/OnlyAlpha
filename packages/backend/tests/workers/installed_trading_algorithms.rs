//! Installed source compiler and native Strategy execution. This technical fixture
//! proves arithmetic and recovery, not a READY certificate or a product grant.
use onlyalpha_backend::{
    application::{private_strategy::Definition as Strategy, strategy_research::DecisionGraph},
    workers::algorithm::{AlgorithmProcess, describe_research_runtime},
};
use onlyalpha_calculation::{
    Definition,
    product::Definition as ProductDefinition,
    program::{BoundProgram, Program as FactorProgram, ProgramInput, ProgramValue, evaluate_batch},
};
use onlyalpha_calculation_bridge::{
    ChartInstallation, ProcessState, ProgramCalculation, ProgramFactor, ProgramNodes, WorkerError,
    native_operators::OperatorCalculation, native_predicates::PredicateCalculation,
};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    market::OnlyBar,
    time::{OnlyTimestamp, OnlyUtcDateTime},
};
use onlyalpha_strategy::{
    Executor, NodeDescriptor, NodePort, Program, Revision, Scope, SourceRevision,
    record_fingerprint,
};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
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

type Result<T> = std::result::Result<T, Box<dyn Error>>;
const WORK: usize = 8 * 1024 * 1024;
const DEADLINE: Duration = Duration::from_secs(10);
const GENERATION: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

struct Completion(Arc<AtomicUsize>);
impl Drop for Completion {
    fn drop(&mut self) {
        self.0.fetch_sub(1, Ordering::SeqCst);
    }
}

fn selected_fixture() -> Result<(Value, ChartInstallation)> {
    let case = serde_json::from_slice(&std::fs::read(std::env::var(
        "ONLYALPHA_TRADING_TEST_INPUT",
    )?)?)?;
    let artifact = std::env::var("ONLYALPHA_TRADING_TEST_ARTIFACT")?;
    let installation = ChartInstallation::open(
        Path::new(&std::env::var("ONLYALPHA_TRADING_TEST_INSTALLATION")?),
        &artifact,
    )?;
    Ok((case, installation))
}

fn compile_request(revision: &Value) -> Result<Value> {
    let source = [
        "source_text",
        "source_sha256",
        "factor_api_version",
        "factor_api_contract_fingerprint",
        "input_contract",
        "parameter_contract",
        "output_contract",
    ]
    .into_iter()
    .map(|key| Ok((key.to_owned(), revision.get(key).ok_or(key)?.clone())))
    .collect::<Result<Map<String, Value>>>()?;
    Ok(json!({"schema_version":1,"contract":"ONLYALPHA_FACTOR_PROGRAM_COMPILE_V1","source":source}))
}

struct Fixture {
    case: Value,
    bound: Arc<BoundProgram>,
    program_artifact: String,
    compiler_artifact: String,
    image: String,
}

fn fixture() -> Result<Fixture> {
    let (case, installation) = selected_fixture()?;
    let revision = &case["factor_revision"];
    let request = compile_request(revision)?;
    let mut worker =
        AlgorithmProcess::research_resolution(&installation, GENERATION, Box::new(()))?;
    let owner = worker.cancellation()?;
    let observed = (|| {
        worker.handshake_research(DEADLINE)?;
        worker.compile_factor(request, DEADLINE)
    })();
    worker.terminate()?;
    assert_eq!(owner.state(), ProcessState::Joined);
    let observed = observed?;
    installation.verify()?;
    assert_eq!(observed["contract"], "ONLYALPHA_FACTOR_PROGRAM_COMPILED_V1");
    assert_eq!(observed["source_sha256"], revision["source_sha256"]);
    assert_eq!(observed["parse_count"], 1);
    assert_eq!(
        observed["isolation"],
        "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1"
    );
    let ir = FactorProgram::decode(observed["program"].to_string().as_bytes())?;
    let params = ir.resolve_parameters(&case["factor_parameters"])?;
    let bound = Arc::new(ir.bind(&params)?);
    let compiler_artifact = installation.artifact_fingerprint().to_owned();
    let image = describe_research_runtime(env!("CARGO_PKG_VERSION"))?["artifact"]
        .as_str()
        .ok_or("native image")?
        .to_owned();
    // Bind the actual compiler result to its exact fixture inputs. This digest
    // identifies only the controlled test artifact, never a stored Build result.
    let program_artifact = record_fingerprint(&json!({
        "program":ir.record(),"source_sha256":revision["source_sha256"],
        "revision_fingerprint":revision["revision_fingerprint"],
        "compiler":compiler_artifact,"image":image
    }));
    Ok(Fixture {
        case,
        bound,
        program_artifact,
        compiler_artifact,
        image,
    })
}

#[derive(Clone)]
struct Implementation {
    research: String,
    trading: String,
    capability: &'static str,
    schema: Option<u64>,
}

impl Implementation {
    fn new(
        research: Value,
        trading: Value,
        capability: &'static str,
        schema: Option<u64>,
    ) -> Result<Self> {
        let identity = |row: &Value| -> Result<String> {
            Ok(row["implementation_fingerprint"]
                .as_str()
                .ok_or("implementation")?
                .to_owned())
        };
        Ok(Self {
            research: identity(&research)?,
            trading: identity(&trading)?,
            capability,
            schema,
        })
    }
}

fn product_setup(fixture: &Fixture) -> Result<(SourceRevision, Program, ProgramNodes)> {
    let case = &fixture.case;
    let mut strategy = case["strategy"].clone();
    strategy["universe"]["instruments"] = json!(["BTCUSDT.BINANCE"]);
    strategy["calculations"] = case["instances"].clone();
    let compiled_revision = &case["factor_revision"];
    strategy["factor_revision_dependencies"] = json!([{
        "factor_id":compiled_revision["factor_id"],
        "revision_fingerprint":compiled_revision["revision_fingerprint"]
    }]);
    strategy["signals"]["entry"]["operator"] = json!(">=");
    strategy["signals"]["entry"]["right"]["value"]["value"] = json!("0.001");
    let strategy = Strategy::from_record(&strategy)?;
    let mut resolved = BTreeMap::<String, ProductDefinition>::new();
    let mut nodes = Vec::new();
    let mut implementations = BTreeMap::new();
    for instance in case["instances"].as_array().ok_or("instances")? {
        let key = instance["instance_key"].as_str().ok_or("instance key")?;
        let mut bindings = Map::new();
        for row in instance["input_bindings"]
            .as_array()
            .ok_or("input bindings")?
        {
            let name = row["input_name"].as_str().ok_or("input name")?;
            let source = &row["source"];
            let binding = if source.is_string() {
                json!({"node_fingerprint":null,"output_name":"value","source":source})
            } else {
                let parent = resolved
                    .get(source["instance_key"].as_str().ok_or("parent key")?)
                    .ok_or("parent definition")?;
                json!({"node_fingerprint":parent.fingerprint(),"output_name":source["output_name"],"source":null})
            };
            assert!(bindings.insert(name.into(), binding).is_none());
        }
        let reference = &instance["type_reference"];
        let parameters = instance["parameters"]
            .as_object()
            .ok_or("parameters")?
            .iter()
            .map(|(k, v)| (k.clone(), v["value"].clone()))
            .collect::<Map<_, _>>();
        let bindings = Value::Object(bindings);
        let (definition, declaration, implementation) = match reference["kind"].as_str() {
            Some("FACTOR") => {
                assert_eq!(
                    fixture.bound.parameters().record(),
                    &Value::Object(parameters)
                );
                let c = ProgramCalculation::resolve(
                    &case["factor_revision"],
                    fixture.bound.clone(),
                    &fixture.program_artifact,
                    &fixture.image,
                    &bindings,
                )?;
                (
                    c.definition().clone(),
                    c.type_declaration()?.to_record(),
                    Implementation::new(
                        c.implementation_manifest("RESEARCH")?,
                        c.implementation_manifest("TRADING")?,
                        "CHECKPOINTABLE",
                        Some(1),
                    )?,
                )
            }
            Some("INDICATOR") => {
                let c = OperatorCalculation::resolve(
                    reference["type_id"].as_str().ok_or("operator type")?,
                    reference["semantic_version"]
                        .as_str()
                        .ok_or("operator version")?,
                    &Value::Object(parameters),
                    &bindings,
                )?;
                (
                    c.definition().clone(),
                    c.type_declaration()?,
                    Implementation::new(
                        c.implementation_manifest("RESEARCH", &fixture.image)?,
                        c.implementation_manifest("TRADING", &fixture.image)?,
                        c.state_capability(),
                        c.checkpoint_schema_version(),
                    )?,
                )
            }
            _ => return Err("unexpected fixture calculation".into()),
        };
        let row = definition.to_record();
        for field in ["kind", "type_id", "semantic_version"] {
            assert_eq!(row[field], reference[field]);
        }
        let id = definition.fingerprint();
        nodes.push(json!({"instance_key":key,"definition":row,"definition_fingerprint":id,"type_declaration":declaration}));
        assert!(implementations.insert(id, implementation).is_none());
        assert!(resolved.insert(key.into(), definition).is_none());
    }
    let decision = DecisionGraph::derive(&strategy, &json!(nodes))?;
    let mut mapping = BTreeMap::new();
    let mut definitions = BTreeMap::new();
    let mut factors = BTreeMap::new();
    let mut descriptors = Vec::new();
    let mut implementation_bindings = Vec::new();
    for product in decision.graph().ordered_nodes() {
        let original = product.fingerprint();
        let mut row = product.to_record();
        let implementation = if row["kind"] == "PREDICATE" {
            let predicate = PredicateCalculation::from_record(&row)?;
            Implementation::new(
                predicate.implementation_manifest("RESEARCH", &fixture.image)?,
                predicate.implementation_manifest("TRADING", &fixture.image)?,
                "STATELESS",
                None,
            )?
        } else {
            implementations
                .remove(&original)
                .ok_or("implementation binding")?
        };
        implementation_bindings.push(json!({"node_fingerprint":original,"research_implementation_fingerprint":implementation.research,"trading_implementation_fingerprint":implementation.trading}));
        // Project local parent identities without rewriting the original decision graph.
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
        let key = definition.fingerprint();
        mapping.insert(original, key.clone());
        if row["kind"] == "FACTOR" {
            factors.insert(
                key.clone(),
                ProgramFactor::new(fixture.bound.clone(), &implementation.trading)?,
            );
        }
        definitions.insert(key, native.clone());
        descriptors.push(NodeDescriptor {
            definition,
            native_definition: native.fingerprint(),
            implementation: implementation.trading,
            state_capability: implementation.capability.into(),
            checkpoint_schema: implementation.schema,
        });
    }
    assert!(implementations.is_empty());
    implementation_bindings.sort_by_key(|row| row["node_fingerprint"].as_str().unwrap().to_owned());
    let mut source = json!({"schema_version":1,"universe":strategy.to_record()["universe"],"market_input_contract":strategy.to_record()["market_input"],"decision_graph_fingerprint":decision.graph().fingerprint(),"implementation_bindings":implementation_bindings,"signal_semantics":decision.record()["signal_semantics"]});
    let mut identity = source.clone();
    identity["domain"] = json!("onlyalpha.strategy.revision");
    source["strategy_fingerprint"] = json!(record_fingerprint(&identity));
    source["decision_graph"] = decision.graph().to_record();
    let source = SourceRevision::from_json(&source.to_string(), WORK)?;
    let revision = Revision::from_product(source.to_record(), descriptors, mapping)?;
    assert!(revision.is_product_materialization());
    assert_eq!(revision.fingerprint(), source.fingerprint());
    let program = Program::new(
        revision,
        Scope {
            engine: "technical-engine".parse()?,
            runtime: "technical-runtime".parse()?,
            cluster: "technical-cluster".parse()?,
        },
        GENERATION,
        &"c".repeat(64),
        &fixture.compiler_artifact,
    )?;
    let port = ProgramNodes::new(program.clone(), definitions, factors, &fixture.image)?;
    Ok((source, program, port))
}

fn bar(base: &Value, index: i64) -> Result<OnlyBar> {
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

#[path = "next_open_trading.rs"]
mod next_open_trading;

#[test]
fn native_nodes_keep_predicates_and_restore_exact_continuation() -> Result<()> {
    let fixture = fixture()?;
    let (_, program, port) = product_setup(&fixture)?;
    let mut executor = Executor::new(program, port)?;
    let process = |executor: &mut Executor<ProgramNodes>, index| -> Result<Value> {
        let observation = bar(&fixture.case["base"], index)?;
        Ok(executor
            .process(
                &observation,
                &OnlyTimestamp::from_datetime(*observation.bar_end()),
                &"d".repeat(64),
            )?
            .to_record())
    };
    for index in 0..20 {
        assert_eq!(process(&mut executor, index)?["status"], "BLOCKED");
    }
    let is_factor = |node: &Value| node["plugin_state"]["definition"]["kind"] == "FACTOR";
    let assert_factor_output = |checkpoint: &Value, expected: &str| -> Result<()> {
        let node = checkpoint["port"]["nodes"]
            .as_array()
            .ok_or("port nodes")?
            .iter()
            .map(|r| &r[1])
            .find(|node| is_factor(node))
            .ok_or("factor node")?;
        assert_eq!(node["receipt"]["ready"], true);
        assert_eq!(
            node["receipt"]["outputs"]["value"],
            json!({"type":"DECIMAL","value":expected})
        );
        Ok(())
    };
    let checkpoint = executor.capture_checkpoint()?;
    assert!(
        checkpoint["port"]["nodes"]
            .as_array()
            .ok_or("port nodes")?
            .iter()
            .all(|r| { !is_factor(&r[1]) || r[1]["receipt"].is_null() })
    );
    let mut restored = executor.restored_candidate(
        checkpoint.to_string().as_bytes(),
        &record_fingerprint(&checkpoint),
    )?;
    assert_eq!(restored.capture_checkpoint()?, checkpoint);
    let entry = process(&mut executor, 20)?;
    assert_eq!(entry["status"], "READY");
    assert_eq!(entry["decision"]["entry"], true);
    assert_eq!(entry["decision"]["exit"], false);
    assert_eq!(process(&mut restored, 20)?, entry);
    let after = executor.capture_checkpoint()?;
    assert_factor_output(&after, "2.1")?;
    assert_eq!(process(&mut executor, 20)?, entry);
    assert_eq!(executor.capture_checkpoint()?, after);
    let port_rows = after["port"]["nodes"].as_array().ok_or("port nodes")?;
    assert_eq!(port_rows.len(), executor.program().bindings().len());
    assert!(
        port_rows
            .iter()
            .all(|r| r[1]["cursor"]["revision"].as_u64().is_some())
    );
    for (field, foreign) in [
        ("state", json!({"unrecognized":true})),
        ("definition", json!({})),
        ("implementation_fingerprint", json!("f".repeat(64))),
        ("checkpoint_schema_version", json!(2)),
    ] {
        let mut damaged = after["port"].clone();
        let node = damaged["nodes"]
            .as_array_mut()
            .ok_or("port nodes")?
            .iter_mut()
            .find(|r| r[1]["plugin_state"]["definition"]["kind"] == "FACTOR")
            .ok_or("factor node")?;
        assert_eq!(node[1]["checkpoint_schema_version"], 1);
        node[1]["plugin_state"][field] = foreign;
        node[1]["state_fingerprint"] = json!(record_fingerprint(&node[1]["plugin_state"]));
        assert!(executor.port().restore_candidate(&damaged).is_err());
        assert_eq!(executor.capture_checkpoint()?, after);
    }
    let exit = process(&mut executor, 21)?;
    assert_eq!(exit["decision"]["exit"], true);
    assert_eq!(process(&mut restored, 21)?, exit);
    let before = executor.capture_checkpoint()?;
    assert_factor_output(&before, "-0.009900990099")?;
    drop(executor);
    let (_, program, port) = product_setup(&fixture)?;
    let mut resumed = Executor::new(program, port)?;
    resumed.restore_checkpoint(before.to_string().as_bytes(), &record_fingerprint(&before))?;
    assert_eq!(resumed.capture_checkpoint()?, before);
    assert_eq!(process(&mut resumed, 22)?, process(&mut restored, 22)?);
    assert_eq!(
        resumed.capture_checkpoint()?,
        restored.capture_checkpoint()?
    );
    eprintln!("Native Strategy execution and exact fresh continuation verified");
    Ok(())
}

fn factor_input(index: usize, values: [Option<&str>; 4]) -> Result<ProgramInput> {
    let fields = ["close", "close_lag_20", "volume", "volume_mean_20"]
        .into_iter()
        .zip(values)
        .map(|(name, value)| {
            let value = match value {
                Some(v) => ProgramValue::Decimal(v.parse()?),
                None => ProgramValue::Missing,
            };
            Ok((name.into(), value))
        })
        .collect::<Result<BTreeMap<_, _>>>()?;
    Ok(ProgramInput::new("BTCUSDT.BINANCE", index as u64, fields)?)
}

#[test]
fn native_factor_batch_preserves_exact_volume_momentum_vectors() -> Result<()> {
    let fixture = fixture()?;
    let inputs = [
        (
            [Some("120"), Some("100"), Some("21"), Some("2")],
            json!("2.100000000000"),
        ),
        (
            [Some("121"), Some("101"), Some("1"), Some("2")],
            json!("0.099009900990"),
        ),
        (
            [Some("120"), Some("100"), Some("4"), Some("2")],
            json!("0.400000000000"),
        ),
        (
            [Some("120"), Some("100"), Some("0"), Some("0")],
            Value::Null,
        ),
        ([Some("120"), None, Some("4"), Some("2")], Value::Null),
        (
            [Some("0.9999999999985"), Some("1"), Some("1"), Some("1")],
            json!("-0.000000000002"),
        ),
        (
            [Some("1.0000000000005"), Some("1"), Some("1"), Some("1")],
            json!("0.000000000000"),
        ),
        (
            [Some("1.0000000000015"), Some("1"), Some("1"), Some("1")],
            json!("0.000000000002"),
        ),
    ];
    let rows = inputs
        .iter()
        .enumerate()
        .map(|(index, (values, _))| factor_input(index, *values))
        .collect::<Result<Vec<_>>>()?;
    let outputs = evaluate_batch(&fixture.bound, &rows)?;
    assert_eq!(outputs.len(), inputs.len());
    for (actual, (_, expected)) in outputs.iter().zip(inputs) {
        assert_eq!(actual["value"].record(), expected);
    }

    // Independent native batch kernels feed the Factor without any persisted grant.
    let evaluate = |close: &[Value], volume: &str| -> Result<Vec<Value>> {
        let operator = |kind: &str, source: &str, values: &[Value]| -> Result<Value> {
            let node = OperatorCalculation::resolve(
                kind,
                "3",
                &json!({"period":{"type":"INTEGER","value":20}}),
                &json!({"value":{"node_fingerprint":null,"output_name":"value","source":source}}),
            )?;
            Ok(node.evaluate_batch(&json!({"value":values}))?)
        };
        let lag = operator("onlyalpha.operator.delay", "bar.close", close)?;
        let mean = operator(
            "onlyalpha.operator.rolling_mean",
            "bar.volume",
            &vec![json!(volume); close.len()],
        )?;
        let rows = close
            .iter()
            .enumerate()
            .map(|(index, close)| {
                factor_input(
                    index,
                    [
                        close.as_str(),
                        lag["value"][index].as_str(),
                        Some(volume),
                        mean["value"][index].as_str(),
                    ],
                )
            })
            .collect::<Result<Vec<_>>>()?;
        Ok(evaluate_batch(&fixture.bound, &rows)?
            .iter()
            .map(|row| row["value"].record())
            .collect())
    };
    let mut close = (100..820).map(|n| json!(n.to_string())).collect::<Vec<_>>();
    let full = evaluate(&close, "200")?;
    assert_eq!(full.len(), 720);
    assert_eq!(full[..20], vec![Value::Null; 20]);
    assert_eq!(full[20], "0.200000000000");
    assert_eq!(full[40], "0.166666666667");
    close[1] = Value::Null;
    let gapped = evaluate(&close, "200")?;
    assert_eq!(gapped.len(), full.len());
    assert_eq!(gapped[21], Value::Null);
    assert_eq!(gapped[..21], full[..21]);
    assert_eq!(gapped[22..], full[22..]);
    assert_eq!(evaluate(&close, "0")?, vec![Value::Null; close.len()]);
    Ok(())
}

#[test]
fn compiler_child_owner_joins_on_cancel_and_refuses_foreign_source_bytes() -> Result<()> {
    let (case, installation) = selected_fixture()?;
    let count = Arc::new(AtomicUsize::new(1));
    let mut worker = AlgorithmProcess::research_resolution(
        &installation,
        GENERATION,
        Box::new(Completion(count.clone())),
    )?;
    let old = worker.cancellation()?;
    worker.handshake_research(DEADLINE)?;
    assert_eq!(old.state(), ProcessState::Running);
    assert_eq!(count.load(Ordering::SeqCst), 1);
    old.cancel()?;
    assert_eq!(old.state(), ProcessState::Joined);
    assert_eq!(count.load(Ordering::SeqCst), 0);
    let mut worker =
        AlgorithmProcess::research_resolution(&installation, GENERATION, Box::new(()))?;
    let fresh = worker.cancellation()?;
    assert!(!old.same_owner(&fresh));
    worker.handshake_research(DEADLINE)?;
    let mut request = compile_request(&case["factor_revision"])?;
    let revised = format!(
        "{}\n# Byte identity control\n",
        request["source"]["source_text"]
            .as_str()
            .ok_or("source text")?
    );
    request["source"]["source_text"] = json!(revised);
    let result = worker.compile_factor(request.clone(), DEADLINE);
    worker.terminate()?;
    assert_eq!(fresh.state(), ProcessState::Joined);
    assert_eq!(result, Err(WorkerError::Rejected));

    // The edited program remains valid; only its declared byte identity differed.
    let revised_sha: String = Sha256::digest(revised.as_bytes())
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    request["source"]["source_sha256"] = json!(revised_sha);
    let mut worker =
        AlgorithmProcess::research_resolution(&installation, GENERATION, Box::new(()))?;
    let owner = worker.cancellation()?;
    worker.handshake_research(DEADLINE)?;
    let compiled = worker.compile_factor(request, DEADLINE);
    worker.terminate()?;
    assert_eq!(owner.state(), ProcessState::Joined);
    let compiled = compiled?;
    assert_eq!(compiled["contract"], "ONLYALPHA_FACTOR_PROGRAM_COMPILED_V1");
    assert_eq!(compiled["source_sha256"], revised_sha);
    assert_eq!(compiled["parse_count"], 1);
    eprintln!("Installed compiler child cancellation and exact fresh owner verified");
    Ok(())
}
