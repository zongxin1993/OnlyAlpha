const FIXTURE: &str = include_str!("../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE: &str = include_str!("../../../test-data/settlement/common-v1.json");
#[path = "../../execution/tests/support/mod.rs"]
mod support;
use onlyalpha_execution::digest;
use onlyalpha_runtime::Runtime;
use serde_json::json;
use std::{fs, path::PathBuf};
#[test]
fn replay_journal_binds_work_and_rejects_unrelated_execution() {
    let root = PathBuf::from(std::env::var("CARGO_TARGET_DIR").unwrap())
        .join(format!("replay-journal-{}", std::process::id()));
    fs::create_dir_all(&root).unwrap();
    let cfg = support::config();
    let binding = json!({"schema_version":1,"configuration":digest(cfg.to_string().as_bytes()),"kernel_artifact":"b".repeat(64),"driver_artifact":"f".repeat(64),"work":"c".repeat(64),"input_pin":"d".repeat(64),"program":"e".repeat(64),"initial_state":{"cursor":0}});
    let mut runtime = Runtime::create(&root, cfg.clone(), &"b".repeat(64)).unwrap();
    runtime.bind_replay(&binding).unwrap();
    assert!(runtime.replay_steps().unwrap().is_empty());
    let mut foreign = binding.clone();
    foreign["work"] = json!("f".repeat(64));
    assert!(runtime.bind_replay(&foreign).is_err());
    drop(runtime);
    let mut runtime = Runtime::open(&root, cfg, &"b".repeat(64)).unwrap();
    runtime.bind_replay(&binding).unwrap();
    assert!(runtime.replay_steps().unwrap().is_empty());
    drop(runtime);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn deleted_zero_execution_tail_is_not_a_valid_shorter_history() {
    let root = std::env::temp_dir().join(format!("oa-replay-tail-{}", std::process::id()));
    fs::create_dir(&root).unwrap();
    let cfg = support::config();
    let artifact = "b".repeat(64);
    let binding = json!({"schema_version":1,"configuration":digest(cfg.to_string().as_bytes()),"kernel_artifact":artifact,"driver_artifact":"f".repeat(64),"work":"c".repeat(64),"input_pin":"d".repeat(64),"program":"e".repeat(64),"initial_state":{"cursor":0}});
    let mut runtime = Runtime::create(&root, cfg.clone(), &artifact).unwrap();
    runtime.bind_replay(&binding).unwrap();
    let step = json!({"schema_version":1,"index":1,"previous":digest(binding.to_string().as_bytes()),"execution_start":0,"cause":{"kind":"BAR"},"inputs":[],"state":{"cursor":1}});
    runtime.prepare_replay(&step).unwrap();
    runtime.complete_replay(1).unwrap();
    drop(runtime);
    let db = rusqlite::Connection::open(root.join("runtime.sqlite3")).unwrap();
    db.execute("DELETE FROM replay_steps", []).unwrap();
    drop(db);
    let mut runtime = Runtime::open(&root, cfg, &artifact).unwrap();
    assert!(runtime.bind_replay(&binding).is_err());
    drop(runtime);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn journal_step_and_anchor_roll_back_together_on_sql_failure() {
    let root = std::env::temp_dir().join(format!("oa-replay-rollback-{}", std::process::id()));
    fs::create_dir(&root).unwrap();
    let cfg = support::config();
    let artifact = "b".repeat(64);
    let binding = json!({"schema_version":1,"configuration":digest(cfg.to_string().as_bytes()),"kernel_artifact":artifact,"driver_artifact":"f".repeat(64),"work":"c".repeat(64),"input_pin":"d".repeat(64),"program":"e".repeat(64),"initial_state":{"cursor":0}});
    let mut runtime = Runtime::create(&root, cfg.clone(), &artifact).unwrap();
    runtime.bind_replay(&binding).unwrap();
    let step = json!({"schema_version":1,"index":1,"previous":digest(binding.to_string().as_bytes()),"execution_start":0,"cause":{"kind":"BAR"},"inputs":[],"state":{"cursor":1}});
    let db = rusqlite::Connection::open(root.join("runtime.sqlite3")).unwrap();
    db.execute_batch("CREATE TRIGGER injected BEFORE UPDATE ON replay_binding BEGIN SELECT RAISE(ABORT,'injected'); END").unwrap();
    assert!(runtime.prepare_replay(&step).is_err());
    assert!(
        runtime.replay_steps().is_err(),
        "a failed write requires explicit recovery even when its transaction rolled back"
    );
    assert_eq!(
        db.query_row("SELECT count(*) FROM replay_steps", [], |r| r
            .get::<_, i64>(0))
            .unwrap(),
        0
    );
    db.execute_batch("DROP TRIGGER injected").unwrap();
    drop(db);
    runtime.recover().unwrap();
    assert!(runtime.replay_steps().unwrap().is_empty());
    runtime.prepare_replay(&step).unwrap();
    runtime.complete_replay(1).unwrap();
    drop(runtime);
    let mut reopened = Runtime::open(&root, cfg, &artifact).unwrap();
    reopened.bind_replay(&binding).unwrap();
    assert_eq!(reopened.replay_steps().unwrap().len(), 1);
    drop(reopened);
    fs::remove_dir_all(root).unwrap();
}

fn pending_completion_cut(name: &str) -> (PathBuf, Runtime, serde_json::Value) {
    let root = std::env::temp_dir().join(format!(
        "oa-replay-operation-cut-{}-{name}",
        std::process::id()
    ));
    fs::create_dir(&root).unwrap();
    let cfg = support::config();
    let artifact = "b".repeat(64);
    let binding = json!({"schema_version":1,"configuration":digest(cfg.to_string().as_bytes()),"kernel_artifact":artifact,"driver_artifact":"f".repeat(64),"work":"c".repeat(64),"input_pin":"d".repeat(64),"program":"e".repeat(64),"initial_state":{"cursor":0}});
    let mut runtime = Runtime::create(&root, cfg, &artifact).unwrap();
    runtime.bind_replay(&binding).unwrap();
    let step = json!({"schema_version":1,"index":1,"previous":digest(binding.to_string().as_bytes()),"execution_start":0,"cause":{"kind":"BAR"},"inputs":[],"state":{"cursor":1}});
    runtime.prepare_replay(&step).unwrap();
    (root, runtime, step)
}
#[test]
fn completion_rows_are_the_actual_post_write_cut_and_are_not_next_call_authority() {
    let (root, mut runtime, step) = pending_completion_cut("actual");
    let completed = runtime.complete_replay_rows(1, &step).unwrap();
    assert_eq!(completed, vec![json!({"step":step,"ready":true})]);
    assert_eq!(runtime.replay_steps().unwrap(), completed);
    let db = rusqlite::Connection::open(root.join("runtime.sqlite3")).unwrap();
    db.execute("UPDATE replay_steps SET ready=0 WHERE sequence=1", [])
        .unwrap();
    drop(db);
    let bytes = fs::read(root.join("runtime.sqlite3")).unwrap();
    let fresh = runtime.replay_steps().unwrap();
    assert_eq!(fresh[0]["ready"], false);
    assert_eq!(fresh[0]["step"], step);
    assert_eq!(
        completed[0]["ready"], true,
        "a returned value remains an observation of its past cut"
    );
    assert_eq!(
        fs::read(root.join("runtime.sqlite3")).unwrap(),
        bytes,
        "reading new source does not heal it from the old value"
    );
    drop(runtime);
    fs::remove_dir_all(root).unwrap();
}
#[test]
fn completion_expected_value_cannot_create_a_different_ready_proposal() {
    let (root, mut runtime, step) = pending_completion_cut("foreign");
    let mut expected = step.clone();
    expected["state"]["cursor"] = json!(2);
    let bytes = fs::read(root.join("runtime.sqlite3")).unwrap();
    assert!(runtime.complete_replay_rows(1, &expected).is_err());
    assert_eq!(
        fs::read(root.join("runtime.sqlite3")).unwrap(),
        bytes,
        "mismatched expectation must be refused before Ready mutation"
    );
    assert!(
        runtime.replay_steps().is_err(),
        "a failed completion retains the original recovery boundary"
    );
    runtime.recover().unwrap();
    assert_eq!(
        runtime.replay_steps().unwrap()[0],
        json!({"step":step,"ready":false})
    );
    let _: () = runtime.complete_replay(1).unwrap();
    assert_eq!(
        runtime.replay_steps().unwrap()[0],
        json!({"step":step,"ready":true})
    );
    drop(runtime);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn committed_prepare_readback_fault_keeps_the_original_step_behind_explicit_recovery() {
    let root =
        std::env::temp_dir().join(format!("oa-replay-prepare-sticky-{}", std::process::id()));
    fs::create_dir(&root).unwrap();
    let cfg = support::config();
    let artifact = "b".repeat(64);
    let binding = json!({"schema_version":1,"configuration":digest(cfg.to_string().as_bytes()),"kernel_artifact":artifact,"driver_artifact":"f".repeat(64),"work":"c".repeat(64),"input_pin":"d".repeat(64),"program":"e".repeat(64),"initial_state":{"cursor":0}});
    let step = json!({"schema_version":1,"index":1,"previous":digest(binding.to_string().as_bytes()),"execution_start":0,"cause":{"kind":"BAR"},"inputs":[],"state":{"cursor":1}});
    let mut runtime = Runtime::create(&root, cfg, &artifact).unwrap();
    runtime.bind_replay(&binding).unwrap();
    let path = root.join("runtime.sqlite3");
    let db = rusqlite::Connection::open(&path).unwrap();
    db.execute_batch("CREATE TRIGGER prepare_readback_fault AFTER INSERT ON replay_steps BEGIN UPDATE replay_steps SET ready=1 WHERE sequence=NEW.sequence; END").unwrap();
    assert!(runtime.prepare_replay(&step).is_err());
    let committed: (i64, String, String, i64) = db
        .query_row(
            "SELECT sequence,payload,digest,ready FROM replay_steps",
            [],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
        )
        .unwrap();
    assert_eq!(
        (committed.0, committed.3),
        (1, 1),
        "the failure occurs after the original proposal was committed"
    );
    let logical = digest(step.to_string().as_bytes());
    let anchor: (i64, String) = db
        .query_row("SELECT head,last_hash FROM replay_binding", [], |row| {
            Ok((row.get(0)?, row.get(1)?))
        })
        .unwrap();
    assert_eq!(anchor, (1, logical.clone()));
    db.execute_batch(
        "DROP TRIGGER prepare_readback_fault; UPDATE replay_steps SET ready=0 WHERE sequence=1",
    )
    .unwrap();
    drop(db);
    let restored = fs::read(&path).unwrap();
    assert!(
        runtime.state().is_err(),
        "restoring the SQL source cannot silently reopen a failed Runtime"
    );
    assert!(runtime.records().is_err());
    assert!(runtime.pending_events().is_err());
    assert!(runtime.replay_steps().is_err());
    assert!(runtime.prepare_replay(&step).is_err());
    assert!(runtime.complete_replay(1).is_err());
    assert_eq!(
        fs::read(&path).unwrap(),
        restored,
        "closed operations cannot duplicate or complete the original proposal"
    );
    runtime.recover().unwrap();
    assert_eq!(
        runtime.replay_steps().unwrap(),
        vec![json!({"step":step,"ready":false})]
    );
    runtime.prepare_replay(&step).unwrap();
    runtime.complete_replay(1).unwrap();
    assert_eq!(
        runtime.replay_steps().unwrap(),
        vec![json!({"step":step,"ready":true})]
    );
    let db = rusqlite::Connection::open(&path).unwrap();
    let retained: (i64, String, String, i64) = db
        .query_row(
            "SELECT sequence,payload,digest,ready FROM replay_steps",
            [],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
        )
        .unwrap();
    assert_eq!(
        retained,
        (committed.0, committed.1, committed.2, 1),
        "recovery retains the same immutable payload and physical identity"
    );
    assert_eq!(
        db.query_row("SELECT count(*) FROM replay_steps", [], |row| row
            .get::<_, i64>(0))
            .unwrap(),
        1
    );
    assert_eq!(
        db.query_row("SELECT last_hash FROM replay_binding", [], |row| row
            .get::<_, String>(0))
            .unwrap(),
        logical
    );
    drop(db);
    drop(runtime);
    fs::remove_dir_all(root).unwrap();
}
