use criterion::{BatchSize, BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use onlyalpha_execution::digest;
use onlyalpha_runtime::durability::{RecoveryFacts, TradingBinding};
use onlyalpha_runtime::{RunBinding, RunConfiguration, Session, TradingInput};
use serde_json::{Value, json};
use std::{hint::black_box, time::Duration};

const FIXTURE: &str = include_str!("../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE: &str = include_str!("../../../test-data/settlement/common-v1.json");
#[path = "../../execution/tests/support/mod.rs"]
mod support;

fn memory_owner() -> Session {
    let cfg = RunConfiguration::from_record(support::config()).unwrap();
    let binding = RunBinding::new(&cfg, &"b".repeat(64), &"c".repeat(64), &"d".repeat(64)).unwrap();
    Session::new(&cfg, &binding).unwrap()
}
fn memory_apply(owner: &mut Session, input: Value) {
    let event = owner
        .apply(&TradingInput::from_record(input).unwrap())
        .unwrap();
    owner.acknowledge(event.sequence()).unwrap();
}
fn memory_inputs() -> Vec<Value> {
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
fn as_sim(input: Value) -> Value {
    let mut input = input;
    input["runtime_kind"] = json!("SIM");
    if let Some(proofs) = input["payload"].as_object_mut() {
        for key in ["fees", "settlement", "valuation"] {
            let Some(proof) = proofs.get_mut(key).and_then(|p| p.as_object_mut()) else {
                continue;
            };
            let Some(scope) = proof.get_mut("scope").and_then(|s| s.as_object_mut()) else {
                continue;
            };
            scope.insert("runtime_kind".into(), json!("SIM"));
            proof.remove("source_digest");
            let digest = digest(Value::Object(proof.clone()).to_string().as_bytes());
            proof.insert("source_digest".into(), json!(digest));
        }
    }
    input
}
fn recovery_history(rounds: u64) -> (TradingBinding, Vec<onlyalpha_execution::Record>) {
    let mut configuration = support::config();
    configuration["runtime_kind"] = json!("SIM");
    let binding = TradingBinding::new(
        RunConfiguration::from_record(configuration).unwrap(),
        &"b".repeat(64),
    )
    .unwrap();
    let mut facts =
        RecoveryFacts::from_records(&binding, binding.fingerprint(), 0, Vec::new()).unwrap();
    let mut rows = Vec::new();
    for round in 0..rounds {
        let base = round * 8;
        for input in [
            support::open(base + 1, "BUY"),
            support::stage(base + 2, 1, "UNKNOWN"),
            support::fill(base + 3, 1, "1", "10.00", "1.00"),
            support::fill(base + 4, 1, "3", "10.00", "1.00"),
            support::open(base + 5, "SELL"),
            support::stage(base + 6, 2, "UNKNOWN"),
            support::fill(base + 7, 2, "1", "12.00", "1.00"),
            support::fill(base + 8, 2, "3", "12.00", "1.00"),
        ] {
            let prepared = facts.prepare(&as_sim(input)).unwrap();
            rows.push(record(&prepared));
            facts = restore(&binding, &rows);
        }
    }
    (binding, rows)
}
fn record(
    facts: &onlyalpha_runtime::durability::PreparedTradingFacts,
) -> onlyalpha_execution::Record {
    onlyalpha_execution::Record::decode(&json!({
        "schema_version": 1,
        "prepared": facts.prepared().record(),
        "ready": true,
        "delivered": false
    }))
    .unwrap()
}
fn restore(binding: &TradingBinding, rows: &[onlyalpha_execution::Record]) -> RecoveryFacts {
    RecoveryFacts::from_records(
        binding,
        binding.fingerprint(),
        rows.len() as u64,
        rows.to_vec(),
    )
    .unwrap()
}
fn memory_bench(c: &mut Criterion) {
    use onlyalpha_observability::{Config, Mode, Session as Observation};
    let mut group = c.benchmark_group("memory.runtime");
    let inputs = memory_inputs();
    let mut golden = memory_owner();
    for input in &inputs {
        memory_apply(&mut golden, input.clone());
    }
    let expected = golden.finish().unwrap().economic_result().clone();
    assert_eq!(expected["final_account"]["cash"], "1006.00");
    println!(
        "BENCHMARK_RESULT memory {}",
        digest(expected.to_string().as_bytes())
    );
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
        let observation = Observation::new(
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
fn recovery_bench(c: &mut Criterion) {
    let mut group = c.benchmark_group("durability.recovery");
    for rounds in [1u64, 4, 16] {
        let (binding, rows) = recovery_history(rounds);
        let verified = restore(&binding, &rows);
        println!(
            "BENCHMARK_RESULT {} {}",
            rows.len(),
            digest(verified.state().unwrap().to_string().as_bytes())
        );
        group.throughput(Throughput::Elements(rows.len() as u64));
        group.bench_function(BenchmarkId::new("recover", rows.len()), |b| {
            b.iter(|| black_box(restore(black_box(&binding), black_box(&rows))))
        });
    }
    group.finish();
}
criterion_group! { name=benches; config=Criterion::default().sample_size(10).warm_up_time(Duration::from_millis(200)).measurement_time(Duration::from_secs(1)); targets=memory_bench,recovery_bench }
criterion_main!(benches);
