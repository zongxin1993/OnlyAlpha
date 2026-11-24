//! One image for original Source/READY and actual owner fault recovery.
#![cfg(test)]
#[expect(
    unused_imports,
    dead_code,
    reason = "The non-libtest driver omits unit-test bodies; the original libtest and Shipping targets check the complete source."
)]
#[path = "../../../src/application/mod.rs"]
pub mod application;
mod job_fact_connection;
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
use crate as host_backend;
mod backtest_native_host;
#[path = "postgres_probe.rs"]
mod consumer;
mod strategy_freeze_boundary;
use std::{
    error::Error,
    io::{self, IsTerminal, Read},
};

async fn drive_worker_gates(path: std::path::PathBuf) -> Result<(), Box<dyn Error>> {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use workers::backtest_worker::tests::gate;

    let mut socket = tokio::net::UnixStream::connect(path).await?;
    let mut frame = [0; 37];
    socket.read_exact(&mut frame).await?;
    let run_id = std::str::from_utf8(&frame[..36])?;
    if frame[36] != b'\n' || !application::command::uuid4(run_id) {
        return Err("worker gate requires the reserved Run ID".into());
    }
    let phases = ["before_claim", "after_first_step", "after_publish"]
        .map(|phase| (phase, gate(run_id, phase)));
    socket.write_all(b"armed\n").await?;
    for (phase, barrier) in phases {
        barrier.entered().await;
        socket.write_all(format!("{phase}\n").as_bytes()).await?;
        if phase != "after_publish" {
            let mut release = [0; 8];
            socket.read_exact(&mut release).await?;
            if &release != b"release\n" {
                return Err("worker gate requires explicit release".into());
            }
        }
    }
    Ok(())
}

fn main() -> Result<(), Box<dyn Error>> {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    if args == ["--backtest-native-host-with-worker-gates"] {
        let mut configuration = backtest_native_host::configuration()?;
        let path = configuration.as_object_mut()
            .and_then(|fields| fields.remove("worker_gate_socket"))
            .and_then(|value| value.as_str().map(std::path::PathBuf::from))
            .filter(|path| path.is_absolute())
            .ok_or("absolute worker gate socket required")?;
        return tokio::runtime::Builder::new_current_thread().enable_all().build()?.block_on(async {
            tokio::try_join!(backtest_native_host::serve(configuration), drive_worker_gates(path))?;
            Ok(())
        });
    }
    if args == ["--exact", "actual_command_boundary", "--nocapture"] {
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()?;
        let diagnostics = std::env::var_os("ONLYALPHA_DIAGNOSTICS_PATH")
            .map(|path| {
                use bootstrap::observability;
                observability::start(
                    observability::mode(Some("detail"), None)?,
                    Some(std::path::Path::new(&path)),
                )
            })
            .transpose()?
            .flatten();
        runtime.block_on(strategy_freeze_boundary::run_command_boundary());
        if let Some(session) = diagnostics {
            let receipt = session.close();
            assert!(receipt.shutdown_complete, "{}", receipt.record());
        }
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
