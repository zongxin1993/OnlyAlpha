//! 原 Generation 锁的只读诊断。计时/关联不授权、不重试，也不替代 OS flock。
use onlyalpha_observability::{Correlation, Marker, Operation};
use rustix::fd::OwnedFd;
use std::os::fd::{AsFd, BorrowedFd};

fn annotate(operation: &Operation, kind: &'static str, device: u64, inode: u64) {
    operation.span().record("lock_type", kind);
    operation.span().record("device", device);
    operation.span().record("inode", inode);
}
pub(super) fn attempt(kind: &'static str, device: u64, inode: u64) -> Operation {
    let operation = Operation::start("runtime", "generation.lock_attempt", Correlation::default());
    annotate(&operation, kind, device, inode);
    operation.marker(Marker::LockWait);
    operation
}
pub(super) fn correlation(operation: &Operation) -> Correlation {
    operation
        .span()
        .with_subscriber(|(_, dispatch)| {
            tracing::dispatcher::with_default(dispatch, || {
                operation.span().in_scope(Correlation::linked_current)
            })
        })
        .unwrap_or_default()
}
pub(super) fn failed(operation: Operation, errno: i32, contended: bool) {
    operation.span().record("errno", i64::from(errno));
    operation.marker(if contended {
        Marker::LockContention
    } else {
        Marker::LockError
    });
    operation.finish(if contended { "contended" } else { "failed" }, 1, 0);
}
/// 私有单一 fd 所有者；外层 Arc 仍按原生命周期共享整个 RuntimeInputHold。
/// 不复制 lock fd，不在诊断完成时提前解锁。
pub(super) struct Held {
    fd: Option<OwnedFd>,
    operation: Option<Operation>,
}
impl Held {
    pub(super) fn new(
        fd: OwnedFd,
        kind: &'static str,
        device: u64,
        inode: u64,
        correlation: Correlation,
    ) -> Self {
        let operation = Operation::root("runtime", "generation.hold", correlation);
        annotate(&operation, kind, device, inode);
        operation.marker(Marker::LockAcquired);
        Self {
            fd: Some(fd),
            operation: Some(operation),
        }
    }
}
impl AsFd for Held {
    fn as_fd(&self) -> BorrowedFd<'_> {
        self.fd
            .as_ref()
            .expect("owned fd remains live until Drop")
            .as_fd()
    }
}
impl Drop for Held {
    fn drop(&mut self) {
        if let Some(operation) = self.operation.take() {
            // guaranteed hold 区间到这里为止；真正 release 要等原 fd 关闭。
            operation.marker(Marker::LockReleaseBegin);
            drop(self.fd.take());
            operation.marker(Marker::LockReleased);
            operation.finish("released", 0, 0);
        } else {
            drop(self.fd.take());
        }
    }
}
