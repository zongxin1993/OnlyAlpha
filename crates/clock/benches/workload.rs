use criterion::{BatchSize, BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use onlyalpha_clock::OnlyVirtualClock;
use std::{hint::black_box, time::Duration};
fn bench(c: &mut Criterion) {
    let mut g = c.benchmark_group("virtual_clock.dispatch");
    for n in [16u64, 128, 740] {
        let prepare = || {
            let mut clock = OnlyVirtualClock::new(0.into());
            for i in 1..=n {
                clock
                    .schedule_at(&format!("timer-{i}"), i.into(), Box::new(|_, _| Ok(())))
                    .unwrap();
            }
            clock
        };
        let mut check = prepare();
        let result = check.advance_to(n.into()).unwrap();
        assert_eq!(result.current_ns, n.into());
        println!(
            "BENCHMARK_RESULT {n} {}",
            serde_json::json!({"current_ns":result.current_ns.to_string(),"timers":n})
        );
        g.throughput(Throughput::Elements(n));
        g.bench_function(BenchmarkId::from_parameter(n), |b| {
            b.iter_batched(
                prepare,
                |mut clock| black_box(clock.advance_to(n.into()).unwrap()),
                BatchSize::PerIteration,
            )
        });
    }
    g.finish();
}
criterion_group! {name=benches;config=Criterion::default().sample_size(10).warm_up_time(Duration::from_millis(200)).measurement_time(Duration::from_secs(1));targets=bench}
criterion_main!(benches);
