use criterion::{BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use std::{hint::black_box, time::Duration};
const RAW: &str = include_str!("../../../test-data/backtest-benchmarks/replay.json");
use onlyalpha_metadata_json::{canonical_json, fingerprint};
fn bench(c: &mut Criterion) {
    let v: serde_json::Value = serde_json::from_str(RAW).unwrap();
    let mut g = c.benchmark_group("canonical_metadata");
    for n in [16usize, 128, 740] {
        let raw = serde_json::to_string(&v["inputs"]["records"].as_array().unwrap()[..n]).unwrap();
        let canonical = canonical_json(&raw, 8 * 1024 * 1024).unwrap();
        assert_eq!(
            canonical_json(&canonical, 8 * 1024 * 1024).unwrap(),
            canonical
        );
        println!(
            "BENCHMARK_RESULT {n} {}",
            fingerprint(&raw, 8 * 1024 * 1024).unwrap()
        );
        g.throughput(Throughput::Bytes(raw.len() as u64));
        g.bench_function(BenchmarkId::from_parameter(n), |b| {
            b.iter(|| black_box(fingerprint(black_box(&raw), 8 * 1024 * 1024).unwrap()))
        });
    }
    g.finish();
}
criterion_group! {name=benches;config=Criterion::default().sample_size(10).warm_up_time(Duration::from_millis(200)).measurement_time(Duration::from_secs(1));targets=bench}
criterion_main!(benches);
