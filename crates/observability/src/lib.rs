//! 诊断基础设施；不读取环境、不安装全局 subscriber，不参与正式事实。
mod context;
mod layer;
mod output;
pub use context::{Correlation, Marker, Operation};
pub use output::{Receipt, Session};

/// 同步基础设施边界的测量；不改变闭包返回值。
pub fn measure<T, E>(
    module: &'static str,
    operation: &'static str,
    correlation: Correlation,
    work: impl FnOnce() -> Result<T, E>,
) -> Result<T, E> {
    measure_counted(module, operation, correlation, 0, 0, work)
}
/// 记录已有输入计数，不为观测再编码或再次读取输入。
pub fn measure_counted<T, E>(
    module: &'static str,
    operation: &'static str,
    correlation: Correlation,
    items: u64,
    bytes: u64,
    work: impl FnOnce() -> Result<T, E>,
) -> Result<T, E> {
    if !tracing::enabled!(target:"onlyalpha.observability",tracing::Level::INFO) {
        return work();
    }
    let op = Operation::start(module, operation, correlation);
    let result = op.span().in_scope(work);
    op.finish(if result.is_ok() { "ok" } else { "failed" }, items, bytes);
    result
}

/// 后端显式选择的诊断粒度。Basic 只保留摘要和异常。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Mode {
    Off,
    Basic,
    Detail,
}
/// 每次进程启动使用不同的 process_instance_id；capacity 是队列行数上限。
pub struct Config {
    pub mode: Mode,
    pub process_instance_id: String,
    pub capacity: usize,
}
impl Config {
    pub fn new(mode: Mode, process_instance_id: impl Into<String>, capacity: usize) -> Self {
        Self {
            mode,
            process_instance_id: process_instance_id.into(),
            capacity,
        }
    }
}
