use criterion::{BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use std::{hint::black_box, time::Duration};
const RAW: &str = include_str!("../../../test-data/backtest-benchmarks/replay.json");
use onlyalpha_market_data_construction::{OnlyConstructionGraph, OnlyConstructionPlan};
fn bench(c: &mut Criterion) {
    let v: serde_json::Value = serde_json::from_str(RAW).unwrap();
    let raw = &v["binding"]["participants"]["pipeline"]["sources"][0]["graph"];
    let graph = OnlyConstructionGraph::from_record(raw).unwrap();
    let mut g = c.benchmark_group("provider_graph.compile");
    for n in [1u64, 8, 32] {
        println!(
            "BENCHMARK_RESULT {n} {:?}",
            OnlyConstructionPlan::compile(&graph, "benchmark-source").unwrap()
        );
        g.throughput(Throughput::Elements(n));
        g.bench_function(BenchmarkId::from_parameter(n), |b| {
            b.iter(|| {
                for _ in 0..n {
                    black_box(
                        OnlyConstructionPlan::compile(black_box(&graph), "benchmark-source")
                            .unwrap(),
                    );
                }
            })
        });
    }
    g.finish();
}
criterion_group! {name=benches;config=Criterion::default().sample_size(10).warm_up_time(Duration::from_millis(200)).measurement_time(Duration::from_secs(1));targets=bench}
criterion_main!(benches);
