//! 真实隔离文件触发 Witness 原失败分支；只诊断，不改变错误码或接受集合。
use super::*;
use onlyalpha_observability::{Config, Correlation, Mode, Operation, Session};
use std::{
    io::{self, Write},
    os::unix::fs::{MetadataExt, PermissionsExt, symlink},
    path::PathBuf,
    sync::{
        Arc, Mutex,
        atomic::{AtomicU64, Ordering},
    },
};
#[derive(Clone, Default)]
struct Events(Arc<Mutex<Vec<u8>>>);
impl Write for Events {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        self.0.lock().unwrap().extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
impl Events {
    fn rows(&self) -> Vec<Value> {
        String::from_utf8(self.0.lock().unwrap().clone())
            .unwrap()
            .lines()
            .map(|v| serde_json::from_str(v).unwrap())
            .collect()
    }
}
struct Root(PathBuf);
impl Root {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let p = std::env::temp_dir().join(format!(
            "onlyalpha-witness-diagnostic-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir(&p).unwrap();
        Self(p)
    }
    fn directory(&self) -> Directory {
        let path = self.0.join("evidence-".to_owned() + &"x".repeat(180));
        std::fs::create_dir(&path).unwrap();
        Directory::open(&path).unwrap()
    }
}
impl Drop for Root {
    fn drop(&mut self) {
        std::fs::remove_dir_all(&self.0).unwrap();
    }
}
fn capture(directory: &Directory) -> Witness {
    let path = directory.path.join("manifest.json");
    std::fs::write(&path, b"SECRET_PAYLOAD_NOT_FOR_DIAGNOSTICS").unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
    let (raw, file) = read_file(directory, "manifest.json").unwrap();
    witness(directory, "manifest.json", &raw, &file).unwrap()
}
fn run_case(kind: &str) {
    for mode in [Mode::Off, Mode::Basic, Mode::Detail] {
        let root = Root::new();
        let directory = root.directory();
        let original = capture(&directory);
        let path = directory.path.join("manifest.json");
        let (predicate, expected, actual) = match kind {
            "inode" => {
                let replacement = directory.path.join("replacement");
                std::fs::write(&replacement, b"SECRET_PAYLOAD_NOT_FOR_DIAGNOSTICS").unwrap();
                std::fs::set_permissions(&replacement, std::fs::Permissions::from_mode(0o600))
                    .unwrap();
                std::fs::rename(replacement, &path).unwrap();
                (
                    "WITNESS_INODE_MISMATCH",
                    original.inode.to_string(),
                    std::fs::metadata(&path).unwrap().ino().to_string(),
                )
            }
            "size" => {
                std::fs::write(&path, b"short").unwrap();
                (
                    "WITNESS_SIZE_MISMATCH",
                    original.size.to_string(),
                    "5".into(),
                )
            }
            "digest" => {
                let data = vec![b'x'; original.size as usize];
                std::fs::write(&path, &data).unwrap();
                (
                    "WITNESS_DIGEST_MISMATCH",
                    original.digest.clone(),
                    byte_sha(&data),
                )
            }
            "missing" => {
                std::fs::remove_file(&path).unwrap();
                (
                    "WITNESS_FILE_MISSING",
                    "successful_open".into(),
                    "errno:2".into(),
                )
            }
            "symlink" => {
                std::fs::remove_file(&path).unwrap();
                symlink("missing-target", &path).unwrap();
                (
                    "WITNESS_SYMLINK_REJECTED",
                    "successful_open".into(),
                    format!("errno:{}", rustix::io::Errno::LOOP.raw_os_error()),
                )
            }
            "hardlink" => {
                std::fs::hard_link(&path, directory.path.join("alias")).unwrap();
                ("WITNESS_LINK_COUNT_INVALID", "1".into(), "2".into())
            }
            "mode" => {
                std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o620)).unwrap();
                ("WITNESS_WRITE_BITS_INVALID", "0o0".into(), "0o20".into())
            }
            "directory" => {
                std::fs::remove_file(&path).unwrap();
                std::fs::create_dir(&path).unwrap();
                (
                    "WITNESS_FILE_TYPE_INVALID",
                    "regular_file".into(),
                    format!("mode:{:#o}", std::fs::metadata(&path).unwrap().mode()),
                )
            }
            "too_large" => {
                std::fs::OpenOptions::new()
                    .write(true)
                    .open(&path)
                    .unwrap()
                    .set_len(LIMIT as u64 + 1)
                    .unwrap();
                (
                    "WITNESS_STAT_SIZE_LIMIT",
                    format!("<={LIMIT}"),
                    (LIMIT + 1).to_string(),
                )
            }
            _ => unreachable!(),
        };
        let events = Events::default();
        let session = Session::new(Config::new(mode, "witness-test", 64), events.clone()).unwrap();
        let result = tracing::dispatcher::with_default(session.dispatch(), || {
            let operation = Operation::root(
                "backend",
                "test.witness",
                Correlation {
                    run_id: Some("original-run".into()),
                    command_id: Some("original-command".into()),
                    ..Default::default()
                },
            );
            let result = operation.span().in_scope(|| original.verify());
            operation.finish("failed", 0, 0);
            result
        });
        assert_eq!(result, Err(INVALID));
        assert!(session.close().shutdown_complete);
        let rows = events.rows();
        let failures: Vec<_> = rows
            .iter()
            .filter(|row| row["operation"] == "evidence.witness.failure")
            .collect();
        if mode == Mode::Off {
            assert!(rows.is_empty());
            continue;
        }
        assert_eq!(
            failures.len(),
            1,
            "missing exact Witness failure for {kind}"
        );
        let event = failures[0];
        eprintln!("WITNESS_CONTROLLED_DIAGNOSTIC {event}");
        assert_eq!(event["file_path"], path.to_str().unwrap());
        assert_eq!(event["error_code"], predicate);
        assert_eq!(event["expected_value"], expected);
        assert_eq!(event["actual_value"], actual);
        assert_eq!(event["run_id"], "original-run");
        assert_eq!(event["command_id"], "original-command");
        assert!(
            !serde_json::to_string(&rows)
                .unwrap()
                .contains("SECRET_PAYLOAD_NOT_FOR_DIAGNOSTICS")
        );
    }
}
macro_rules! case {
    ($name:ident,$kind:literal) => {
        #[test]
        fn $name() {
            run_case($kind)
        }
    };
}
case!(witness_inode_replacement_is_diagnosed, "inode");
case!(witness_size_change_is_diagnosed, "size");
case!(witness_byte_change_is_diagnosed, "digest");
case!(witness_missing_file_is_diagnosed, "missing");
case!(witness_symlink_is_diagnosed, "symlink");
case!(witness_hardlink_is_diagnosed, "hardlink");
case!(witness_write_bits_are_diagnosed, "mode");
case!(witness_directory_is_diagnosed, "directory");
case!(witness_size_limit_is_diagnosed, "too_large");

