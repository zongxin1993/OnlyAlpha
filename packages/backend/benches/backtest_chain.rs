//! 保留回测输入的只读模块基准；不构成发布证明或 Web 验收。
use onlyalpha_backend::workers::{
    backtest::{PreparedNextOpen, terminal_policy},
    backtest_result::ObservedBacktest,
};
use onlyalpha_backtest::{Inputs, RunSpec, TerminalSnapshot};
use onlyalpha_calculation_bridge::fingerprint as digest;
use onlyalpha_domain::time::{OnlyTimestamp, OnlyUtcDateTime};
use onlyalpha_market_crypto::spot::SpotRuleSnapshot;
use onlyalpha_runtime::VerifiedReplaySnapshot;
use onlyalpha_strategy::SourceRevision;
use serde_json::{Value, json};
use std::{path::PathBuf, time::Instant};

fn build_profile() -> &'static str {
    if cfg!(debug_assertions) {
        "dev"
    } else {
        "release"
    }
}
fn measure<T>(round: usize, stage: &str, work: impl FnOnce() -> T) -> T {
    let started = Instant::now();
    let value = work();
    println!(
        "BACKTEST_BENCHMARK {}",
        json!({"round":round,"stage":stage,"elapsed_ns":started.elapsed().as_nanos().to_string()})
    );
    value
}
fn main() {
    assert_eq!(build_profile(), "release", "性能比较必须使用 release");
    let trace_path = PathBuf::from(std::env::var("OA_BENCH_TRACE").unwrap());
    let root = PathBuf::from(std::env::var("OA_BENCH_RUNTIME").unwrap());
    let storage =
        std::env::var("OA_BENCH_STORAGE").expect("明确记录 bind-mount/overlay 等存储环境");
    let rounds = std::env::var("OA_BENCH_ROUNDS").map_or(3, |raw| raw.parse::<usize>().unwrap());
    assert!((1..=20).contains(&rounds));
    let bytes = std::fs::read(&trace_path).unwrap();
    let trace: Value = serde_json::from_slice(&bytes).unwrap();
    let binding = &trace["binding"];
    let configuration = binding["participants"]["policy"]["execution"].clone();
    let artifact = binding["kernel_artifact"].as_str().unwrap();
    let inputs = Inputs::from_record(&trace["inputs"]).unwrap();
    let binary = std::fs::read(std::env::current_exe().unwrap()).unwrap();
    let compiler = std::process::Command::new("rustc")
        .arg("--version")
        .output()
        .unwrap();
    assert!(compiler.status.success());
    println!(
        "BACKTEST_BENCHMARK_META {}",
        json!({"schema_version":1,"scope":"backtest.read","benchmark_binary_sha256":digest(&binary),"compiler":String::from_utf8(compiler.stdout).unwrap().trim(),"os":std::env::consts::OS,"arch":std::env::consts::ARCH,"profile":"release","rounds":rounds,"stage_count":12,"storage":storage,"trace_sha256":digest(&bytes),"configuration_sha256":digest(configuration.to_string().as_bytes()),"kernel_artifact":artifact,"input_pin":inputs.fingerprint(),"bars":inputs.records().len(),"cache":"first sample retained; no cache eviction or automatic warmup"})
    );
    let mut expected = None;
    for round in 1..=rounds {
        let total = Instant::now();
        let inputs = measure(round, "inputs.decode", || {
            Inputs::from_record(&trace["inputs"]).unwrap()
        });
        let prepared = measure(round, "preparation.rebuild", || {
            PreparedNextOpen::new(
                SourceRevision::from_json(
                    &binding["participants"]["program"]["revision"]["product"]["source"]
                        .to_string(),
                    8 * 1024 * 1024,
                )
                .unwrap(),
                inputs,
                SpotRuleSnapshot::from_record(
                    &binding["participants"]["native_policy"]["rules_snapshot"],
                )
                .unwrap(),
                configuration.clone(),
                OnlyTimestamp::from_datetime(
                    "2025-01-03T00:00:00Z".parse::<OnlyUtcDateTime>().unwrap(),
                ),
                OnlyTimestamp::from_datetime(
                    "2025-01-03T12:00:00Z".parse::<OnlyUtcDateTime>().unwrap(),
                ),
            )
            .unwrap()
        });
        let source = measure(round, "runtime.snapshot.read", || {
            VerifiedReplaySnapshot::read(&root, configuration.clone(), artifact).unwrap()
        });
        measure(round, "runtime.steps.read", || {
            for reference in source.refs() {
                assert!(source.read_step(reference).unwrap().is_object());
            }
        });
        measure(round, "runtime.verify_cut", || source.verify_cut().unwrap());
        let record = source.records().last().unwrap().prepared().record();
        let parts: Vec<_> = record["projections"]
            .as_array()
            .unwrap()
            .iter()
            .map(|p| p["result"].clone())
            .collect();
        let checkpoint = json!({"schema_version":1,"config":configuration,"sequence":source.records().len(),"pending":null,"components":parts});
        let _hash = measure(round, "execution.checkpoint.digest", || {
            digest(checkpoint.to_string().as_bytes())
        });
        drop(source);
        let snapshot = measure(round, "terminal.read", || {
            TerminalSnapshot::read(
                &root,
                RunSpec {
                    work_id: binding["work_id"].as_str().unwrap().into(),
                    configuration: configuration.clone(),
                    kernel_artifact: artifact.into(),
                    driver_artifact: binding["driver_artifact"].as_str().unwrap().into(),
                    initial_ns: binding["initial_state"]["clock_ns"]
                        .as_str()
                        .unwrap()
                        .parse()
                        .unwrap(),
                },
                prepared.inputs(),
                terminal_policy,
            )
            .unwrap()
        });
        measure(round, "terminal.verify_cut", || {
            snapshot.verify_cut().unwrap()
        });
        measure(round, "terminal.trace.verify", || {
            snapshot.verify_encoded_trace(&trace).unwrap()
        });
        let result = measure(round, "result.from_terminal", || {
            ObservedBacktest::from_terminal(&prepared, &snapshot).unwrap()
        });
        let fingerprint = measure(round, "result.serialize_digest", || {
            digest(result.result().to_string().as_bytes())
        });
        if let Some(prior) = &expected {
            assert_eq!(prior, &fingerprint, "每轮正式结果必须一致");
        }
        expected = Some(fingerprint);
        println!(
            "BACKTEST_BENCHMARK {}",
            json!({"round":round,"stage":"chain.total","elapsed_ns":total.elapsed().as_nanos().to_string(),"result_sha256":expected})
        );
    }
}
