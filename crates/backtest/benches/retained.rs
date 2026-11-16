#[path = "../tests/support/memory_run.rs"]
mod memory_support;
#[path = "../../calculation-bridge/tests/support/memory_signal.rs"]
mod signal_support;
struct Policy(onlyalpha_market_crypto::spot::SpotSimulationPolicy);
impl onlyalpha_backtest::NextOpenPolicy for Policy {
    fn analytical_entry_quote(
        &self,
        p: &onlyalpha_domain::value::OnlyPrice,
        q: &onlyalpha_domain::value::OnlyQuantity,
        c: &Value,
    ) -> Result<Value, onlyalpha_backtest::Error> {
        self.0
            .analytical_entry_quote(p, q, c)
            .map_err(|e| onlyalpha_backtest::Error(e.to_string()))
    }
    fn binding(&self) -> Value {
        self.0.binding()
    }
    fn admission(
        &self,
        o: &Value,
        p: &onlyalpha_domain::value::OnlyPrice,
        c: &Value,
    ) -> Result<Value, onlyalpha_backtest::Error> {
        self.0
            .admission(o, p, c)
            .map_err(|e| onlyalpha_backtest::Error(e.to_string()))
    }
    fn fill(
        &self,
        o: &Value,
        p: &onlyalpha_domain::value::OnlyPrice,
        q: &onlyalpha_domain::value::OnlyQuantity,
        c: &Value,
    ) -> Result<Value, onlyalpha_backtest::Error> {
        self.0
            .fill(o, p, q, c)
            .map_err(|e| onlyalpha_backtest::Error(e.to_string()))
    }
}
fn resolve(
    settings: &Value,
    native: &Value,
) -> Result<Box<dyn onlyalpha_backtest::NextOpenPolicy>, onlyalpha_backtest::Error> {
    let rules =
        onlyalpha_market_crypto::spot::SpotRuleSnapshot::from_record(&native["rules_snapshot"])
            .map_err(|e| onlyalpha_backtest::Error(e.to_string()))?;
    let p = onlyalpha_market_crypto::spot::SpotSimulationPolicy::new(
        rules,
        settings["execution"].clone(),
    )
    .map_err(|e| onlyalpha_backtest::Error(e.to_string()))?;
    let mut original = native.clone();
    original.as_object_mut().unwrap().remove("execution_model");
    assert_eq!(p.binding(), original);
    Ok(Box::new(Policy(p)))
}
use serde_json::Value;
use std::{path::PathBuf, time::Instant};
const RAW: &str = include_str!("../../../test-data/backtest-benchmarks/replay.json");
fn sample<T>(round: usize, stage: &str, work: impl FnOnce() -> T) -> T {
    let now = Instant::now();
    let value = work();
    println!(
        "BENCHMARK_SAMPLE {}",
        serde_json::json!({"schema_version":1,"crate":env!("CARGO_PKG_NAME"),"round":round,"stage":stage,"elapsed_ns":now.elapsed().as_nanos().to_string()})
    );
    value
}
fn signal_bench() {
    for rows in [64usize, 128, 256, 1024] {
        let mut expected = None;
        for round in 1..=3 {
            let setup = Instant::now();
            let bars = (1..=rows)
                .map(|i| {
                    signal_support::bar(
                        i as u64,
                        ["1.00", "3.00", "5.00", "1.00", "0.50", "2.00", "1.00"][(i - 1) % 7],
                    )
                })
                .collect::<Vec<_>>();
            let mut run =
                onlyalpha_strategy::ResearchRun::new(signal_support::executor(), bars).unwrap();
            let setup_ns = setup.elapsed().as_nanos();
            let execute = Instant::now();
            for _ in 0..rows {
                run.step().unwrap();
            }
            let execute_ns = execute.elapsed().as_nanos();
            let finish = Instant::now();
            let result = run.finish().unwrap();
            let finish_ns = finish.elapsed().as_nanos();
            let content = serde_json::json!({"signals":result.signals(),"calculations":result.calculations(),"execution":result.execution_fingerprint(),"inputs":result.input_fingerprint()});
            let digest = onlyalpha_execution::digest(content.to_string().as_bytes());
            if let Some(previous) = &expected {
                assert_eq!(previous, &digest);
            }
            expected = Some(digest.clone());
            println!(
                "SIGNAL_BENCH {}",
                serde_json::json!({"rows":rows,"round":round,"setup_ns":setup_ns.to_string(),"execute_ns":execute_ns.to_string(),"finish_ns":finish_ns.to_string(),"signals":result.signals().len(),"calculations":result.calculations().len(),"result":digest})
            );
        }
    }
}
fn memory_bench() {
    let rounds = 3;
    for (case, denied, cash) in [
        ("no_trade", false, "1000000.00"),
        ("active", false, "1000000.00"),
        ("model_rejection", true, "1000000.00"),
        ("risk_rejection", false, "1.00"),
    ] {
        for rows in [64usize, 128, 256, 1024] {
            let pattern = ["1.00", "3.00", "5.00", "1.00", "0.50", "2.00", "1.00"];
            let prices = (0..rows)
                .map(|i| {
                    if case == "no_trade" {
                        "1.00"
                    } else {
                        pattern[i % pattern.len()]
                    }
                })
                .collect::<Vec<_>>();
            let mut expected = None;
            for round in 1..=rounds {
                let setup = Instant::now();
                let mut run = memory_support::run_prices(cash, denied, &prices);
                let setup_ns = setup.elapsed().as_nanos();
                let execute = Instant::now();
                for _ in 0..rows {
                    run.step().unwrap();
                }
                let execute_ns = execute.elapsed().as_nanos();
                let counts = run.retained_counts();
                let bytes = run.retained_payload_bytes();
                let finish = Instant::now();
                let completed = run.finish().unwrap();
                let finish_ns = finish.elapsed().as_nanos();
                let result = serde_json::json!({"economic":completed.economic_result(),"curve":completed.close_curve(),"facts":completed.execution_facts(),"signal":completed.raw_signals(),"baseline":completed.baseline()});
                let digest = onlyalpha_execution::digest(result.to_string().as_bytes());
                if let Some(previous) = &expected {
                    assert_eq!(previous, &digest);
                }
                expected = Some(digest.clone());
                println!(
                    "MEMORY_BENCH {}",
                    serde_json::json!({"case":case,"round":round,"rows":rows,"setup_ns":setup_ns.to_string(),"execute_ns":execute_ns.to_string(),"finish_ns":finish_ns.to_string(),"retained_counts":counts,"retained_payload_bytes":bytes,"result":digest})
                );
            }
        }
    }
}
fn main() {
    if std::env::args().any(|a| a == "--signal") {
        return signal_bench();
    }
    if std::env::args().any(|a| a == "--memory") {
        return memory_bench();
    }
    let root = PathBuf::from(
        std::env::var("OA_BENCH_RUNTIME")
            .expect("retained bench requires OA_BENCH_RUNTIME; see BENCHMARK.md"),
    );
    let v: Value = serde_json::from_str(RAW).unwrap();
    let binding = &v["binding"];
    let config = binding["participants"]["policy"]["execution"].clone();
    let artifact = binding["kernel_artifact"].as_str().unwrap();
    let rounds = std::env::var("OA_BENCH_ROUNDS").map_or(3, |v| v.parse::<usize>().unwrap());
    assert!((1..=20).contains(&rounds));
    let inputs = onlyalpha_backtest::Inputs::from_record(&v["inputs"]).unwrap();
    let mut expected = None;
    for round in 1..=rounds {
        let snapshot = sample(round, "terminal.read", || {
            onlyalpha_backtest::TerminalSnapshot::read(
                &root,
                onlyalpha_backtest::RunSpec {
                    work_id: binding["work_id"].as_str().unwrap().into(),
                    configuration: config.clone(),
                    kernel_artifact: artifact.into(),
                    driver_artifact: binding["driver_artifact"].as_str().unwrap().into(),
                    initial_ns: binding["initial_state"]["clock_ns"]
                        .as_str()
                        .unwrap()
                        .parse()
                        .unwrap(),
                },
                &inputs,
                resolve,
            )
            .unwrap()
        });
        sample(round, "terminal.verify_cut", || {
            snapshot.verify_cut().unwrap()
        });
        let result = snapshot.result().clone();
        if let Some(before) = &expected {
            assert_eq!(before, &result);
        }
        println!(
            "BENCHMARK_RESULT {round} {}",
            onlyalpha_execution::digest(result.to_string().as_bytes())
        );
        expected = Some(result);
    }
}
