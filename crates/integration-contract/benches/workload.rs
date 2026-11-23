use criterion::{BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use onlyalpha_integration_contract::IntegrationTypeId;
use std::{hint::black_box, time::Duration};
fn bench(c: &mut Criterion) {
    assert_eq!(
        IntegrationTypeId::new("binance.spot.market_data")
            .unwrap()
            .value(),
        "binance.spot.market_data"
    );
    assert!(IntegrationTypeId::new("latest").is_err());
    let mut g = c.benchmark_group("integration_type.parse");
    for n in [16u64, 128, 740] {
        println!(
            "BENCHMARK_RESULT {n} {}",
            IntegrationTypeId::new("binance.spot.market_data")
                .unwrap()
                .value()
        );
        g.throughput(Throughput::Elements(n));
        g.bench_function(BenchmarkId::from_parameter(n), |b| {
            b.iter(|| {
                for _ in 0..n {
                    black_box(
                        IntegrationTypeId::new(black_box("binance.spot.market_data")).unwrap(),
                    );
                }
            })
        });
    }
    g.finish();
}
criterion_group! {name=benches;config=Criterion::default().sample_size(10).warm_up_time(Duration::from_millis(200)).measurement_time(Duration::from_secs(1));targets=bench}
criterion_main!(benches);
