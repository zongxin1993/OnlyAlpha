use criterion::{BatchSize, BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use onlyalpha_operators::algebra::{Decimal, Kernel, Operator, Parameters, Stream};
use std::num::NonZeroUsize;
use std::{hint::black_box, time::Duration};
fn bench(c: &mut Criterion) {
    for (name, operation, ready_at) in [
        ("rolling_mean", Operator::RollingMean, 20),
        ("delay", Operator::Delay, 21),
    ] {
        let kernel = Kernel::new(
            operation,
            Parameters {
                period: Some(NonZeroUsize::new(20).unwrap()),
                ..Default::default()
            },
        )
        .unwrap();
        let input = [Some("100.00".parse::<Decimal>().unwrap())];
        let mut g = c.benchmark_group(format!("decimal_stream.{name}"));
        for n in [16u64, 128, 740] {
            let mut check = Stream::new(kernel.clone()).unwrap();
            let mut last = None;
            for _ in 0..n {
                last = check.push(&input).unwrap();
                if let Some(value) = &last {
                    assert_eq!(value, &"100.00".parse::<Decimal>().unwrap());
                }
            }
            assert_eq!(last.is_some(), n >= ready_at);
            let cp = check.checkpoint();
            let mut restored = Stream::new(kernel.clone()).unwrap();
            restored.restore(cp.clone()).unwrap();
            assert_eq!(restored.checkpoint(), cp);
            let captured: Vec<Vec<Option<String>>> = cp
                .iter()
                .map(|column| {
                    column
                        .iter()
                        .map(|v| v.as_ref().map(ToString::to_string))
                        .collect()
                })
                .collect();
            println!(
                "BENCHMARK_RESULT {name}-{n} {}",
                serde_json::json!({"windows":captured})
            );
            g.throughput(Throughput::Elements(n));
            g.bench_function(BenchmarkId::from_parameter(n), |b| {
                b.iter_batched(
                    || Stream::new(kernel.clone()).unwrap(),
                    |mut stream| {
                        for _ in 0..n {
                            black_box(stream.push(black_box(&input)).unwrap());
                        }
                    },
                    BatchSize::PerIteration,
                )
            });
        }
        g.finish();
    }
}
criterion_group! {name=benches;config=Criterion::default().sample_size(10).warm_up_time(Duration::from_millis(200)).measurement_time(Duration::from_secs(1));targets=bench}
criterion_main!(benches);
