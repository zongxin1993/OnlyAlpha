use criterion::{BatchSize, BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use onlyalpha_fee::{Catalog, Manager, digest};
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
const REPLAY: &str = include_str!("../../../test-data/backtest-benchmarks/replay.json");
fn bench(c: &mut Criterion) {
    let replay: Value = serde_json::from_str(REPLAY).unwrap();
    let execution = &replay["binding"]["participants"]["policy"]["execution"];
    let catalog =
        Catalog::new(replay["binding"]["participants"]["native_policy"]["fee_catalog"].clone())
            .unwrap();
    let (cluster, profile) = execution["profiles"]
        .as_object()
        .unwrap()
        .iter()
        .next()
        .unwrap();
    let subject = serde_json::json!({"engine":execution["engine"],"runtime":execution["runtime"],"account":execution["account"],"broker":"BINANCE_SPOT_SIMULATION","gateway":execution["gateway"],"generation":execution["generation"],"runtime_kind":"BACKTEST","cluster":cluster,"revision":profile["revision"],"instrument":"BTCUSDT.BINANCE","market":"BINANCE_SPOT_MODEL","venue":"BINANCE","instrument_class":"CASH","currency":execution["currency"],"side":"BUY","offset":"OPEN"});
    let basis = serde_json::json!({"quantity":"0.01","notional":"921.1842","contracts":null,"currency":"USDT"});
    let quote = || {
        catalog
            .quote_one_fill(subject.clone(), 1, 1u64, basis.clone(), None)
            .unwrap()
    };
    assert_eq!(quote().record()["charges"], "0.92118420");
    println!("BENCHMARK_RESULT quote {}", quote().fingerprint());
    let mut quotes = c.benchmark_group("catalog.quote_one_fill");
    for n in [16u64, 128, 740] {
        quotes.throughput(Throughput::Elements(n));
        quotes.bench_function(BenchmarkId::from_parameter(n), |b| {
            b.iter(|| {
                for _ in 0..n {
                    black_box(quote());
                }
            })
        });
    }
    quotes.finish();
    let mut group = c.benchmark_group("checkpoint");
    for (size, raw) in INPUTS {
        let v: Value = serde_json::from_str(raw).unwrap();
        let cp = &v["execution"]["components"][5]["fee_authority"];
        let create = || {
            Manager::new(
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
        let first = &cp["history"][0]["input"];
        let mut fresh = create();
        let expected = fresh.apply_admitted_target(first).unwrap().record();
        println!("BENCHMARK_RESULT apply-{size} {}", digest(&expected));
        let before = verified.checkpoint();
        assert_eq!(
            verified.apply_admitted_target(first).unwrap().record(),
            expected
        );
        assert_eq!(verified.checkpoint(), before);
        group.throughput(Throughput::Elements(1));
        group.bench_function(BenchmarkId::new("apply_target", size), |b| {
            b.iter_batched(
                create,
                |mut owner| {
                    black_box(owner.apply_admitted_target(black_box(first)).unwrap());
                    black_box(owner)
                },
                BatchSize::PerIteration,
            )
        });
        group.bench_function(BenchmarkId::new("duplicate_target", size), |b| {
            b.iter_batched(
                || verified.clone(),
                |mut owner| {
                    black_box(owner.apply_admitted_target(black_box(first)).unwrap());
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
