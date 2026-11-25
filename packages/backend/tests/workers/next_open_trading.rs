//! Controlled technical composition over in-memory BacktestRun and InstalledTradingNodes.
//! No actual market, Freeze publication, or Product Run grant.
use super::{DEADLINE, fixture, product_setup};
use onlyalpha_backend::workers::{
    backtest::{PreparedNextOpen, next_open_policy},
    trading_nodes::InstalledTradingNodes,
};
use onlyalpha_backtest::{
    BacktestRun, ExecutionBinding, Inputs, MarketInput, MemoryRunSpec, Source,
    verify_finite_backtest,
};
use onlyalpha_calculation_bridge::{ChartInstallation, fingerprint};
use onlyalpha_data_source_binance::spot_source::spot_calendar;
use onlyalpha_domain::{
    base::OnlyDomainModel,
    market::OnlyBar,
    time::{OnlyTimestamp, OnlyUtcDateTime},
};
use onlyalpha_execution::verify_finite_backtest_result;
use onlyalpha_market_crypto::spot::SpotRuleSnapshot;
use onlyalpha_runtime::{RunBinding, RunConfiguration};
use onlyalpha_strategy::{Executor, Program};
use serde_json::{Value, json};
use std::{error::Error, path::Path, sync::Arc};

const BAR_NS: i64 = 60_000_000_000;
type Result<T> = std::result::Result<T, Box<dyn Error>>;

fn at(value: &str) -> Result<OnlyTimestamp> {
    Ok(OnlyTimestamp::from_datetime(
        value.parse::<OnlyUtcDateTime>()?,
    ))
}

fn rules() -> Result<SpotRuleSnapshot> {
    // A dated controlled snapshot, not historical or current venue-rule certification.
    let raw = json!({"symbol":"BTCUSDT","baseAsset":"BTC","quoteAsset":"USDT","status":"TRADING","isSpotTradingAllowed":true,"orderTypes":["LIMIT","MARKET"],"baseAssetPrecision":8,"quoteAssetPrecision":8,"baseCommissionPrecision":8,"quoteCommissionPrecision":8,"filters":[
        {"filterType":"PRICE_FILTER","minPrice":"0.01000000","maxPrice":"1000000.00000000","tickSize":"0.01000000"},
        {"filterType":"LOT_SIZE","minQty":"0.00001000","maxQty":"9000.00000000","stepSize":"0.00001000"},
        {"filterType":"MARKET_LOT_SIZE","minQty":"0.00000000","maxQty":"100.00000000","stepSize":"0.00000000"},
        {"filterType":"NOTIONAL","minNotional":"5.00000000","applyMinToMarket":true,"maxNotional":"9000000.00000000","applyMaxToMarket":false,"avgPriceMins":5}]});
    Ok(SpotRuleSnapshot::capture(
        raw,
        at("2026-11-01T00:00:00Z")?,
        "controlled-native-composition",
    )?)
}

fn vector_inputs(
    base: &Value,
    source: &str,
    row_count: u64,
    data_version: &str,
    snapshot: &str,
    binding: &str,
) -> Result<Inputs> {
    assert!((24..=740).contains(&row_count));
    let initial = at("2025-01-02T23:40:00Z")?.to_unix_nanos();
    let mut rows = Vec::new();
    for index in 0..row_count {
        // The next opening is distinct from both the prior and its own closing price.
        let (open, close): (u64, u64) = match index {
            0..=19 => (100000, 100000),
            20 => (100000, 100200),
            21 => (100100, 99900),
            22 => (99800, 99700),
            last if last + 1 == row_count => (99700, 100000),
            _ => (99700, 99700),
        };
        let mut row = base.clone();
        for (name, value) in [
            ("open", open),
            ("high", open.max(close)),
            ("low", open.min(close)),
            ("close", close),
        ] {
            row[name] = json!({"schema_version":1,"value":format!("{value}.00"),"precision":2});
        }
        row["volume"] = json!({"schema_version":1,"value":"100.00000","precision":5});
        let start =
            OnlyTimestamp::from_unix_nanos(&initial + index as i64 * BAR_NS).to_datetime_exact()?;
        let end = OnlyTimestamp::from_unix_nanos(&initial + (index as i64 + 1) * BAR_NS)
            .to_datetime_exact()?;
        row["bar_start"] = json!(start.to_string());
        for key in ["bar_end", "ts_event", "ts_init"] {
            row[key] = json!(end.to_string());
        }
        row["trading_day"] = json!(start.date().to_string());
        row["session_type"] = json!("CONTINUOUS");
        rows.push(MarketInput::new(
            source,
            index + 1,
            data_version,
            OnlyBar::from_record(&row)?,
        )?);
    }
    Ok(Inputs::new(
        vec![Source::new(
            source,
            snapshot,
            binding,
            data_version,
            0,
            row_count,
        )?],
        rows,
    )?)
}

