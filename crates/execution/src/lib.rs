//! Isolated execution planning and exact committed projection recovery.
//! Storage drivers, provider rules and official Runtime activation remain outside this library.
mod components;
mod model;
mod planning;
pub use components::Components;
pub use model::{Error, Prepared, digest};
mod coordinator;
pub use coordinator::{CommitIntent, Record, Store, coordinate, pending_events, recover};

mod margin;
mod valuation;

mod reconciliation;
pub use reconciliation::LedgerReconciliation;

mod performance;
pub use performance::RuntimePerformance;

mod backtest_result;
pub use backtest_result::BacktestResult;

#[cfg(test)]
extern crate self as onlyalpha_execution;
#[cfg(test)]
mod projection_digest_tests;


#[cfg(test)]
mod valuation_ledger_view_tests;
