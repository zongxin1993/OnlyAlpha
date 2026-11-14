use criterion::{BatchSize, BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use std::{hint::black_box, time::Duration};
const RAW: &str = include_str!("../../../test-data/backtest-benchmarks/replay.json");
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBar, time::OnlyTimestamp};
use onlyalpha_market_data::state::*;
use std::sync::Arc;
fn bench(c: &mut Criterion) {
    let v: serde_json::Value = serde_json::from_str(RAW).unwrap();
    let bars: Vec<_> = v["inputs"]["records"]
        .as_array()
        .unwrap()
        .iter()
        .map(|r| Arc::new(OnlyBar::from_record(&r["bar"]).unwrap()))
        .collect();
    let create = || {
        OnlyMarketDataState::new(
            OnlyMarketDataStateScope::new(
                "benchmark-engine".parse().unwrap(),
                "benchmark-runtime".parse().unwrap(),
            ),
            OnlyMarketDataStateConfig { history_limit: 128 },
        )
        .unwrap()
    };
    let mut g = c.benchmark_group("state.apply_closed");
    for n in [16usize, 128, 740] {
        let apply = |owner: &mut OnlyMarketDataState| {
            for bar in &bars[..n] {
                black_box(
                    owner
                        .apply_closed(
                            &[Arc::clone(bar)],
                            bar.bar_type(),
                            OnlyTimestamp::from_datetime(*bar.ts_event()),
                            vec![],
                        )
                        .unwrap(),
                );
            }
        };
        let mut check = create();
        apply(&mut check);
        let cp = check.capture_checkpoint();
        let mut restored = create();
        restored.restore_checkpoint(&cp).unwrap();
        assert_eq!(restored.capture_checkpoint(), cp);
        println!("BENCHMARK_RESULT {n} {cp:?}");
        g.throughput(Throughput::Elements(n as u64));
        g.bench_function(BenchmarkId::from_parameter(n), |b| {
            b.iter_batched(
                create,
                |mut owner| {
                    apply(&mut owner);
                    black_box(owner)
                },
                BatchSize::PerIteration,
            )
        });
    }
    g.finish();
}
criterion_group! {name=benches;config=Criterion::default().sample_size(10).warm_up_time(Duration::from_millis(200)).measurement_time(Duration::from_secs(1));targets=bench}
criterion_main!(benches);