fn execution_configuration(program: &Program) -> Value {
    let scope = program.scope();
    json!({"schema_version":2,"account_checkpoint_version":5,"engine":scope.engine.value(),"runtime":scope.runtime.value(),"account":"technical-account","gateway":"technical-gateway","generation":program.generation(),"runtime_kind":"BACKTEST","currency":{"schema_version":1,"code":"USDT","precision":8,"currency_type":"CRYPTO"},"initial_cash":"10000.00000000","capitals":{(scope.cluster.value()):"10000.00000000"},"profiles":{(scope.cluster.value()):{"schema_version":1,"revision":program.revision().fingerprint(),"instruments":["BTCUSDT.BINANCE"],"rules":[]}},"instruments":[{"schema_version":1,"id":"BTCUSDT.BINANCE","price_precision":2,"quantity_precision":5,"multiplier":"1"}]})
}

fn build_run(
    case: &Value,
    installation: Arc<ChartInstallation>,
    artifact: &str,
    mutate_settings: impl FnOnce(&mut Value),
) -> Result<(
    BacktestRun<InstalledTradingNodes>,
    Inputs,
    Value,
    PreparedNextOpen,
    String,
    i64,
)> {
    let (source, program, definitions) = product_setup(case, artifact)?;
    let cluster = program.scope().cluster.value().to_string();
    let cfg = execution_configuration(&program);
    let pinned = vector_inputs(
        &case["base"],
        program.source(),
        740,
        "controlled-native-v1",
        &"d".repeat(64),
        &"e".repeat(64),
    )?;
    let prepared = PreparedNextOpen::new(
        source,
        pinned,
        rules()?,
        cfg.clone(),
        at("2025-01-03T00:00:00Z")?,
        at("2025-01-03T12:00:00Z")?,
    )?;
    assert_eq!(
        prepared.record()["strategy_fingerprint"],
        program.revision().fingerprint()
    );
    let calendar = spot_calendar()?;
    assert_eq!(
        calendar.to_record()["calendar_id"]["value"],
        "BINANCE-SPOT-24X7"
    );
    for day in ["2025-01-02", "2025-01-03"] {
        let day = onlyalpha_domain::time::OnlyTradingDay::from_record(
            &json!({"schema_version":1,"value":day}),
        )?;
        assert!(calendar.is_effective_on(day));
        assert!(calendar.is_trading_day(day));
    }
    let mut settings = prepared.record()["settings"].clone();
    settings["calendar"] = calendar.to_record();
    mutate_settings(&mut settings);
    let initial_ns: i64 = prepared.initial_ns().try_into()?;
    let kernel = fingerprint(&std::fs::read(std::env::current_exe()?)?);
    let configuration = RunConfiguration::from_record(cfg)?;
    let resolver = prepared.simulation_policy().binding();
    let execution =
        ExecutionBinding::new(&configuration, &settings, initial_ns, &cluster, &resolver)?;
    let nodes = InstalledTradingNodes::new(
        installation,
        program.clone(),
        definitions,
        case["sources"].as_array().ok_or("sources")?.clone(),
        Arc::new(()),
        DEADLINE,
    )?;
    let executor = Executor::new(program, nodes)?;
    let inputs = prepared.inputs().clone();
    let pins = RunBinding::new(
        &configuration,
        &kernel,
        &inputs.fingerprint(),
        executor.program().fingerprint(),
    )?
    .with_execution_fingerprint(execution.fingerprint())?;
    let run = BacktestRun::new(
        MemoryRunSpec {
            configuration,
            binding: pins,
            policy_settings: settings.clone(),
            initial_ns,
            cluster,
        },
        inputs.clone(),
        executor,
        next_open_policy(prepared.simulation_policy().clone()),
    )?;
    Ok((run, inputs, settings, prepared, kernel, initial_ns))
}

