use serde_json::Value;
use std::process::{Command, Stdio};
#[test]
fn executable_identifies_its_own_bytes_and_refuses_commands_without_an_admitted_plan() {
    let binary = env!("CARGO_BIN_EXE_onlyalpha-backtest-runtime");
    let output = Command::new(binary).arg("--describe").output().unwrap();
    assert!(output.status.success());
    let description: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(description["protocol"], "onlyalpha.backtest.driver/1");
    assert_eq!(
        description["artifact"],
        onlyalpha_calculation_worker::fingerprint(&std::fs::read(binary).unwrap())
    );
    assert_eq!(description["version"], env!("CARGO_PKG_VERSION"));
    let output = Command::new(binary).stdin(Stdio::null()).output().unwrap();
    assert!(!output.status.success());
    assert!(output.stdout.is_empty());
}
