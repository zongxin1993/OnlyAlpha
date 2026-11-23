use criterion::{BatchSize, BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use onlyalpha_calculation_bridge::native_operators::OperatorCalculation;
use serde_json::json;
use std::{hint::black_box, time::Duration};
fn bench(c: &mut Criterion) {
    for name in ["rolling_mean", "delay"] {
        let op = OperatorCalculation::resolve(
            &format!("onlyalpha.operator.{name}"),
            "2",
            &json!({"period":{"type":"INTEGER","value":20}}),
            &json!({"value":{"source":"bar.close","node_fingerprint":null,"output_name":"close"}}),
        )
        .unwrap();
        let mut g = c.benchmark_group(format!("operator_stream.{name}.push"));
        for n in [16u64, 128, 740] {
            let input = json!({"value":"100.00"});
            let mut check = op.stream().unwrap();
            for _ in 0..n {
                black_box(check.push(&input).unwrap());
            }
            let cp = check.checkpoint().unwrap();
            assert_eq!(
                check.restored_candidate(&cp).unwrap().checkpoint().unwrap(),
                cp
            );
            println!("BENCHMARK_RESULT {name}-{n} {cp}");
            g.throughput(Throughput::Elements(n));
            g.bench_function(BenchmarkId::from_parameter(n), |b| {
                b.iter_batched(
                    || op.stream().unwrap(),
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
