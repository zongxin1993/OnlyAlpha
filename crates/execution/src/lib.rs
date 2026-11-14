//! Isolated execution planning and exact committed projection recovery.
//! Storage drivers, provider rules and official Runtime activation remain outside this library.
mod canonical_roundtrip;
mod components;
mod model;
mod perpetual;
mod perpetual_fees;
mod planning;
pub use components::Components;
pub use model::{Error, Prepared, digest};
pub use planning::AdmissionPreview;
mod coordinator;
pub use coordinator::{CommitIntent, Record, Store, coordinate, pending_events, recover};

mod margin;
mod valuation;

mod reconciliation;
pub use reconciliation::LedgerReconciliation;

mod performance;
pub use performance::RuntimePerformance;

mod backtest_result;
pub use backtest_result::{BacktestResult, TranscriptDraft};

#[cfg(test)]
extern crate self as onlyalpha_execution;
// 单一 support 挂载点：单元与集成编译各自按 crate 根解析，避免同文件重复 mod。
// support 按父作用域契约读取这两个参考向量，与既有集成目标根作用域写法一致。
#[cfg(test)]
const FIXTURE: &str = include_str!("../../../test-data/execution/domain-inputs.json");
#[cfg(test)]
const SETTLEMENT_FIXTURE: &str = include_str!("../../../test-data/settlement/common-v1.json");
#[cfg(test)]
#[path = "tests/projection_digest_tests.rs"]
mod projection_digest_tests;
#[cfg(test)]
#[path = "../tests/support/mod.rs"]
pub(crate) mod support;

#[cfg(test)]
#[path = "tests/valuation_ledger_view_tests.rs"]
mod valuation_ledger_view_tests;

pub use onlyalpha_domain::market_source::OnlyMarketSourceCut as MarketSourceCut;

pub use perpetual::funding_boundary;

mod projection_data;
pub use projection_data::{FundingDraft, ProjectionData};
