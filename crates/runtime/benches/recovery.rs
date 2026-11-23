use criterion::{BatchSize, BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use onlyalpha_execution::digest;
use onlyalpha_runtime::Runtime;
use serde_json::json;
use std::{hint::black_box, path::PathBuf, time::Duration};
const FIXTURE: &str = include_str!("../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE: &str = include_str!("../../../test-data/settlement/common-v1.json");
#[path = "../../execution/tests/support/mod.rs"]
mod support;
struct Root(PathBuf);
impl Drop for Root {
    fn drop(&mut self) {
        std::fs::remove_dir_all(&self.0).unwrap();
    }
}
fn bench(c: &mut Criterion) {
    if std::env::args().any(|a| a.starts_with("memory.runtime")) {
        return;
    }
    let mut group = c.benchmark_group("sqlite.runtime");
    for n in [8u64, 32, 128] {
        let path =
            std::env::temp_dir().join(format!("oa-runtime-bench-{}-{n}", std::process::id()));
        std::fs::create_dir(&path).expect("unique benchmark root must not already exist");
        let root = Root(path);
        let config = support::config();
        let artifact = "b".repeat(64);
        let mut original = Runtime::create(&root.0, config.clone(), &artifact).unwrap();
        for input in [
            support::open(1, "BUY"),
            support::stage(2, 1, "UNKNOWN"),
            support::fill(3, 1, "4", "10.00", "1.00"),
        ] {
            original.apply(&input).unwrap();
        }
        let mut valuation_inputs = Vec::new();
        for i in 4..=n + 3 {
            let (components, _) = original.fork_ready().unwrap();
            let cp = components.checkpoint().unwrap();
            let state = original.state().unwrap();
            let input = support::input(
                i,
                "VALUATION",
                json!({"schema_version":1,"valuation":format!("valuation-{i}"),"version":i,"position_evidence":digest(cp["components"][1].to_string().as_bytes()),"economic_version":state["account"]["snapshot"]["economic_version"],"marks":[{"schema_version":1,"instrument":"600000.XSHG","mark":"12.00","source_ref":format!("mark-{i}"),"family":"CLOSED_BAR","version":i,"time":i,"as_of_sequence":i}]}),
            );
            original.apply(&input).unwrap();
            valuation_inputs.push(input);
        }
        original.save_checkpoint().unwrap();
        let expected = original.state().unwrap();
        drop(original);
        let verified = Runtime::open(&root.0, config.clone(), &artifact).unwrap();
        assert_eq!(verified.state().unwrap(), expected);
        println!(
            "BENCHMARK_RESULT {n} {}",
            digest(verified.state().unwrap().to_string().as_bytes())
        );
        drop(verified);
        group.throughput(Throughput::Elements(n + 3));
        group.bench_function(BenchmarkId::new("open_recover_close", n), |b| {
            b.iter_batched(
                || (),
                |()| {
                    let owner =
                        Runtime::open(black_box(&root.0), config.clone(), &artifact).unwrap();
                    black_box(owner);
                },
                BatchSize::PerIteration,
            )
        });
        group.throughput(Throughput::Elements(n));
        let mut serial = 0u64;
        group.bench_function(BenchmarkId::new("apply_valuation_history", n), |b| {
            b.iter_batched(
                || {
                    serial += 1;
                    let path = std::env::temp_dir().join(format!(
                        "oa-runtime-append-{}-{n}-{serial}",
                        std::process::id()
                    ));
                    std::fs::create_dir(&path).unwrap();
                    let root = Root(path);
                    let mut owner = Runtime::create(&root.0, config.clone(), &artifact).unwrap();
                    for input in [
                        support::open(1, "BUY"),
                        support::stage(2, 1, "UNKNOWN"),
                        support::fill(3, 1, "4", "10.00", "1.00"),
                    ] {
                        owner.apply(&input).unwrap();
                    }
                    (owner, root)
                },
                |(mut owner, root)| {
                    for input in &valuation_inputs {
                        owner.apply(black_box(input)).unwrap();
                    }
                    // Runtime closes before its owned temporary root is removed.
                    black_box((owner, root))
                },
                BatchSize::PerIteration,
            )
        });
    }
    group.finish();
}
fn memory_owner() -> onlyalpha_runtime::Session {
    let cfg = onlyalpha_runtime::RunConfiguration::from_record(support::config()).unwrap();
    let binding =
        onlyalpha_runtime::RunBinding::new(&cfg, &"b".repeat(64), &"c".repeat(64), &"d".repeat(64))
            .unwrap();
    onlyalpha_runtime::Session::new(&cfg, &binding).unwrap()
}
fn memory_apply(owner: &mut onlyalpha_runtime::Session, input: serde_json::Value) {
    let event = owner
        .apply(&onlyalpha_runtime::TradingInput::from_record(input).unwrap())
        .unwrap();
    owner.acknowledge(event.sequence()).unwrap();
}
fn memory_inputs() -> Vec<serde_json::Value> {
    vec![
        support::open(1, "BUY"),
        support::stage(2, 1, "UNKNOWN"),
        support::fill(3, 1, "1", "10.00", "1.00"),
        support::fill(4, 1, "3", "10.00", "1.00"),
        support::open(5, "SELL"),
        support::stage(6, 2, "UNKNOWN"),
        support::fill(7, 2, "1", "12.00", "1.00"),
        support::fill(8, 2, "3", "12.00", "1.00"),
    ]
}
fn memory_bench(c: &mut Criterion) {
    use onlyalpha_observability::{Config, Mode, Session};
    let mut group = c.benchmark_group("memory.runtime");
    let inputs = memory_inputs();
    let mut golden = memory_owner();
    for input in &inputs {
        memory_apply(&mut golden, input.clone());
    }
    let expected = golden.finish().unwrap().economic_result().clone();
    assert_eq!(expected["final_account"]["cash"], "1006.00");
    group.bench_function("create", |b| b.iter(|| black_box(memory_owner())));
    group.bench_function("admission.accept", |b| {
        b.iter_batched(
            memory_owner,
            |mut o| {
                memory_apply(&mut o, support::open(1, "BUY"));
                black_box(o)
            },
            BatchSize::PerIteration,
        )
    });
    group.bench_function("apply.fill", |b| {
        b.iter_batched(
            || {
                let mut o = memory_owner();
                memory_apply(&mut o, support::open(1, "BUY"));
                memory_apply(&mut o, support::stage(2, 1, "UNKNOWN"));
                o
            },
            |mut o| {
                memory_apply(&mut o, support::fill(3, 1, "4", "10.00", "1.00"));
                black_box(o)
            },
            BatchSize::PerIteration,
        )
    });
    group.bench_function("finish", |b| {
        b.iter_batched(
            || {
                let mut o = memory_owner();
                for input in &inputs {
                    memory_apply(&mut o, input.clone());
                }
                o
            },
            |o| black_box(o.finish().unwrap()),
            BatchSize::PerIteration,
        )
    });
    for (name, mode) in [("off", Mode::Off), ("detail", Mode::Detail)] {
        let observation = Session::new(
            Config::new(mode, format!("memory-bench-{name}"), 65536),
            std::io::sink(),
        )
        .unwrap();
        let dispatch = observation.dispatch().clone();
        let check = tracing::dispatcher::with_default(&dispatch, || {
            let mut o = memory_owner();
            for input in &inputs {
                memory_apply(&mut o, input.clone());
            }
            o.finish().unwrap()
        });
        assert_eq!(check.economic_result(), &expected);
        group.throughput(Throughput::Elements(inputs.len() as u64));
        group.bench_function(format!("complete/{name}"), |b| {
            b.iter_batched(
                memory_owner,
                |mut o| {
                    tracing::dispatcher::with_default(&dispatch, || {
                        for input in &inputs {
                            memory_apply(&mut o, input.clone());
                        }
                        black_box(o.finish().unwrap())
                    })
                },
                BatchSize::PerIteration,
            )
        });
        let receipt = observation.close();
        assert!(receipt.shutdown_complete);
        assert_eq!(receipt.io_errors, 0);
        assert_eq!(receipt.dropped_events, 0);
    }
    group.finish();
}
criterion_group! { name=benches; config=Criterion::default().sample_size(10).warm_up_time(Duration::from_millis(200)).measurement_time(Duration::from_secs(1)); targets=bench,memory_bench }
criterion_main!(benches);
