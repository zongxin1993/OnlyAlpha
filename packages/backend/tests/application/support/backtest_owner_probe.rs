//! One image for original Source/READY and actual owner fault recovery.
#![cfg(test)]
#[expect(
    unused_imports,
    dead_code,
    reason = "The non-libtest driver omits unit-test bodies; the original libtest and Shipping targets check the complete source."
)]
#[path = "../../../src/application/mod.rs"]
pub mod application;
mod backtest_owner_scenarios;
mod backtest_preparation_queue;
mod backtest_run_lifecycle;
#[expect(
    unused_imports,
    reason = "The non-libtest driver omits #[test] bodies; the original libtest target checks these imports."
)]
#[path = "../../../src/bootstrap/mod.rs"]
pub mod bootstrap;
mod manual_freeze_owner;
mod manual_validation_producer;
#[expect(
    unused_imports,
    dead_code,
    reason = "The non-libtest driver omits unit-test bodies; the original libtest and Shipping targets check the complete source."
)]
#[path = "../../../src/persistence/mod.rs"]
pub mod persistence;
mod qualification_lifecycle;
mod qualification_product;
mod runtime_registry_init;
#[expect(
    unused_imports,
    dead_code,
    reason = "The non-libtest driver omits unit-test bodies; the original libtest and Shipping targets check the complete source."
)]
#[path = "../../../src/security/mod.rs"]
pub mod security;
mod strategy_alias_freeze;
mod strategy_evidence_owner;
mod strategy_preparation_queue;
#[expect(
    unused_imports,
    dead_code,
    reason = "The non-libtest driver omits unit-test bodies; the original libtest and Shipping targets check the complete source."
)]
#[path = "../../../src/transport/mod.rs"]
pub mod transport;
#[expect(
    unused_imports,
    dead_code,
    reason = "The non-libtest driver omits unit-test bodies; the original libtest and Shipping targets check the complete source."
)]
#[path = "../../../src/workers/mod.rs"]
pub mod workers;
pub(crate) fn is_sha256_hex(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
#[path = "postgres_probe.rs"]
mod consumer;
mod strategy_freeze_boundary;
use std::{
    error::Error,
    io::{self, IsTerminal, Read},
};

fn main() -> Result<(), Box<dyn Error>> {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    if args == ["--exact", "actual_command_boundary", "--nocapture"] {
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()?;
        runtime.block_on(strategy_freeze_boundary::run_command_boundary());
        return Ok(());
    }
    if args.is_empty() {
        if io::stdin().is_terminal() {
            println!("BACKTEST_OWNER_SCENARIO_NOT_REQUESTED");
            return Ok(());
        }
        let mut raw = String::new();
        io::stdin()
            .take(8 * 1024 * 1024 + 4097)
            .read_to_string(&mut raw)?;
        if raw.is_empty() {
            println!("BACKTEST_OWNER_SCENARIO_NOT_REQUESTED");
            return Ok(());
        }
        return consumer::run_with_input(Some(raw));
    }
    // Existing exact native describe, terminal reader and actual Running Host
    // modes retain their original implementation and the same loaded image.
    consumer::main()
}
