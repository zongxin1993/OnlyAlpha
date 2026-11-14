use criterion::{BatchSize, BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use onlyalpha_position::{Manager, digest};
use serde_json::Value;
use std::{hint::black_box, time::Duration};
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
    let mut group = c.benchmark_group("checkpoint");
    for (size, raw) in INPUTS {
        let v: Value = serde_json::from_str(raw).unwrap();
        let cp = &v["execution"]["components"][1];
        let config = &cp["config"];
        let bytes = serde_json::to_vec(cp).unwrap();
        let hash = digest(&bytes);
        let create = || Manager::new(config.clone()).unwrap();
        let mut verified = create();
        verified.restore(&bytes, &hash).unwrap();
        assert_eq!(verified.checkpoint().unwrap().0, bytes);
        println!(
            "BENCHMARK_RESULT {size} {}",
            digest(&verified.checkpoint().unwrap().0)
        );
        group.throughput(Throughput::Bytes(bytes.len() as u64));
        group.bench_with_input(BenchmarkId::new("restore", size), &bytes, |b, bytes| {
            b.iter_batched(
                create,
                |mut owner| {
                    owner.restore(black_box(bytes), &hash).unwrap();
                    black_box(owner)
                },
                BatchSize::PerIteration,
            )
        });
        group.throughput(Throughput::Elements(1));
        group.bench_function(BenchmarkId::new("new", size), |b| {
            b.iter_batched(|| (), |_| black_box(create()), BatchSize::PerIteration)
        });
        group.throughput(Throughput::Bytes(bytes.len() as u64));
        group.bench_function(BenchmarkId::new("capture_warm", size), |b| {
            b.iter(|| black_box(verified.checkpoint().unwrap()))
        });
        group.throughput(Throughput::Elements(1));
        let first = &cp["journal"][0];
        let mut first_owner = create();
        let empty = first_owner.checkpoint().unwrap();
        let first_result = first_owner.apply(first).unwrap();
        println!("BENCHMARK_RESULT first-{size} {first_result:?}");
        assert_ne!(first_owner.checkpoint().unwrap(), empty);
        let before = verified.checkpoint().unwrap();
        let duplicate_result = verified.apply(first).unwrap();
        println!("BENCHMARK_RESULT duplicate-{size} {duplicate_result:?}");
        assert_eq!(verified.checkpoint().unwrap(), before);
        group.bench_function(BenchmarkId::new("first_apply", size), |b| {
            b.iter_batched(
                create,
                |mut owner| {
                    black_box(owner.apply(black_box(first)).unwrap());
                    black_box(owner)
                },
                BatchSize::PerIteration,
            )
        });
        group.bench_function(BenchmarkId::new("duplicate_apply", size), |b| {
            b.iter_batched(
                || verified.clone(),
                |mut owner| {
                    black_box(owner.apply(black_box(first)).unwrap());
                    black_box(owner)
                },
                BatchSize::PerIteration,
            )
        });
        group.throughput(Throughput::Bytes(bytes.len() as u64));
        let mut damaged = bytes.clone();
        damaged[0] = b'!';
        assert!(create().restore(&damaged, &hash).is_err());
        group.bench_function(BenchmarkId::new("reject_digest", size), |b| {
            b.iter_batched(
                create,
                |mut owner| {
                    assert!(owner.restore(black_box(&damaged), &hash).is_err());
                    black_box(owner)
                },
                BatchSize::PerIteration,
            )
        });
    }
    group.finish();
}
criterion_group! {name=benches;config=Criterion::default().sample_size(10).warm_up_time(Duration::from_millis(200)).measurement_time(Duration::from_secs(1));targets=bench}
criterion_main!(benches);
