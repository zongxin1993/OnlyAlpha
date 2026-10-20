const FIXTURE: &str = include_str!("../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE: &str = include_str!("../../../test-data/settlement/common-v1.json");
#[path = "../../../crates/onlyalpha-kernel/execution/tests/support/mod.rs"]
mod support;
use onlyalpha_execution::{Components, Store, coordinate, digest, pending_events};
use onlyalpha_runtime_persistence::{Runtime, SqliteStore};
use serde_json::{Value, json};
use std::{
    fs,
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};
use support::*;
static NEXT: AtomicU64 = AtomicU64::new(0);
struct Root(PathBuf);
impl Root {
    fn new() -> Self {
        let p = std::env::temp_dir().join(format!(
            "oa-runtime-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&p).unwrap();
        Self(p)
    }
    fn db(&self) -> PathBuf {
        self.0.join("runtime.sqlite3")
    }
}
impl Drop for Root {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}
fn artifact() -> String {
    "b".repeat(64)
}
fn inputs() -> Vec<Value> {
    vec![
        open(1, "BUY"),
        stage(2, 1, "UNKNOWN"),
        fill(3, 1, "1", "10.00", "1.00"),
        terminal(4, 1, "CANCELLED"),
    ]
}
fn hash(v: &Value) -> String {
    digest(v.to_string().as_bytes())
}
fn manifest() -> Value {
    json!({"schema_version":1,"configuration":hash(&config()),"kernel_artifact":artifact(),"input_pin":"c".repeat(64),"initial_time":{"schema_version":1,"unix_nanos":0},"final_time":{"schema_version":1,"unix_nanos":100},"inputs":inputs().iter().map(hash).collect::<Vec<_>>()})
}
fn result(r: &Runtime) -> Value {
    r.backtest_result(
        &manifest(),
        &json!({"schema_version":1,"status":"COMPLETED","reason":null}),
    )
    .unwrap()
    .record()
}
#[test]
fn exact_reopen_and_missing_store_are_distinct() {
    let p = Root::new();
    assert!(Runtime::open(&p.0, config(), &artifact()).is_err());
    assert!(!p.db().exists());
    let mut r = Runtime::create(&p.0, config(), &artifact()).unwrap();
    assert!(Runtime::create(&p.0, config(), &artifact()).is_err());
    assert!(Runtime::open(&p.0, config(), &artifact()).is_err());
    for v in inputs() {
        r.apply(&v).unwrap();
    }
    let cp = r.save_checkpoint().unwrap();
    let value = result(&r);
    let state = r.state().unwrap();
    let events = r.pending_events().unwrap();
    assert!(!events.is_empty());
    assert_eq!(value["final_account"]["equity"], "999.00");
    assert_eq!(value["reconciliation"]["status"], "MATCHED");
    let records = r.records().unwrap();
    r.apply(&inputs()[0]).unwrap();
    assert_eq!(r.records().unwrap(), records);
    r.acknowledge(4).unwrap();
    let ev = r.pending_events().unwrap();
    assert!(ev.len() < events.len());
    assert_eq!(result(&r), value);
    drop(r);
    let mut r = Runtime::open(&p.0, config(), &artifact()).unwrap();
    assert_eq!(r.state().unwrap(), state);
    assert_eq!(r.save_checkpoint().unwrap(), cp);
    assert_eq!(result(&r), value);
    assert_eq!(r.pending_events().unwrap(), ev);
    drop(r);
    let bytes = fs::read(p.db()).unwrap();
    let mut wrong = config();
    wrong["generation"] = json!("d".repeat(64));
    assert!(Runtime::open(&p.0, wrong, &artifact()).is_err());
    assert!(Runtime::open(&p.0, config(), &"e".repeat(64)).is_err());
    assert_eq!(fs::read(p.db()).unwrap(), bytes);
}
#[test]
fn every_projection_cut_recovers_complete_causal_history() {
    for cut in 0..=6 {
        let p = Root::new();
        let mut s = SqliteStore::create(&p.0, config(), &artifact()).unwrap();
        let mut c = Components::new(config()).unwrap();
        for v in inputs().into_iter().take(2) {
            let plan = c.prepare(&s, &v).unwrap();
            coordinate(&mut s, &mut c, &plan).unwrap();
        }
        s.save_checkpoint(&c).unwrap();
        let v = inputs()[2].clone();
        let plan = c.prepare(&s, &v).unwrap();
        struct Cut<'a> {
            s: &'a mut SqliteStore,
        }
        impl Store for Cut<'_> {
            fn head(&self) -> Result<u64, onlyalpha_execution::Error> {
                self.s.head()
            }
            fn get(
                &self,
                n: u64,
            ) -> Result<Option<onlyalpha_execution::Record>, onlyalpha_execution::Error>
            {
                self.s.get(n)
            }
            fn commit(
                &mut self,
                i: &onlyalpha_execution::CommitIntent,
            ) -> Result<onlyalpha_execution::Record, onlyalpha_execution::Error> {
                let r = self.s.commit(i)?;
                Err(onlyalpha_execution::Error(format!(
                    "unknown-after-{}",
                    r.prepared().sequence()
                )))
            }
            fn mark_ready(&mut self, n: u64) -> Result<(), onlyalpha_execution::Error> {
                self.s.mark_ready(n)
            }
            fn acknowledge(&mut self, n: u64) -> Result<(), onlyalpha_execution::Error> {
                self.s.acknowledge(n)
            }
        }
        assert!(coordinate(&mut Cut { s: &mut s }, &mut c, &plan).is_err());
        assert!(!s.get(3).unwrap().unwrap().ready());
        for i in 0..cut {
            c.install_projection(&s, &plan, i).unwrap();
        }
        assert!(s.save_checkpoint(&c).is_err());
        assert_eq!(pending_events(&s, &c).unwrap().len(), 2);
        drop(s);
        let mut r = Runtime::open(&p.0, config(), &artifact()).unwrap();
        r.apply(&v).unwrap();
        r.apply(&inputs()[3]).unwrap();
        assert_eq!(r.records().unwrap().len(), 4);
        assert_eq!(result(&r)["final_account"]["equity"], "999.00");
        r.save_checkpoint().unwrap();
    }
}
#[test]
fn corruption_and_missing_prior_fact_never_accept_a_current_checkpoint() {
    for sql in [
        "DELETE FROM records WHERE sequence=1",
        "UPDATE records SET digest='bad' WHERE sequence=1",
        "UPDATE records SET input_id='foreign' WHERE sequence=1",
        "UPDATE checkpoints SET digest='bad'",
        "UPDATE state SET head=100",
        "PRAGMA user_version=99",
        "DROP TABLE records",
    ] {
        let p = Root::new();
        let mut r = Runtime::create(&p.0, config(), &artifact()).unwrap();
        for v in inputs() {
            r.apply(&v).unwrap();
        }
        r.save_checkpoint().unwrap();
        drop(r);
        let db = rusqlite::Connection::open(p.db()).unwrap();
        db.execute_batch(sql).unwrap();
        drop(db);
        let bytes = fs::read(p.db()).unwrap();
        assert!(Runtime::open(&p.0, config(), &artifact()).is_err(), "{sql}");
        assert_eq!(fs::read(p.db()).unwrap(), bytes, "{sql}");
    }
}
#[test]
fn empty_or_foreign_database_is_not_initialized_on_open() {
    for sql in ["", "CREATE TABLE execution_store_metadata(x TEXT)"] {
        let p = Root::new();
        let db = rusqlite::Connection::open(p.db()).unwrap();
        db.execute_batch(sql).unwrap();
        drop(db);
        let before = fs::read(p.db()).unwrap();
        assert!(Runtime::open(&p.0, config(), &artifact()).is_err());
        assert_eq!(before, fs::read(p.db()).unwrap());
    }
}
#[test]
fn process_writer() {
    use std::io::{BufRead, Write};
    let Ok(root) = std::env::var("OA_RUNTIME_PROCESS_ROOT") else {
        return;
    };
    let mode = std::env::var("OA_RUNTIME_PROCESS_MODE").unwrap();
    if let Some(cut) = mode.strip_prefix("cut-") {
        let cut: usize = cut.parse().unwrap();
        let mut s =
            SqliteStore::create(std::path::Path::new(&root), config(), &artifact()).unwrap();
        let mut c = Components::new(config()).unwrap();
        for v in inputs().into_iter().take(2) {
            let p = c.prepare(&s, &v).unwrap();
            coordinate(&mut s, &mut c, &p).unwrap();
        }
        s.save_checkpoint(&c).unwrap();
        struct Unknown<'a>(&'a mut SqliteStore);
        impl Store for Unknown<'_> {
            fn head(&self) -> Result<u64, onlyalpha_execution::Error> {
                self.0.head()
            }
            fn get(
                &self,
                n: u64,
            ) -> Result<Option<onlyalpha_execution::Record>, onlyalpha_execution::Error>
            {
                self.0.get(n)
            }
            fn commit(
                &mut self,
                i: &onlyalpha_execution::CommitIntent,
            ) -> Result<onlyalpha_execution::Record, onlyalpha_execution::Error> {
                self.0.commit(i)?;
                Err(onlyalpha_execution::Error("UNKNOWN".into()))
            }
            fn mark_ready(&mut self, n: u64) -> Result<(), onlyalpha_execution::Error> {
                self.0.mark_ready(n)
            }
            fn acknowledge(&mut self, n: u64) -> Result<(), onlyalpha_execution::Error> {
                self.0.acknowledge(n)
            }
        }
        let p = c.prepare(&s, &inputs()[2]).unwrap();
        assert!(coordinate(&mut Unknown(&mut s), &mut c, &p).is_err());
        for i in 0..cut {
            c.install_projection(&s, &p, i).unwrap();
        }
        println!("\nBARRIER");
        std::io::stdout().flush().unwrap();
        let mut line = String::new();
        std::io::stdin().lock().read_line(&mut line).unwrap();
        drop(s);
    } else {
        let mut r = Runtime::create(std::path::Path::new(&root), config(), &artifact()).unwrap();
        for v in inputs() {
            r.apply(&v).unwrap();
        }
        r.save_checkpoint().unwrap();
        if mode == "ack" {
            for n in 1..=4 {
                r.acknowledge(n).unwrap();
            }
        }
        println!("\nBARRIER");
        std::io::stdout().flush().unwrap();
        let mut line = String::new();
        std::io::stdin().lock().read_line(&mut line).unwrap();
        drop(r);
    }
}
#[test]
fn killed_writer_releases_lease_and_restores_identical_result_and_outbox() {
    use std::{
        io::{BufRead, BufReader},
        process::{Command, Stdio},
    };
    let baseline = Root::new();
    let mut b = Runtime::create(&baseline.0, config(), &artifact()).unwrap();
    for v in inputs() {
        b.apply(&v).unwrap();
    }
    let expected = result(&b);
    let expected_events = b.pending_events().unwrap();
    for mode in (0..=6)
        .map(|n| format!("cut-{n}"))
        .chain(["ready".into(), "ack".into()])
    {
        let p = Root::new();
        let mut child = Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "process_writer", "--nocapture"])
            .env("OA_RUNTIME_PROCESS_ROOT", &p.0)
            .env("OA_RUNTIME_PROCESS_MODE", &mode)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .unwrap();
        let mut reader = BufReader::new(child.stdout.take().unwrap());
        loop {
            let mut line = String::new();
            assert!(
                reader.read_line(&mut line).unwrap() > 0,
                "child exited before barrier {mode}"
            );
            if line.trim() == "BARRIER" {
                break;
            }
        }
        assert!(Runtime::open(&p.0, config(), &artifact()).is_err());
        child.kill().unwrap();
        let status = child.wait().unwrap();
        assert!(!status.success());
        let mut r = Runtime::open(&p.0, config(), &artifact()).unwrap();
        for v in inputs() {
            r.apply(&v).unwrap();
        }
        assert_eq!(result(&r), expected, "{mode}");
        assert_eq!(r.records().unwrap().len(), 4);
        assert_eq!(
            r.pending_events().unwrap(),
            if mode == "ack" {
                vec![]
            } else {
                expected_events.clone()
            },
            "{mode}"
        );
    }
}
#[test]
fn sqlite_failure_rolls_back_all_commit_data_and_requires_explicit_recovery() {
    let p = Root::new();
    let mut r = Runtime::create(&p.0, config(), &artifact()).unwrap();
    let db = rusqlite::Connection::open(p.db()).unwrap();
    db.execute_batch(
        "CREATE TRIGGER injected BEFORE UPDATE ON state BEGIN SELECT RAISE(ABORT,'injected'); END",
    )
    .unwrap();
    assert!(r.apply(&inputs()[0]).is_err());
    assert!(r.state().is_err());
    assert!(r.pending_events().is_err());
    assert_eq!(
        db.query_row("SELECT count(*) FROM records", [], |r| r.get::<_, i64>(0))
            .unwrap(),
        0
    );
    db.execute_batch("DROP TRIGGER injected").unwrap();
    drop(db);
    r.recover().unwrap();
    r.apply(&inputs()[0]).unwrap();
    assert_eq!(r.records().unwrap().len(), 1);
}
#[test]
fn rehashed_checkpoint_mutations_and_wrong_result_artifact_fail_closed() {
    for mutation in 0..7 {
        let p = Root::new();
        let mut r = Runtime::create(&p.0, config(), &artifact()).unwrap();
        for v in inputs() {
            r.apply(&v).unwrap();
        }
        let mut cp = r.save_checkpoint().unwrap();
        let mut foreign = manifest();
        foreign["kernel_artifact"] = json!("e".repeat(64));
        assert!(
            r.backtest_result(
                &foreign,
                &json!({"schema_version":1,"status":"COMPLETED","reason":null})
            )
            .is_err()
        );
        drop(r);
        match mutation {
            0 => cp["identity"] = json!("d".repeat(64)),
            1 => cp["sequence"] = json!(3),
            2 => cp["source"] = json!("d".repeat(64)),
            3 => cp["components"]["config"]["account"] = json!("foreign"),
            4 => cp["components"]["components"][0] = cp["components"]["components"][1].clone(),
            5 => cp["components"]["components"]
                .as_array_mut()
                .unwrap()
                .pop()
                .map(|_| ())
                .unwrap(),
            _ => cp["family"] = json!("FOREIGN"),
        };
        let db = rusqlite::Connection::open(p.db()).unwrap();
        db.execute(
            "UPDATE checkpoints SET payload=?1,digest=?2",
            rusqlite::params![cp.to_string(), hash(&cp)],
        )
        .unwrap();
        drop(db);
        let before = fs::read(p.db()).unwrap();
        assert!(
            Runtime::open(&p.0, config(), &artifact()).is_err(),
            "{mutation}"
        );
        assert_eq!(before, fs::read(p.db()).unwrap());
    }
}
#[test]
fn rehashed_fact_scope_source_leaf_and_owner_mutations_are_not_recovery_evidence() {
    for mutation in 0..6 {
        let p = Root::new();
        let mut r = Runtime::create(&p.0, config(), &artifact()).unwrap();
        for v in inputs() {
            r.apply(&v).unwrap();
        }
        drop(r);
        let db = rusqlite::Connection::open(p.db()).unwrap();
        let raw: String = db
            .query_row("SELECT payload FROM records WHERE sequence=4", [], |r| {
                r.get(0)
            })
            .unwrap();
        let mut v: Value = serde_json::from_str(&raw).unwrap();
        let prepared = &mut v["prepared"];
        match mutation {
            0 => prepared["input"]["generation"] = json!("d".repeat(64)),
            1 => prepared["input"]["account"] = json!("foreign"),
            2 => prepared["input"]["source_ref"] = json!("foreign-source"),
            3 => prepared["input"]["payload"]["order"] = json!("foreign-order"),
            4 => prepared["input"]["cluster"] = json!("foreign"),
            _ => prepared["input"]["revision"] = json!("foreign"),
        };
        let id = format!("ETX-{}", hash(&prepared["input"]));
        prepared["transaction_id"] = json!(id);
        prepared["events"][0] = json!({"schema_version":1,"event_id":format!("{id}-EVENT-1"),"transaction_id":id,"sequence":4,"input":prepared["input"]});
        prepared.as_object_mut().unwrap().remove("payload_hash");
        prepared["payload_hash"] = json!(hash(prepared));
        let last = hash(prepared);
        db.execute(
            "UPDATE records SET payload=?1,digest=?2 WHERE sequence=4",
            rusqlite::params![v.to_string(), hash(&v)],
        )
        .unwrap();
        db.execute("UPDATE state SET last_hash=?1", [last]).unwrap();
        drop(db);
        let before = fs::read(p.db()).unwrap();
        assert!(
            Runtime::open(&p.0, config(), &artifact()).is_err(),
            "{mutation}"
        );
        assert_eq!(before, fs::read(p.db()).unwrap());
    }
}
#[test]
fn conflicting_input_never_becomes_another_transaction() {
    let p = Root::new();
    let mut r = Runtime::create(&p.0, config(), &artifact()).unwrap();
    r.apply(&inputs()[0]).unwrap();
    let original = r.records().unwrap();
    let mut wrong = inputs()[0].clone();
    wrong["source_ref"] = json!("different");
    assert!(r.apply(&wrong).is_err());
    assert!(r.records().is_err());
    r.recover().unwrap();
    assert_eq!(r.records().unwrap(), original);
    r.apply(&inputs()[0]).unwrap();
    assert_eq!(r.records().unwrap(), original);
    assert!(r.acknowledge(0).is_err());
    r.recover().unwrap();
    assert!(r.acknowledge(2).is_err());
    r.recover().unwrap();
    assert_eq!(r.records().unwrap(), original);
}

