//! In-memory finite execution sessions and continuous-trading durability ports, outside Trading Kernel.
pub mod durability;
pub mod research;
mod session;

pub use research::{Cohort, ResearchEngine, ResearchPanel, ResearchReport, SeriesStatistics};
pub use session::{
    AppliedEvent, CompletedSession, RunBinding, RunConfiguration, Session, TradingInput,
};

// 单一 support 挂载点：与 execution 集成目标共享同一实现，重复挂载由 crate 根吸收。
// support 按父作用域契约读取这两个参考向量，与既有集成目标根作用域写法一致。
#[cfg(test)]
const FIXTURE: &str = include_str!("../../../test-data/execution/domain-inputs.json");
#[cfg(test)]
const SETTLEMENT_FIXTURE: &str = include_str!("../../../test-data/settlement/common-v1.json");
#[cfg(test)]
#[path = "../../execution/tests/support/mod.rs"]
pub(crate) mod support;
