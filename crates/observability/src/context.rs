use tracing::Span;
/// 有限的资源生命周期标记；不允许任意事件名或动态正文。
#[derive(Clone, Copy)]
pub enum Marker {
    LockWait,
    LockAcquired,
    LockReleaseBegin,
    LockReleased,
    LockContention,
    LockError,
}
impl Marker {
    /// 对指定 Span 的原 subscriber 发标记；即使调用任务已离开原 Dispatch 也不串链。
    pub fn emit_in(self, span: &Span) {
        let kind = match self {
            Self::LockWait => "lock_wait",
            Self::LockAcquired => "lock_acquired",
            Self::LockReleaseBegin => "lock_release_begin",
            Self::LockReleased => "lock_released",
            Self::LockContention => "lock_contention",
            Self::LockError => "lock_error",
        };
        in_origin(span, || {
            if matches!(self, Self::LockContention | Self::LockError) {
                tracing::warn!(target:"onlyalpha.observability",event_kind=kind,outcome="failed");
            } else {
                tracing::info!(target:"onlyalpha.observability",event_kind=kind);
            }
        });
    }
}
/// 仅供诊断的因果关联，不进入 checkpoint、正式请求或身份摘要。
#[derive(Clone, Default)]
pub struct Correlation {
    pub request_id: Option<String>,
    pub command_id: Option<String>,
    pub run_id: Option<String>,
    pub attempt: Option<u64>,
    pub links: Option<String>,
}
impl Correlation {
    /// 当前 tracing 作用域的诊断关联快照；独立资源根以 links 关联，不伪造父操作。
    pub fn linked_current() -> Self {
        crate::layer::linked_current()
    }
}
/// 显式 operation 生命周期，finish 不等待其他 Span handle 释放。
/// future 使用 Instrument；同步阻塞闭包用 in_scope，不跨 await 持有 enter guard。
#[must_use]
pub struct Operation {
    span: Span,
    finished: bool,
}
impl Operation {
    pub fn marker(&self, marker: Marker) {
        marker.emit_in(&self.span);
    }
    pub fn start(module: &'static str, operation: &'static str, correlation: Correlation) -> Self {
        Self::create(module, operation, correlation, false)
    }
    /// 后台任务独立建根，通过 links/command/run 关联已结束的 HTTP 请求。
    pub fn root(module: &'static str, operation: &'static str, correlation: Correlation) -> Self {
        Self::create(module, operation, correlation, true)
    }
    fn create(module: &'static str, operation: &'static str, c: Correlation, root: bool) -> Self {
        let request_id = c.request_id.as_deref().unwrap_or("");
        let command_id = c.command_id.as_deref().unwrap_or("");
        let run_id = c.run_id.as_deref().unwrap_or("");
        let links = c.links.as_deref().unwrap_or("");
        let attempt = c.attempt;
        let span = if root {
            tracing::info_span!(target: "onlyalpha.observability", parent: None, "operation",
                module, operation, request_id, command_id, run_id, links, attempt,
                lock_type=tracing::field::Empty,device=tracing::field::Empty,inode=tracing::field::Empty,errno=tracing::field::Empty)
        } else {
            tracing::info_span!(target: "onlyalpha.observability", "operation",
                module, operation, request_id, command_id, run_id, links, attempt,
                lock_type=tracing::field::Empty,device=tracing::field::Empty,inode=tracing::field::Empty,errno=tracing::field::Empty)
        };
        in_origin(
            &span,
            || tracing::info!(target: "onlyalpha.observability", event_kind = "operation_start"),
        );
        Self {
            span,
            finished: false,
        }
    }
    pub fn span(&self) -> &Span {
        &self.span
    }
    pub fn finish(mut self, outcome: &'static str, work_items: u64, bytes: u64) {
        in_origin(&self.span, || {
            tracing::info!(target: "onlyalpha.observability",
            event_kind = "operation_end", outcome, work_items, bytes)
        });
        self.finished = true;
    }
}
impl Drop for Operation {
    fn drop(&mut self) {
        if !self.finished {
            in_origin(&self.span, || {
                tracing::info!(target: "onlyalpha.observability",
                event_kind = "operation_abandoned", outcome = "incomplete")
            });
        }
    }
}

// Span::enter 只切换该 subscriber 的当前 span；不会替事件切换 default Dispatch。
// future 取消/跨任务释放可能已经离开 WithSubscriber，因此显式复用 Span 的原 Dispatch。
fn in_origin(span: &Span, emit: impl FnOnce()) {
    span.with_subscriber(|(_, dispatch)| {
        tracing::dispatcher::with_default(dispatch, || span.in_scope(emit));
    });
}
