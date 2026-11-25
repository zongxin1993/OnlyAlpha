#[path = "../tests/support/memory_run.rs"]
mod memory_support;
#[path = "../../calculation-bridge/tests/support/memory_signal.rs"]
mod signal_support;

use serde_json::json;
use std::{hint::black_box, time::Instant};

fn sample<T>(round: usize, stage: &str, work: impl FnOnce() -> T) -> T {
    let now = Instant::now();
    let value = work();
    println!(
        "BENCHMARK_SAMPLE {}",
        json!({
            "schema_version": 1,
            "crate": env!("CARGO_PKG_NAME"),
            "round": round,
            "stage": stage,
            "elapsed_ns": now.elapsed().as_nanos().to_string()
        })
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
            let content = json!({
                "signals": result.signals(),
                "calculations": result.calculations(),
                "execution": result.execution_fingerprint(),
                "inputs": result.input_fingerprint()
            });
            let digest = onlyalpha_execution::digest(content.to_string().as_bytes());
            if let Some(previous) = &expected {
                assert_eq!(previous, &digest);
            }
            expected = Some(digest.clone());
            println!(
                "SIGNAL_BENCH {}",
                json!({
                    "rows": rows,
                    "round": round,
                    "setup_ns": setup_ns.to_string(),
                    "execute_ns": execute_ns.to_string(),
                    "finish_ns": finish_ns.to_string(),
                    "signals": result.signals().len(),
                    "calculations": result.calculations().len(),
                    "result": digest
                })
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
                let result = json!({
                    "economic": completed.economic_result(),
                    "curve": completed.close_curve(),
                    "facts": completed.execution_facts(),
                    "signal": completed.raw_signals(),
                    "baseline": completed.baseline()
                });
                let digest = onlyalpha_execution::digest(result.to_string().as_bytes());
                if let Some(previous) = &expected {
                    assert_eq!(previous, &digest);
                }
                expected = Some(digest.clone());
                println!(
                    "MEMORY_BENCH {}",
                    json!({
                        "case": case,
                        "round": round,
                        "rows": rows,
                        "setup_ns": setup_ns.to_string(),
                        "execute_ns": execute_ns.to_string(),
                        "finish_ns": finish_ns.to_string(),
                        "retained_counts": counts,
                        "retained_payload_bytes": bytes,
                        "result": digest
                    })
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
    let rounds = std::env::var("OA_BENCH_ROUNDS").map_or(3, |v| v.parse::<usize>().unwrap());
    assert!((1..=20).contains(&rounds));
    let rows = 256usize;
    let pattern = ["1.00", "3.00", "5.00", "1.00", "0.50", "2.00", "1.00"];
    let prices: Vec<&str> = (0..rows).map(|i| pattern[i % pattern.len()]).collect();
    let mut expected = None;
    for round in 1..=rounds {
        let completed = sample(round, "memory.execute", || {
            let mut run = memory_support::run_prices("1000000.00", false, black_box(&prices));
            for _ in 0..rows {
                run.step().unwrap();
            }
            run.finish().unwrap()
        });
        let result_digest = sample(round, "result.read", || {
            let payload = json!({
                "economic": completed.economic_result(),
                "curve": completed.close_curve(),
                "facts": completed.execution_facts(),
                "signal": completed.raw_signals(),
                "baseline": completed.baseline()
            });
            onlyalpha_execution::digest(payload.to_string().as_bytes())
        });
        if let Some(before) = &expected {
            assert_eq!(before, &result_digest);
        }
        println!("BENCHMARK_RESULT {round} {result_digest}");
        expected = Some(result_digest);
    }
}
