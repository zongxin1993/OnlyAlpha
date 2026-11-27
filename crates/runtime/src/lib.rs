//! In-memory finite execution sessions and continuous-trading durability ports, outside Trading Kernel.
//!
//! [`OnlyAlphaRuntime`] is the single façade owning quant computation and trading semantics:
//! Research and the Backtest/SIM/LIVE event loop are constructed from the same compiled declarative
//! factor definitions and the same numeric policy (ADR 0152 §2.1, §2.2).
pub mod durability;
pub mod research;
mod session;
pub mod trading;

use onlyalpha_calculation::factor_expr::{FactorExpr, TargetExpr};
use onlyalpha_domain::identifiers::OnlyInstrumentId;
use onlyalpha_execution::Error;
pub use research::{Cohort, ResearchEngine, ResearchPanel, ResearchReport, SeriesStatistics};
pub use session::{
    AppliedEvent, CompletedSession, RunBinding, RunConfiguration, Session, TradingInput,
};
pub use trading::{
    BarOutcome, ExecutionPort, MarketBar, MarketPort, NamedFactorExpr, StrategyDecision,
    StrategyPort, TradingEngine,
};

/// 量化计算与交易语义的统一门面。研究与本机事件主循环共用同一份已编译因子定义，
/// 因此同一因子在向量内核与事件内核上逐点一致，不靠容差掩盖差异。
#[derive(Clone, Debug)]
pub struct OnlyAlphaRuntime {
    research: ResearchEngine,
}

impl OnlyAlphaRuntime {
    pub fn new() -> Result<Self, Error> {
        Ok(Self {
            research: ResearchEngine::new()?,
        })
    }

    /// 只读研究求值：不产出任何可发布事实，也不改变内核状态。
    pub fn run_research(
        &self,
        panel: &ResearchPanel,
        factor: &FactorExpr,
        target: &TargetExpr,
    ) -> Result<ResearchReport, Error> {
        self.research.run(panel, factor, target)
    }

    /// 用调用方给出的同一份因子定义构建事件主循环。
    /// 模式差异由调用方注入的端口承担，门面不携带模式。
    pub fn trading_engine(
        &self,
        instruments: Vec<OnlyInstrumentId>,
        factors: Vec<NamedFactorExpr>,
    ) -> Result<TradingEngine, Error> {
        TradingEngine::new(instruments, factors)
    }
}

// 单一 support 挂载点：与 execution 集成目标共享同一实现，重复挂载由 crate 根吸收。
// support 按父作用域契约读取这两个参考向量，与既有集成目标根作用域写法一致。
#[cfg(test)]
const FIXTURE: &str = include_str!("../../../test-data/execution/domain-inputs.json");
#[cfg(test)]
const SETTLEMENT_FIXTURE: &str = include_str!("../../../test-data/settlement/common-v1.json");
#[cfg(test)]
#[path = "../../execution/tests/support/mod.rs"]
pub(crate) mod support;