#[test]
fn installed_source_to_native_next_open_memory_backtest_and_verification() -> Result<()> {
    let case = fixture()?;
    let artifact = std::env::var("ONLYALPHA_TRADING_TEST_ARTIFACT")?;
    let installation = Arc::new(ChartInstallation::open(
        Path::new(&std::env::var("ONLYALPHA_TRADING_TEST_INSTALLATION")?),
        &artifact,
    )?);
    let (run, inputs, settings, prepared, kernel, initial_ns) =
        build_run(&case, installation.clone(), &artifact, |_| {})?;
    let completed = run.run()?;
    let economic = completed.economic_result();
    assert_eq!(economic["final_account"]["cash"], "9994.60119940");
    assert_eq!(economic["final_account"]["fees"], "1.99900060");
    assert_eq!(economic["execution"]["trade_count"], 2);
    assert_eq!(completed.source_rows(), 740);
    assert_eq!(completed.close_curve().len(), 720);
    let fills: Vec<_> = completed
        .execution_facts()
        .iter()
        .filter(|fact| fact["body"]["input"]["op"] == "FILL")
        .collect();
    assert_eq!(fills.len(), 2);
    assert_eq!(
        fills[0]["body"]["input"]["payload"]["fill"]["price"]["value"],
        "100100.00"
    );
    assert_eq!(
        fills[1]["body"]["input"]["payload"]["fill"]["price"]["value"],
        "99800.00"
    );
    let final_ns: i64 = settings["policy"]["end_ns"].as_str().unwrap().parse()?;
    let verified = verify_finite_backtest_result(
        economic,
        completed.account_checkpoint(),
        &settings["execution"],
        &kernel,
        &inputs.fingerprint(),
        initial_ns,
        final_ns,
    )?;
    let policy = next_open_policy(prepared.simulation_policy().clone());
    let fact_refs: Vec<_> = completed.execution_facts().iter().collect();
    let curve_refs: Vec<_> = completed.close_curve().iter().collect();
    verify_finite_backtest(
        &inputs,
        &settings,
        &*policy,
        completed.raw_signals(),
        &fact_refs,
        &curve_refs,
        economic,
        verified.equity_points(),
        completed.baseline(),
    )?;
    // Deterministic recomputation with a fresh InstalledTradingNodes child produces identical facts.
    let (second, _, _, _, _, _) = build_run(&case, installation, &artifact, |_| {})?;
    let recomputed = second.run()?;
    assert_eq!(recomputed.economic_result(), completed.economic_result());
    assert_eq!(recomputed.execution_facts(), completed.execution_facts());
    assert_eq!(recomputed.close_curve(), completed.close_curve());
    assert_eq!(recomputed.baseline(), completed.baseline());
    assert_eq!(recomputed.raw_signals(), completed.raw_signals());
    Ok(())
}

#[test]
fn cancelled_or_incomplete_memory_run_cannot_produce_a_completed_backtest() -> Result<()> {
    let case = fixture()?;
    let artifact = std::env::var("ONLYALPHA_TRADING_TEST_ARTIFACT")?;
    let installation = Arc::new(ChartInstallation::open(
        Path::new(&std::env::var("ONLYALPHA_TRADING_TEST_INSTALLATION")?),
        &artifact,
    )?);
    let (mut incomplete, _, _, _, _, _) = build_run(&case, installation.clone(), &artifact, |_| {})?;
    // 22 个输入步远未覆盖冻结样本；未走完输入的运行不能产出完成结果。
    for _ in 0..22 {
        incomplete.step()?;
    }
    assert!(incomplete.finish().is_err());
    let (mut cancelled, inputs, _, _, _, _) = build_run(&case, installation, &artifact, |_| {})?;
    // 走完全部输入后取消，仍不得产出完成结果。
    for _ in 0..inputs.records().len() {
        cancelled.step()?;
    }
    cancelled.cancel();
    assert!(cancelled.finish().is_err());
    Ok(())
}

#[test]
fn foreign_instrument_context_is_refused_before_market_or_order_processing() -> Result<()> {
    let case = fixture()?;
    let artifact = std::env::var("ONLYALPHA_TRADING_TEST_ARTIFACT")?;
    let installation = Arc::new(ChartInstallation::open(
        Path::new(&std::env::var("ONLYALPHA_TRADING_TEST_INSTALLATION")?),
        &artifact,
    )?);
    assert!(
        build_run(&case, installation, &artifact, |settings| {
            settings["instrument"]["instrument_id"]["symbol"]["value"] = json!("ETHUSDT");
        })
        .is_err()
    );
    Ok(())
}
