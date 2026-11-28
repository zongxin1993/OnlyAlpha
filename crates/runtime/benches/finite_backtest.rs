#[path = "../tests/support/memory_run.rs"]
mod memory_support;
#[path = "../tests/support/memory_signal.rs"]
mod signal_support;

use onlyalpha_runtime::{
    OnlyAlphaRuntime,
    trading::backtest::{CompletedBacktest, FrozenReplay},
};
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

fn encode_result(result: &CompletedBacktest) -> Vec<u8> {
    let venue = result.venue();
    let payload = json!({
        "source_rows": result.source_rows(),
        "run": result.binding().record(), "execution": result.execution_binding().record(),
        "program": result.program(), "signal_execution": result.signal_execution_fingerprint(),
        "signals": result.raw_signals(), "signal_receipts": result.signal_receipts(),
        "signal_checkpoint": result.signal_checkpoint(), "economic": result.economic_result(),
        "account_checkpoint": result.account_checkpoint(), "facts": result.execution_facts(),
        "curve": result.close_curve(), "equity": result.equity_points(), "baseline": result.baseline(),
        "venue_source": venue.source_fingerprint(), "protocol": venue.protocol(),
        "protocol_records": venue.protocol_records().iter().map(|row| row.record()).collect::<Vec<_>>(),
        "source_trace": venue.source_trace().iter().map(|row| row.record()).collect::<Vec<_>>()
    });
    serde_json::to_vec(&payload).unwrap()
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
                let fixture =
                    memory_support::parts(cash, denied, &prices, signal_support::executor());
                let replay = FrozenReplay::new(
                    &fixture.panel,
                    fixture.panel.snapshot(),
                    fixture.panel.content_digest(),
                )
                .unwrap();
                let runtime = OnlyAlphaRuntime::new().unwrap();
                let mut task = runtime
                    .backtest(
                        replay,
                        fixture.spec,
                        &fixture.inputs,
                        fixture.executor,
                        Box::new(fixture.policy),
                        fixture.venue,
                    )
                    .unwrap();
                let setup_ns = setup.elapsed().as_nanos();
                let execute = Instant::now();
                task.run(|_, _| Ok(())).unwrap();
                let execute_ns = execute.elapsed().as_nanos();
                let finish = Instant::now();
                let completed = task.finish().unwrap();
                let finish_ns = finish.elapsed().as_nanos();
                let bytes = encode_result(&completed);
                let digest = onlyalpha_execution::digest(&bytes);
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
                        "signal_count": completed.raw_signals().len(),
                        "event_count": completed.execution_facts().len(),
                        "close_count": completed.close_curve().len(),
                        "encoded_result_bytes": bytes.len(),
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
            memory_support::run_prices("1000000.00", false, black_box(&prices))
        });
        let result_digest = sample(round, "result.read", || {
            onlyalpha_execution::digest(&encode_result(&completed))
        });
        if let Some(before) = &expected {
            assert_eq!(before, &result_digest);
        }
        println!("BENCHMARK_RESULT {round} {result_digest}");
        expected = Some(result_digest);
    }
}
