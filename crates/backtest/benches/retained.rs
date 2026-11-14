struct Policy(onlyalpha_market_crypto::spot::SpotSimulationPolicy);
impl onlyalpha_backtest::NextOpenPolicy for Policy {
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
fn main() {
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
