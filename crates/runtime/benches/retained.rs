use onlyalpha_observability::{Config, Mode, Session as Observation};
use onlyalpha_runtime::durability::{RecoveryFacts, TradingBinding};
use onlyalpha_runtime::{RunBinding, RunConfiguration, Session, TradingInput};
use serde_json::{Value, json};
use std::{hint::black_box, time::Instant};

const FIXTURE: &str = include_str!("../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE: &str = include_str!("../../../test-data/settlement/common-v1.json");
#[path = "../../execution/tests/support/mod.rs"]
mod support;

fn sample<T>(round: usize, stage: &str, work: impl FnOnce() -> T) -> T {
    let now = Instant::now();
    let value = work();
    println!(
        "BENCHMARK_SAMPLE {}",
        json!({"schema_version":1,"crate":env!("CARGO_PKG_NAME"),"round":round,"stage":stage,"elapsed_ns":now.elapsed().as_nanos().to_string()})
    );
    value
}

fn session() -> Session {
    let config = RunConfiguration::from_record(support::config()).unwrap();
    let binding =
        RunBinding::new(&config, &"b".repeat(64), &"c".repeat(64), &"d".repeat(64)).unwrap();
    Session::new(&config, &binding).unwrap()
}

fn inputs() -> Vec<Value> {
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
            let digest = onlyalpha_execution::digest(Value::Object(proof.clone()).to_string().as_bytes());
            proof.insert("source_digest".into(), json!(digest));
        }
    }
    input
}

fn execute() -> onlyalpha_runtime::CompletedSession {
    let mut owner = session();
    for input in inputs() {
        let event = owner
            .apply(&TradingInput::from_record(input).unwrap())
            .unwrap();
        owner.acknowledge(event.sequence()).unwrap();
    }
    owner.finish().unwrap()
}

fn main() {
    let rounds = std::env::var("OA_BENCH_ROUNDS").map_or(3, |v| v.parse::<usize>().unwrap());
    assert!((1..=20).contains(&rounds));
    let mode_name = std::env::var("OA_BENCH_DIAGNOSTICS").unwrap_or_else(|_| "off".into());
    let mode = match mode_name.as_str() {
        "off" => Mode::Off,
        "detail" => Mode::Detail,
        _ => panic!("unsupported benchmark diagnostics mode"),
    };
    let observation = Observation::new(
        Config::new(mode, format!("runtime-bench-{}", std::process::id()), 65536),
        std::io::sink(),
    )
    .unwrap();
    let mut expected = None;
    tracing::dispatcher::with_default(observation.dispatch(), || {
        for round in 1..=rounds {
            let completed = sample(round, "memory.execute", execute);
            let result = sample(round, "result.read", || completed.economic_result().clone());
            assert_eq!(result["final_account"]["cash"], "1006.00");
            let digest = onlyalpha_execution::digest(result.to_string().as_bytes());
            if let Some(previous) = &expected {
                assert_eq!(previous, &digest);
            }
            expected = Some(digest.clone());
            println!("BENCHMARK_RESULT {round} {digest}");
            sample(round, "durability.recovery", || {
                let mut configuration = support::config();
                configuration["runtime_kind"] = json!("SIM");
                let binding = TradingBinding::new(
                    RunConfiguration::from_record(configuration).unwrap(),
                    &"b".repeat(64),
                )
                .unwrap();
                let mut facts = RecoveryFacts::from_records(
                    &binding,
                    binding.fingerprint(),
                    0,
                    Vec::new(),
                )
                .unwrap();
                let mut rows = Vec::new();
                for input in inputs() {
                    let prepared = facts.prepare(&as_sim(input)).unwrap();
                    let row = onlyalpha_execution::Record::decode(&json!({
                        "schema_version": 1,
                        "prepared": prepared.prepared().record(),
                        "ready": true,
                        "delivered": false
                    }))
                    .unwrap();
                    rows.push(row);
                    facts = RecoveryFacts::from_records(
                        &binding,
                        binding.fingerprint(),
                        rows.len() as u64,
                        rows.clone(),
                    )
                    .unwrap();
                }
                black_box(facts.state().unwrap())
            });
        }
    });
    let receipt = observation.close();
    assert!(receipt.shutdown_complete && receipt.dropped_events == 0 && receipt.io_errors == 0);
    println!(
        "BENCHMARK_DIAGNOSTICS {}",
        json!({"mode":mode_name,"receipt":receipt.record()})
    );
}
