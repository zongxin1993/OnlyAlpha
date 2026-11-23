//! 有界日志故障不改变工作结果，关闭证据不能把丢失日志伪装成完整。
mod support;
use onlyalpha_observability::{Config, Correlation, Mode, Operation, Session};
use std::{
    fmt,
    io::{self, Write},
    sync::mpsc,
    time::Duration,
};
use support::Buffer;

#[test]
fn basic_mode_keeps_lock_contention_but_omits_wait_details() {
    use onlyalpha_observability::Marker;
    let buffer = Buffer::default();
    let session = Session::new(Config::new(Mode::Basic, "basic-lock", 64), buffer.clone()).unwrap();
    tracing::dispatcher::with_default(session.dispatch(), || {
        let op = Operation::root("runtime", "generation.lock_attempt", Correlation::default());
        op.marker(Marker::LockWait);
        op.marker(Marker::LockContention);
        op.finish("contended", 1, 0);
    });
    assert!(session.close().shutdown_complete);
    let rows = buffer.rows();
    assert!(rows.iter().any(|r| r["event_kind"] == "lock_contention"));
    assert!(!rows.iter().any(|r| r["event_kind"] == "lock_wait"));
}

#[test]
fn existing_input_work_and_bytes_are_recorded_on_failed_operations_too() {
    let buffer = Buffer::default();
    let session = Session::new(Config::new(Mode::Detail, "work", 64), buffer.clone()).unwrap();
    let result = tracing::dispatcher::with_default(session.dispatch(), || {
        onlyalpha_observability::measure_counted(
            "runtime",
            "checkpoint",
            Correlation::default(),
            64,
            4096,
            || Err::<(), _>("ORIGINAL"),
        )
    });
    assert_eq!(result, Err("ORIGINAL"));
    assert!(session.close().shutdown_complete);
    let rows = buffer.rows();
    let end = rows
        .iter()
        .find(|r| r["event_kind"] == "operation_end")
        .unwrap();
    assert_eq!(end["work_items"], 64);
    assert_eq!(end["bytes"], 4096);
    assert_eq!(end["outcome"], "failed");
}

#[test]
fn measured_closure_runs_once_and_logs_original_success_or_error() {
    for mode in [Mode::Off, Mode::Basic, Mode::Detail] {
        let buffer = Buffer::default();
        let session = Session::new(Config::new(mode, "measure", 64), buffer.clone()).unwrap();
        let mut calls = 0;
        let result = tracing::dispatcher::with_default(session.dispatch(), || {
            onlyalpha_observability::measure("runtime", "restore", Correlation::default(), || {
                calls += 1;
                Err::<(), _>("ORIGINAL")
            })
        });
        assert_eq!(result, Err("ORIGINAL"));
        assert_eq!(calls, 1);
        assert!(session.close().shutdown_complete);
        let rows = buffer.rows();
        let expected = if mode == Mode::Off { 0 } else { 1 };
        assert_eq!(
            rows.iter()
                .filter(|r| r["event_kind"] == "operation_end" && r["outcome"] == "failed")
                .count(),
            expected
        );
    }
}

struct Broken;
impl Write for Broken {
    fn write(&mut self, _: &[u8]) -> io::Result<usize> {
        Err(io::Error::from(io::ErrorKind::StorageFull))
    }
    fn flush(&mut self) -> io::Result<()> {
        Err(io::Error::from(io::ErrorKind::StorageFull))
    }
}
#[test]
fn storage_errors_are_counted_without_changing_original_error() {
    let session = Session::new(Config::new(Mode::Detail, "broken", 64), Broken).unwrap();
    let original: Result<(), &str> = tracing::dispatcher::with_default(session.dispatch(), || {
        let op = Operation::root("test", "work", Correlation::default());
        op.finish("failed", 0, 0);
        Err("ORIGINAL_BUSINESS_ERROR")
    });
    assert_eq!(original, Err("ORIGINAL_BUSINESS_ERROR"));
    let receipt = session.close();
    assert!(!receipt.shutdown_complete);
    assert!(receipt.io_errors > 0);
    assert_eq!(receipt.record()["event_kind"], "session_end");
}

