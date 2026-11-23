use onlyalpha_observability::{Config, Mode, Session};
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
    let mode_name = std::env::var("OA_BENCH_DIAGNOSTICS").unwrap_or_else(|_| "off".into());
    let mode = match mode_name.as_str() {
        "off" => Mode::Off,
        "detail" => Mode::Detail,
        _ => panic!("unsupported benchmark diagnostics mode"),
    };
    let session = Session::new(
        Config::new(mode, format!("runtime-bench-{}", std::process::id()), 65536),
        std::io::sink(),
    )
    .unwrap();
    let mut expected = None;
    tracing::dispatcher::with_default(session.dispatch(), || {
        for round in 1..=rounds {
            let snapshot = sample(round, "source.read", || {
                onlyalpha_runtime::VerifiedReplaySnapshot::read(&root, config.clone(), artifact)
                    .unwrap()
            });
            assert_eq!(snapshot.binding(), binding);
            assert_eq!(snapshot.refs().len(), 1482);
            assert_eq!(snapshot.records().len(), 326);
            let state = snapshot.state().clone();
            if let Some(previous) = &expected {
                assert_eq!(previous, &state);
            }
            expected = Some(state.clone());
            println!(
                "BENCHMARK_RESULT {round} {}",
                onlyalpha_execution::digest(state.to_string().as_bytes())
            );
            sample(round, "source.steps", || {
                for r in snapshot.refs() {
                    std::hint::black_box(snapshot.read_step(r).unwrap());
                }
            });
            sample(round, "source.verify_cut", || {
                snapshot.verify_cut().unwrap()
            });
        }
    });
    let receipt = session.close();
    assert!(receipt.shutdown_complete && receipt.dropped_events == 0 && receipt.io_errors == 0);
    println!(
        "BENCHMARK_DIAGNOSTICS {}",
        serde_json::json!({"mode":mode_name,"receipt":receipt.record()})
    );
}
