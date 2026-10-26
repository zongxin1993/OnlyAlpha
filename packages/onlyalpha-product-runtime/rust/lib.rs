//! Transport-neutral Rust Product Application and owning persistence.
pub mod command;
pub mod postgres;
pub mod source_access;

fn is_sha256_hex(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

pub mod watchlist_postgres;
pub mod watchlists;

pub mod integration_configuration;

pub mod integration_postgres;

pub mod integration_resolver;

pub mod integration_commands;

pub mod credentials;

pub mod credential_postgres;

pub mod integration_catalog;

pub mod deployment;

pub mod schema;

pub mod authority_session;
pub mod frozen_strategy;
pub mod protected_files;

mod strategy_projection;
pub use strategy_projection::ReconciliationError;

pub mod qualification_policy;

pub mod market_data_wal;

pub mod market_data;

pub mod market_product;

pub mod chart;
pub mod private_assets;

pub mod workspace;
pub mod workspace_postgres;
