//! Shared integration construction using actual native Program/Operator/Predicate owners.
use onlyalpha_calculation::{Definition, Graph, program::Program as Factor};
use onlyalpha_calculation_bridge::{
    ProgramFactor, ProgramNodes, native_operators::OperatorCalculation,
    native_predicates::PredicateCalculation,
};
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBar, time::OnlyTimestamp};
use onlyalpha_strategy::{NodeDescriptor, Program, Revision, Scope, SignalBinding};
use serde_json::{Value, json};
use std::{collections::BTreeMap, sync::Arc};
const BARS: &str = include_str!("../../../../test-data/strategy/decisions-v2.jsonl");
pub fn bar(index: u64, price: &str) -> OnlyBar {
    let mut value: Value =
        serde_json::from_str::<Value>(BARS.lines().next().unwrap()).unwrap()["record"].clone();
    for f in ["open", "high", "low", "close"] {
        value[f]["value"] = json!(price);
    }
    for f in ["bar_start", "bar_end", "ts_event", "ts_init"] {
        let stamp = OnlyTimestamp::from_datetime(value[f].as_str().unwrap().parse().unwrap());
        value[f] = json!(
            OnlyTimestamp::from_unix_nanos(
                stamp.unix_nanos() + i64::try_from(index - 1).unwrap() * 60_000_000_000i64
            )
            .to_datetime_exact()
            .unwrap()
            .to_string()
        );
    }
    OnlyBar::from_record(&value).unwrap()
}
pub fn executor() -> onlyalpha_strategy::Executor<ProgramNodes> {
    let (program, nodes) = parts();
    onlyalpha_strategy::Executor::new(program, nodes).unwrap()
}
pub fn parts() -> (Program, ProgramNodes) {
    let image = "f".repeat(64);
    let root = OperatorCalculation::resolve(
        "onlyalpha.operator.rolling_mean",
        "2",
        &json!({"period":{"type":"INTEGER","value":2}}),
        &json!({"value":{"node_fingerprint":null,"output_name":"value","source":"bar.close"}}),
    )
    .unwrap();
    let mut root = root.definition().to_record();
    root["kind"] = json!("FACTOR");
    root["type_id"] = json!("private.factor.memory_signal");
    root["factor_kind"] = json!("TIME_SERIES");
    let root =
        onlyalpha_calculation::product::Definition::from_record(&root, 8 * 1024 * 1024).unwrap();
    let factor=Factor::decode(json!({"schema_version":1,"numeric_policy":"DECIMAL28_HALF_EVEN_Q12_V1","inputs":{"value":{"type":"DECIMAL","role":"MARKET"}},"parameters":[{"name":"period","parameter_type":"INTEGER","required":false,"default":{"type":"INTEGER","value":2},"minimum":{"type":"INTEGER","value":1},"maximum":{"type":"INTEGER","value":100000},"enum_values":[],"uppercase":false}],"nodes":[{"op":"input","name":"value"},{"op":"rolling_mean","args":[0],"period":{"parameter":"period"}}],"outputs":{"value":1}}).to_string().as_bytes()).unwrap();
    let bound = Arc::new(
        factor
            .bind(&factor.resolve_parameters(&json!({"period":2})).unwrap())
            .unwrap(),
    );
    let factor_binding = ProgramFactor::new(bound, &"e".repeat(64)).unwrap();
    let mut products = vec![root.clone()];
    let mut descriptors = vec![];
    let mut signals = vec![];
    for (compare, terminal, threshold) in [
        ("ge", "eligibility", "0.00"),
        ("gt", "entry_signal", "2.50"),
        ("lt", "exit_signal", "2.50"),
    ] {
        let predicate=PredicateCalculation::resolve(&format!("onlyalpha.predicate.internal.compare.{compare}.decimal.literal"),"1",&json!({"literal":{"type":"DECIMAL","value":threshold}}),&json!({"left":{"node_fingerprint":native(&root).fingerprint(),"output_name":"value","source":null}})).unwrap();
        let leaf=PredicateCalculation::resolve(&format!("onlyalpha.predicate.internal.terminal.{terminal}"),"1",&json!({}),&json!({"value":{"node_fingerprint":native(predicate.definition()).fingerprint(),"output_name":"value","source":null}})).unwrap();
        signals
            .push(SignalBinding::new(&native(leaf.definition()).fingerprint(), "value").unwrap());
        for p in [predicate, leaf] {
            descriptors.push(NodeDescriptor { definition:native(p.definition()),native_definition:p.definition().fingerprint(),implementation:p.implementation_manifest("TRADING",&image).unwrap()["implementation_fingerprint"].as_str().unwrap().into(),state_capability:"STATELESS".into(),checkpoint_schema:None });
            products.push(p.definition().clone());
        }
    }
    let root_native = native(&root);
    descriptors.push(NodeDescriptor {
        definition: root_native.clone(),
        native_definition: root.fingerprint(),
        implementation: "e".repeat(64),
        state_capability: "CHECKPOINTABLE".into(),
        checkpoint_schema: Some(1),
    });
    let graph = Graph::new(products.iter().map(|p| (native(p), None)).collect()).unwrap();
    let first = bar(1, "1.00");
    let recipe = onlyalpha_market_data::construction::OnlyConstructionRecipe::native(
        first.bar_type().semantic().clone(),
    );
    let revision = Revision::new(
        vec![first.instrument_id().clone()],
        first.bar_type().semantic().clone(),
        recipe,
        graph,
        descriptors,
        signals.try_into().unwrap(),
    )
    .unwrap();
    let program = Program::new(
        revision,
        Scope {
            engine: "engine".parse().unwrap(),
            runtime: "runtime".parse().unwrap(),
            cluster: "cluster".parse().unwrap(),
        },
        &"a".repeat(64),
        &"c".repeat(64),
        &"b".repeat(64),
    )
    .unwrap();
    let definitions = products
        .into_iter()
        .map(|p| (native(&p).fingerprint(), p))
        .collect::<BTreeMap<_, _>>();
    let nodes = ProgramNodes::new(
        program.clone(),
        definitions,
        BTreeMap::from([(root_native.fingerprint(), factor_binding)]),
        &image,
    )
    .unwrap();
    (program, nodes)
}
fn native(p: &onlyalpha_calculation::product::Definition) -> Definition {
    let mut r = p.to_record();
    r["schema_version"] = json!(3);
    Definition::from_record(&r).unwrap()
}
