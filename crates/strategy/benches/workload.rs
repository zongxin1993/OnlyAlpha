use criterion::{BatchSize, BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use std::{hint::black_box, time::Duration};
const CORPUS: &str = include_str!("../../../test-data/strategy/decisions-v2.jsonl");
#[path = "../tests/support/mod.rs"]
mod support;
fn bench(c: &mut Criterion) {
    let mut g = c.benchmark_group("executor.process");
    for n in [16u32, 128, 740] {
        let inputs: Vec<_> = (1..=n)
            .map(|i| {
                let bar = support::bar(i);
                let time = support::time(&bar);
                (bar, time, format!("{i:064x}"))
            })
            .collect();
        let mut check = support::executor();
        for (index, (bar, time, digest)) in inputs.iter().enumerate() {
            assert!(
                check
                    .process(bar, time, digest)
                    .unwrap()
                    .decision()
                    .is_some()
                    || index < 2
            );
        }
        let cp = check.capture_checkpoint().unwrap();
        let mut restored = support::executor();
        support::restore(&mut restored, &cp).unwrap();
        assert_eq!(restored.capture_checkpoint().unwrap(), cp);
        println!("BENCHMARK_RESULT {n} {cp}");
        g.throughput(Throughput::Elements(n as u64));
        g.bench_function(BenchmarkId::from_parameter(n), |b| {
            b.iter_batched(
                support::executor,
                |mut owner| {
                    for (bar, time, digest) in &inputs {
                        black_box(owner.process(black_box(bar), time, digest).unwrap());
                    }
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