fn recorded(work: impl FnOnce() -> Result<()>) -> (Result<()>, Vec<Value>) {
    let events = Events::default();
    let session = Session::new(
        Config::new(Mode::Detail, "controlled-witness", 64),
        events.clone(),
    )
    .unwrap();
    let result = tracing::dispatcher::with_default(session.dispatch(), || {
        let operation = Operation::root("backend", "controlled.witness", Correlation::default());
        let result = operation.span().in_scope(work);
        operation.finish("observed", 0, 0);
        result
    });
    assert!(session.close().shutdown_complete);
    let rows = events.rows();
    for row in rows
        .iter()
        .filter(|row| row["operation"] == "evidence.witness.failure")
    {
        eprintln!("WITNESS_CONTROLLED_DIAGNOSTIC {row}");
    }
    (result, rows)
}
fn diagnostic(rows: &[Value]) -> &Value {
    rows.iter()
        .find(|row| row["operation"] == "evidence.witness.failure")
        .unwrap()
}
#[test]
fn witness_device_mismatch_keeps_the_original_failure() {
    let root = Root::new();
    let directory = root.directory();
    let mut original = capture(&directory);
    let actual = original.device;
    original.device += 1;
    let (result, rows) = recorded(|| original.verify());
    assert_eq!(result, Err(INVALID));
    let row = diagnostic(&rows);
    assert_eq!(row["error_code"], "WITNESS_DEVICE_MISMATCH");
    assert_eq!(row["expected_value"], (actual + 1).to_string());
    assert_eq!(row["actual_value"], actual.to_string());
}
#[test]
fn witness_owner_and_negative_size_metadata_are_not_relaxed() {
    for kind in ["owner", "negative_size", "earlier_branch"] {
        let root = Root::new();
        let directory = root.directory();
        let _original = capture(&directory);
        let file = File::open(directory.path.join("manifest.json")).unwrap();
        let mut stat = fs::fstat(file.as_fd()).unwrap();
        let euid = rustix::process::geteuid().as_raw();
        if kind == "owner" {
            stat.st_uid = if euid == 1 { 2 } else { 1 };
        } else if kind == "negative_size" {
            stat.st_uid = 0;
            stat.st_size = -1;
        } else {
            stat.st_nlink = 2;
        }
        let (result, rows) = recorded(|| {
            validate_file_metadata(
                &directory,
                "manifest.json",
                &stat,
                || {
                    assert_eq!(kind, "owner", "UID getter changed original short circuit");
                    euid
                },
                INVALID,
            )
        });
        assert_eq!(result, Err(INVALID));
        let row = diagnostic(&rows);
        if kind == "owner" {
            assert_eq!(row["error_code"], "WITNESS_OWNER_INVALID");
            assert_eq!(row["expected_value"], format!("0_or_{euid}"));
            assert_eq!(row["actual_value"], stat.st_uid.to_string());
        } else if kind == "negative_size" {
            assert_eq!(row["error_code"], "WITNESS_NEGATIVE_SIZE");
            assert_eq!(row["actual_value"], "-1");
        } else {
            assert_eq!(row["error_code"], "WITNESS_LINK_COUNT_INVALID");
        }
    }
}
#[test]
fn witness_short_reads_growth_and_unavailable_keep_original_codes() {
    struct Broken(bool);
    impl Read for Broken {
        fn read(&mut self, _: &mut [u8]) -> io::Result<usize> {
            Err(if self.0 {
                io::Error::from_raw_os_error(5)
            } else {
                io::Error::other("SECRET_ERROR_BODY")
            })
        }
    }
    for kind in [
        "short",
        "growth_invalid",
        "growth_unavailable",
        "io",
        "io_without_errno",
    ] {
        let root = Root::new();
        let directory = root.directory();
        let (result, rows) = recorded(|| {
            if kind == "short" {
                read_content(
                    &directory,
                    "manifest.json",
                    &mut io::Cursor::new(b"abc"),
                    4,
                    INVALID,
                )
                .map(drop)
            } else if kind.starts_with("growth") {
                read_content(
                    &directory,
                    "manifest.json",
                    &mut io::Cursor::new(vec![0; LIMIT + 1]),
                    1,
                    if kind == "growth_invalid" {
                        INVALID
                    } else {
                        UNAVAILABLE
                    },
                )
                .map(drop)
            } else {
                read_content(
                    &directory,
                    "manifest.json",
                    &mut Broken(kind == "io"),
                    1,
                    INVALID,
                )
                .map(drop)
            }
        });
        let row = diagnostic(&rows);
        if kind == "short" {
            assert_eq!(result, Err(INVALID));
            assert_eq!(row["error_code"], "WITNESS_READ_LENGTH_MISMATCH");
            assert_eq!(row["expected_value"], "4");
            assert_eq!(row["actual_value"], "3");
        } else if kind.starts_with("growth") {
            assert_eq!(
                result,
                Err(if kind == "growth_invalid" {
                    INVALID
                } else {
                    UNAVAILABLE
                })
            );
            assert_eq!(row["error_code"], "WITNESS_READ_SIZE_LIMIT");
            assert_eq!(row["actual_value"], (LIMIT + 1).to_string());
        } else {
            assert_eq!(result, Err(UNAVAILABLE));
            assert_eq!(row["error_code"], "WITNESS_READ_UNAVAILABLE");
            if kind == "io" {
                assert_eq!(row["errno"], 5);
            } else {
                assert!(row.get("errno").is_none());
                assert_eq!(row["actual_value"], "io_error_without_errno");
            }
        }
        assert!(
            !serde_json::to_string(&rows)
                .unwrap()
                .contains("SECRET_ERROR_BODY")
        );
    }
}
#[test]
fn witness_open_errno_mapping_is_preserved() {
    let root = Root::new();
    let directory = root.directory();
    for (errno, expected, predicate) in [
        (rustix::io::Errno::NOTDIR, INVALID, "WITNESS_NOT_DIRECTORY"),
        (
            rustix::io::Errno::ACCESS,
            UNAVAILABLE,
            "WITNESS_OPEN_UNAVAILABLE",
        ),
    ] {
        let (result, rows) = recorded(|| Err(open_failure(&directory, "manifest.json", errno)));
        assert_eq!(result, Err(expected));
        assert_eq!(diagnostic(&rows)["error_code"], predicate);
        assert_eq!(diagnostic(&rows)["errno"], errno.raw_os_error());
    }
}
#[test]
fn witness_success_emits_no_failure_and_log_io_cannot_change_failure() {
    struct BrokenWriter;
    impl Write for BrokenWriter {
        fn write(&mut self, _: &[u8]) -> io::Result<usize> {
            Err(io::Error::other("writer down"))
        }
        fn flush(&mut self) -> io::Result<()> {
            Err(io::Error::other("writer down"))
        }
    }
    let root = Root::new();
    let directory = root.directory();
    let original = capture(&directory);
    let (result, rows) = recorded(|| original.verify());
    assert_eq!(result, Ok(()));
    assert!(
        !rows
            .iter()
            .any(|row| row["operation"] == "evidence.witness.failure")
    );
    std::fs::remove_file(directory.path.join("manifest.json")).unwrap();
    let session =
        Session::new(Config::new(Mode::Detail, "broken-writer", 64), BrokenWriter).unwrap();
    let result = tracing::dispatcher::with_default(session.dispatch(), || original.verify());
    assert_eq!(result, Err(INVALID));
    assert!(!session.close().shutdown_complete);
}
#[test]
fn witness_encoding_and_directory_failure_keep_original_error_codes() {
    let root = Root::new();
    let directory = root.directory();
    let original = capture(&directory);
    let (result, rows) =
        recorded(|| document(&directory, "manifest.json", &mut Vec::new()).map(drop));
    assert_eq!(result, Err(INVALID));
    assert_eq!(
        diagnostic(&rows)["error_code"],
        "WITNESS_DOCUMENT_ENCODING_INVALID"
    );
    let old = directory.path.with_extension("original");
    std::fs::rename(&directory.path, &old).unwrap();
    std::fs::create_dir(&directory.path).unwrap();
    let (result, rows) = recorded(|| original.verify());
    assert_eq!(result, Err("IMMUTABLE_JSON_INVALID"));
    assert_eq!(diagnostic(&rows)["error_code"], "WITNESS_DIRECTORY_BEFORE");
}
