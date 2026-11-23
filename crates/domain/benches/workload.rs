use criterion::{BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use std::{hint::black_box, time::Duration};
const RAW: &str = include_str!("../../../test-data/backtest-benchmarks/replay.json");
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBar};
fn bench(c: &mut Criterion) {
    let v: serde_json::Value = serde_json::from_str(RAW).unwrap();
    let records = v["inputs"]["records"].as_array().unwrap();
    let mut g = c.benchmark_group("bar.decode");
    for n in [16usize, 128, 740] {
        let rows: Vec<_> = records[..n].iter().map(|r| r["bar"].clone()).collect();
        for r in &rows {
            assert_eq!(OnlyBar::from_record(r).unwrap().to_record(), *r);
        }
        println!(
            "BENCHMARK_RESULT {n} {}",
            serde_json::to_string(&rows).unwrap()
        );
        g.throughput(Throughput::Elements(n as u64));
        g.bench_with_input(BenchmarkId::from_parameter(n), &rows, |b, rows| {
            b.iter(|| {
                for r in rows {
                    black_box(OnlyBar::from_record(black_box(r)).unwrap());
                }
            })
        });
    }
    g.finish();
}
criterion_group! {name=benches;config=Criterion::default().sample_size(10).warm_up_time(Duration::from_millis(200)).measurement_time(Duration::from_secs(1));targets=bench}
criterion_main!(benches);
