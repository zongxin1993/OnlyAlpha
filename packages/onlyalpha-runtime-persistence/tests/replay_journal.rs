const FIXTURE: &str = include_str!("../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE: &str = include_str!("../../../test-data/settlement/common-v1.json");
#[path = "../../../crates/onlyalpha-kernel/execution/tests/support/mod.rs"]
mod support;
use onlyalpha_execution::digest;
use onlyalpha_runtime_persistence::Runtime;
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
    assert!(runtime.replay_steps().unwrap().is_empty());
    assert_eq!(
        db.query_row("SELECT count(*) FROM replay_steps", [], |r| r
            .get::<_, i64>(0))
            .unwrap(),
        0
    );
    db.execute_batch("DROP TRIGGER injected").unwrap();
    drop(db);
    runtime.prepare_replay(&step).unwrap();
    runtime.complete_replay(1).unwrap();
    drop(runtime);
    let mut reopened = Runtime::open(&root, cfg, &artifact).unwrap();
    reopened.bind_replay(&binding).unwrap();
    assert_eq!(reopened.replay_steps().unwrap().len(), 1);
    drop(reopened);
    fs::remove_dir_all(root).unwrap();
}
