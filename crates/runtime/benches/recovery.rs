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
criterion_group! { name=benches; config=Criterion::default().sample_size(10).warm_up_time(Duration::from_millis(200)).measurement_time(Duration::from_secs(1)); targets=bench }
criterion_main!(benches);
