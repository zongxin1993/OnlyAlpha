use criterion::{BatchSize, BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use onlyalpha_execution::{AdmissionPreview, Components, digest};
use serde_json::Value;
use std::{hint::black_box, time::Duration};
const FIXTURE: &str = include_str!("../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE: &str = include_str!("../../../test-data/settlement/common-v1.json");
#[path = "../tests/support/mod.rs"]
mod support;
const INPUTS: [(&str, &str); 3] = [
    (
        "small",
        include_str!("../../../test-data/backtest-benchmarks/small.json"),
    ),
    (
        "medium",
        include_str!("../../../test-data/backtest-benchmarks/medium.json"),
    ),
    (
        "large",
        include_str!("../../../test-data/backtest-benchmarks/large.json"),
    ),
];
fn bench(c: &mut Criterion) {
    let mut g = c.benchmark_group("components");
    for (size, raw) in INPUTS {
        let v: Value = serde_json::from_str(raw).unwrap();
        let cp = &v["execution"];
        let config = &cp["config"];
        let bytes = cp.to_string();
        let hash = digest(bytes.as_bytes());
        let create = || Components::new(config.clone()).unwrap();
        let mut check = create();
        check.restore(cp, &hash).unwrap();
        assert_eq!(check.checkpoint().unwrap(), *cp);
        println!(
            "BENCHMARK_RESULT {size} {}",
            digest(check.checkpoint().unwrap().to_string().as_bytes())
        );
        g.throughput(Throughput::Elements(1));
        g.bench_function(BenchmarkId::new("new", size), |b| {
            b.iter_batched(|| (), |_| black_box(create()), BatchSize::PerIteration)
        });
        g.throughput(Throughput::Bytes(bytes.len() as u64));
        g.bench_function(BenchmarkId::new("capture_warm", size), |b| {
            b.iter(|| black_box(check.checkpoint().unwrap()))
        });
        g.bench_function(BenchmarkId::new("encode", size), |b| {
            b.iter(|| black_box(serde_json::to_vec(black_box(cp)).unwrap()))
        });
        g.bench_function(BenchmarkId::new("digest", size), |b| {
            b.iter(|| black_box(digest(black_box(bytes.as_bytes()))))
        });

        g.bench_function(BenchmarkId::new("restore", size), |b| {
            b.iter_batched(
                create,
                |mut owner| {
                    owner.restore(black_box(cp), &hash).unwrap();
                    black_box(owner)
                },
                BatchSize::PerIteration,
            )
        });
    }
    g.finish();
    for rejected in [false, true] {
        let mut configuration = support::config();
        if rejected {
            configuration["initial_cash"] = serde_json::json!("1.00");
            configuration["capitals"]["cluster"] = serde_json::json!("1.00");
        }
        let checkpoint = Components::new(configuration.clone())
            .unwrap()
            .checkpoint()
            .unwrap();
        let input = support::open(1, "BUY");
        let expected =
            Components::admission_rejection(&configuration, &checkpoint, &input).unwrap();
        assert_eq!(expected.is_some(), rejected);
        println!("BENCHMARK_RESULT admission-{rejected} {expected:?}");
        let mut preview = AdmissionPreview::default();
        assert_eq!(
            preview.check(&configuration, &checkpoint, &input).unwrap(),
            expected
        );
        let mut g = c.benchmark_group(if rejected {
            "admission.reject"
        } else {
            "admission.accept"
        });
        for n in [1u64, 8, 32] {
            g.throughput(Throughput::Elements(n));
            g.bench_function(BenchmarkId::new("cold", n), |b| {
                b.iter(|| {
                    for _ in 0..n {
                        black_box(
                            Components::admission_rejection(
                                &configuration,
                                &checkpoint,
                                black_box(&input),
                            )
                            .unwrap(),
                        );
                    }
                })
            });
            g.bench_function(BenchmarkId::new("reused", n), |b| {
                b.iter(|| {
                    for _ in 0..n {
                        black_box(
                            preview
                                .check(&configuration, &checkpoint, black_box(&input))
                                .unwrap(),
                        );
                    }
                })
            });
        }
        g.finish();
    }
    let h = support::Harness::new(support::config()).unwrap();
    let input = support::open(1, "BUY");
    h.prepare(&input).unwrap();
    let mut g = c.benchmark_group("prepare_admit.same_prefix");
    for n in [1u64, 8, 32] {
        g.throughput(Throughput::Elements(n));
        g.bench_function(BenchmarkId::from_parameter(n), |b| {
            b.iter(|| {
                for _ in 0..n {
                    black_box(h.prepare(black_box(&input)).unwrap());
                }
            })
        });
    }
    g.finish();
}
criterion_group! {name=benches;config=Criterion::default().sample_size(10).warm_up_time(Duration::from_millis(200)).measurement_time(Duration::from_secs(1));targets=bench}
criterion_main!(benches);