#[cfg(unix)]
#[test]
fn regression_hard_link_alias_cannot_reopen_a_database_under_a_different_journal_locator() {
    let p = Root::new();
    let alias = Root::new();
    drop(Runtime::create(&p.0, config(), &artifact()).unwrap());
    fs::hard_link(p.db(), alias.db()).unwrap();
    assert!(Runtime::open(&alias.0, config(), &artifact()).is_err());
    assert!(Runtime::open(&p.0, config(), &artifact()).is_err());
}
#[test]
fn regression_live_reader_revalidates_causal_source_after_a_rehashed_row_change() {
    let p = Root::new();
    let mut r = Runtime::create(&p.0, config(), &artifact()).unwrap();
    for v in inputs() {
        r.apply(&v).unwrap();
    }
    r.state().unwrap();
    r.records().unwrap();
    let mut db = rusqlite::Connection::open(p.db()).unwrap();
    let raw: String = db
        .query_row("SELECT payload FROM records WHERE sequence=4", [], |r| {
            r.get(0)
        })
        .unwrap();
    let mut v: Value = serde_json::from_str(&raw).unwrap();
    let prepared = &mut v["prepared"];
    prepared["input"]["source_ref"] = json!("changed-after-open");
    let id = format!("ETX-{}", hash(&prepared["input"]));
    prepared["transaction_id"] = json!(id);
    prepared["events"][0] = json!({"schema_version":1,"event_id":format!("{id}-EVENT-1"),"transaction_id":id,"sequence":4,"input":prepared["input"]});
    prepared.as_object_mut().unwrap().remove("payload_hash");
    prepared["payload_hash"] = json!(hash(prepared));
    let last = hash(prepared);
    let tx = db.transaction().unwrap();
    tx.execute(
        "UPDATE records SET payload=?1,digest=?2 WHERE sequence=4",
        rusqlite::params![v.to_string(), hash(&v)],
    )
    .unwrap();
    tx.execute("UPDATE state SET last_hash=?1", [last]).unwrap();
    tx.commit().unwrap();
    drop(db);
    assert!(r.state().is_err());
    assert!(r.records().is_err());
    assert!(r.pending_events().is_err());
    assert!(r.recover().is_err());
}

