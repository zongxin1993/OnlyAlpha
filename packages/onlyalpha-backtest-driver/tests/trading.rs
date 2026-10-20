mod support;
use onlyalpha_backtest_driver::{Inputs, MarketInput, RunLoop, RunSpec, Source, Trading};
use onlyalpha_calculation_worker::{Worker, fingerprint};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    market::OnlyBar,
    time::{OnlyTimestamp, OnlyUtcDateTime},
};
use serde_json::{Value, json};
use std::{path::Path, str::FromStr, time::Duration};
const FACTS: &str = include_str!("../../../test-data/domain/fact-records-v1.jsonl");
fn setup() -> (
    RunSpec,
    Inputs,
    Trading<onlyalpha_calculation_worker::StrategyNodes>,
) {
    setup_with_settings(|_| {}).unwrap()
}
fn setup_with_settings(
    mutate: impl FnOnce(&mut Value),
) -> Result<
    (
        RunSpec,
        Inputs,
        Trading<onlyalpha_calculation_worker::StrategyNodes>,
    ),
    onlyalpha_backtest_driver::Error,
> {
    let python = std::env::var("REPLAY_PYTHON").unwrap();
    let artifact = std::env::var("REPLAY_WORKER_ARTIFACT").unwrap();
    let instrument: Value =
        serde_json::from_str(&std::env::var("REPLAY_INSTRUMENT").unwrap()).unwrap();
    let mut base = FACTS
        .lines()
        .map(|s| serde_json::from_str::<Value>(s).unwrap())
        .find(|v| v["id"] == "bar")
        .unwrap()["record"]
        .clone();
    base["bar_type"]["instrument_id"] = instrument["instrument_id"].clone();
    let preparation = support::setup(
        Path::new(&python),
        &artifact,
        &base,
        "onlyalpha.indicator.sma",
    )
    .unwrap();
    let program = preparation.strategy().program();
    let revision = program.revision().fingerprint().to_owned();
    let generation = program.generation().to_owned();
    let cfg = json!({"schema_version":1,"engine":"engine","runtime":"runtime","account":"account","gateway":"gateway","generation":generation,"runtime_kind":"BACKTEST","currency":instrument["settlement_currency"],"initial_cash":"1000.00","capitals":{"cluster":"1000.00"},"profiles":{"cluster":{"schema_version":1,"revision":revision,"instruments":["600000.XSHG"],"rules":[]}},"instruments":[{"schema_version":1,"id":"600000.XSHG","price_precision":2,"quantity_precision":0,"multiplier":"1"}]});
    let request: Value = serde_json::from_str(include_str!(
        "../../../test-data/execution/domain-inputs.json"
    ))
    .unwrap();
    let mut buy = request["request"].clone();
    buy["price"]["value"] = json!("10.00");
    buy["quantity"]["value"] = json!("4");
    let mut sell = buy.clone();
    sell["request_id"]["value"] = json!("request-2");
    sell["side"] = json!("SELL");
    sell["offset"] = json!("CLOSE");
    sell["execution_intent"]["side"] = json!("SELL");
    sell["execution_intent"]["position_effect"] = json!("CLOSE");
    sell["price"]["value"] = json!("12.00");
    let mut settings = json!({"schema_version":1,"execution":cfg,"instrument":instrument,"maximum_fill_quantity":"2","requests":[buy,sell]});
    mutate(&mut settings);
    let worker = Worker::spawn(
        Path::new(&python),
        generation,
        artifact,
        Duration::from_secs(10),
    )
    .unwrap();
    let trading = Trading::new(preparation, worker, settings, 0.into())?;
    let source = Source::new(
        &"c".repeat(64),
        &"d".repeat(64),
        &"e".repeat(64),
        &"f".repeat(64),
        0,
        8,
    )
    .unwrap();
    let mut records = vec![];
    for (index, price) in [1, 2, 3, 4, 5, 6, 14, 15].iter().enumerate() {
        let mut v = base.clone();
        for k in ["open", "high", "low", "close"] {
            v[k]["value"] = json!(format!("{price}.00"));
        }
        for k in ["bar_start", "bar_end", "ts_event", "ts_init"] {
            let t = OnlyUtcDateTime::from_str(base[k].as_str().unwrap()).unwrap();
            let ns =
                OnlyTimestamp::from_datetime(t).to_unix_nanos() + index as i64 * 60_000_000_000_i64;
            v[k] = json!(
                OnlyTimestamp::from_unix_nanos(ns)
                    .to_datetime_exact()
                    .unwrap()
                    .to_string()
            );
        }
        records.push(
            MarketInput::new(
                source.id(),
                index as u64 + 1,
                &"f".repeat(64),
                OnlyBar::from_record(&v).unwrap(),
            )
            .unwrap(),
        );
    }
    let inputs = Inputs::new(vec![source], records).unwrap();
    let inputs = std::env::var("REPLAY_INPUTS")
        .map(|raw| Inputs::from_record(&serde_json::from_str(&raw).unwrap()).unwrap())
        .unwrap_or(inputs);
    let spec = RunSpec {
        work_id: "real-replay".into(),
        configuration: cfg,
        kernel_artifact: fingerprint(&std::fs::read(std::env::current_exe().unwrap()).unwrap()),
        driver_artifact: fingerprint(&std::fs::read(std::env::current_exe().unwrap()).unwrap()),
        initial_ns: 0.into(),
    };
    Ok((spec, inputs, trading))
}
#[test]
fn actual_strategy_virtual_broker_kernel_and_reopen_produce_the_same_full_result() {
    let root = std::env::temp_dir().join(format!("oa-real-replay-{}", std::process::id()));
    std::fs::create_dir(&root).unwrap();
    let (spec, inputs, trading) = setup();
    let mut run = RunLoop::create(&root, spec, inputs, trading).unwrap();
    run.run().unwrap();
    assert!(run.terminate("COMPLETED", None).is_err());
    let mut ids = vec![];
    run.deliver(|event| {
        ids.push(event["event_id"].clone());
        Ok(())
    })
    .unwrap();
    assert!(!ids.is_empty());
    run.terminate("COMPLETED", None).unwrap();
    let result = run.result().unwrap();
    assert_eq!(result["execution_result"]["run"]["status"], "COMPLETED");
    assert_eq!(
        result["execution_result"]["final_account"]["cash"],
        "1007.92"
    );
    assert_eq!(result["execution_result"]["final_account"]["fees"], "0.08");
    assert_eq!(
        result["execution_result"]["trades"]
            .as_array()
            .unwrap()
            .len(),
        4
    );
    let trace = run.trace().unwrap();
    drop(run);
    let (spec, inputs, trading) = setup();
    let run = RunLoop::open(&root, spec, inputs, trading).unwrap();
    assert_eq!(run.result().unwrap(), result);
    assert_eq!(run.trace().unwrap(), trace);
    drop(run);
    std::fs::remove_dir_all(root).unwrap();
}

