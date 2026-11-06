//! Isolated persistence test harness: actual backend owners, cfg(test) seals only.
//! The canonical Python lane provisions the guarded DB; no Shipping acceptance.
#![allow(dead_code)]
#[path = "../../../src/application/mod.rs"]
pub mod application;
mod backtest_owner_scenarios;
mod backtest_preparation_queue;
mod backtest_run_lifecycle;
#[path = "../../../src/bootstrap/mod.rs"]
pub mod bootstrap;
mod manual_freeze_owner;
mod manual_validation_producer;
#[path = "../../../src/persistence/mod.rs"]
pub mod persistence;
mod qualification_lifecycle;
mod qualification_product;
mod runtime_registry_init;
#[path = "../../../src/security/mod.rs"]
pub mod security;
mod strategy_alias_freeze;
mod strategy_evidence_owner;
mod strategy_preparation_queue;
#[path = "../../../src/transport/mod.rs"]
pub mod transport;
#[path = "../../../src/workers/mod.rs"]
pub mod workers;
pub(crate) fn is_sha256_hex(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
mod strategy_freeze_boundary;

#[tokio::test]
async fn actual_command_boundary() {
    strategy_freeze_boundary::run_command_boundary().await;
}
