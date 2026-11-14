//! 入口初始化归后端；纯导出/算法协议角色不能创建日志文件或输出诊断。
use onlyalpha_backend::bootstrap::observability;
use onlyalpha_observability::Mode;
use std::{
    path::PathBuf,
    process::{Command, Stdio},
};

#[test]
fn mode_is_explicit_and_legacy_flag_maps_to_detail() {
    for (configured, legacy, expected) in [
        (None, None, Mode::Basic),
        (None, Some("1"), Mode::Detail),
        (Some("off"), Some("1"), Mode::Off),
        (Some("basic"), None, Mode::Basic),
        (Some("detail"), None, Mode::Detail),
    ] {
        assert_eq!(observability::mode(configured, legacy).unwrap(), expected);
    }
    assert_eq!(
        observability::mode(Some("debug-everything"), None),
        Err("OBSERVABILITY_CONFIGURATION_INVALID")
    );
}

#[test]
fn repeated_global_initialization_is_rejected_before_opening_another_output() {
    let first = observability::start(Mode::Basic, None).unwrap().unwrap();
    let candidate = PathBuf::from(format!(
        "/tmp/oa-observability-duplicate-{}.jsonl",
        std::process::id()
    ));
    assert!(!candidate.exists());
    assert!(matches!(
        observability::start(Mode::Detail, Some(&candidate)),
        Err("OBSERVABILITY_ALREADY_INITIALIZED")
    ));
    assert!(!candidate.exists());
    assert!(first.close().shutdown_complete);
}

#[test]
fn protocol_and_pure_export_roles_ignore_diagnostic_environment_without_side_effects() {
    let binary = env!("CARGO_BIN_EXE_onlyalpha-backend");
    for role in [
        "--export-openapi",
        "--export-websocket",
        "--native-chart-worker",
    ] {
        let output = PathBuf::from(format!(
            "/tmp/oa-observability-role-{}-{}.jsonl",
            std::process::id(),
            role
        ));
        assert!(!output.exists());
        let child = Command::new(binary)
            .arg(role)
            .env("ONLYALPHA_DIAGNOSTICS", "detail")
            .env("ONLYALPHA_DIAGNOSTICS_PATH", &output)
            .env("ONLYALPHA_BACKTEST_PROFILE", "1")
            .stdin(Stdio::null())
            .output()
            .unwrap();
        assert!(
            !output.exists(),
            "role must not initialize diagnostics: {role}"
        );
        assert!(!String::from_utf8_lossy(&child.stderr).contains("ONLYALPHA_DIAGNOSTIC"));
        if role.starts_with("--export") {
            assert!(child.status.success());
            let _: serde_json::Value = serde_json::from_slice(&child.stdout).unwrap();
        }
    }
}
