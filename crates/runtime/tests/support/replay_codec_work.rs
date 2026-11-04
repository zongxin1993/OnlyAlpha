//! Counts actual full-row JSON decodes, not elapsed time or proof reuse.
//! This synthetic zero-Execution journal grants no Product admission.
use super::*;
use rusqlite::Connection;
use std::{fs, path::PathBuf, sync::atomic::{AtomicU64, Ordering}};

const FIXTURE: &str = include_str!("../../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE: &str = include_str!("../../../../test-data/settlement/common-v1.json");
#[path = "../../../execution/tests/support/mod.rs"]
mod support;

// Explicit empty schema2 fixture: no fact is migrated or rewritten. These
// original raw-codec adversarial vectors retain their original format.
fn legacy_store(root:&std::path::Path,configuration:Value,artifact:&str)->SqliteStore {
 let created=SqliteStore::create(root,configuration.clone(),artifact).unwrap();drop(created);
 let db=Connection::open(root.join("runtime.sqlite3")).unwrap();
 db.execute_batch("DROP TABLE records; CREATE TABLE records (sequence INTEGER PRIMARY KEY CHECK(sequence>0), input_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL, digest TEXT NOT NULL) STRICT;").unwrap();db.pragma_update(None,"user_version",2).unwrap();drop(db);
 SqliteStore::open(root,configuration,artifact).unwrap()
}
static NEXT: AtomicU64 = AtomicU64::new(0);
struct Root(PathBuf);
impl Root {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!("oa-replay-codec-{}-{}", std::process::id(), NEXT.fetch_add(1, Ordering::Relaxed)));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
    fn db(&self) -> PathBuf { self.0.join("runtime.sqlite3") }
}
impl Drop for Root {
    fn drop(&mut self) { fs::remove_dir_all(&self.0).unwrap(); }
}
fn journal() -> (SqliteStore, Root, Vec<Value>) {
    let root = Root::new();
    let configuration = support::config();
    let mut store = legacy_store(&root.0,configuration.clone(),&"b".repeat(64));
    let binding = json!({"schema_version":1,"configuration":hash(&configuration),"kernel_artifact":"b".repeat(64),"driver_artifact":"f".repeat(64),"work":"c".repeat(64),"input_pin":"d".repeat(64),"program":"e".repeat(64),"initial_state":{"cursor":0}});
    store.bind_replay(&binding).unwrap();
    let first = json!({"schema_version":1,"index":1,"previous":hash(&binding),"execution_start":0,"cause":{"kind":"TECHNICAL_CODEC_SOURCE"},"inputs":[],"state":{"cursor":1,"nested":{"tail":["a".repeat(16384),"b".repeat(16384)],"null":null,"decimal":"0.000000001"}}});
    store.prepare_replay(&first).unwrap();
    store.complete_replay(1,&first).unwrap();
    let second = json!({"schema_version":1,"index":2,"previous":hash(&first),"execution_start":0,"cause":{"kind":"TECHNICAL_CODEC_SOURCE"},"inputs":[],"state":{"cursor":2,"nested":{"tail":["c".repeat(16384),"d".repeat(16384)],"null":null,"decimal":"0.000000002"}}});
    store.prepare_replay(&second).unwrap();
    store.complete_replay(2,&second).unwrap();
    (store, root, vec![json!({"step":first,"ready":true}), json!({"step":second,"ready":true})])
}
fn write_step(db: &Connection, sequence: i64, step: &Value) {
    db.execute("UPDATE replay_steps SET payload=?1,digest=?2 WHERE sequence=?3", params![step.to_string(),hash(step),sequence]).unwrap();
}

#[test]
fn unchanged_actual_rows_reuse_decoding_without_aliasing_returned_full_state() {
    let (store, root, expected) = journal();
    REPLAY_STEP_SOURCE_DECODES.with(|count| count.set(0));
    for _ in 0..4 { assert_eq!(store.replay_steps().unwrap(), expected); }
    assert_eq!(REPLAY_STEP_SOURCE_DECODES.with(std::cell::Cell::get), 0,
        "exact already-read SQL row bytes repeatedly decoded the complete participant state");
    let mut returned = store.replay_steps().unwrap();
    returned[0]["step"]["state"]["nested"]["tail"][1] = json!("caller-owned change");
    assert_eq!(store.replay_steps().unwrap(), expected, "returned Values cannot mutate the private codec memo");
    drop(store);
    let reopened = SqliteStore::open(&root.0, support::config(), &"b".repeat(64)).unwrap();
    REPLAY_STEP_SOURCE_DECODES.with(|count| count.set(0));
    assert_eq!(reopened.replay_steps().unwrap(), expected);
    assert_eq!(REPLAY_STEP_SOURCE_DECODES.with(std::cell::Cell::get), 2,
        "a new Store must decode its own actual source, not inherit an earlier proof");
    assert_eq!(reopened.replay_steps().unwrap(), expected);
    assert_eq!(REPLAY_STEP_SOURCE_DECODES.with(std::cell::Cell::get), 2);
    drop(reopened);
}

