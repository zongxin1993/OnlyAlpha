use crate::{Config, Mode, layer::ObservationLayer};
use serde_json::{Value, json};
use std::{
    io::{self, Write},
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
    time::{Instant, SystemTime, UNIX_EPOCH},
};
use tracing_appender::non_blocking::{ErrorCounter, NonBlockingBuilder, WorkerGuard};
use tracing_subscriber::prelude::*;
#[derive(Default)]
pub(crate) struct Counters {
    pub submitted: AtomicUsize,
    written: AtomicUsize,
    flushed: AtomicUsize,
    errors: AtomicUsize,
}
struct CheckedWriter<W> {
    inner: W,
    counters: Arc<Counters>,
}
impl<W: Write> Write for CheckedWriter<W> {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        match self.inner.write_all(bytes) {
            Ok(()) => {
                self.counters.written.fetch_add(
                    bytes.iter().filter(|b| **b == b'\n').count(),
                    Ordering::Relaxed,
                );
                Ok(bytes.len())
            }
            Err(error) => {
                self.counters.errors.fetch_add(1, Ordering::Relaxed);
                Err(error)
            }
        }
    }
    fn flush(&mut self) -> io::Result<()> {
        match self.inner.flush() {
            Ok(()) => {
                self.counters.flushed.store(
                    self.counters.written.load(Ordering::Relaxed),
                    Ordering::Release,
                );
                Ok(())
            }
            Err(error) => {
                self.counters.errors.fetch_add(1, Ordering::Relaxed);
                Err(error)
            }
        }
    }
}
/// 关闭收据由入口保留到独立诊断 stderr/协调器；缺收据不能证明 JSONL 完整。
pub struct Receipt {
    pub shutdown_complete: bool,
    pub dropped_events: usize,
    pub io_errors: usize,
    process_instance_id: String,
    mono_ns: u64,
}
impl Receipt {
    pub fn record(&self) -> Value {
        json!({"schema_version":1,"event_kind":"session_end", "process_instance_id":self.process_instance_id,
            "pid":std::process::id(),"mono_ns":self.mono_ns,"shutdown_complete":self.shutdown_complete,
            "dropped_events":self.dropped_events,"io_errors":self.io_errors})
    }
}
/// 一个本地 subscriber 和有界 writer。调用方管理全局安装及配置。
/// close 前必须停止并 join 生产者；保留 Span clone 不延迟 operation_end。
pub struct Session {
    dispatch: tracing::Dispatch,
    guard: Option<WorkerGuard>,
    errors: Option<ErrorCounter>,
    counters: Arc<Counters>,
    process_instance_id: String,
    origin: Instant,
}
impl Session {
    pub fn new(config: Config, writer: impl Write + Send + 'static) -> Result<Self, &'static str> {
        if config.process_instance_id.is_empty()
            || config.process_instance_id.len() > 256
            || config.capacity == 0
        {
            return Err("OBSERVABILITY_CONFIG_INVALID");
        }
        let counters = Arc::new(Counters::default());
        let origin = Instant::now();
        let mut result = Self {
            dispatch: tracing::Dispatch::none(),
            guard: None,
            errors: None,
            counters: counters.clone(),
            process_instance_id: config.process_instance_id.clone(),
            origin,
        };
        if config.mode == Mode::Off {
            return Ok(result);
        }
        let (writer, guard) = NonBlockingBuilder::default()
            .buffered_lines_limit(config.capacity)
            .lossy(true)
            .thread_name("onlyalpha-diagnostics")
            .finish(CheckedWriter {
                inner: writer,
                counters: counters.clone(),
            });
        result.errors = Some(writer.error_counter());
        let layer = ObservationLayer {
            mode: config.mode,
            process_instance_id: config.process_instance_id,
            origin,
            writer,
            counters,
            next_operation_id: std::sync::atomic::AtomicU64::new(1),
        };
        layer.emit(json!({"event_kind":"session_start"}));
        result.dispatch = tracing::Dispatch::new(tracing_subscriber::registry().with(layer));
        result.guard = Some(guard);
        Ok(result)
    }
    pub fn dispatch(&self) -> &tracing::Dispatch {
        &self.dispatch
    }
    /// WorkerGuard 上游最多等待入队 100ms、flush 协商 1000ms，不无限 join。
    /// 超时、丢失和 I/O 错误通过收据明示，不修改业务返回值。
    pub fn close(mut self) -> Receipt {
        drop(self.guard.take());
        let dropped_events = self.errors.as_ref().map_or(0, ErrorCounter::dropped_lines);
        let io_errors = self.counters.errors.load(Ordering::Acquire);
        let shutdown_complete = dropped_events == 0
            && io_errors == 0
            && self.counters.submitted.load(Ordering::Acquire)
                == self.counters.flushed.load(Ordering::Acquire);
        Receipt {
            shutdown_complete,
            dropped_events,
            io_errors,
            process_instance_id: self.process_instance_id.clone(),
            mono_ns: nanos(self.origin.elapsed().as_nanos()),
        }
    }
}
pub(crate) fn nanos(value: u128) -> u64 {
    value.min(u64::MAX as u128) as u64
}
pub(crate) fn wall_time() -> u64 {
    nanos(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos(),
    )
}
