//! 实际封闭 SDK 的拒绝路径：观测不能改变错误、工件或业务结果。
use super::*;
use onlyalpha_observability::{Config, Mode, Session};
use std::{
    io::Write,
    sync::{Arc, Mutex},
};

#[derive(Clone)]
struct Output(Arc<Mutex<Vec<u8>>>);
impl Write for Output {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        self.0.lock().unwrap().extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

#[test]
fn diagnostic_modes_preserve_original_release_rejection_and_emit_bounded_stages() {
    let suffix = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    // SDK-dependent regression runs only in the fixed dev Linux workspace.
    let workspace = Path::new("/workspace");
    let root = workspace.join(format!(
        "test-results/runtime-diagnostics-{}-{suffix}",
        std::process::id()
    ));
    std::fs::create_dir_all(&root).unwrap();
    let built = std::process::Command::new("python")
        .current_dir(workspace)
        .arg(workspace.join("scripts/build_algorithm_sdk.py"))
        .arg(root.join("wheels"))
        .arg("--install")
        .arg(root.join("algorithms"))
        .output()
        .unwrap();
    assert!(
        built.status.success(),
        "{}",
        String::from_utf8_lossy(&built.stderr)
    );
    let artifact = String::from_utf8(built.stdout).unwrap().trim().to_owned();
    let installation = ChartInstallation::open(&root.join("algorithms"), &artifact).unwrap();
    let manifest = json!({"schema_version":2,"runtime_root":root,"version":"incompatible-controlled-version","algorithm_artifact":artifact});
    let bytes = serde_json::to_vec(&manifest).unwrap();
    std::fs::write(root.join("manifest.json"), &bytes).unwrap();
    for mode in [Mode::Off, Mode::Detail] {
        let output = Output(Arc::new(Mutex::new(Vec::new())));
        let session = Session::new(
            Config::new(mode, "runtime-diagnostic-test", 128),
            output.clone(),
        )
        .unwrap();
        let error =
            tracing::dispatcher::with_default(session.dispatch(), || {
                match prepare_strategy(&installation, &root, "0.11.1") {
                    Err(error) => error,
                    Ok(_) => panic!("an incompatible release must remain rejected"),
                }
            });
        assert_eq!(error.code(), INVALID);
        assert!(error.recovery_owner().is_none());
        assert_eq!(std::fs::read(root.join("manifest.json")).unwrap(), bytes);
        assert!(session.close().shutdown_complete);
        let raw = output.0.lock().unwrap().clone();
        if mode == Mode::Off {
            assert!(raw.is_empty());
            continue;
        }
        let records = raw
            .split(|b| *b == b'\n')
            .filter(|b| !b.is_empty())
            .map(|b| serde_json::from_slice::<Value>(b).unwrap())
            .collect::<Vec<_>>();
        let ended = |name: &str, outcome: &str| {
            records.iter().any(|r| {
                r["event_kind"] == "operation_end"
                    && r["operation"] == name
                    && r["outcome"] == outcome
            })
        };
        assert!(ended("runtime.prepare.installation_verify", "ok"));
        assert!(ended("runtime.prepare.release_open", "failed"));
        assert!(
            !String::from_utf8(raw)
                .unwrap()
                .contains("incompatible-controlled-version"),
            "diagnostics must not encode arbitrary inputs/errors"
        );
    }
}
