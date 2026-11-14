use criterion::{BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use onlyalpha_predicates::decimal_predicate::{DecimalLiteralPredicate, DecimalOperand};
use std::{hint::black_box, time::Duration};
fn bench(c: &mut Criterion) {
    for (operation, literal, expected) in
        [("gt", "0", true), ("ge", "0.001", true), ("le", "0", false)]
    {
        let predicate = DecimalLiteralPredicate::resolve(
            &format!("onlyalpha.predicate.internal.compare.{operation}.decimal.literal"),
            "1",
            DecimalOperand::parse(literal).unwrap(),
            false,
        )
        .unwrap();
        let operands = [Some(DecimalOperand::parse("100.01").unwrap())];
        assert_eq!(predicate.evaluate(&operands).unwrap(), Some(expected));
        assert_eq!(predicate.evaluate(&[None]).unwrap(), None);
        let mut group = c.benchmark_group(format!("decimal_literal.{operation}"));
        for n in [16u64, 128, 740] {
            println!(
                "BENCHMARK_RESULT {operation}-{n} {}",
                serde_json::json!({"value":predicate.evaluate(&operands).unwrap(),"comparisons":n})
            );
            group.throughput(Throughput::Elements(n));
            group.bench_function(BenchmarkId::from_parameter(n), |b| {
                b.iter(|| {
                    for _ in 0..n {
                        black_box(predicate.evaluate(black_box(&operands)).unwrap());
                    }
                })
            });
        }
        group.finish();
    }
}
criterion_group! {name=benches;config=Criterion::default().sample_size(10).warm_up_time(Duration::from_millis(200)).measurement_time(Duration::from_secs(1));targets=bench}
criterion_main!(benches);
