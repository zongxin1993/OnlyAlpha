const FIXTURE: &str = include_str!("../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE: &str = include_str!("../../../test-data/settlement/common-v1.json");
#[path = "../../execution/tests/support/mod.rs"]
mod support;
use onlyalpha_execution::{Components, Store, coordinate, digest, pending_events};
use onlyalpha_runtime::{Runtime, SqliteStore};
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
// Test-only physical codec helpers preserve the original semantic adversary;
// they construct no opaque reference, prepared origin or publication grant.
// Reuse the actual private pure codecs in this test binary; these modules
// expose no Runtime/source proof, planned Prepared or publication capability.
#[path = "../src/codec.rs"]
mod codec;
#[path = "../src/dictionary_codec.rs"]
mod dictionary_codec;
fn test_frame(value: &Value, summary: Value) -> String {
    use base64::Engine;
    use std::io::Write;
    let bytes = value.to_string().into_bytes();
    let mut encoder = flate2::write::ZlibEncoder::new(Vec::new(), flate2::Compression::fast());
    encoder.write_all(&bytes).unwrap();
    json!({"schema_version":1,"codec":"ZLIB_CANONICAL_JSON_V1","logical_sha256":digest(&bytes),"logical_size":bytes.len(),"summary":summary,"data":base64::engine::general_purpose::STANDARD.encode(encoder.finish().unwrap())}).to_string()
}
fn test_logical(raw: &str) -> Value {
    use base64::Engine;
    use std::io::Read;
    let value: Value = serde_json::from_str(raw).unwrap();
    if value["codec"] == dictionary_codec::NAME {
        let n = value["summary"]["index"].as_u64().unwrap();
        let f = dictionary_codec::inspect(raw, &digest(raw.as_bytes()), n).unwrap();
        assert!(f.basis.is_none());
        return dictionary_codec::decode_anchor(&f).unwrap().0;
    }
    if value["codec"] != "ZLIB_CANONICAL_JSON_V1" {
        return value;
    }
    let compressed = base64::engine::general_purpose::STANDARD
        .decode(value["data"].as_str().unwrap())
        .unwrap();
    let mut bytes = Vec::new();
    flate2::read::ZlibDecoder::new(&compressed[..])
        .take(8 * 1024 * 1024 + 1)
        .read_to_end(&mut bytes)
        .unwrap();
    assert!(bytes.len() <= 8 * 1024 * 1024);
    assert_eq!(digest(&bytes), value["logical_sha256"].as_str().unwrap());
    serde_json::from_slice(&bytes).unwrap()
}
fn test_dictionary_anchor(db: &rusqlite::Connection, n: u64) -> Option<dictionary_codec::Anchor> {
    let base = dictionary_codec::anchor_sequence(n).unwrap();
    if base == n {
        return None;
    }
    let (raw, physical): (String, String) = db
        .query_row(
            "SELECT payload,digest FROM records WHERE sequence=?1",
            [i64::try_from(base).unwrap()],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .unwrap();
    let frame = dictionary_codec::inspect(&raw, &physical, base).unwrap();
    Some(dictionary_codec::decode_anchor(&frame).unwrap().1)
}
fn test_record(db: &rusqlite::Connection, n: i64) -> Value {
    let version: i64 = db
        .pragma_query_value(None, "user_version", |row| row.get(0))
        .unwrap();
    let raw: String = db
        .query_row("SELECT payload FROM records WHERE sequence=?1", [n], |r| {
            r.get(0)
        })
        .unwrap();
    let value: Value = serde_json::from_str(&raw).unwrap();
    let prepared = if version == 4 {
        let physical: String = db
            .query_row("SELECT digest FROM records WHERE sequence=?1", [n], |row| {
                row.get(0)
            })
            .unwrap();
        let sequence = u64::try_from(n).unwrap();
        let frame = dictionary_codec::inspect(&raw, &physical, sequence).unwrap();
        let input_id: String = db
            .query_row(
                "SELECT input_id FROM records WHERE sequence=?1",
                [n],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(
            frame.summary,
            json!({"kind":"EXECUTION_PREPARED","sequence":n,"input_id":input_id})
        );
        let anchor = test_dictionary_anchor(db, sequence);
        dictionary_codec::decode(&frame, anchor.as_ref()).unwrap()
    } else if value["codec"] == "ZLIB_CANONICAL_JSON_V1" {
        test_logical(&raw)
    } else {
        return value;
    };
    let (ready, delivered): (i64, i64) = db
        .query_row(
            "SELECT ready,delivered FROM records WHERE sequence=?1",
            [n],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .unwrap();
    json!({"schema_version":1,"prepared":prepared,"ready":ready==1,"delivered":delivered==1})
}
fn test_update_dictionary_record(
    db: &rusqlite::Connection,
    n: i64,
    value: &Value,
    anchor: Option<&dictionary_codec::Anchor>,
) -> String {
    let input_id: String = db
        .query_row(
            "SELECT input_id FROM records WHERE sequence=?1",
            [n],
            |row| row.get(0),
        )
        .unwrap();
    let raw = dictionary_codec::encode(
        &value["prepared"],
        json!({"kind":"EXECUTION_PREPARED","sequence":n,"input_id":input_id}),
        u64::try_from(n).unwrap(),
        anchor,
    )
    .unwrap();
    db.execute(
        "UPDATE records SET payload=?1,digest=?2,ready=?3,delivered=?4 WHERE sequence=?5",
        rusqlite::params![
            &raw,
            digest(raw.as_bytes()),
            i64::from(value["ready"] == true),
            i64::from(value["delivered"] == true),
            n
        ],
    )
    .unwrap();
    raw
}
fn test_replace_record(db: &rusqlite::Connection, n: i64, value: &Value) {
    let version: i64 = db
        .pragma_query_value(None, "user_version", |r| r.get(0))
        .unwrap();
    if version == 4 {
        let sequence = u64::try_from(n).unwrap();
        let base = dictionary_codec::anchor_sequence(sequence).unwrap();
        if sequence == base {
            // Capture every complete original dependent before changing its anchor.
            // Re-encoding their physical base pins preserves their original logical
            // bytes so the intended semantic adversary reaches the owning verifier.
            let indices=db.prepare("SELECT sequence FROM records WHERE sequence>?1 AND sequence<=?2 ORDER BY sequence").unwrap().query_map(rusqlite::params![n,n.checked_add(15).unwrap()],|row|row.get::<_,i64>(0)).unwrap().collect::<rusqlite::Result<Vec<_>>>().unwrap();
            let dependents = indices
                .into_iter()
                .map(|index| (index, test_record(db, index)))
                .collect::<Vec<_>>();
            let raw = test_update_dictionary_record(db, n, value, None);
            let frame = dictionary_codec::inspect(&raw, &digest(raw.as_bytes()), sequence).unwrap();
            let anchor = dictionary_codec::decode_anchor(&frame).unwrap().1;
            for (index, original) in dependents {
                test_update_dictionary_record(db, index, &original, Some(&anchor));
            }
        } else {
            let anchor = test_dictionary_anchor(db, sequence).unwrap();
            test_update_dictionary_record(db, n, value, Some(&anchor));
        }
    } else if version == 3 {
        let raw = test_frame(
            &value["prepared"],
            json!({"kind":"EXECUTION_PREPARED","sequence":n,"input_id":value["prepared"]["input"]["input_id"]}),
        );
        db.execute(
            "UPDATE records SET payload=?1,digest=?2,ready=?3,delivered=?4 WHERE sequence=?5",
            rusqlite::params![
                &raw,
                digest(raw.as_bytes()),
                i64::from(value["ready"] == true),
                i64::from(value["delivered"] == true),
                n
            ],
        )
        .unwrap();
    } else {
        db.execute(
            "UPDATE records SET payload=?1,digest=?2 WHERE sequence=?3",
            rusqlite::params![value.to_string(), hash(value), n],
        )
        .unwrap();
    }
}
fn test_step_frame(step: &Value) -> String {
    let n = step["index"].as_u64().unwrap();
    assert_eq!(dictionary_codec::anchor_sequence(n).unwrap(), n);
    dictionary_codec::encode(step,json!({"kind":"REPLAY_STEP","index":step["index"],"previous":step["previous"],"execution_start":step["execution_start"],"input_fingerprints":step["inputs"].as_array().unwrap().iter().map(hash).collect::<Vec<_>>()}),n,None).unwrap()
}
fn legacy_fixture_runtime(root: &Root) -> Runtime {
    let created = Runtime::create(&root.0, config(), &artifact()).unwrap();
    drop(created);
    let db = rusqlite::Connection::open(root.db()).unwrap();
    db.execute_batch("DROP TABLE records; CREATE TABLE records (sequence INTEGER PRIMARY KEY CHECK(sequence>0), input_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL, digest TEXT NOT NULL) STRICT; PRAGMA user_version=2;").unwrap();
    drop(db);
    Runtime::open(&root.0, config(), &artifact()).unwrap()
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
fn fork_ready_copies_the_actual_head_without_mutating_official_owners_or_history() {
    let root = Root::new();
    let mut runtime = Runtime::create(&root.0, config(), &artifact()).unwrap();
    for value in inputs().into_iter().take(3) {
        runtime.apply(&value).unwrap();
    }
    let official_state = runtime.state().unwrap();
    let official_records = runtime.records().unwrap();
    let original_bytes = fs::read(root.db()).unwrap();
    let (mut isolated, records) = runtime.fork_ready().unwrap();
    assert_eq!(records, official_records);
    let mut memory = MemoryStore::default();
    memory.rows = records;
    let mut rebuilt = Components::new(config()).unwrap();
    onlyalpha_execution::recover(&mut memory, &mut rebuilt).unwrap();
    assert_eq!(
        isolated.checkpoint().unwrap(),
        rebuilt.checkpoint().unwrap()
    );
    let next = inputs().pop().unwrap();
    let planned = isolated.prepare(&memory, &next).unwrap();
    coordinate(&mut memory, &mut isolated, &planned).unwrap();
    assert_eq!(runtime.state().unwrap(), official_state);
    assert_eq!(runtime.records().unwrap(), official_records);
    assert_eq!(fs::read(root.db()).unwrap(), original_bytes);
    runtime.apply(&next).unwrap();
    assert_eq!(runtime.records().unwrap(), memory.rows);
    assert_eq!(runtime.state().unwrap(), isolated.state(&memory).unwrap());
    drop(runtime);
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
        let mut v = test_record(&db, 4);
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
        test_replace_record(&db, 4, &v);
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
    let mut v = test_record(&db, 4);
    let prepared = &mut v["prepared"];
    prepared["input"]["source_ref"] = json!("changed-after-open");
    let id = format!("ETX-{}", hash(&prepared["input"]));
    prepared["transaction_id"] = json!(id);
    prepared["events"][0] = json!({"schema_version":1,"event_id":format!("{id}-EVENT-1"),"transaction_id":id,"sequence":4,"input":prepared["input"]});
    prepared.as_object_mut().unwrap().remove("payload_hash");
    prepared["payload_hash"] = json!(hash(prepared));
    let last = hash(prepared);
    let tx = db.transaction().unwrap();
    test_replace_record(&tx, 4, &v);
    tx.execute("UPDATE state SET last_hash=?1", [last]).unwrap();
    tx.commit().unwrap();
    drop(db);
    assert!(r.state().is_err());
    assert!(r.records().is_err());
    assert!(r.pending_events().is_err());
    assert!(
        r.fork_ready().is_err(),
        "a prior healthy observation cannot authorize a stale head fork"
    );
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
    let mut r = legacy_fixture_runtime(&p);
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
    // Retained schema1 fixtures can use the original 4 KiB physical layout.
    db.pragma_update(None, "page_size", 4096).unwrap();
    db.execute_batch("VACUUM").unwrap();
    drop(db);
    let old = fs::read(p.db()).unwrap();
    assert_eq!(&old[16..18], &[16, 0]);
    assert!(Runtime::open(&p.0, config(), &artifact()).is_err());
    assert_eq!(old, fs::read(p.db()).unwrap());
    let mut foreign = config();
    foreign["generation"] = json!("d".repeat(64));
    assert!(SqliteStore::migrate(&p.0, foreign, &artifact()).is_err());
    assert_eq!(old, fs::read(p.db()).unwrap());
    let migrated = SqliteStore::migrate(&p.0, config(), &artifact()).unwrap();
    assert_eq!(migrated.head().unwrap(), 4);
    drop(migrated);
    assert_eq!(&fs::read(p.db()).unwrap()[16..18], &[16, 0]);
    let mut current = Runtime::open(&p.0, config(), &artifact()).unwrap();
    assert_eq!(current.state().unwrap(), state);
    assert_eq!(current.save_checkpoint().unwrap(), cp);
    assert_eq!(current.pending_events().unwrap(), events);
    assert_eq!(result(&current), expected);
    drop(current);
    let bytes = fs::read(p.db()).unwrap();
    assert_eq!(&bytes[16..18], &[16, 0]);
    assert!(SqliteStore::migrate(&p.0, config(), &artifact()).is_err());
    assert_eq!(bytes, fs::read(p.db()).unwrap());
}

// Lower Store/Execution source proof only. The synthetic driver envelope below
// grants no Strategy, concrete native producer, Product Run or CompletionProof.
fn recorded_replay(p: &Root) -> (Value, Value, Value) {
    let cfg = config();
    let mut runtime = Runtime::create(&p.0, cfg.clone(), &artifact()).unwrap();
    let participant = json!({"schema_version":1,"configuration":hash(&cfg),"generation":cfg["generation"],"initial_ns":"0","strategies":{"cluster":"revision"},"sources":["a".repeat(64)],"opening_profile":{"schema_version":1,"kind":"OPEN_CLOSE_V1"}});
    let work = hash(
        &json!({"work_id":"readonly-technical-work","configuration":cfg,"artifact":artifact(),"driver_artifact":artifact(),"input_pin":"c".repeat(64),"participants":participant,"initial_ns":"0"}),
    );
    let binding = json!({"schema_version":2,"configuration":hash(&cfg),"kernel_artifact":artifact(),"driver_artifact":artifact(),"work_id":"readonly-technical-work","participants":participant,"work":work,"input_pin":"c".repeat(64),"program":hash(&participant),"initial_state":{"clock_ns":"0"}});
    runtime.bind_replay(&binding).unwrap();
    let step = json!({"schema_version":1,"index":1,"previous":hash(&binding),"execution_start":0,"cause":{"kind":"TECHNICAL_EXECUTION_SOURCE"},"inputs":inputs(),"state":{"status":"TERMINATED"}});
    runtime.prepare_replay(&step).unwrap();
    for input in inputs() {
        runtime.apply(&input).unwrap();
    }
    runtime.save_checkpoint().unwrap();
    runtime.complete_replay(1).unwrap();
    for n in 1..=inputs().len() {
        runtime.acknowledge(n as u64).unwrap();
    }
    let state = runtime.state().unwrap();
    let result = result(&runtime);
    drop(runtime);
    (binding, state, result)
}
#[test]
fn readonly_replay_snapshot_reads_existing_ready_owning_source_without_any_write() {
    use onlyalpha_runtime::VerifiedReplaySnapshot;
    use std::os::unix::fs::MetadataExt;
    let p = Root::new();
    let (binding, state, expected) = recorded_replay(&p);
    let before = (
        fs::metadata(p.db()).unwrap().ino(),
        fs::read(p.db()).unwrap(),
    );
    let observed = VerifiedReplaySnapshot::read(&p.0, config(), &artifact()).unwrap();
    observed.verify_cut().unwrap();
    assert_eq!(observed.binding(), &binding);
    assert_eq!(observed.state(), &state);
    assert_eq!(observed.records().len(), 4);
    assert_eq!(observed.refs().len(), 1);
    assert_eq!(
        observed
            .backtest_result(
                &manifest(),
                &json!({"schema_version":1,"status":"COMPLETED","reason":null})
            )
            .unwrap()
            .record(),
        expected
    );
    assert_eq!(
        (
            fs::metadata(p.db()).unwrap().ino(),
            fs::read(p.db()).unwrap()
        ),
        before
    );
    assert_eq!(fs::read_dir(&p.0).unwrap().count(), 1);
    drop(observed);
    let missing = Root::new();
    assert!(VerifiedReplaySnapshot::read(&missing.0, config(), &artifact()).is_err());
    assert!(!missing.db().exists());
}
#[test]
fn readonly_replay_snapshot_rejects_stale_source_in_place_replacement_links_and_sidecars() {
    use onlyalpha_runtime::VerifiedReplaySnapshot;
    use std::os::unix::fs::{MetadataExt, symlink};
    let p = Root::new();
    recorded_replay(&p);
    let original = (
        fs::metadata(p.db()).unwrap().ino(),
        fs::read(p.db()).unwrap(),
    );
    let observed = VerifiedReplaySnapshot::read(&p.0, config(), &artifact()).unwrap();
    // A direct SQL fault bypasses the owning lease deliberately. The retained
    // read proof must consult the actual source, not an old connection's pages.
    let db = rusqlite::Connection::open(p.db()).unwrap();
    let (n, raw): (i64, String) = db
        .query_row(
            "SELECT sequence,payload FROM checkpoints ORDER BY sequence DESC LIMIT 1",
            [],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .unwrap();
    let mut changed: Value = serde_json::from_str(&raw).unwrap();
    changed["source"] = json!("f".repeat(64));
    db.execute(
        "UPDATE checkpoints SET payload=?1,digest=?2 WHERE sequence=?3",
        rusqlite::params![changed.to_string(), hash(&changed), n],
    )
    .unwrap();
    drop(db);
    let damaged = fs::read(p.db()).unwrap();
    assert!(observed.verify_cut().is_err());
    assert_eq!(fs::read(p.db()).unwrap(), damaged);
    drop(observed);
    fs::write(p.db(), &original.1).unwrap();
    let observed = VerifiedReplaySnapshot::read(&p.0, config(), &artifact()).unwrap();
    let retained = p.0.join("retained.sqlite3");
    fs::rename(p.db(), &retained).unwrap();
    fs::write(p.db(), &original.1).unwrap();
    assert!(
        observed.verify_cut().is_err(),
        "a byte-equal replacement inode is not the original owning source"
    );
    drop(observed);
    fs::remove_file(p.db()).unwrap();
    fs::rename(&retained, p.db()).unwrap();
    let alias = p.0.join("alias.sqlite3");
    fs::hard_link(p.db(), &alias).unwrap();
    assert!(VerifiedReplaySnapshot::read(&p.0, config(), &artifact()).is_err());
    fs::remove_file(alias).unwrap();
    fs::rename(p.db(), &retained).unwrap();
    symlink(&retained, p.db()).unwrap();
    assert!(VerifiedReplaySnapshot::read(&p.0, config(), &artifact()).is_err());
    fs::remove_file(p.db()).unwrap();
    fs::rename(retained, p.db()).unwrap();
    for name in [
        "runtime.sqlite3-wal",
        "runtime.sqlite3-shm",
        "runtime.sqlite3-journal",
    ] {
        let path = p.0.join(name);
        fs::write(&path, b"unresolved").unwrap();
        let before = fs::read(p.db()).unwrap();
        assert!(VerifiedReplaySnapshot::read(&p.0, config(), &artifact()).is_err());
        assert_eq!(fs::read(p.db()).unwrap(), before);
        assert_eq!(fs::read(&path).unwrap(), b"unresolved");
        fs::remove_file(path).unwrap();
    }
    let mut trailing = original.1.clone();
    trailing.extend_from_slice(b"unanchored tail");
    fs::write(p.db(), &trailing).unwrap();
    assert!(VerifiedReplaySnapshot::read(&p.0, config(), &artifact()).is_err());
    assert_eq!(fs::read(p.db()).unwrap(), trailing);
    fs::write(p.db(), &original.1).unwrap();
    assert_eq!(fs::metadata(p.db()).unwrap().ino(), original.0);
}
#[test]
fn readonly_replay_snapshot_refuses_unready_or_unacknowledged_source_instead_of_recovering_it() {
    use onlyalpha_runtime::VerifiedReplaySnapshot;
    for fault in ["ready", "delivered", "checkpoint", "step"] {
        let p = Root::new();
        recorded_replay(&p);
        let db = rusqlite::Connection::open(p.db()).unwrap();
        if fault == "checkpoint" {
            db.execute("DELETE FROM checkpoints", []).unwrap();
        } else if fault == "step" {
            db.execute("UPDATE replay_steps SET ready=0", []).unwrap();
        } else {
            let n: i64 = db
                .query_row("SELECT max(sequence) FROM records", [], |row| row.get(0))
                .unwrap();
            let mut row = test_record(&db, n);
            row["delivered"] = json!(false);
            if fault == "ready" {
                row["ready"] = json!(false);
            }
            test_replace_record(&db, n, &row);
        }
        drop(db);
        let damaged = fs::read(p.db()).unwrap();
        assert!(
            VerifiedReplaySnapshot::read(&p.0, config(), &artifact()).is_err(),
            "{fault}"
        );
        assert_eq!(fs::read(p.db()).unwrap(), damaged);
    }
}

#[test]
fn replay_projection_keeps_complete_large_state_and_observes_fresh_flags() {
    let root = Root::new();
    recorded_replay(&root);
    let connection = rusqlite::Connection::open(root.db()).unwrap();
    let raw: String = connection
        .query_row(
            "SELECT payload FROM replay_steps WHERE sequence=1",
            [],
            |row| row.get(0),
        )
        .unwrap();
    let mut step = test_logical(&raw);
    step["state"]["opaque_owner_state"] = json!({"nested":{"rows":["a".repeat(16384),"b".repeat(16384)],"decimal":"0.000000000001","null":null},"ordering":[3,2,1]});
    let encoded = test_step_frame(&step);
    let identity = hash(&step);
    connection
        .execute(
            "UPDATE replay_steps SET payload=?1,digest=?2 WHERE sequence=1",
            rusqlite::params![&encoded, digest(encoded.as_bytes())],
        )
        .unwrap();
    connection
        .execute(
            "UPDATE replay_binding SET last_hash=?1 WHERE singleton=1",
            [identity],
        )
        .unwrap();
    drop(connection);
    let runtime = Runtime::open(&root.0, config(), &artifact()).unwrap();
    assert_eq!(
        runtime.replay_steps().unwrap(),
        vec![json!({"step":step,"ready":true})]
    );
    let connection = rusqlite::Connection::open(root.db()).unwrap();
    connection
        .execute("UPDATE replay_steps SET ready=0 WHERE sequence=1", [])
        .unwrap();
    drop(connection);
    assert_eq!(
        runtime.replay_steps().unwrap(),
        vec![json!({"step":step,"ready":false})]
    );
}
#[test]
fn replay_projection_revalidates_full_state_canonical_hash_head_and_input_mapping() {
    for fault in [
        "state-hash",
        "noncanonical",
        "journal-head",
        "journal-last",
        "ready-flag",
        "execution-input",
    ] {
        let root = Root::new();
        recorded_replay(&root);
        let runtime = Runtime::open(&root.0, config(), &artifact()).unwrap();
        assert_eq!(runtime.replay_steps().unwrap().len(), 1);
        let connection = rusqlite::Connection::open(root.db()).unwrap();
        let (raw, digest): (String, String) = connection
            .query_row(
                "SELECT payload,digest FROM replay_steps WHERE sequence=1",
                [],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .unwrap();
        match fault {
            "state-hash" => {
                let mut step = test_logical(&raw);
                step["state"]["changed_nested_tail"] = json!([{"value":"changed"}]);
                connection
                    .execute(
                        "UPDATE replay_steps SET payload=?1 WHERE sequence=1",
                        [test_step_frame(&step)],
                    )
                    .unwrap();
            }
            "noncanonical" => {
                let raw = format!(" {raw}");
                let digest = onlyalpha_execution::digest(raw.as_bytes());
                connection
                    .execute(
                        "UPDATE replay_steps SET payload=?1,digest=?2 WHERE sequence=1",
                        rusqlite::params![raw, digest],
                    )
                    .unwrap();
            }
            "journal-head" => {
                connection
                    .execute("UPDATE replay_binding SET head=2 WHERE singleton=1", [])
                    .unwrap();
            }
            "journal-last" => {
                connection
                    .execute(
                        "UPDATE replay_binding SET last_hash=?1 WHERE singleton=1",
                        ["a".repeat(64)],
                    )
                    .unwrap();
            }
            "ready-flag" => {
                connection.execute_batch("PRAGMA ignore_check_constraints=ON; UPDATE replay_steps SET ready=2 WHERE sequence=1").unwrap();
            }
            _ => {
                let mut step = test_logical(&raw);
                step["inputs"][0]["input_id"] = json!("another-input");
                let logical = hash(&step);
                let encoded = test_step_frame(&step);
                connection
                    .execute(
                        "UPDATE replay_steps SET payload=?1,digest=?2 WHERE sequence=1",
                        rusqlite::params![
                            &encoded,
                            onlyalpha_execution::digest(encoded.as_bytes())
                        ],
                    )
                    .unwrap();
                connection
                    .execute(
                        "UPDATE replay_binding SET last_hash=?1 WHERE singleton=1",
                        [logical],
                    )
                    .unwrap();
            }
        }
        drop(connection);
        assert!(
            runtime.replay_steps().is_err(),
            "{fault}; old row digest was {digest}"
        );
    }
}

#[test]
fn schema4_anchor_fault_fixture_preserves_dependent_logical_bytes_and_reaches_original_guard() {
    let root = Root::new();
    let mut runtime = Runtime::create(&root.0, config(), &artifact()).unwrap();
    for input in inputs() {
        runtime.apply(&input).unwrap();
    }
    let original = runtime
        .records()
        .unwrap()
        .iter()
        .map(|record| record.record())
        .collect::<Vec<_>>();
    drop(runtime);
    let db = rusqlite::Connection::open(root.db()).unwrap();
    assert_eq!(
        db.pragma_query_value(None, "user_version", |row| row.get::<_, i64>(0))
            .unwrap(),
        4
    );
    for n in 1..=4 {
        assert_eq!(
            test_record(&db, n),
            original[n as usize - 1],
            "fixture decoder must return the complete logical Record rather than its physical envelope"
        );
    }
    let mut bad = original[0].clone();
    bad["prepared"]["payload_hash"] = json!("f".repeat(64));
    test_replace_record(&db, 1, &bad);
    assert_eq!(test_record(&db, 1), bad);
    for n in 2..=4 {
        assert_eq!(
            test_record(&db, n),
            original[n as usize - 1],
            "all original dependent logical bytes and flags survive the anchor's physical re-encoding"
        );
    }
    drop(db);
    let before = fs::read(root.db()).unwrap();
    let error = Runtime::open(&root.0, config(), &artifact())
        .err()
        .expect("changed payload hash must fail original logical verification");
    assert!(
        error.0.contains("EXECUTION_PAYLOAD_HASH"),
        "the semantic adversary was masked by a dictionary/format refusal: {error}"
    );
    assert_eq!(
        fs::read(root.db()).unwrap(),
        before,
        "a denied historical observation cannot repair the original source"
    );
}
