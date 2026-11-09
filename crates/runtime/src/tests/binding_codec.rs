//! Binding codec reuse never certifies mutable Replay/Execution source state.
use super::*;
use crate::Runtime;
#[cfg(target_os = "linux")]
use crate::VerifiedReplaySnapshot;
use crate::support;
use std::{
    fs,
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};
static NEXT: AtomicU64 = AtomicU64::new(0);
struct Root(PathBuf);
impl Root {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "oa-binding-codec-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
}
impl Drop for Root {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}
fn binding(modern: bool) -> Value {
    let configuration = support::config();
    let mut value = json!({"schema_version":1,"configuration":hash(&configuration),"kernel_artifact":"b".repeat(64),"driver_artifact":"f".repeat(64),"work":"c".repeat(64),"input_pin":"d".repeat(64),"program":"e".repeat(64),"initial_state":{"cursor":0,"clock_ns":"0"}});
    if modern {
        let program = json!({"schema_version":1,"configuration":hash(&configuration),"generation":configuration["generation"],"initial_ns":"0","strategies":{"cluster":"revision"},"opening_profile":{"schema_version":1,"kind":"OPEN_CLOSE_V1"}});
        value["schema_version"] = json!(2);
        value["work_id"] = json!("binding-codec");
        value["participants"] = program.clone();
        value["program"] = json!(hash(&program));
        value["work"] = json!(hash(
            &json!({"work_id":value["work_id"],"configuration":configuration,"artifact":value["kernel_artifact"],"driver_artifact":value["driver_artifact"],"input_pin":value["input_pin"],"participants":program,"initial_ns":"0"})
        ));
    }
    value
}
fn fixture(modern: bool, execution: bool) -> (Runtime, Root, Vec<crate::ReplayEntryRef>) {
    let root = Root::new();
    let mut runtime = Runtime::create(&root.0, support::config(), &"b".repeat(64)).unwrap();
    let binding = binding(modern);
    runtime.bind_replay(&binding).unwrap();
    let inputs = if execution {
        vec![support::open(1, "BUY")]
    } else {
        Vec::new()
    };
    let step = json!({"schema_version":1,"index":1,"previous":hash(&binding),"execution_start":0,"cause":{"kind":"BAR"},"inputs":inputs,"state":{"cursor":1}});
    let pending = runtime.prepare_replay_ref(&[], &step).unwrap();
    if execution {
        runtime.apply(&inputs[0]).unwrap();
    }
    let refs = runtime.complete_replay_ref(&[], &pending).unwrap();
    (runtime, root, refs)
}
fn reset() {
    BINDING_ACTUAL_ROWS.with(|n| n.set(0));
    BINDING_CODEC_DECODES.with(|n| n.set(0));
    BINDING_CODEC_HITS.with(|n| n.set(0));
}
// Exact original SQL and cold reader: compare error boundary/ordering, not a
// newly invented acceptance condition for the optimized implementation.
fn original_read(store: &SqliteStore) -> Result<Option<Value>, Error> {
    let row: Option<(String, String)> = sql(store
        .connection
        .query_row(
            "SELECT payload,digest FROM replay_binding WHERE singleton=1",
            [],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional())?;
    row.map(|(raw, fingerprint)| {
        let value = decoded(&raw, &fingerprint)?;
        store.validate_replay_binding(&value)?;
        Ok(value)
    })
    .transpose()
}
#[test]
fn exact_binding_codec_warm_reads_still_observe_sql_and_cold_reopen_rechecks() {
    for modern in [false, true] {
        let (runtime, root, refs) = fixture(modern, false);
        reset();
        for _ in 0..4 {
            runtime.verify_replay_refs(&refs).unwrap();
        }
        assert_eq!(BINDING_ACTUAL_ROWS.with(std::cell::Cell::get), 4);
        assert_eq!(BINDING_CODEC_HITS.with(std::cell::Cell::get), 4);
        assert_eq!(BINDING_CODEC_DECODES.with(std::cell::Cell::get), 0);
        let observed = runtime.store.replay_binding_data().unwrap().unwrap();
        assert_eq!(observed.fingerprint(), hash(&observed.value));
        assert_eq!(observed.raw, observed.value.to_string());
        assert_eq!(
            original_read(&runtime.store).unwrap(),
            Some(observed.value.clone())
        );
        let mut detached = runtime.store.replay_binding().unwrap().unwrap();
        detached["initial_state"]["cursor"] = json!(999);
        assert_ne!(runtime.store.replay_binding().unwrap().unwrap(), detached);
        drop(observed);
        drop(runtime);
        let runtime = Runtime::open(&root.0, support::config(), &"b".repeat(64)).unwrap();
        reset();
        runtime.verify_replay_refs(&refs).unwrap();
        assert_eq!(BINDING_CODEC_DECODES.with(std::cell::Cell::get), 1);
        assert_eq!(BINDING_ACTUAL_ROWS.with(std::cell::Cell::get), 1);
        drop(runtime);
        drop(root);
    }
}
#[test]
fn binding_codec_key_includes_complete_identity_and_invalid_context_never_reuses() {
    let (mut runtime, root, _) = fixture(true, false);
    let identity = runtime.store.identity.clone();
    for field in ["configuration", "kernel_artifact", "family"] {
        runtime.store.identity = identity.clone();
        runtime.store.replay_binding().unwrap();
        reset();
        match field {
            "configuration" => runtime.store.identity[field]["initial_cash"] = json!("2000.00"),
            "kernel_artifact" => runtime.store.identity[field] = json!("f".repeat(64)),
            _ => runtime.store.identity[field] = json!("OTHER_CONTEXT"),
        }
        assert_eq!(
            runtime.store.replay_binding(),
            original_read(&runtime.store)
        );
        assert_eq!(BINDING_CODEC_HITS.with(std::cell::Cell::get), 0, "{field}");
        assert_eq!(
            BINDING_CODEC_DECODES.with(std::cell::Cell::get),
            1,
            "{field}"
        );
    }
    runtime.store.identity = identity;
    assert_eq!(
        runtime.store.replay_binding(),
        original_read(&runtime.store)
    );
    drop(runtime);
    drop(root);
}
#[test]
fn actual_binding_tampering_absence_and_sql_type_utf8_errors_keep_original_order() {
    for fault in [
        "payload",
        "digest",
        "resealed",
        "valid-resealed",
        "absent",
        "utf8-first",
        "blob",
    ] {
        let (runtime, root, refs) = fixture(true, false);
        let db = rusqlite::Connection::open(root.0.join("runtime.sqlite3")).unwrap();
        if fault == "blob" {
            db.execute_batch("PRAGMA writable_schema=ON; UPDATE sqlite_schema SET sql=replace(sql,' STRICT','') WHERE name='replay_binding'; PRAGMA writable_schema=OFF;").unwrap();
            let n: i64 = db
                .pragma_query_value(None, "schema_version", |r| r.get(0))
                .unwrap();
            db.pragma_update(None, "schema_version", n + 1).unwrap();
        }
        match fault {
            "payload" => {
                db.execute_batch("UPDATE replay_binding SET payload='{}'")
                    .unwrap();
            }
            "digest" => {
                db.execute("UPDATE replay_binding SET digest=?1", ["f".repeat(64)])
                    .unwrap();
            }
            "resealed" => {
                let mut changed = binding(true);
                changed["program"] = json!("f".repeat(64));
                db.execute(
                    "UPDATE replay_binding SET payload=?1,digest=?2",
                    params![changed.to_string(), hash(&changed)],
                )
                .unwrap();
            }
            "valid-resealed" => {
                let mut changed = binding(true);
                changed["initial_state"]["cursor"] = json!(999);
                db.execute(
                    "UPDATE replay_binding SET payload=?1,digest=?2",
                    params![changed.to_string(), hash(&changed)],
                )
                .unwrap();
            }
            "absent" => {
                db.execute_batch("DELETE FROM replay_binding").unwrap();
            }
            "utf8-first" => {
                db.execute_batch("UPDATE replay_binding SET payload=CAST(X'80' AS TEXT),digest=CAST(X'81' AS TEXT)").unwrap();
            }
            _ => {
                db.execute_batch("UPDATE replay_binding SET payload=CAST(payload AS BLOB)")
                    .unwrap();
            }
        }
        drop(db);
        let before = fs::read(root.0.join("runtime.sqlite3")).unwrap();
        let expected = original_read(&runtime.store);
        assert_eq!(runtime.store.replay_binding(), expected, "{fault}");
        assert!(runtime.verify_replay_refs(&refs).is_err(), "{fault}");
        assert_eq!(fs::read(root.0.join("runtime.sqlite3")).unwrap(), before);
        drop(runtime);
        drop(root);
    }
}
#[test]
fn warm_binding_codec_never_hides_actual_head_flags_or_missing_execution_source() {
    for fault in ["head", "last", "flags", "missing", "replay-flags"] {
        let (runtime, root, refs) = fixture(true, true);
        runtime.verify_replay_refs(&refs).unwrap();
        let db = rusqlite::Connection::open(root.0.join("runtime.sqlite3")).unwrap();
        db.execute_batch("PRAGMA ignore_check_constraints=ON;")
            .unwrap();
        db.execute_batch(match fault {
            "head" => "UPDATE replay_binding SET head=99",
            "last" => "UPDATE replay_binding SET last_hash='bad'",
            "flags" => "UPDATE records SET ready=0,delivered=0 WHERE sequence=1",
            "missing" => "DELETE FROM records WHERE sequence=1",
            _ => "UPDATE replay_steps SET ready=7 WHERE sequence=1",
        })
        .unwrap();
        drop(db);
        let before = fs::read(root.0.join("runtime.sqlite3")).unwrap();
        assert!(runtime.verify_replay_refs(&refs).is_err(), "{fault}");
        assert_eq!(fs::read(root.0.join("runtime.sqlite3")).unwrap(), before);
        drop(runtime);
        drop(root);
    }
}
#[cfg(target_os = "linux")]
#[test]
fn read_only_step_callback_mutation_cannot_reuse_a_binding_codec_as_a_source_cut() {
    let (mut runtime, root, _) = fixture(true, false);
    runtime.save_checkpoint().unwrap();
    drop(runtime);
    let source = VerifiedReplaySnapshot::read(&root.0, support::config(), &"b".repeat(64)).unwrap();
    let mut calls = 0;
    let result = source.for_each_step(|_, _| {
        calls += 1;
        let db = rusqlite::Connection::open(root.0.join("runtime.sqlite3")).unwrap();
        db.execute_batch("UPDATE replay_binding SET head=99")
            .unwrap();
        Ok(())
    });
    assert_eq!(calls, 1);
    assert!(result.is_err());
    drop(source);
    drop(root);
}
