//! 原 WriteGate 外侧的诊断。事件在原 gate 锁释放后发出，不参与权限判断。
use onlyalpha_observability::{Correlation, Operation};
use std::{io, task::Poll};
#[derive(Default)]
pub(super) struct SocketTrace {
    write: Option<Operation>,
    flush: Option<Operation>,
    shutdown: Option<Operation>,
}
fn begin(slot: &mut Option<Operation>, id: u64, name: &'static str) {
    if slot.is_none() && tracing::enabled!(target:"onlyalpha.observability",tracing::Level::INFO) {
        *slot = Some(Operation::root(
            "transport",
            name,
            Correlation {
                request_id: Some(format!("connection:{id}")),
                ..Default::default()
            },
        ));
    }
}
fn end<T>(
    slot: &mut Option<Operation>,
    result: &Poll<io::Result<T>>,
    bytes: impl FnOnce(&T) -> u64,
) {
    if let Poll::Ready(result) = result
        && let Some(operation) = slot.take()
    {
        if let Err(error) = result
            && let Some(errno) = error.raw_os_error()
        {
            operation.span().record("errno", errno);
        }
        operation.finish(
            if result.is_ok() { "ok" } else { "failed" },
            1,
            result.as_ref().map_or(0, bytes),
        );
    }
}
impl SocketTrace {
    pub(super) fn begin_write(&mut self, id: u64) {
        begin(&mut self.write, id, "http.socket.write");
    }
    pub(super) fn end_write(&mut self, result: &Poll<io::Result<usize>>) {
        end(&mut self.write, result, |n| *n as u64);
    }
    pub(super) fn begin_flush(&mut self, id: u64) {
        begin(&mut self.flush, id, "http.socket.flush");
    }
    pub(super) fn end_flush(&mut self, result: &Poll<io::Result<()>>) {
        end(&mut self.flush, result, |_| 0);
    }
    pub(super) fn begin_shutdown(&mut self, id: u64) {
        begin(&mut self.shutdown, id, "http.socket.shutdown");
    }
    pub(super) fn end_shutdown(&mut self, result: &Poll<io::Result<()>>) {
        end(&mut self.shutdown, result, |_| 0);
    }
}
impl Drop for SocketTrace {
    fn drop(&mut self) {
        for slot in [&mut self.write, &mut self.flush, &mut self.shutdown] {
            if let Some(operation) = slot.take() {
                operation.finish("dropped", 0, 0);
            }
        }
    }
}

/// 应用响应还会经过 ingress 的超时与权限处理；这里记录实际返回给 Hyper 的状态。
/// 只拥有诊断操作，不拥有业务响应、连接、permit 或权限证明。
pub(super) struct ResponseTrace(Option<Operation>);
impl ResponseTrace {
    pub(super) fn begin(id: u64) -> Self {
        let mut operation = None;
        begin(&mut operation, id, "http.ingress.dispatch");
        Self(operation)
    }
    pub(super) fn span(&self) -> tracing::Span {
        self.0
            .as_ref()
            .map_or_else(tracing::Span::none, |op| op.span().clone())
    }
    pub(super) fn ready(mut self, status: http::StatusCode) {
        if let Some(operation) = self.0.take() {
            operation.span().with_subscriber(|(_,dispatch)|tracing::dispatcher::with_default(dispatch,||operation.span().in_scope(|| {
                tracing::info!(target:"onlyalpha.observability",event_kind="summary",outcome=status.as_str());
            })));
            operation.finish(
                if status.is_server_error() {
                    "failed"
                } else {
                    "ready"
                },
                1,
                0,
            );
        }
    }
}
impl Drop for ResponseTrace {
    fn drop(&mut self) {
        if let Some(operation) = self.0.take() {
            operation.finish("dropped", 0, 0);
        }
    }
}