/// Subprocess fixture driven by the canonical replay fault lane, like persistence::process_writer.
#[test]
fn process_writer() {
    use std::io::{BufRead, Write};
    let Ok(root) = std::env::var("OA_REPLAY_PROCESS_ROOT") else {
        return;
    };
    let root = Path::new(&root);
    let mode = std::env::var("OA_REPLAY_PROCESS_MODE").unwrap();
    let (spec, inputs, trading) = setup();
    if matches!(mode.as_str(), "REFUSE" | "REFUSE_RELATION") {
        if mode == "REFUSE_RELATION" {
            let runtime = onlyalpha_runtime_persistence::Runtime::open(
                root,
                spec.configuration.clone(),
                &spec.kernel_artifact,
            )
            .unwrap();
            runtime.replay_steps().expect("structural mutation must pass journal and Execution integrity before participant rederivation");
            drop(runtime);
        }
        assert!(RunLoop::open(root, spec, inputs, trading).is_err());
        println!("REFUSED");
        return;
    }
    let mut run = if root.join("runtime.sqlite3").exists() {
        RunLoop::open(root, spec, inputs, trading).unwrap()
    } else {
        RunLoop::create(root, spec, inputs, trading).unwrap()
    };
    let cut = std::env::var("OA_REPLAY_CUT").unwrap_or_default();
    let barrier =
        |phase: &str, step: u64, n: u64| -> Result<(), onlyalpha_backtest_driver::Error> {
            if cut == format!("{phase}:{step}:{n}") {
                println!("\nBARRIER");
                std::io::stdout().flush().unwrap();
                let mut line = String::new();
                std::io::stdin().lock().read_line(&mut line).unwrap();
                panic!("barrier must be killed");
            }
            Ok(())
        };
    if matches!(
        mode.as_str(),
        "CANCELLED" | "UNKNOWN" | "FAILED" | "INCOMPLETE"
    ) {
        while run.state().unwrap()["account"]["snapshot"]["reserved"] == "0.00" {
            assert!(run.step().unwrap(), "input must reach a real reservation");
        }
        let before = run.state().unwrap();
        assert_ne!(before["account"]["snapshot"]["reserved"], "0.00");
        run.terminate(&mode, Some("EXPLICIT_OPERATOR_OUTCOME"))
            .unwrap();
        assert_eq!(run.state().unwrap(), before);
        let result = run.result().unwrap();
        assert_eq!(result["outcome"]["status"], mode);
        assert_eq!(
            result["status"],
            if mode == "UNKNOWN" {
                "INCOMPLETE"
            } else {
                mode.as_str()
            }
        );
        assert_eq!(result["drained"], false);
        assert_eq!(
            result["execution_result"]["final_account"]["reserved"],
            before["account"]["snapshot"]["reserved"]
        );
        assert_eq!(
            result["execution_result"]["final_account"]["cash"],
            "1000.00"
        );
        assert_eq!(result["execution_result"]["execution"]["trade_count"], 0);
        std::fs::write(
            root.join("result.json"),
            json!({"result":result,"trace":run.trace().unwrap(),"state":run.state().unwrap()})
                .to_string(),
        )
        .unwrap();
        return;
    }
    while run
        .step_observed(&mut |phase, step, n| barrier(phase, step, n))
        .unwrap()
    {}
    let mut ids = vec![];
    run.deliver(|event| {
        ids.push(event["event_id"].clone());
        barrier("DELIVERY", 0, 0)
    })
    .unwrap();
    run.terminate("COMPLETED", None).unwrap();
    std::fs::write(root.join("result.json"),json!({"result":run.result().unwrap(),"trace":run.trace().unwrap(),"events":ids,"state":run.state().unwrap()}).to_string()).unwrap();
}

#[test]
fn foreign_instrument_context_is_refused_before_market_or_order_processing() {
    assert!(
        setup_with_settings(|settings| {
            settings["instrument"]["instrument_id"]["symbol"]["value"] = json!("600001");
            settings["requests"] = json!([]);
        })
        .is_err()
    );
}

#[test]
fn frozen_policy_numeric_bounds_are_checked_before_plugin_work() {
    let error =
        setup_with_settings(|settings| settings["requests"][0]["price"]["value"] = json!("1e100"))
            .err()
            .expect("oversized numeric policy must be rejected");
    assert_eq!(error.0, "EXECUTION_DECIMAL_BOUND");
}
