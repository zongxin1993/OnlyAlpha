use criterion::{BatchSize, BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use onlyalpha_calculation::{ExecutionBinding, ExecutionCursor};
use std::{hint::black_box, time::Duration};
fn bench(c: &mut Criterion) {
    let binding = ExecutionBinding::new(
        [
            "a".repeat(64),
            "b".repeat(64),
            "c".repeat(64),
            "d".repeat(64),
            "e".repeat(64),
            "f".repeat(64),
        ],
        "runtime/strategy/node",
    )
    .unwrap();
    let digest = "1".repeat(64);
    let mut g = c.benchmark_group("cursor.prepare_commit");
    for n in [1usize, 32, 256] {
        let times: Vec<_> = (1..=n).map(|n| n.to_string()).collect();
        let refs: Vec<_> = times.iter().map(String::as_str).collect();
        let mut check = ExecutionCursor::new(binding.clone());
        let p = check.prepare(&refs, &digest).unwrap();
        check
            .commit(&p, &binding, 1, &refs, n as u64, &digest)
            .unwrap();
        assert_eq!(check.revision(), 1);
        println!("BENCHMARK_RESULT {n} {}", check.capture());
        g.throughput(Throughput::Elements(n as u64));
        g.bench_function(BenchmarkId::from_parameter(n), |b| {
            b.iter_batched(
                || ExecutionCursor::new(binding.clone()),
                |mut cursor| {
                    let p = cursor.prepare(black_box(&refs), &digest).unwrap();
                    cursor
                        .commit(&p, &binding, 1, &refs, n as u64, &digest)
                        .unwrap();
                    black_box(cursor)
                },
                BatchSize::PerIteration,
            )
        });
    }
    g.finish();
}
criterion_group! {name=benches;config=Criterion::default().sample_size(10).warm_up_time(Duration::from_millis(200)).measurement_time(Duration::from_secs(1));targets=bench}
criterion_main!(benches);