#[test]
fn foreign_history_commit_intent_is_rejected_before_destination_mutation() {
    use onlyalpha_execution::{CommitIntent, Error, Record};
    let a = Root::new();
    let b = Root::new();
    let mut source = SqliteStore::create(&a.0, config(), &artifact()).unwrap();
    let mut destination = SqliteStore::create(&b.0, config(), &artifact()).unwrap();
    let mut ca = Components::new(config()).unwrap();
    let mut cb = Components::new(config()).unwrap();
    let first = open(1, "BUY");
    let mut other = first.clone();
    other["input_id"] = json!("other-prefix");
    other["source_ref"] = json!("other-prefix-source");
    let p = ca.prepare(&source, &first).unwrap();
    coordinate(&mut source, &mut ca, &p).unwrap();
    let p = cb.prepare(&destination, &other).unwrap();
    coordinate(&mut destination, &mut cb, &p).unwrap();
    assert_eq!(source.head().unwrap(), destination.head().unwrap());
    struct Forward<'a> {
        source: &'a SqliteStore,
        destination: &'a mut SqliteStore,
    }
    impl Store for Forward<'_> {
        fn head(&self) -> Result<u64, Error> {
            self.source.head()
        }
        fn get(&self, n: u64) -> Result<Option<Record>, Error> {
            self.source.get(n)
        }
        fn commit(&mut self, intent: &CommitIntent) -> Result<Record, Error> {
            self.destination.commit(intent)
        }
        fn mark_ready(&mut self, _: u64) -> Result<(), Error> {
            panic!("wrong-source commit must not reach projection readiness")
        }
        fn acknowledge(&mut self, _: u64) -> Result<(), Error> {
            panic!("no external delivery in commit test")
        }
    }
    let before = fs::read(b.db()).unwrap();
    let p = ca.prepare(&source, &stage(2, 1, "UNKNOWN")).unwrap();
    assert!(
        coordinate(
            &mut Forward {
                source: &source,
                destination: &mut destination
            },
            &mut ca,
            &p
        )
        .is_err()
    );
    assert_eq!(destination.head().unwrap(), 1);
    assert_eq!(fs::read(b.db()).unwrap(), before);
    drop(destination);
    assert_eq!(
        Runtime::open(&b.0, config(), &artifact())
            .unwrap()
            .records()
            .unwrap()
            .len(),
        1
    );
}

