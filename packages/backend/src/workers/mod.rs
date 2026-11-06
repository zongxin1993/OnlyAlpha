pub mod algorithm;
pub mod backtest;
pub mod backtest_result;
pub mod research;
pub mod research_environment;
pub(crate) mod research_service;
pub mod trading_nodes;

#[cfg(test)]
#[path = "../../tests/application/support/backtest_service_assertions.rs"]
pub(crate) mod backtest_service_tests;

pub(crate) mod backtest_service;
pub(crate) mod trading_program;

pub mod backtest_terminal;

pub(crate) mod backtest_worker;

pub mod research_calculations;
