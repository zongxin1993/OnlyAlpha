//! Real registered producer and MarketData preparation comparison.
use onlyalpha_calculation::Graph;
use onlyalpha_calculation_bridge::{StrategyNodes, StrategyPreparation, Worker, fingerprint};
use onlyalpha_domain::{
    base::OnlyDomainModel, calendar::*, enums::OnlySessionType, market::OnlyBar, time::OnlyTimeZone,
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
    let d = StrategyNodes::resolve(worker, request.clone(), DEADLINE)?;
    requests.insert(d.definition.fingerprint(), request);
    Ok(d)
}
fn upstream(node: &NodeDescriptor) -> Value {
    json!({"node_fingerprint":node.definition.fingerprint(),"output_name":"value","source":null})
}
pub fn setup(
    python: &Path,
    artifact: &str,
    base: &Value,
    root_type: &str,
) -> Result<StrategyPreparation<StrategyNodes>, Box<dyn Error>> {
    let generation = "a".repeat(64);
    let source = "c".repeat(64);
    let mut worker = Worker::spawn(python, generation.clone(), artifact.into(), DEADLINE)?;
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
        ("exit_signal", "ge", "2"),
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
        engine: "engine".parse()?,
        runtime: "runtime".parse()?,
        cluster: "cluster".parse()?,
    };
    let program = Program::new(revision, scope.clone(), &generation, &source, artifact)?;
    let nodes = StrategyNodes::new(python.to_owned(), program.clone(), requests, DEADLINE)?;
    let strategy = Executor::new(program, nodes)?;
    let calendar = Arc::new(OnlyTradingCalendar::new(OnlyTradingCalendarInput {
        calendar_id: "probe-calendar".parse()?,
        venue_id: bar.instrument_id().venue().clone(),
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
