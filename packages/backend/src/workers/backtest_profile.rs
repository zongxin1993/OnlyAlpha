//! 回测基础设施的同步测量适配；配置与全局订阅器由后端 bootstrap 持有。
//! 异步操作必须用 Instrument，不能把同步闭包包在 block_on 外侧。
use onlyalpha_observability::Correlation;

pub(crate) fn measure<T, E>(
    run: &str,
    stage: &'static str,
    work: impl FnOnce() -> Result<T, E>,
) -> Result<T, E> {
    if !tracing::enabled!(target:"onlyalpha.observability",tracing::Level::INFO) {
        return work();
    }
    onlyalpha_observability::measure(
        "backend",
        stage,
        Correlation {
            run_id: Some(run.into()),
            ..Default::default()
        },
        work,
    )
}
/// 仅用于同步阻塞闭包；闭包内含 block_on 时必须显式 Instrument future。
pub(crate) fn spawn_blocking<F, T>(work: F) -> tokio::task::JoinHandle<T>
where
    F: FnOnce() -> T + Send + 'static,
    T: Send + 'static,
{
    let span = tracing::Span::current();
    let dispatch = tracing::dispatcher::get_default(Clone::clone);
    tokio::task::spawn_blocking(move || {
        tracing::dispatcher::with_default(&dispatch, || span.in_scope(work))
    })
}

/// 仅诊断资源区间，不拥有或释放业务 guard。
/// 必须在真实 MutexGuard 之前声明，begin_release_marker 在 guard 之后声明。
/// Rust 局部变量反向析构：pre-marker → 原 guard → post-marker。
pub(crate) struct HoldEnd {
    operation: Option<onlyalpha_observability::Operation>,
}
pub(crate) struct HoldBegin(tracing::Span);
impl HoldEnd {
    pub(crate) fn pending() -> Self {
        Self { operation: None }
    }
    pub(crate) fn acquired(&mut self, kind: &'static str, name: &'static str) {
        use onlyalpha_observability::{Marker, Operation};
        let op = Operation::root("backend", name, Correlation::linked_current());
        op.span().record("lock_type", kind);
        op.marker(Marker::LockAcquired);
        self.operation = Some(op);
    }
    pub(crate) fn begin_release_marker(&self) -> HoldBegin {
        HoldBegin(
            self.operation
                .as_ref()
                .map_or_else(tracing::Span::none, |op| op.span().clone()),
        )
    }
}
impl Drop for HoldBegin {
    fn drop(&mut self) {
        onlyalpha_observability::Marker::LockReleaseBegin.emit_in(&self.0);
    }
}
impl Drop for HoldEnd {
    fn drop(&mut self) {
        if let Some(operation) = self.operation.take() {
            operation.marker(onlyalpha_observability::Marker::LockReleased);
            operation.finish("released", 0, 0);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use onlyalpha_observability::{Config, Mode, Session};
    #[tokio::test(flavor = "current_thread")]
    async fn writer_markers_surround_original_mutex_guard_drop() {
        use std::sync::{Arc, Mutex};
        use tracing::instrument::WithSubscriber;
        use tracing::{
            Event, Subscriber,
            field::{Field, Visit},
        };
        use tracing_subscriber::{Layer, layer::Context, prelude::*};
        #[derive(Default)]
        struct Kind(String);
        impl Visit for Kind {
            fn record_str(&mut self, field: &Field, value: &str) {
                if field.name() == "event_kind" {
                    self.0 = value.into();
                }
            }
            fn record_debug(&mut self, _: &Field, _: &dyn std::fmt::Debug) {}
        }
        struct Probe {
            writer: Arc<tokio::sync::Mutex<()>>,
            events: Arc<Mutex<Vec<(String, bool)>>>,
        }
        impl<S: Subscriber> Layer<S> for Probe {
            fn on_event(&self, event: &Event<'_>, _: Context<'_, S>) {
                let mut kind = Kind::default();
                event.record(&mut kind);
                if matches!(
                    kind.0.as_str(),
                    "lock_acquired" | "lock_release_begin" | "lock_released"
                ) {
                    self.events
                        .lock()
                        .unwrap()
                        .push((kind.0, self.writer.try_lock().is_ok()));
                }
            }
        }
        let writer = Arc::new(tokio::sync::Mutex::new(()));
        let events = Arc::new(Mutex::new(Vec::new()));
        let dispatch = tracing::Dispatch::new(tracing_subscriber::registry().with(Probe {
            writer: writer.clone(),
            events: events.clone(),
        }));
        async {
            let mut post_release = HoldEnd::pending();
            let _original_guard = writer.lock().await;
            post_release.acquired("writer", "writer.hold");
            let _pre_release = post_release.begin_release_marker();
            assert!(writer.try_lock().is_err());
        }
        .with_subscriber(dispatch)
        .await;
        assert_eq!(
            *events.lock().unwrap(),
            vec![
                ("lock_acquired".into(), false),
                ("lock_release_begin".into(), false),
                ("lock_released".into(), true)
            ]
        );
    }
    #[test]
    fn measurement_preserves_original_results_and_parent_after_error_and_panic() {
        let session = Session::new(
            Config::new(Mode::Detail, "profile-test", 128),
            std::io::sink(),
        )
        .unwrap();
        tracing::dispatcher::with_default(session.dispatch(), || {
            assert!(tracing::Span::current().id().is_none());
            assert_eq!(
                measure("run", "outer", || {
                    let parent = tracing::Span::current().id();
                    assert!(parent.is_some());
                    assert_eq!(
                        measure("run", "inner", || Err::<(), _>("ORIGINAL")),
                        Err("ORIGINAL")
                    );
                    assert_eq!(tracing::Span::current().id(), parent);
                    assert!(
                        std::panic::catch_unwind(|| measure::<(), ()>("run", "panic", || panic!(
                            "ORIGINAL"
                        )))
                        .is_err()
                    );
                    assert_eq!(tracing::Span::current().id(), parent);
                    Ok::<_, ()>(42)
                }),
                Ok(42)
            );
            assert!(tracing::Span::current().id().is_none());
        });
        assert!(session.close().shutdown_complete);
    }
}
