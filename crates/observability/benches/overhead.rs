use criterion::{BatchSize, BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use onlyalpha_observability::{Config, Correlation, Mode, Operation, Session};
use std::{hint::black_box, time::Duration};
use tracing::instrument::WithSubscriber;

struct OwnedSession(Option<Session>);
impl OwnedSession {
    fn new(mode: Mode) -> Self {
        Self(Some(
            Session::new(
                Config::new(mode, "benchmark-process", 1024),
                std::io::sink(),
            )
            .unwrap(),
        ))
    }
    fn dispatch(&self) -> tracing::Dispatch {
        self.0.as_ref().unwrap().dispatch().clone()
    }
}
impl Drop for OwnedSession {
    fn drop(&mut self) {
        let receipt = self.0.take().unwrap().close();
        assert!(receipt.shutdown_complete);
        assert_eq!(receipt.dropped_events, 0);
        assert_eq!(receipt.io_errors, 0);
    }
}
fn work(
    kind: &str,
    n: u64,
    dispatch: &tracing::Dispatch,
    runtime: &tokio::runtime::Runtime,
) -> u64 {
    if kind == "cross_task" {
        return runtime.block_on(async {
            let mut tasks = Vec::new();
            for _ in 0..n {
                tasks.push(tokio::spawn(
                    async {
                        let op = Operation::root("benchmark", "task", Correlation::default());
                        op.finish("ok", 1, 0);
                        1u64
                    }
                    .with_subscriber(dispatch.clone()),
                ));
            }
            let mut completed = 0;
            for task in tasks {
                completed += task.await.unwrap();
            }
            completed
        });
    }
    tracing::dispatcher::with_default(dispatch, || {
        for _ in 0..n {
            match kind {
                "noop" => {
                    black_box(());
                }
                "operation" => {
                    let op = Operation::root("benchmark", "sync", Correlation::default());
                    op.finish("ok", 1, 0);
                }
                "event" => {
                    tracing::info!(target:"onlyalpha.observability", event_kind="summary", module="benchmark", operation="event", work_items=1u64)
                }
                _ => unreachable!(),
            }
        }
        n
    })
}
fn bench(c: &mut Criterion) {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .build()
        .unwrap();
    for (mode_name, mode) in [
        ("off", Mode::Off),
        ("basic", Mode::Basic),
        ("detail", Mode::Detail),
    ] {
        for kind in ["noop", "operation", "event", "cross_task"] {
            let mut group = c.benchmark_group(format!("{mode_name}.{kind}"));
            for n in [1u64, 32, 256] {
                let owner = OwnedSession::new(mode);
                assert_eq!(work(kind, n, &owner.dispatch(), &runtime), n);
                drop(owner);
                println!(
                    "BENCHMARK_RESULT {mode_name}.{kind}.{n} {}",
                    serde_json::json!({"completed":n})
                );
                group.throughput(Throughput::Elements(n));
                group.bench_function(BenchmarkId::from_parameter(n), |b| {
                    b.iter_batched(
                        || OwnedSession::new(mode),
                        |owner| {
                            let completed = work(kind, n, &owner.dispatch(), &runtime);
                            (owner, black_box(completed))
                        },
                        BatchSize::PerIteration,
                    )
                });
            }
            group.finish();
        }
    }
}
criterion_group! {name=benches;config=Criterion::default().sample_size(10).warm_up_time(Duration::from_millis(200)).measurement_time(Duration::from_secs(1));targets=bench}
criterion_main!(benches);
