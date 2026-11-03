//! Application responsibilities of the backend product.
pub mod chart;
pub mod command;
pub mod frozen_strategy;
pub mod integration_catalog;
pub mod integration_commands;
pub mod integration_configuration;
pub mod integration_resolver;
pub mod market_product;
pub mod private_assets;
pub mod private_strategy;
pub mod qualification_policy;
pub mod source_access;
pub mod strategy_projection;
pub mod watchlists;
pub mod workspace;

pub mod factor_content;

pub mod factor_proposals;
pub mod research_factor;
pub mod research_statistics;

pub mod research_dataset;

pub mod research_admission;
pub mod research_specification;

pub mod research_novelty;
pub mod research_run;

pub mod factor_studies;
pub mod research_run_execution;

pub mod strategy_research;

pub mod backtest_run;
pub mod backtest_preparation;
pub(crate) mod strategy_validation;

pub mod strategy_promotion;
pub mod qualification;

#[cfg(test)]
#[path = "../../tests/application/backtest_preparation.rs"]
mod backtest_preparation_tests;

pub(crate) mod manual_backtest_context;
