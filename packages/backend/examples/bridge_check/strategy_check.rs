//! Real registered producer and MarketData preparation comparison.
use onlyalpha_backend::workers::algorithm::AlgorithmProcess;
use onlyalpha_calculation::Graph;
use onlyalpha_calculation_bridge::{StrategyNodes, StrategyPreparation, Worker, fingerprint};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    calendar::*,
    enums::OnlySessionType,
    market::OnlyBar,
    time::{OnlyTimeZone, OnlyTimestamp},
};
use onlyalpha_market_data_pipeline::{construction::*, delivery::*, state::*, *};
use onlyalpha_strategy::*;
use serde_json::{Value, json};
use std::{collections::BTreeMap, error::Error, path::Path, sync::Arc, time::Duration};
const DEADLINE: Duration = Duration::from_secs(10);
fn resolve(
    worker: &mut Worker,
    requests: &mut BTreeMap<String, Value>,
    kind: &str,
    id: &str,
    parameters: Value,
    bindings: Value,
) -> Result<NodeDescriptor, Box<dyn Error>> {
    let request = json!({"schema_version":1,"op":"RESOLVE","reference":{"kind":kind,"type_id":id,"semantic_version":"1"},"parameters":parameters,"input_bindings":bindings});
    let d = StrategyNodes::resolve(worker, request.clone(), DEADLINE)
        .map_err(|error| format!("STRATEGY_PROBE_RESOLVE {id}: {error}"))?;
    requests.insert(d.definition.fingerprint(), request);
    Ok(d)
}
fn upstream(node: &NodeDescriptor) -> Value {
    json!({"node_fingerprint":node.definition.fingerprint(),"output_name":"value","source":null})
}
fn setup(
    python: &Path,
    artifact: &str,
    base: &Value,
    root_type: &str,
) -> Result<StrategyPreparation<StrategyNodes>, Box<dyn Error>> {
    let generation = "a".repeat(64);
    let source = "c".repeat(64);
    let mut worker =
        AlgorithmProcess::spawn(python, generation.clone(), artifact.into(), DEADLINE)?;
    let mut requests = BTreeMap::new();
    let external =
        json!({"value":{"node_fingerprint":null,"output_name":"value","source":"bar.close"}});
    let params = json!({"period":{"type":"INTEGER","value":3}});
    let sma = resolve(
        &mut worker,
        &mut requests,
        "INDICATOR",
        root_type,
        params.clone(),
        external.clone(),
    )?;
    let ema = resolve(
        &mut worker,
        &mut requests,
        "INDICATOR",
        "onlyalpha.indicator.ema",
        params,
        external,
    )?;
    let abs = resolve(
        &mut worker,
        &mut requests,
        "INDICATOR",
        "onlyalpha.operator.abs",
        json!({}),
        json!({"value":upstream(&sma)}),
    )?;
    let mut descriptors = vec![sma, ema, abs.clone()];
    let mut signals = vec![];
    for (role, op, literal) in [
        ("eligibility", "ge", "0"),
        ("entry_signal", "gt", "2"),
        ("exit_signal", "lt", "2"),
    ] {
        let predicate = resolve(
            &mut worker,
            &mut requests,
            "PREDICATE",
            &format!("onlyalpha.predicate.internal.compare.{op}.decimal.literal"),
            json!({"literal":{"type":"DECIMAL","value":literal},"literal_left":{"type":"BOOLEAN","value":false}}),
            json!({"left":upstream(&abs)}),
        )?;
        let terminal = resolve(
            &mut worker,
            &mut requests,
            "PREDICATE",
            &format!("onlyalpha.predicate.internal.terminal.{role}"),
            json!({}),
            json!({"value":upstream(&predicate)}),
        )?;
        signals.push(SignalBinding::new(
            &terminal.definition.fingerprint(),
            "value",
        )?);
        descriptors.extend([predicate, terminal]);
    }
    drop(worker);
    let bar = OnlyBar::from_record(base)?;
    let kind = bar.bar_type().clone();
    let graph = Graph::new(
        descriptors
            .iter()
            .map(|d| (d.definition.clone(), None))
            .collect(),
    )?;
    let revision = Revision::new(
        vec![bar.instrument_id().clone()],
        kind.semantic().clone(),
        OnlyConstructionRecipe::native(kind.semantic().clone()),
        graph,
        descriptors,
        signals.try_into().map_err(|_| "signals")?,
    )?;
    let scope = Scope {
        engine: "strategy-probe-engine".parse()?,
        runtime: "strategy-probe-runtime".parse()?,
        cluster: "strategy-probe-cluster".parse()?,
    };
    let program = Program::new(revision, scope.clone(), &generation, &source, artifact)?;
    let nodes = StrategyNodes::new(
        Arc::new(AlgorithmProcess::new(python.to_owned())),
        program.clone(),
        requests,
        DEADLINE,
    )
    .map_err(|error| format!("STRATEGY_PROBE_CREATE: {error}"))?;
    let strategy = Executor::new(program, nodes)?;
    let calendar = Arc::new(OnlyTradingCalendar::new(OnlyTradingCalendarInput {
        calendar_id: "probe-calendar".parse()?,
        venue_id: "X".parse()?,
        timezone: OnlyTimeZone::new("UTC")?,
        sessions: vec![OnlyTradingSession::new(OnlyTradingSessionInput {
            name: "session".into(),
            opens_at: "01:30:00".parse()?,
            closes_at: "23:59:00".parse()?,
            session_type: OnlySessionType::Regular,
            belongs_to_trading_day_offset: 0,
            allows_orders: true,
            allows_market_data: true,
        })?],
        holidays: vec![],
        weekend_days: vec![5, 6],
        session_profile_id: None,
        special_schedules: vec![],
        calendar_version: 1u32.into(),
        effective_from: None,
        effective_to: None,
    })?);
    let graph = OnlyConstructionGraph::new(vec![OnlyConstructionInput::Bar(kind.clone())], vec![])?;
    let executable = fingerprint(&std::fs::read(std::env::current_exe()?)?);
    let source = SourceProgram::new(
        &source,
        calendar,
        Arc::new(OnlyConstructionRegistry::default()),
        &executable,
        graph.clone(),
    )?;
    let cluster = ClusterProgram {
        cluster: scope.cluster,
        subscription: OnlyBarSubscription::new(
            "strategy-probe",
            vec![kind.clone()],
            graph,
            Some(kind),
            OnlyBarFreshness::LatestClosed,
        )?,
    };
    let pipeline = PipelineProgram::new(
        OnlyMarketDataStateScope::new(scope.engine, scope.runtime),
        &generation,
        128,
        vec![source],
        vec![cluster],
        vec![],
        &executable,
    )?;
    Ok(StrategyPreparation::new(pipeline, strategy)?)
}
fn input(bar: &OnlyBar, i: u64) -> PipelineInput {
    PipelineInput {
        source: "c".repeat(64),
        sequence: i,
        fact: OnlyConstructionFact::Bar(Arc::new(bar.clone())),
        logical_init: OnlyTimestamp::from_datetime(*bar.ts_init()),
        quality: vec![],
    }
}
pub fn run(python: &Path, artifact: &str, base: &Value) -> Result<(), Box<dyn Error>> {
    let bars = super::data(base, 6)?;
    let mut original = setup(python, artifact, base, "onlyalpha.indicator.sma")?;
    let mut common = vec![];
    for (i, bar) in bars[..3].iter().enumerate() {
        let result = original.process(&input(bar, (i + 1) as u64))?;
        let outcome = &result["decisions"][0];
        assert_eq!(outcome["status"], if i < 2 { "BLOCKED" } else { "READY" });
        if i == 2 {
            common.push(json!({"minute":i+1,"eligibility":outcome["decision"]["eligibility"],"entry":outcome["decision"]["entry"],"exit":outcome["decision"]["exit"]}));
            assert_eq!(outcome["decision"]["eligibility"], true);
            assert_eq!(outcome["decision"]["entry"], false);
            assert_eq!(outcome["decision"]["exit"], false);
        }
    }
    let cp = original.capture_checkpoint()?;
    // Same terminal Bar is insufficient: the owning input histories must agree too.
    let mut different = setup(python, artifact, base, "onlyalpha.indicator.sma")?;
    for (i, bar) in bars[..3].iter().enumerate() {
        let mut row = bar.to_record();
        if i == 0 {
            for f in ["open", "high", "low", "close"] {
                row[f]["value"] = json!("2");
            }
        }
        let bar = OnlyBar::from_record(&row)?;
        different.process(&input(&bar, (i + 1) as u64))?;
    }
    let other = different.capture_checkpoint()?;
    let mut mixed = cp.clone();
    mixed["strategy"] = other["strategy"].clone();
    assert!(mixed.get("delivery_prefix").is_none());
    mixed["binding"]["strategy"] = json!(record_fingerprint(&mixed["strategy"]));
    let mut target = setup(python, artifact, base, "onlyalpha.indicator.sma")?;
    target.restore_checkpoint(cp.to_string().as_bytes(), &record_fingerprint(&cp))?;
    assert!(
        target
            .restore_checkpoint(mixed.to_string().as_bytes(), &record_fingerprint(&mixed))
            .is_err(),
        "same-Bar different-prefix splice was accepted"
    );
    assert_eq!(cp, target.capture_checkpoint()?);

    let mut restored = setup(python, artifact, base, "onlyalpha.indicator.sma")?;
    restored.restore_checkpoint(cp.to_string().as_bytes(), &record_fingerprint(&cp))?;
    for (i, bar) in bars.iter().enumerate().skip(3) {
        let a = original.process(&input(bar, (i + 1) as u64))?;
        let b = restored.process(&input(bar, (i + 1) as u64))?;
        assert_eq!(a, b);
        let d = &a["decisions"][0]["decision"];
        common.push(json!({"minute":i+1,"eligibility":d["eligibility"],"entry":d["entry"],"exit":d["exit"]}));
        assert_eq!(a["decisions"][0]["decision"]["entry"], true);
        assert_eq!(a["decisions"][0]["decision"]["exit"], false);
    }
    assert_eq!(
        original.capture_checkpoint()?,
        restored.capture_checkpoint()?
    );
    let mut v = original.capture_checkpoint()?;
    v["strategy"] = cp["strategy"].clone();
    v["binding"]["strategy"] = json!(record_fingerprint(&v["strategy"]));
    let before = restored.capture_checkpoint()?;
    assert!(
        restored
            .restore_checkpoint(v.to_string().as_bytes(), &record_fingerprint(&v))
            .is_err()
    );
    assert_eq!(before, restored.capture_checkpoint()?);
    original.strategy().port().cancellation()?.cancel()?;
    assert!(
        original
            .process(&input(&super::data(base, 7)?[6], 7))
            .is_err()
    );
    assert!(original.is_failed());
    assert!(original.capture_checkpoint().is_err());
    original.restore_checkpoint(before.to_string().as_bytes(), &record_fingerprint(&before))?;

    // A full rolling window has the same length at consecutive cuts. Retain the
    // newer acknowledged state commitment while rewriting the nested native state.
    let mut rolling = setup(python, artifact, base, "onlyalpha.operator.rolling_mean")?;
    for (i, bar) in bars[..3].iter().enumerate() {
        rolling.process(&input(bar, (i + 1) as u64))?;
    }
    let earlier = rolling.capture_checkpoint()?;
    rolling.process(&input(&bars[3], 4))?;
    let current = rolling.capture_checkpoint()?;
    let mut spliced = current.clone();
    let program = rolling.strategy().program();
    let node = program
        .revision()
        .descriptors()
        .values()
        .find(|d| d.definition.reference().type_id() == "onlyalpha.operator.rolling_mean")
        .ok_or("rolling node")?
        .definition
        .fingerprint();
    let scope = program.instance_scope(bars[0].instrument_id(), &node);
    let previous = earlier["strategy"]["port"]["nodes"]
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r[0] == scope)
        .unwrap()[1]["plugin_state"]
        .clone();
    let native = spliced["strategy"]["port"]["nodes"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .find(|r| r[0] == scope)
        .unwrap();
    native[1]["plugin_state"] = previous;
    native[1]["state_fingerprint"] = json!(record_fingerprint(&native[1]["plugin_state"]));
    let hashes = spliced["strategy"]
        .as_object()
        .unwrap()
        .iter()
        .filter(|(k, _)| k.as_str() != "component_bindings")
        .map(|(k, v)| (k.clone(), json!(record_fingerprint(v))))
        .collect();
    spliced["strategy"]["component_bindings"] = Value::Object(hashes);
    spliced["binding"]["strategy"] = json!(record_fingerprint(&spliced["strategy"]));
    assert!(
        rolling
            .restore_checkpoint(
                spliced.to_string().as_bytes(),
                &record_fingerprint(&spliced)
            )
            .is_err(),
        "old full rolling window was accepted at a newer receipt"
    );
    assert_eq!(current, rolling.capture_checkpoint()?);
    let continuation = rolling.process(&input(&bars[4], 5))?;
    assert_eq!(continuation["decisions"][0]["decision"]["entry"], true);
    println!("STRATEGY_DECISIONS_JSON {}", json!(common));
    println!(
        "STRATEGY actual registered SMA/EMA/operator/predicate, MarketData handoff, fresh recovery and cancellation PASS"
    );
    Ok(())
}
