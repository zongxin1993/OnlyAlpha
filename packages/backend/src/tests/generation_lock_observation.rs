//! 原 fd/最后一个 Arc 的持有语义，不以诊断计时或表替代 OS 锁。
use super::*;
use std::sync::{Arc, Mutex};
use tracing::{
    Event, Subscriber,
    field::{Field, Visit},
};
use tracing_subscriber::{Layer, layer::Context, prelude::*};

struct ReleaseProbe {
    fd: OwnedFd,
    results: Arc<Mutex<Vec<bool>>>,
}
#[derive(Default)]
struct Kind {
    event: bool,
    released: bool,
}
impl Visit for Kind {
    fn record_str(&mut self, field: &Field, value: &str) {
        if field.name() == "event_kind" {
            self.event = value == "operation_end";
        }
        if field.name() == "outcome" {
            self.released = value == "released";
        }
    }
    fn record_debug(&mut self, _: &Field, _: &dyn std::fmt::Debug) {}
}
impl<S: Subscriber> Layer<S> for ReleaseProbe {
    fn on_event(&self, event: &Event<'_>, _: Context<'_, S>) {
        let mut kind = Kind::default();
        event.record(&mut kind);
        if kind.event && kind.released {
            let result = fs::flock(&self.fd, fs::FlockOperation::NonBlockingLockExclusive);
            self.results.lock().unwrap().push(result.is_ok());
            if result.is_ok() {
                fs::flock(&self.fd, fs::FlockOperation::Unlock).unwrap();
            }
        }
    }
}
#[test]
fn generation_lock_release_event_follows_actual_close_and_final_arc() {
    let root = std::env::temp_dir().join(publication::nonce("oa-generation-observation-").unwrap());
    drop(Registry::initialize_fresh(&root).unwrap());
    let fd = protected::open_directory(&root).unwrap();
    let probe = fs::openat(
        &fd,
        ".generation-authority.lock",
        fs::OFlags::RDONLY | fs::OFlags::NOFOLLOW | fs::OFlags::CLOEXEC,
        fs::Mode::empty(),
    )
    .unwrap();
    let results = Arc::new(Mutex::new(Vec::new()));
    let dispatch = tracing::Dispatch::new(tracing_subscriber::registry().with(ReleaseProbe {
        fd: probe,
        results: results.clone(),
    }));
    let held = tracing::dispatcher::with_default(&dispatch, || {
        Arc::new(
            RuntimeInputHold::acquire(&root, fs::FlockOperation::NonBlockingLockShared).unwrap(),
        )
    });
    let alias = held.clone();
    drop(held);
    assert!(matches!(Registry::open_existing(&root), Err(UNAVAILABLE)));
    assert!(results.lock().unwrap().is_empty());
    drop(alias); // 特意在原 default Dispatch 之外释放。
    assert_eq!(*results.lock().unwrap(), vec![true]);
    drop(Registry::open_existing(&root).unwrap());
    drop(dispatch);
    drop(fd);
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn real_generation_contention_keeps_object_run_and_contending_command() {
    use onlyalpha_observability::{Config, Correlation, Mode, Operation, Session};
    use std::io::{self, Write};
    #[derive(Clone, Default)]
    struct Buffer(Arc<Mutex<Vec<u8>>>);
    impl Write for Buffer {
        fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
            self.0.lock().unwrap().extend_from_slice(bytes);
            Ok(bytes.len())
        }
        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }
    let root = std::env::temp_dir().join(publication::nonce("oa-generation-context-").unwrap());
    drop(Registry::initialize_fresh(&root).unwrap());
    let buffer = Buffer::default();
    let session = Session::new(
        Config::new(Mode::Detail, "real-generation", 256),
        buffer.clone(),
    )
    .unwrap();
    tracing::dispatcher::with_default(session.dispatch(), || {
        let run = Operation::root(
            "test",
            "run",
            Correlation {
                run_id: Some("original-run".into()),
                ..Default::default()
            },
        );
        let held = run.span().in_scope(|| {
            RuntimeInputHold::acquire(&root, fs::FlockOperation::NonBlockingLockShared).unwrap()
        });
        run.finish("ok", 1, 0); // hold is a linked resource root, not a child outliving its parent.
        let command = Operation::root(
            "test",
            "preparation",
            Correlation {
                command_id: Some("contending-command".into()),
                ..Default::default()
            },
        );
        command
            .span()
            .in_scope(|| assert!(matches!(Registry::open_existing(&root), Err(UNAVAILABLE))));
        command.finish("failed", 1, 0);
        drop(held);
    });
    assert!(session.close().shutdown_complete);
    let rows: Vec<serde_json::Value> = String::from_utf8(buffer.0.lock().unwrap().clone())
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    let contention = rows
        .iter()
        .find(|r| r["event_kind"] == "lock_contention")
        .unwrap();
    assert_eq!(contention["command_id"], "contending-command");
    assert!(contention["errno"].as_i64().unwrap() > 0);
    let acquired = rows
        .iter()
        .find(|r| r["event_kind"] == "lock_acquired" && r["run_id"] == "original-run")
        .unwrap();
    assert_eq!(acquired["device"], contention["device"]);
    assert_eq!(acquired["inode"], contention["inode"]);
    assert_eq!(acquired["lock_type"], "shared");
    assert_eq!(contention["lock_type"], "exclusive");
    assert!(acquired.get("parent_span_id").is_none());
    assert!(acquired["links"].as_str().is_some());
    let preclose = rows
        .iter()
        .find(|r| r["span_id"] == acquired["span_id"] && r["event_kind"] == "lock_release_begin")
        .unwrap();
    assert!(acquired["mono_ns"].as_u64().unwrap() < contention["mono_ns"].as_u64().unwrap());
    assert!(contention["mono_ns"].as_u64().unwrap() < preclose["mono_ns"].as_u64().unwrap());
    std::fs::remove_dir_all(root).unwrap();
}
