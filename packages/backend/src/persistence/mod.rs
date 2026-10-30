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
