//! Persistence responsibilities of the backend product.
pub mod authority_session;
pub mod credential_postgres;
pub mod integration_postgres;
pub mod market_data;
pub mod market_data_wal;
pub mod postgres;
pub mod schema;
pub mod watchlist_postgres;
pub mod workspace_postgres;

pub mod private_factor_postgres;

pub mod factor_proposals;
pub mod factor_studies;

pub mod research_dataset;

pub mod research_runtime;

pub mod research_execution;
pub mod research_novelty;

pub mod research_evidence;
pub mod research_submission;

pub mod research_preparation;

pub mod private_strategy_postgres;

pub mod strategy_research;

pub mod backtest_evidence;
pub mod backtest_run;
pub mod qualification_decision;
pub mod strategy_promotion;
pub(crate) mod strategy_validation;

pub(crate) mod qualification_commands;

pub mod factor_build;
pub mod job_publication;