struct Blocked {
    entered: Option<mpsc::SyncSender<()>>,
    release: mpsc::Receiver<()>,
}
impl Write for Blocked {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if let Some(entered) = self.entered.take() {
            entered.send(()).unwrap();
            self.release.recv().unwrap();
        }
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
#[test]
fn full_queue_is_lossy_and_shutdown_returns_before_blocked_io_is_released() {
    let (entered, ready) = mpsc::sync_channel(0);
    let (release, blocked) = mpsc::channel();
    let session = Session::new(
        Config::new(Mode::Detail, "blocked", 2),
        Blocked {
            entered: Some(entered),
            release: blocked,
        },
    )
    .unwrap();
    ready.recv_timeout(Duration::from_secs(2)).unwrap();
    tracing::dispatcher::with_default(session.dispatch(), || {
        for _ in 0..32 {
            let op = Operation::root("test", "work", Correlation::default());
            op.finish("ok", 1, 0);
        }
    });
    let (closed, receipt) = mpsc::channel();
    let join = std::thread::spawn(move || closed.send(session.close()).unwrap());
    // 测试本身用超时防止无限挂起；writer 必须在 release 前返回，不用 sleep 制造竞争。
    let result = receipt.recv_timeout(Duration::from_secs(2));
    release.send(()).unwrap();
    let receipt = result.expect("diagnostic shutdown must be bounded");
    join.join().unwrap();
    assert!(!receipt.shutdown_complete);
    assert!(receipt.dropped_events > 0);
}

struct ForbiddenDebug;
impl fmt::Debug for ForbiddenDebug {
    fn fmt(&self, _: &mut fmt::Formatter<'_>) -> fmt::Result {
        panic!("must not format arbitrary Debug")
    }
}
#[test]
fn mode_filters_and_field_whitelist_never_format_or_emit_private_payloads() {
    for mode in [Mode::Off, Mode::Basic, Mode::Detail] {
        let buffer = Buffer::default();
        let session = Session::new(Config::new(mode, "privacy", 64), buffer.clone()).unwrap();
        tracing::dispatcher::with_default(session.dispatch(), || {
            let op = Operation::root(
                "test",
                "work",
                Correlation {
                    attempt: Some(7),
                    ..Default::default()
                },
            );
            op.span().in_scope(|| {
                tracing::info!(target:"onlyalpha.observability", event_kind="summary",
                run_id=?ForbiddenDebug, request_body="private-password", message=?ForbiddenDebug)
            });
            op.finish("ok", 1, 0);
        });
        assert!(session.close().shutdown_complete);
        let rows = buffer.rows();
        assert!(
            rows.iter()
                .all(|r| r.get("request_body").is_none() && r.get("message").is_none())
        );
        assert!(
            !serde_json::to_string(&rows)
                .unwrap()
                .contains("private-password")
        );
        match mode {
            Mode::Off => assert!(rows.is_empty()),
            Mode::Basic => {
                assert_eq!(rows.len(), 2);
                assert_eq!(rows[1]["event_kind"], "summary");
            }
            Mode::Detail => {
                assert_eq!(rows.len(), 4);
                assert_eq!(rows[1]["attempt"], 7);
            }
        }
    }
}

#[test]
fn basic_keeps_known_server_drop_as_an_exception() {
    let buffer = Buffer::default();
    let session = Session::new(Config::new(Mode::Basic, "basic-drop", 64), buffer.clone()).unwrap();
    tracing::dispatcher::with_default(session.dispatch(), || {
        Operation::root("transport", "http.handler", Correlation::default()).finish("dropped", 0, 0)
    });
    assert!(session.close().shutdown_complete);
    assert!(
        buffer
            .rows()
            .iter()
            .any(|row| row["outcome"] == "dropped" && row["operation"] == "http.handler")
    );
}

#[test]
fn explicit_witness_values_keep_long_paths_but_never_admit_payload_fields() {
    let buffer = Buffer::default();
    let session = Session::new(
        Config::new(Mode::Basic, "witness-fields", 64),
        buffer.clone(),
    )
    .unwrap();
    let path = format!("/retained/{}/manifest.json", "x".repeat(300));
    tracing::dispatcher::with_default(session.dispatch(), || {
        tracing::error!(target:"onlyalpha.observability",event_kind="summary",module="backend",operation="evidence.witness.failure",outcome="failed",error_code="WITNESS_INODE_MISMATCH",file_path=path.as_str(),expected_value="123",actual_value="456",payload="SECRET_PAYLOAD");
    });
    assert!(session.close().shutdown_complete);
    let rows = buffer.rows();
    let row = rows
        .iter()
        .find(|row| row["operation"] == "evidence.witness.failure")
        .unwrap();
    assert_eq!(row["file_path"], path);
    assert_eq!(row["expected_value"], "123");
    assert_eq!(row["actual_value"], "456");
    assert!(row.get("payload").is_none());
}