#[test]
fn fully_rehashed_old_state_is_freshly_decoded_and_visible_to_run_expected_comparison() {
    let (store, root, expected) = journal();
    assert_eq!(store.replay_steps().unwrap(), expected);
    let mut changed = expected.clone();
    changed[0]["step"]["state"]["nested"]["tail"][1] = json!("changed and fully resealed");
    changed[1]["step"]["previous"] = json!(hash(&changed[0]["step"]));
    let db = Connection::open(root.db()).unwrap();
    write_step(&db, 1, &changed[0]["step"]);
    write_step(&db, 2, &changed[1]["step"]);
    db.execute("UPDATE replay_binding SET last_hash=?1", [hash(&changed[1]["step"])]).unwrap();
    drop(db);
    REPLAY_STEP_SOURCE_DECODES.with(|count| count.set(0));
    let observed = store.replay_steps().unwrap();
    assert_eq!(observed, changed);
    assert_ne!(observed, expected, "RunLoop's complete expected-state comparison must receive the actual changed state");
    assert_eq!(REPLAY_STEP_SOURCE_DECODES.with(std::cell::Cell::get), 2,
        "validly rehashed source bytes must not reuse the old decoded state");
    assert_eq!(store.replay_steps().unwrap(), changed);
    assert_eq!(REPLAY_STEP_SOURCE_DECODES.with(std::cell::Cell::get), 2);
    drop(store);
}

#[test]
fn warm_codec_never_authenticates_changed_raw_digest_flags_lineage_or_anchor() {
    for fault in ["raw-with-old-digest", "digest-only", "noncanonical", "older-rehashed-only", "previous", "index", "execution-start", "extra-field", "earlier-unready", "invalid-ready", "missing-tail", "journal-head", "journal-last"] {
        let (store, root, expected) = journal();
        assert_eq!(store.replay_steps().unwrap(), expected);
        let db = Connection::open(root.db()).unwrap();
        match fault {
            "raw-with-old-digest" => {
                let mut step = expected[0]["step"].clone();
                step["state"]["nested"]["tail"][1] = json!("changed full-row tail");
                db.execute("UPDATE replay_steps SET payload=?1 WHERE sequence=1", [step.to_string()]).unwrap();
            }
            "digest-only" => { db.execute("UPDATE replay_steps SET digest=?1 WHERE sequence=1", ["e".repeat(64)]).unwrap(); }
            "noncanonical" => {
                let raw = format!(" {}", expected[0]["step"]);
                db.execute("UPDATE replay_steps SET payload=?1,digest=?2 WHERE sequence=1", params![raw,digest(raw.as_bytes())]).unwrap();
            }
            "older-rehashed-only" => {
                let mut step = expected[0]["step"].clone();
                step["state"]["nested"]["tail"][1] = json!("valid digest with stale descendant");
                write_step(&db, 1, &step);
            }
            "earlier-unready" => { db.execute("UPDATE replay_steps SET ready=0 WHERE sequence=1", []).unwrap(); }
            "invalid-ready" => { db.execute_batch("PRAGMA ignore_check_constraints=ON; UPDATE replay_steps SET ready=2 WHERE sequence=2").unwrap(); }
            "missing-tail" => { db.execute("DELETE FROM replay_steps WHERE sequence=2", []).unwrap(); }
            "journal-head" => { db.execute("UPDATE replay_binding SET head=1", []).unwrap(); }
            "journal-last" => { db.execute("UPDATE replay_binding SET last_hash=?1", ["e".repeat(64)]).unwrap(); }
            _ => {
                let mut step = expected[1]["step"].clone();
                match fault {
                    "previous" => step["previous"] = json!("e".repeat(64)),
                    "index" => step["index"] = json!(3),
                    "execution-start" => step["execution_start"] = json!(1),
                    _ => step["unexpected_field"] = json!({"value":"not in the current schema"}),
                }
                write_step(&db, 2, &step);
                db.execute("UPDATE replay_binding SET last_hash=?1", [hash(&step)]).unwrap();
            }
        }
        drop(db);
        let before = fs::read(root.db()).unwrap();
        assert!(store.replay_steps().is_err(), "warm codec authenticated actual source fault: {fault}");
        assert_eq!(fs::read(root.db()).unwrap(), before, "a denied read cannot repair or rewrite the source");
        drop(store);
    }
}