#[test]
fn explicit_schema_migration_retains_exact_history_and_checkpoint() {
    let p = Root::new();
    let mut r = Runtime::create(&p.0, config(), &artifact()).unwrap();
    for v in inputs() {
        r.apply(&v).unwrap();
    }
    let cp = r.save_checkpoint().unwrap();
    let expected = result(&r);
    let state = r.state().unwrap();
    let events = r.pending_events().unwrap();
    drop(r);
    let db = rusqlite::Connection::open(p.db()).unwrap();
    db.execute_batch("DROP TABLE replay_steps; DROP TABLE replay_binding; PRAGMA user_version=1;")
        .unwrap();
    drop(db);
    let old = fs::read(p.db()).unwrap();
    assert!(Runtime::open(&p.0, config(), &artifact()).is_err());
    assert_eq!(old, fs::read(p.db()).unwrap());
    let mut foreign = config();
    foreign["generation"] = json!("d".repeat(64));
    assert!(SqliteStore::migrate(&p.0, foreign, &artifact()).is_err());
    assert_eq!(old, fs::read(p.db()).unwrap());
    let migrated = SqliteStore::migrate(&p.0, config(), &artifact()).unwrap();
    assert_eq!(migrated.head().unwrap(), 4);
    drop(migrated);
    let mut current = Runtime::open(&p.0, config(), &artifact()).unwrap();
    assert_eq!(current.state().unwrap(), state);
    assert_eq!(current.save_checkpoint().unwrap(), cp);
    assert_eq!(current.pending_events().unwrap(), events);
    assert_eq!(result(&current), expected);
    drop(current);
    let bytes = fs::read(p.db()).unwrap();
    assert!(SqliteStore::migrate(&p.0, config(), &artifact()).is_err());
    assert_eq!(bytes, fs::read(p.db()).unwrap());
}
