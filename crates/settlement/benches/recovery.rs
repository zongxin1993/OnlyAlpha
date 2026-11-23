use criterion::{BatchSize, BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use onlyalpha_settlement::{Authority, digest};
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
        let cp = &v["execution"]["components"][5]["settlement_authority"];
        let create = || {
            Authority::new(
                cp["config"].clone(),
                cp["capacity"].as_u64().unwrap() as usize,
            )
            .unwrap()
        };
        let hash = digest(cp);
        let bytes = cp.to_string().len();
        let mut verified = create();
        verified.restore(cp, &hash).unwrap();
        assert_eq!(verified.checkpoint(), *cp);
        println!("BENCHMARK_RESULT {size} {}", digest(&verified.checkpoint()));
        group.throughput(Throughput::Bytes(bytes as u64));
        group.throughput(Throughput::Elements(1));
        group.bench_function(BenchmarkId::new("new", size), |b| {
            b.iter_batched(|| (), |_| black_box(create()), BatchSize::PerIteration)
        });
        group.throughput(Throughput::Bytes(bytes as u64));
        group.bench_function(BenchmarkId::new("restore", size), |b| {
            b.iter_batched(
                create,
                |mut owner| {
                    owner.restore(black_box(cp), &hash).unwrap();
                    black_box(owner)
                },
                BatchSize::PerIteration,
            )
        });
        group.bench_function(BenchmarkId::new("capture_warm", size), |b| {
            b.iter(|| black_box(verified.checkpoint()))
        });
        assert!(create().restore(cp, &"f".repeat(64)).is_err());
        let order = cp["orders"].as_object().unwrap().values().next().unwrap();
        let admit = |owner: &mut Authority| {
            owner
                .admit_whole_fill_order(
                    order["scope"].clone(),
                    order["order"].as_str().unwrap(),
                    order["side"].as_str().unwrap(),
                    order["quantity"].as_str().unwrap(),
                    order["precision"].as_u64().unwrap() as u8,
                    &order["fill_contract"],
                )
                .unwrap()
        };
        let mut fresh = create();
        admit(&mut fresh);
        assert_eq!(
            fresh.checkpoint()["orders"][order["order"].as_str().unwrap()],
            *order
        );
        let before = verified.checkpoint();
        admit(&mut verified);
        assert_eq!(verified.checkpoint(), before);
        group.throughput(Throughput::Elements(1));
        group.bench_function(BenchmarkId::new("admit_whole_fill", size), |b| {
            b.iter_batched(
                create,
                |mut owner| {
                    admit(&mut owner);
                    black_box(owner)
                },
                BatchSize::PerIteration,
            )
        });
        group.bench_function(BenchmarkId::new("duplicate_admission", size), |b| {
            b.iter_batched(
                || verified.clone(),
                |mut owner| {
                    admit(&mut owner);
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
