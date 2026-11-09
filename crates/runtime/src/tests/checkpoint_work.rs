//! Work bounds and source proofs of the actual Store checkpoint operation.
//! No wall-clock threshold, SDK, Product Run or publication capability is used.
use super::*;
use onlyalpha_execution::coordinate;
use std::{
    fs,
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};

use crate::support;
use support::{Harness, config, fill, input, open, stage, terminal};

// Explicit empty schema2 fixture: no fact is migrated or rewritten. These
// original raw-codec adversarial vectors retain their original format.
fn legacy_store(root: &std::path::Path, configuration: Value, artifact: &str) -> SqliteStore {
    let created = SqliteStore::create(root, configuration.clone(), artifact).unwrap();
    drop(created);
    let db = Connection::open(root.join("runtime.sqlite3")).unwrap();
    db.execute_batch("DROP TABLE records").unwrap();
    db.execute_batch(SCHEMA[2]).unwrap();
    db.pragma_update(None, "user_version", 2).unwrap();
    drop(db);
    SqliteStore::open(root, configuration, artifact).unwrap()
}
static NEXT: AtomicU64 = AtomicU64::new(0);
struct Root(PathBuf);
impl Root {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "oa-checkpoint-work-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
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
// Store drops its actual lease before the test root is removed.
struct History {
    store: SqliteStore,
    components: Components,
    reference: Harness,
    inputs: Vec<Value>,
    checkpoints: Vec<Value>,
    root: Root,
}
fn history(count: u64, mark: &str) -> History {
    assert!(count >= 4);
    let root = Root::new();
    let mut store = legacy_store(&root.0, config(), &"b".repeat(64));
    let mut components = Components::new(config()).unwrap();
    let mut reference = Harness::new(config()).unwrap();
    let mut inputs = vec![];
    let mut checkpoints = vec![];
    for n in 1..=count {
        let value = match n {
            1 => open(1, "BUY"),
            2 => stage(2, 1, "UNKNOWN"),
            3 => fill(3, 1, "1", "10.00", "1.00"),
            4 => terminal(4, 1, "CANCELLED"),
            _ => {
                let state = components.state(&store).unwrap();
                input(
                    n,
                    "VALUATION",
                    json!({"schema_version":1,"valuation":format!("valuation-{n}"),"version":n,
                    "position_evidence":hash(&components.checkpoint().unwrap()["components"][1]),
                    "economic_version":state["account"]["snapshot"]["economic_version"],
                    "marks":[{"schema_version":1,"instrument":"600000.XSHG","mark":mark,"source_ref":format!("mark-{n}"),"family":"CLOSED_BAR","version":n,"time":n,"as_of_sequence":n}]}),
                )
            }
        };
        let planned = components.prepare(&store, &value).unwrap();
        coordinate(&mut store, &mut components, &planned).unwrap();
        let expected = reference.prepare(&value).unwrap();
        coordinate(&mut reference.store, &mut reference.components, &expected).unwrap();
        let checkpoint = store.save_checkpoint(&components).unwrap();
        assert_eq!(
            checkpoint["components"],
            reference.components.checkpoint().unwrap()
        );
        checkpoints.push(checkpoint);
        inputs.push(value);
    }
    History {
        store,
        components,
        reference,
        inputs,
        checkpoints,
        root,
    }
}
fn checkpoint_rows(root: &Root) -> Vec<(i64, String, String)> {
    let db = Connection::open(root.db()).unwrap();
    let mut statement = db
        .prepare("SELECT sequence,payload,digest FROM checkpoints ORDER BY sequence")
        .unwrap();
    statement
        .query_map([], |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)))
        .unwrap()
        .collect::<rusqlite::Result<_>>()
        .unwrap()
}
fn transcript(inputs: &[Value]) -> Value {
    json!({"schema_version":1,"configuration":hash(&config()),"kernel_artifact":"b".repeat(64),"input_pin":"c".repeat(64),
        "initial_time":{"schema_version":1,"unix_nanos":0},"final_time":{"schema_version":1,"unix_nanos":100},
        "inputs":inputs.iter().map(hash).collect::<Vec<_>>()})
}
#[test]
fn dense_checkpoint_save_has_bounded_actual_proof_source_visits() {
    let count = 16_u64;
    let mut h = history(count, "12.00");
    let original = checkpoint_rows(&h.root);
    CHECKPOINT_PROOF_GETS.with(|reads| reads.set(0));
    let checkpoint = h.store.save_checkpoint(&h.components).unwrap();
    let actual = CHECKPOINT_PROOF_GETS.with(std::cell::Cell::get);
    assert_eq!(checkpoint, h.checkpoints.last().unwrap().clone());
    assert_eq!(
        checkpoint_rows(&h.root),
        original,
        "work reduction cannot rewrite retained checkpoints"
    );
    // Count actual accesses through the private isolated proof Store. Dense
    // genesis restarts currently need 3721 gets here; a forward pass retains
    // all source guards and checkpoint comparisons within this quadratic bound.
    assert!(
        actual > 0 && actual <= 3 * count * count + 32 * count,
        "checkpoint proof repeatedly revisited old prefixes: {actual}"
    );
}
#[test]
fn dense_checkpoint_history_preserves_existing_wire_and_fresh_recovered_economics() {
    let mut h = history(12, "12.00");
    let original = checkpoint_rows(&h.root);
    for ((sequence, payload, digest), expected) in original.iter().zip(&h.checkpoints) {
        assert_eq!(payload, &expected.to_string());
        assert_eq!(digest, &hash(expected));
        assert_eq!(expected["schema_version"], 1);
        assert_eq!(expected["sequence"], *sequence);
        assert_eq!(
            expected
                .as_object()
                .unwrap()
                .keys()
                .map(String::as_str)
                .collect::<Vec<_>>(),
            [
                "components",
                "identity",
                "schema_version",
                "sequence",
                "source"
            ]
        );
    }
    let outcome = json!({"schema_version":1,"status":"COMPLETED","reason":null});
    let manifest = transcript(&h.inputs);
    let expected = h
        .reference
        .components
        .backtest_result(&h.reference.store, &manifest, &outcome)
        .unwrap()
        .record();
    assert_eq!(
        h.components
            .backtest_result(&h.store, &manifest, &outcome)
            .unwrap()
            .record(),
        expected
    );
    let state = h.components.state(&h.store).unwrap();
    let events = onlyalpha_execution::pending_events(&h.store, &h.components).unwrap();
    let checkpoint = h.store.save_checkpoint(&h.components).unwrap();
    drop(h.store);
    let mut recovered = crate::Runtime::open(&h.root.0, config(), &"b".repeat(64)).unwrap();
    assert_eq!(recovered.save_checkpoint().unwrap(), checkpoint);
    assert_eq!(recovered.state().unwrap(), state);
    assert_eq!(recovered.pending_events().unwrap(), events);
    assert_eq!(
        recovered
            .backtest_result(&manifest, &outcome)
            .unwrap()
            .record(),
        expected
    );
    assert_eq!(
        checkpoint_rows(&h.root),
        original,
        "recovery cannot rewrite original schema1 checkpoint bytes"
    );
    drop(recovered);
}
#[test]
fn save_revalidates_corrupt_older_checkpoint_after_successful_warm_read() {
    use std::os::unix::fs::MetadataExt;
    for fault in 0..3 {
        let mut h = history(12, "11.00");
        let foreign = history(6, "12.00");
        h.store.save_checkpoint(&h.components).unwrap();
        let mut changed = h.checkpoints[5].clone();
        match fault {
            0 => {}
            1 => changed["source"] = json!("f".repeat(64)),
            _ => changed["components"] = foreign.checkpoints[5]["components"].clone(),
        }
        let db = Connection::open(h.root.db()).unwrap();
        // A completed SQL write is the deterministic fault boundary. Both the
        // latest checkpoint and current Components remain genuine and untouched.
        db.execute(
            "UPDATE checkpoints SET payload=?1,digest=?2 WHERE sequence=6",
            params![
                changed.to_string(),
                if fault == 0 {
                    "invalid".into()
                } else {
                    hash(&changed)
                }
            ],
        )
        .unwrap();
        drop(db);
        let before = (
            fs::metadata(h.root.db()).unwrap().ino(),
            fs::read(h.root.db()).unwrap(),
        );
        assert!(
            h.store.save_checkpoint(&h.components).is_err(),
            "older checkpoint fault {fault} escaped current save"
        );
        assert_eq!(
            (
                fs::metadata(h.root.db()).unwrap().ino(),
                fs::read(h.root.db()).unwrap()
            ),
            before,
            "failure must retain original inode and bytes"
        );
        drop(h.store);
        assert!(
            crate::Runtime::open(&h.root.0, config(), &"b".repeat(64)).is_err(),
            "recovery cannot skip invalid older checkpoint {fault}"
        );
        assert_eq!(
            (
                fs::metadata(h.root.db()).unwrap().ino(),
                fs::read(h.root.db()).unwrap()
            ),
            before
        );
    }
}

#[test]
fn repeated_head_queries_reuse_encoding_only_for_the_actual_exact_decoded_row() {
    let h = history(4, "11.00");
    let original = h.store.get(4).unwrap().unwrap();
    let expected = hash(&original.prepared().record());
    assert_ne!(
        Value::String(expected.clone()),
        original.prepared().record()["payload_hash"]
    );
    assert_ne!(
        expected,
        hash(&original.record()),
        "outer Record flags are not the Prepared source"
    );
    PREPARED_SOURCE_ENCODINGS.with(|count| count.set(0));
    for _ in 0..8 {
        assert_eq!(h.store.get(1).unwrap().unwrap().prepared().sequence(), 1);
        assert_eq!(h.store.head().unwrap(), 4);
    }
    assert_eq!(
        PREPARED_SOURCE_ENCODINGS.with(std::cell::Cell::get),
        0,
        "unchanged SQL rows repeatedly serialized the complete Prepared head"
    );
    let mut changed = original.record();
    changed["delivered"] = json!(true);
    let db = Connection::open(h.root.db()).unwrap();
    db.execute(
        "UPDATE records SET payload=?1,digest=?2 WHERE sequence=4",
        params![changed.to_string(), hash(&changed)],
    )
    .unwrap();
    drop(db);
    let observed = h.store.get(4).unwrap().unwrap();
    assert_eq!(
        observed.record(),
        changed,
        "changed actual row flags cannot reuse a stale decoded Record"
    );
    assert_eq!(hash(&observed.prepared().record()), expected);
    let after_change = PREPARED_SOURCE_ENCODINGS.with(std::cell::Cell::get);
    assert_eq!(
        after_change, 1,
        "only a changed actual row needs its full Prepared encoding"
    );
    assert_eq!(h.store.get(4).unwrap().unwrap(), observed);
    assert_eq!(
        PREPARED_SOURCE_ENCODINGS.with(std::cell::Cell::get),
        after_change
    );
}

#[test]
fn warm_encoding_memo_never_authenticates_changed_head_metadata_or_raw_bytes() {
    for fault in 0..3 {
        let h = history(4, "11.00");
        let record = h.store.get(4).unwrap().unwrap();
        let db = Connection::open(h.root.db()).unwrap();
        match fault {
            0 => {
                db.execute(
                    "UPDATE state SET last_hash=?1",
                    [record.prepared().record()["payload_hash"].as_str().unwrap()],
                )
                .unwrap();
            }
            1 => {
                db.execute("UPDATE meta SET digest=?1", ["f".repeat(64)])
                    .unwrap();
            }
            _ => {
                let mut changed = record.record();
                changed["prepared"]["input"]["source_ref"] =
                    json!("changed-but-rehashed-outer-record");
                db.execute(
                    "UPDATE records SET payload=?1,digest=?2 WHERE sequence=4",
                    params![changed.to_string(), hash(&changed)],
                )
                .unwrap();
            }
        }
        drop(db);
        let before = fs::read(h.root.db()).unwrap();
        assert!(
            h.store.get(1).is_err(),
            "warm codec bypassed actual source fault {fault}"
        );
        assert_eq!(
            fs::read(h.root.db()).unwrap(),
            before,
            "a denied read cannot repair the source"
        );
    }
}

// Reuse the real canonical economic fixture; only the first four checkpoints
// are preconditions. Later valuations exercise growing history without a dense
// checkpoint benchmark becoming part of this source-read regression.
fn source_history(count: u64) -> History {
    let mut h = history(4, "12.00");
    for n in 5..=count {
        let state = h.components.state(&h.store).unwrap();
        let value = input(
            n,
            "VALUATION",
            json!({"schema_version":1,"valuation":format!("source-valuation-{n}"),"version":n,
            "position_evidence":hash(&h.components.checkpoint().unwrap()["components"][1]),
            "economic_version":state["account"]["snapshot"]["economic_version"],
            "marks":[{"schema_version":1,"instrument":"600000.XSHG","mark":"12.00","source_ref":format!("source-mark-{n}"),"family":"CLOSED_BAR","version":n,"time":n,"as_of_sequence":n}]}),
        );
        let planned = h.components.prepare(&h.store, &value).unwrap();
        coordinate(&mut h.store, &mut h.components, &planned).unwrap();
        let expected = h.reference.prepare(&value).unwrap();
        coordinate(
            &mut h.reference.store,
            &mut h.reference.components,
            &expected,
        )
        .unwrap();
        h.inputs.push(value);
    }
    h
}
fn reset_source_work() {
    SOURCE_HEAD_AGGREGATES.with(|count| count.set(0));
    SOURCE_RAW_ROWS.with(|count| count.set(0));
    SOURCE_PROJECTION_COPIES.with(|count| count.set(0));
}
#[test]
fn runtime_reads_bound_actual_sql_work_by_one_complete_source_instead_of_per_record_heads() {
    for count in [16_u64, 32] {
        let h = source_history(count);
        let state = h.components.state(&h.store).unwrap();
        let events =
            onlyalpha_execution::pending_events(&h.reference.store, &h.reference.components)
                .unwrap();
        let reference_result = h
            .reference
            .components
            .backtest_result(
                &h.reference.store,
                &transcript(&h.inputs),
                &json!({"schema_version":1,"status":"COMPLETED","reason":null}),
            )
            .unwrap()
            .record();
        drop(h.store);
        let runtime = crate::Runtime::open(&h.root.0, config(), &"b".repeat(64)).unwrap();
        for operation in ["records", "state", "events", "result", "fork"] {
            reset_source_work();
            match operation {
                "records" => assert_eq!(runtime.records().unwrap(), h.reference.store.rows),
                "state" => assert_eq!(runtime.state().unwrap(), state),
                "events" => assert_eq!(runtime.pending_events().unwrap(), events),
                "result" => assert_eq!(
                    runtime
                        .backtest_result(
                            &transcript(&h.inputs),
                            &json!({"schema_version":1,"status":"COMPLETED","reason":null})
                        )
                        .unwrap()
                        .record(),
                    reference_result
                ),
                _ => {
                    let (fork, records) = runtime.fork_ready().unwrap();
                    assert_eq!(records, h.reference.store.rows);
                    assert_eq!(
                        fork.checkpoint().unwrap(),
                        h.components.checkpoint().unwrap()
                    );
                }
            }
            let aggregates = SOURCE_HEAD_AGGREGATES.with(std::cell::Cell::get);
            let rows = SOURCE_RAW_ROWS.with(std::cell::Cell::get);
            assert!(
                aggregates <= 2,
                "{operation} repeated a SQLite COUNT/MAX head scan per retained record: {aggregates} for {count}"
            );
            assert!(
                rows >= count && rows <= 2 * count + 4,
                "{operation} must read the real complete source with bounded SQL row visits: {rows} for {count}"
            );
        }
        drop(runtime);
    }
}
#[test]
fn warm_projection_hash_codec_still_reads_every_actual_row_without_copying_complete_owner_histories()
 {
    let h = source_history(16);
    h.store.read_records().unwrap();
    reset_source_work();
    for _ in 0..4 {
        assert_eq!(h.store.read_records().unwrap(), h.reference.store.rows);
    }
    assert_eq!(
        SOURCE_RAW_ROWS.with(std::cell::Cell::get),
        64,
        "warm codec cannot replace actual SQL rows"
    );
    assert_eq!(
        SOURCE_PROJECTION_COPIES.with(std::cell::Cell::get),
        0,
        "unchanged actual rows repeatedly cloned all six full owner projections for their hashes"
    );
}
#[test]
fn warm_runtime_observations_never_authenticate_tampered_source_or_repair_it() {
    for fault in [
        "identity",
        "head",
        "index",
        "raw",
        "ready",
        "lineage",
        "missing-tail",
        "delivered",
    ] {
        let h = source_history(8);
        drop(h.store);
        let runtime = crate::Runtime::open(&h.root.0, config(), &"b".repeat(64)).unwrap();
        let original = runtime.records().unwrap();
        runtime.state().unwrap();
        runtime.pending_events().unwrap();
        let db = Connection::open(h.root.db()).unwrap();
        match fault {
            "identity" => {
                db.execute("UPDATE meta SET digest=?1", ["f".repeat(64)])
                    .unwrap();
            }
            "head" => {
                db.execute("UPDATE state SET head=head-1", []).unwrap();
            }
            "index" => {
                db.execute(
                    "UPDATE records SET input_id='another-input-index' WHERE sequence=2",
                    [],
                )
                .unwrap();
            }
            "raw" => {
                db.execute(
                    "UPDATE records SET payload=payload||' ' WHERE sequence=2",
                    [],
                )
                .unwrap();
            }
            "missing-tail" => {
                db.execute("DELETE FROM records WHERE sequence=8", [])
                    .unwrap();
            }
            _ => {
                let mut changed = original[1].record();
                if fault == "ready" {
                    changed["ready"] = json!(false);
                    changed["delivered"] = json!(false);
                } else if fault == "delivered" {
                    changed["delivered"] = json!(true);
                } else {
                    changed["prepared"]["projections"][0]["before_hash"] = json!("f".repeat(64));
                    changed["prepared"]
                        .as_object_mut()
                        .unwrap()
                        .remove("payload_hash");
                    changed["prepared"]["payload_hash"] = json!(hash(&changed["prepared"]));
                }
                db.execute(
                    "UPDATE records SET payload=?1,digest=?2 WHERE sequence=2",
                    params![changed.to_string(), hash(&changed)],
                )
                .unwrap();
            }
        }
        drop(db);
        let bytes = fs::read(h.root.db()).unwrap();
        if fault == "delivered" {
            assert_eq!(runtime.records().unwrap()[1].record()["delivered"], true);
            assert_eq!(runtime.pending_events().unwrap().len(), 7);
        } else {
            assert!(runtime.records().is_err(), "{fault}");
            assert!(runtime.state().is_err(), "{fault}");
            assert!(runtime.pending_events().is_err(), "{fault}");
        }
        assert_eq!(
            fs::read(h.root.db()).unwrap(),
            bytes,
            "read-only observation must not repair fault {fault}"
        );
        drop(runtime);
    }
}

// Empty historical schema3 fixture only: this changes no existing fact and
// does not provide any production migration or compatibility fallback.
fn zlib_store(root: &std::path::Path, configuration: Value, artifact: &str) -> SqliteStore {
    let created = SqliteStore::create(root, configuration.clone(), artifact).unwrap();
    drop(created);
    let db = Connection::open(root.join("runtime.sqlite3")).unwrap();
    db.pragma_update(None, "user_version", 3).unwrap();
    drop(db);
    SqliteStore::open(root, configuration, artifact).unwrap()
}
fn encoded_source_history() -> History {
    let root = Root::new();
    let mut store = zlib_store(&root.0, config(), &"b".repeat(64));
    assert_eq!(store.storage_version, 3);
    let mut components = Components::new(config()).unwrap();
    let mut reference = Harness::new(config()).unwrap();
    let inputs = vec![
        open(1, "BUY"),
        stage(2, 1, "UNKNOWN"),
        fill(3, 1, "1", "10.00", "1.00"),
        terminal(4, 1, "CANCELLED"),
    ];
    for input in &inputs {
        let actual = components.prepare(&store, input).unwrap();
        coordinate(&mut store, &mut components, &actual).unwrap();
        let expected = reference.prepare(input).unwrap();
        coordinate(&mut reference.store, &mut reference.components, &expected).unwrap();
    }
    History {
        store,
        components,
        reference,
        inputs,
        checkpoints: Vec::new(),
        root,
    }
}
fn reset_encoded_work() {
    crate::codec::PHYSICAL_HASHES.with(|count| count.set(0));
    crate::codec::DECODED_BYTES.with(|count| count.set(0));
    SOURCE_RAW_ROWS.with(|count| count.set(0));
    PREPARED_SOURCE_ENCODINGS.with(|count| count.set(0));
}
#[test]
fn exact_encoded_rows_reuse_only_codec_work_while_reading_the_actual_complete_source() {
    let h = encoded_source_history();
    let expected = h.reference.store.rows.clone();
    assert_eq!(h.store.read_records().unwrap(), expected);
    reset_encoded_work();
    for _ in 0..4 {
        assert_eq!(h.store.read_records().unwrap(), expected);
    }
    assert_eq!(
        SOURCE_RAW_ROWS.with(std::cell::Cell::get),
        16,
        "the complete actual SQL payload/index/digest/flag rows are still read every time"
    );
    assert_eq!(
        crate::codec::PHYSICAL_HASHES.with(std::cell::Cell::get),
        0,
        "already verified identical immutable bytes need no repeated physical SHA calculation"
    );
    assert_eq!(crate::codec::DECODED_BYTES.with(std::cell::Cell::get), 0);
    assert_eq!(PREPARED_SOURCE_ENCODINGS.with(std::cell::Cell::get), 0);
    let db = Connection::open(h.root.db()).unwrap();
    db.execute("UPDATE records SET delivered=1 WHERE sequence=4", [])
        .unwrap();
    drop(db);
    reset_encoded_work();
    let changed = h.store.read_records().unwrap();
    assert_eq!(
        changed[3].record()["delivered"],
        true,
        "a valid changed actual flag cannot use a stale cached Record"
    );
    assert_eq!(changed[3].prepared(), expected[3].prepared());
    assert_eq!(SOURCE_RAW_ROWS.with(std::cell::Cell::get), 4);
    let hashes = crate::codec::PHYSICAL_HASHES.with(std::cell::Cell::get);
    assert_eq!(
        hashes, 0,
        "fresh independent flags must not rehash unchanged immutable Prepared bytes"
    );
    let decoded = crate::codec::DECODED_BYTES.with(std::cell::Cell::get);
    assert_eq!(
        decoded, 0,
        "fresh independent flags must not decompress the same Prepared again"
    );
    assert_eq!(PREPARED_SOURCE_ENCODINGS.with(std::cell::Cell::get), 0);
    for _ in 0..3 {
        assert_eq!(h.store.read_records().unwrap(), changed);
    }
    assert_eq!(SOURCE_RAW_ROWS.with(std::cell::Cell::get), 16);
    assert_eq!(
        crate::codec::PHYSICAL_HASHES.with(std::cell::Cell::get),
        hashes
    );
    assert_eq!(
        crate::codec::DECODED_BYTES.with(std::cell::Cell::get),
        decoded
    );
}
#[test]
fn warm_encoded_row_memo_never_hides_actual_hash_flags_index_or_history_mutations() {
    for fault in [
        "digest",
        "raw",
        "rehashed-noncanonical",
        "index",
        "valid-frame-foreign-summary",
        "invalid-flags",
        "invalid-delivered",
        "delivery-before-ready",
        "unready-predecessor",
        "lineage",
        "missing-tail",
        "head",
        "identity",
        "storage-version",
    ] {
        let h = encoded_source_history();
        h.store.read_records().unwrap();
        reset_encoded_work();
        let db = Connection::open(h.root.db()).unwrap();
        match fault {
            "digest" => {
                db.execute(
                    "UPDATE records SET digest=?1 WHERE sequence=2",
                    ["f".repeat(64)],
                )
                .unwrap();
            }
            "raw" => {
                db.execute(
                    "UPDATE records SET payload=payload||' ' WHERE sequence=2",
                    [],
                )
                .unwrap();
            }
            "rehashed-noncanonical" => {
                let raw: String = db
                    .query_row("SELECT payload FROM records WHERE sequence=2", [], |row| {
                        row.get(0)
                    })
                    .unwrap();
                let raw = raw + " ";
                db.execute(
                    "UPDATE records SET payload=?1,digest=?2 WHERE sequence=2",
                    params![&raw, digest(raw.as_bytes())],
                )
                .unwrap();
            }
            "index" => {
                db.execute(
                    "UPDATE records SET input_id='foreign-actual-index' WHERE sequence=2",
                    [],
                )
                .unwrap();
            }
            "valid-frame-foreign-summary" => {
                let raw: String = db
                    .query_row("SELECT payload FROM records WHERE sequence=2", [], |row| {
                        row.get(0)
                    })
                    .unwrap();
                let mut frame: Value = serde_json::from_str(&raw).unwrap();
                frame["summary"]["input_id"] = json!("foreign-summary");
                let raw = frame.to_string();
                db.execute(
                    "UPDATE records SET payload=?1,digest=?2 WHERE sequence=2",
                    params![&raw, digest(raw.as_bytes())],
                )
                .unwrap();
            }
            "invalid-flags" => {
                db.execute_batch("PRAGMA ignore_check_constraints=ON; UPDATE records SET ready=2 WHERE sequence=2; PRAGMA ignore_check_constraints=OFF;").unwrap();
            }
            "invalid-delivered" => {
                db.execute_batch("PRAGMA ignore_check_constraints=ON; UPDATE records SET delivered=2 WHERE sequence=2; PRAGMA ignore_check_constraints=OFF;").unwrap();
            }
            "delivery-before-ready" => {
                db.execute_batch("PRAGMA ignore_check_constraints=ON; UPDATE records SET ready=0,delivered=1 WHERE sequence=2; PRAGMA ignore_check_constraints=OFF;").unwrap();
            }
            "unready-predecessor" => {
                db.execute(
                    "UPDATE records SET ready=0,delivered=0 WHERE sequence=2",
                    [],
                )
                .unwrap();
            }
            "lineage" => {
                let original = &h.reference.store.rows[1];
                let mut prepared = original.prepared().record();
                prepared["projections"][0]["before_hash"] = json!("f".repeat(64));
                prepared.as_object_mut().unwrap().remove("payload_hash");
                prepared["payload_hash"] = json!(hash(&prepared));
                let raw=crate::codec::encode(&prepared,json!({"kind":"EXECUTION_PREPARED","sequence":2,"input_id":prepared["input"]["input_id"]})).unwrap();
                db.execute(
                    "UPDATE records SET payload=?1,digest=?2 WHERE sequence=2",
                    params![&raw, digest(raw.as_bytes())],
                )
                .unwrap();
            }
            "missing-tail" => {
                db.execute("DELETE FROM records WHERE sequence=4", [])
                    .unwrap();
            }
            "head" => {
                db.execute("UPDATE state SET head=head-1", []).unwrap();
            }
            "identity" => {
                db.execute("UPDATE meta SET digest=?1", ["f".repeat(64)])
                    .unwrap();
            }
            _ => {
                db.pragma_update(None, "user_version", 4).unwrap();
            }
        }
        drop(db);
        let before = fs::read(h.root.db()).unwrap();
        assert!(
            h.store.read_records().is_err(),
            "warm exact codec memo hid actual source fault {fault}"
        );
        if fault == "unready-predecessor" {
            assert_eq!(
                crate::codec::PHYSICAL_HASHES.with(std::cell::Cell::get),
                0,
                "actual unready predecessor must fail on fresh lineage/flags, without decoding unchanged bytes"
            );
            assert_eq!(crate::codec::DECODED_BYTES.with(std::cell::Cell::get), 0);
        }
        if matches!(fault, "index" | "valid-frame-foreign-summary" | "lineage") {
            assert!(
                crate::codec::PHYSICAL_HASHES.with(std::cell::Cell::get) > 0,
                "changed source must use the actual physical verifier: {fault}"
            );
            assert!(
                crate::codec::DECODED_BYTES.with(std::cell::Cell::get) > 0,
                "changed actual bytes/index/flags must decode the original complete body: {fault}"
            );
        }
        assert_eq!(
            fs::read(h.root.db()).unwrap(),
            before,
            "a rejected observation cannot repair source {fault}"
        );
    }
}

#[test]
fn actual_execution_rows_borrow_warm_payload_bytes_and_own_only_cold_codec_entries() {
    for encoded in [false, true] {
        let h = if encoded {
            encoded_source_history()
        } else {
            history(4, "12.00")
        };
        let expected = h.reference.store.rows.clone();
        assert_eq!(h.store.read_records().unwrap(), expected);
        SOURCE_OWNED_PAYLOAD_BYTES.with(|count| count.set(0));
        SOURCE_RAW_ROWS.with(|count| count.set(0));
        for _ in 0..4 {
            assert_eq!(h.store.read_records().unwrap(), expected);
            for (index, record) in expected.iter().enumerate() {
                assert_eq!(
                    h.store.read_one(index as u64 + 1).unwrap().unwrap().0,
                    *record
                );
            }
        }
        assert_eq!(
            SOURCE_RAW_ROWS.with(std::cell::Cell::get),
            8 * expected.len() as u64,
            "full scans and point reads still consume every actual SQL row"
        );
        assert_eq!(
            SOURCE_OWNED_PAYLOAD_BYTES.with(std::cell::Cell::get),
            0,
            "warm source observation copied full SQLite payload strings before comparing exact codec bytes"
        );
        h.store.decoded_rows.borrow_mut().clear();
        SOURCE_OWNED_PAYLOAD_BYTES.with(|count| count.set(0));
        assert_eq!(h.store.read_records().unwrap(), expected);
        assert!(
            SOURCE_OWNED_PAYLOAD_BYTES.with(std::cell::Cell::get) > 0,
            "a cold decoder must retain its own exact immutable source bytes"
        );
        SOURCE_OWNED_PAYLOAD_BYTES.with(|count| count.set(0));
        assert_eq!(h.store.read_records().unwrap(), expected);
        assert_eq!(SOURCE_OWNED_PAYLOAD_BYTES.with(std::cell::Cell::get), 0);
        let db = Connection::open(h.root.db()).unwrap();
        let raw: String = db
            .query_row("SELECT payload FROM records WHERE sequence=2", [], |row| {
                row.get(0)
            })
            .unwrap();
        let changed = raw + " ";
        db.execute(
            "UPDATE records SET payload=?1,digest=?2 WHERE sequence=2",
            params![&changed, digest(changed.as_bytes())],
        )
        .unwrap();
        drop(db);
        let before = fs::read(h.root.db()).unwrap();
        assert!(h.store.read_records().is_err());
        assert!(h.store.read_one(2).is_err());
        assert_eq!(
            fs::read(h.root.db()).unwrap(),
            before,
            "a borrowed noncanonical actual row cannot reuse earlier bytes or repair history"
        );
    }
}

#[test]
fn independent_actual_flags_reuse_only_the_immutable_prepared_codec() {
    let h = encoded_source_history();
    let original = h.store.read_records().unwrap();
    let retained = original[3].record();
    let raw: String = h
        .store
        .connection
        .query_row("SELECT payload FROM records WHERE sequence=4", [], |row| {
            row.get(0)
        })
        .unwrap();
    // A SQL observation may see a legal pending tail or any later delivery
    // state. This does not authorize a write or certify a Ready Runtime.
    for (ready, delivered) in [(0_i64, 0_i64), (1, 0), (1, 1), (1, 0), (0, 0)] {
        h.store
            .connection
            .execute(
                "UPDATE records SET ready=?1,delivered=?2 WHERE sequence=4",
                params![ready, delivered],
            )
            .unwrap();
        let before = fs::read(h.root.db()).unwrap();
        reset_encoded_work();
        let observed = h.store.read_records().unwrap();
        let point = h.store.get(4).unwrap().unwrap();
        let mut expected = retained.clone();
        expected["ready"] = json!(ready == 1);
        expected["delivered"] = json!(delivered == 1);
        assert_eq!(observed[3].record(), expected);
        assert_eq!(point.record(), expected);
        assert_eq!(&observed[..3], &original[..3]);
        assert_eq!(
            original[3].record(),
            retained,
            "fresh flags cannot alter previously returned snapshots"
        );
        assert_eq!(observed[3].prepared(), original[3].prepared());
        assert_eq!(
            SOURCE_RAW_ROWS.with(std::cell::Cell::get),
            6,
            "the full scan, actual head record and named row are still read"
        );
        assert_eq!(
            crate::codec::PHYSICAL_HASHES.with(std::cell::Cell::get),
            0,
            "fresh flags repeated the physical immutable-body SHA"
        );
        assert_eq!(
            crate::codec::DECODED_BYTES.with(std::cell::Cell::get),
            0,
            "fresh flags decompressed immutable Prepared again"
        );
        assert_eq!(PREPARED_SOURCE_ENCODINGS.with(std::cell::Cell::get), 0);
        let actual: String = h
            .store
            .connection
            .query_row("SELECT payload FROM records WHERE sequence=4", [], |row| {
                row.get(0)
            })
            .unwrap();
        assert_eq!(actual, raw);
        assert_eq!(
            fs::read(h.root.db()).unwrap(),
            before,
            "observing flags cannot write or repair the source"
        );
    }
}

#[test]
fn cold_record_validation_borrows_canonical_owner_images_instead_of_deep_copying_them() {
    for encoded in [false, true] {
        let h = if encoded {
            encoded_source_history()
        } else {
            source_history(8)
        };
        let expected = h.store.read_records().unwrap();
        h.store.decoded_rows.borrow_mut().clear();
        reset_source_work();
        let actual = h.store.read_records().unwrap();
        assert_eq!(actual, expected);
        assert_eq!(
            SOURCE_RAW_ROWS.with(std::cell::Cell::get),
            expected.len() as u64,
            "cold verification must still read every actual SQL row"
        );
        assert_eq!(
            SOURCE_PROJECTION_COPIES.with(std::cell::Cell::get),
            0,
            "cold source verification copied a complete Prepared body only to inspect its fields"
        );
    }
}
#[test]
fn read_only_drain_checks_observe_actual_flags_without_copying_complete_record_bodies() {
    let mut h = history(4, "12.00");
    assert!(
        h.store.read_ready_components().is_err(),
        "unacknowledged actual Events cannot form a drained read-only cut"
    );
    for sequence in 1..=4 {
        h.store.acknowledge(sequence).unwrap();
    }
    let expected = h.store.read_records().unwrap();
    let expected_state = h.components.checkpoint().unwrap();
    h.store.decoded_rows.borrow_mut().clear();
    reset_source_work();
    let before = fs::read(h.root.db()).unwrap();
    let (actual, records, _) = h.store.read_ready_components().unwrap();
    assert_eq!(records, expected);
    assert_eq!(actual.checkpoint().unwrap(), expected_state);
    assert_eq!(
        fs::read(h.root.db()).unwrap(),
        before,
        "drain observation cannot mutate original bytes"
    );
    assert_eq!(
        SOURCE_PROJECTION_COPIES.with(std::cell::Cell::get),
        0,
        "a drain boolean check copied all retained Prepared body data"
    );
}

#[test]
fn warm_checkpoint_validation_reuses_only_pure_record_data_and_keeps_every_actual_source_cut() {
    for count in [16_u64, 32] {
        let mut h = history(count, "12.00");
        let original = checkpoint_rows(&h.root);
        let expected = h.checkpoints.last().unwrap().clone();
        h.store.save_checkpoint(&h.components).unwrap();
        let prefix_sum: u64 = original
            .iter()
            .map(|(sequence, _, _)| *sequence as u64)
            .sum();
        for _ in 0..2 {
            CHECKPOINT_PROOF_GETS.with(|reads| reads.set(0));
            SOURCE_RAW_ROWS.with(|rows| rows.set(0));
            assert_eq!(h.store.save_checkpoint(&h.components).unwrap(), expected);
            let proof_reads = CHECKPOINT_PROOF_GETS.with(std::cell::Cell::get);
            // Each retained prefix must still execute the original full-source
            // reconciliation (two visits per retained Record). Repeating every
            // projection installation from genesis is additional pure work.
            assert!(
                proof_reads >= 2 * prefix_sum && proof_reads <= 2 * prefix_sum + 2 * count + 8,
                "warm checkpoint repeatedly replayed complete owner prefixes: {proof_reads} for {count} facts and prefix sum {prefix_sum}"
            );
            assert_eq!(
                SOURCE_RAW_ROWS.with(std::cell::Cell::get),
                count,
                "a pure data memo cannot authenticate an old SQL source cut"
            );
            assert_eq!(checkpoint_rows(&h.root), original);
        }
        h.store.decoded_rows.borrow_mut().clear();
        assert_eq!(
            h.store.save_checkpoint(&h.components).unwrap(),
            expected,
            "a cold body cache must independently recover the same complete history"
        );
        assert_eq!(checkpoint_rows(&h.root), original);
    }
}
// One format-owned fault writer so schema4 can reuse its original dictionary
// encoder; this test must never degrade into a malformed-codec rejection.
fn replace_prepared_source(
    store: &SqliteStore,
    sequence: u64,
    prepared: &Value,
    ready: bool,
    delivered: bool,
) {
    let (raw, physical) = match store.storage_version {
        2 => {
            let value =
                json!({"schema_version":1,"prepared":prepared,"ready":ready,"delivered":delivered});
            (value.to_string(), hash(&value))
        }
        3 => {
            let raw=crate::codec::encode(prepared,json!({"kind":"EXECUTION_PREPARED","sequence":sequence,"input_id":prepared["input"]["input_id"]})).unwrap();
            let physical = digest(raw.as_bytes());
            (raw, physical)
        }
        4 => {
            let anchor = store.dictionary_anchor_for(sequence).unwrap();
            let raw=crate::dictionary_codec::encode(prepared,json!({"kind":"EXECUTION_PREPARED","sequence":sequence,"input_id":prepared["input"]["input_id"]}),sequence,anchor.as_ref().map(|source|&source.anchor)).unwrap();
            let physical = digest(raw.as_bytes());
            (raw, physical)
        }
        _ => panic!("fault writer requires the selected format's original encoder"),
    };
    if store.storage_version == 2 {
        store
            .connection
            .execute(
                "UPDATE records SET payload=?1,digest=?2 WHERE sequence=?3",
                params![&raw, &physical, sequence as i64],
            )
            .unwrap();
    } else {
        store
            .connection
            .execute(
                "UPDATE records SET payload=?1,digest=?2,ready=?3,delivered=?4 WHERE sequence=?5",
                params![
                    &raw,
                    &physical,
                    if ready { 1 } else { 0 },
                    if delivered { 1 } else { 0 },
                    sequence as i64
                ],
            )
            .unwrap();
    }
}
fn rehash_prepared(prepared: &mut Value) {
    prepared.as_object_mut().unwrap().remove("payload_hash");
    prepared["payload_hash"] = json!(hash(prepared));
}
#[test]
fn a_resealed_bad_intermediate_state_cannot_borrow_warm_data_validity_from_its_corrected_head() {
    let mut h = encoded_source_history();
    let original = h.store.read_records().unwrap();
    h.store.save_checkpoint(&h.components).unwrap();
    let mut bad = original[1].prepared().record();
    bad["projections"][2]["result"]["state"]["snapshot"]["cash"] = json!("999.00");
    bad["projections"][2]["result_hash"] = json!(hash(&bad["projections"][2]["result"]));
    rehash_prepared(&mut bad);
    let mut corrected = original[2].prepared().record();
    corrected["projections"][2]["before_hash"] = bad["projections"][2]["result_hash"].clone();
    rehash_prepared(&mut corrected);
    replace_prepared_source(&h.store, 2, &bad, true, false);
    replace_prepared_source(&h.store, 3, &corrected, true, false);
    let actual = h.store.read_records().unwrap();
    assert_eq!(
        actual.last(),
        original.last(),
        "the complete final source Record and retained head checkpoint really remain unchanged"
    );
    assert!(
        actual
            .iter()
            .zip(&original)
            .all(|(a, b)| a.prepared().input() == b.prepared().input()),
        "same original inputs do not prove the intermediate component state"
    );
    let before = fs::read(h.root.db()).unwrap();
    assert!(h.store.save_checkpoint(&h.components).is_err());
    assert_eq!(
        fs::read(h.root.db()).unwrap(),
        before,
        "no bad transition or old checkpoint can be repaired by observing it"
    );
}
#[test]
fn warm_checkpoint_data_does_not_replace_current_owner_or_cross_owner_reconciliation() {
    let mut h = history(5, "12.00");
    let foreign = history(5, "13.00");
    h.store.save_checkpoint(&h.components).unwrap();
    let before = fs::read(h.root.db()).unwrap();
    assert!(h.store.save_checkpoint(&foreign.components).is_err());
    assert_eq!(fs::read(h.root.db()).unwrap(), before);
    // Install a syntactically valid original Ledger checkpoint whose own
    // commands replay, but whose valuation conflicts with this Account. The
    // full original cross-owner diagnostic remains an independent obligation.
    let records = h.store.read_records().unwrap();
    let mut changed = records[4].record();
    changed["prepared"]["projections"][3]["result"] =
        foreign.components.checkpoint().unwrap()["components"][3].clone();
    changed["prepared"]["projections"][3]["result_hash"] =
        json!(hash(&changed["prepared"]["projections"][3]["result"]));
    rehash_prepared(&mut changed["prepared"]);
    let db = Connection::open(h.root.db()).unwrap();
    db.execute(
        "UPDATE records SET payload=?1,digest=?2 WHERE sequence=5",
        params![changed.to_string(), hash(&changed)],
    )
    .unwrap();
    db.execute(
        "UPDATE state SET last_hash=?1 WHERE singleton=1",
        [hash(&changed["prepared"])],
    )
    .unwrap();
    db.execute("DELETE FROM checkpoints WHERE sequence=5", [])
        .unwrap();
    drop(db);
    let mut components = Components::new(config()).unwrap();
    recover(&mut h.store, &mut components).unwrap();
    let diagnostic = components.reconcile(&h.store).unwrap().record();
    assert_eq!(
        diagnostic["status"], "MISMATCHED",
        "individually replayable owners do not imply aggregate consistency"
    );
    let saved = h.store.save_checkpoint(&components).unwrap();
    assert_eq!(
        saved["components"],
        components.checkpoint().unwrap(),
        "storage must preserve safety history even when diagnostics report a financial difference"
    );
    assert_eq!(components.reconcile(&h.store).unwrap().record(), diagnostic);
}
#[test]
fn pure_transition_validity_cannot_certify_a_foreign_replayed_fee_history() {
    let mut h = encoded_source_history();
    h.store.save_checkpoint(&h.components).unwrap();
    let mut donor = Harness::new(config()).unwrap();
    for value in [
        open(1, "BUY"),
        stage(2, 1, "UNKNOWN"),
        fill(3, 1, "1", "10.00", "0.50"),
        terminal(4, 1, "CANCELLED"),
    ] {
        let planned = donor.prepare(&value).unwrap();
        coordinate(&mut donor.store, &mut donor.components, &planned).unwrap();
    }
    let mut prepared = h.store.read_records().unwrap()[3].prepared().record();
    prepared["projections"][5]["result"]["fee_authority"] =
        donor.components.checkpoint().unwrap()["components"][5]["fee_authority"].clone();
    prepared["projections"][5]["result_hash"] = json!(hash(&prepared["projections"][5]["result"]));
    rehash_prepared(&mut prepared);
    replace_prepared_source(&h.store, 4, &prepared, true, false);
    h.store
        .connection
        .execute(
            "UPDATE state SET last_hash=?1 WHERE singleton=1",
            [hash(&prepared)],
        )
        .unwrap();
    h.store
        .connection
        .execute("DELETE FROM checkpoints WHERE sequence=4", [])
        .unwrap();
    let mut components = Components::new(config()).unwrap();
    recover(&mut h.store, &mut components).unwrap();
    assert_eq!(
        components.reconcile(&h.store).unwrap_err().0,
        "RECONCILIATION_FEE_HISTORY_UNAVAILABLE"
    );
    let before = fs::read(h.root.db()).unwrap();
    assert!(
        h.store.save_checkpoint(&components).is_err(),
        "pure owner data validity cannot authenticate its Fee relation to current ordered Fill facts"
    );
    assert_eq!(fs::read(h.root.db()).unwrap(), before);
}

fn dictionary_history() -> History {
    let root = Root::new();
    let mut store = SqliteStore::create(&root.0, config(), &"b".repeat(64)).unwrap();
    let mut components = Components::new(config()).unwrap();
    let mut reference = Harness::new(config()).unwrap();
    let mut inputs = Vec::new();
    for n in 1..=18 {
        let value = match n {
            1 => open(1, "BUY"),
            2 => stage(2, 1, "UNKNOWN"),
            3 => fill(3, 1, "1", "10.00", "1.00"),
            4 => terminal(4, 1, "CANCELLED"),
            _ => {
                let state = components.state(&store).unwrap();
                input(
                    n,
                    "VALUATION",
                    json!({"schema_version":1,"valuation":format!("dictionary-{n}"),"version":n,"position_evidence":hash(&components.checkpoint().unwrap()["components"][1]),"economic_version":state["account"]["snapshot"]["economic_version"],"marks":[{"schema_version":1,"instrument":"600000.XSHG","mark":"12.00","source_ref":format!("dictionary-mark-{n}"),"family":"CLOSED_BAR","version":n,"time":n,"as_of_sequence":n}]}),
                )
            }
        };
        let planned = components.prepare(&store, &value).unwrap();
        coordinate(&mut store, &mut components, &planned).unwrap();
        let expected = reference.prepare(&value).unwrap();
        coordinate(&mut reference.store, &mut reference.components, &expected).unwrap();
        inputs.push(value);
    }
    History {
        store,
        components,
        reference,
        inputs,
        checkpoints: Vec::new(),
        root,
    }
}
fn dictionary_raw(store: &SqliteStore, sequence: u64) -> (String, String) {
    store
        .connection
        .query_row(
            "SELECT payload,digest FROM records WHERE sequence=?1",
            [i64::try_from(sequence).unwrap()],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .unwrap()
}
#[test]
fn dictionary_store_keeps_exact_logical_records_and_fixed_actual_anchor_bindings() {
    let h = dictionary_history();
    assert_eq!(h.store.storage_version, 4);
    let expected = h.reference.store.rows.clone();
    assert_eq!(h.store.read_records().unwrap(), expected);
    for n in 1..=18_u64 {
        let (raw, physical) = dictionary_raw(&h.store, n);
        let frame: Value = serde_json::from_str(&raw).unwrap();
        let base = 1 + (n - 1) / 16 * 16;
        assert_eq!(digest(raw.as_bytes()), physical);
        assert_eq!(frame["codec"], "ZSTD_CANONICAL_JSON_DICTIONARY_V1");
        assert_eq!(
            frame["logical_sha256"],
            digest(&expected[n as usize - 1].prepared().encode().unwrap())
        );
        assert_eq!(
            frame["summary"],
            json!({"kind":"EXECUTION_PREPARED","sequence":n,"input_id":expected[n as usize-1].prepared().input()["input_id"]})
        );
        if base == n {
            assert!(frame["basis"].is_null());
        } else {
            let (base_raw, base_physical) = dictionary_raw(&h.store, base);
            let base_frame: Value = serde_json::from_str(&base_raw).unwrap();
            assert_eq!(
                frame["basis"],
                json!({"sequence":base,"physical_sha256":base_physical,"logical_sha256":base_frame["logical_sha256"]})
            );
        }
    }
    let checkpoint = h.components.checkpoint().unwrap();
    assert_eq!(checkpoint, h.reference.components.checkpoint().unwrap());
}
#[test]
fn dictionary_store_warm_full_and_point_reads_still_observe_actual_base_and_current_flags() {
    let h = dictionary_history();
    let expected = h.store.read_records().unwrap();
    reset_encoded_work();
    for _ in 0..2 {
        assert_eq!(h.store.read_records().unwrap(), expected);
    }
    assert_eq!(
        SOURCE_RAW_ROWS.with(std::cell::Cell::get),
        36,
        "full scans freshly read every actual row, without extra per-dependent base SQL reads"
    );
    assert_eq!(
        crate::codec::DECODED_BYTES.with(std::cell::Cell::get),
        0,
        "exact base and target data may share only prior codec work"
    );
    assert_eq!(crate::codec::PHYSICAL_HASHES.with(std::cell::Cell::get), 0);
    SOURCE_RAW_ROWS.with(|n| n.set(0));
    let record = h.store.read_one(16).unwrap().unwrap().0;
    assert_eq!(record, expected[15]);
    assert_eq!(
        SOURCE_RAW_ROWS.with(std::cell::Cell::get),
        2,
        "a point read must observe its actual base row too"
    );
    h.store
        .connection
        .execute("UPDATE records SET delivered=1 WHERE sequence=16", [])
        .unwrap();
    SOURCE_RAW_ROWS.with(|n| n.set(0));
    let changed = h.store.read_one(16).unwrap().unwrap().0;
    assert!(changed.delivered());
    assert!(changed.ready());
    assert_eq!(changed.prepared(), record.prepared());
    assert!(!record.delivered());
    assert_eq!(SOURCE_RAW_ROWS.with(std::cell::Cell::get), 2);
    let all = h.store.read_records().unwrap();
    assert!(all[15].delivered());
    assert_eq!(all[15].prepared(), expected[15].prepared());
}
#[test]
fn dictionary_store_changed_actual_anchor_cannot_hide_behind_unchanged_dependent_memo() {
    use base64::{Engine, engine::general_purpose::STANDARD};
    let h = dictionary_history();
    h.store.read_one(16).unwrap();
    let (base_raw, base_physical) = dictionary_raw(&h.store, 1);
    let first_id = h.reference.store.rows[0].prepared().input()["input_id"]
        .as_str()
        .unwrap()
        .to_owned();
    h.store
        .connection
        .execute("DELETE FROM records WHERE sequence=1", [])
        .unwrap();
    assert!(h.store.read_one(16).is_err());
    assert!(h.store.read_records().is_err());
    assert_eq!(
        h.store
            .connection
            .query_row("SELECT count(*) FROM records WHERE sequence=1", [], |row| {
                row.get::<_, i64>(0)
            })
            .unwrap(),
        0,
        "missing actual base is never repaired from its old memo"
    );
    h.store
        .connection
        .execute(
            "INSERT INTO records VALUES(1,?1,?2,?3,1,0)",
            params![first_id, &base_raw, &base_physical],
        )
        .unwrap();
    h.store.read_one(16).unwrap();
    h.store
        .connection
        .execute(
            "UPDATE records SET digest=?1 WHERE sequence=1",
            ["0".repeat(64)],
        )
        .unwrap();
    assert!(h.store.read_one(16).is_err());
    assert_eq!(dictionary_raw(&h.store, 1).1, "0".repeat(64));
    h.store
        .connection
        .execute(
            "UPDATE records SET digest=?1 WHERE sequence=1",
            [&base_physical],
        )
        .unwrap();
    h.store.read_one(16).unwrap();
    // A different VALID physical anchor for the SAME logical body must still
    // invalidate the dependent physical-base pin and its old successful memo.
    let frame = crate::dictionary_codec::inspect(&base_raw, &base_physical, 1).unwrap();
    let (body, anchor) = crate::dictionary_codec::decode_anchor(&frame).unwrap();
    let mut changed: Value = serde_json::from_str(&base_raw).unwrap();
    changed["data"] = json!(STANDARD.encode(zstd::bulk::compress(anchor.bytes(), 19).unwrap()));
    let changed = changed.to_string();
    let changed_sha = digest(changed.as_bytes());
    assert_ne!(changed, base_raw);
    let changed_frame = crate::dictionary_codec::inspect(&changed, &changed_sha, 1).unwrap();
    assert_eq!(
        crate::dictionary_codec::decode_anchor(&changed_frame)
            .unwrap()
            .0,
        body
    );
    h.store
        .connection
        .execute(
            "UPDATE records SET payload=?1,digest=?2 WHERE sequence=1",
            params![&changed, &changed_sha],
        )
        .unwrap();
    assert!(h.store.read_one(16).is_err());
    assert!(h.store.read_records().is_err());
    assert_eq!(
        dictionary_raw(&h.store, 1).0,
        changed,
        "refusal never rewrites an immutable anchor"
    );
    h.store
        .connection
        .execute(
            "UPDATE records SET payload=?1,digest=?2 WHERE sequence=1",
            params![&base_raw, &base_physical],
        )
        .unwrap();
    h.store.read_one(16).unwrap();
    let (target_raw, target_sha) = dictionary_raw(&h.store, 16);
    let target_frame = crate::dictionary_codec::inspect(&target_raw, &target_sha, 16).unwrap();
    let mut target = crate::dictionary_codec::decode(&target_frame, Some(&anchor)).unwrap();
    target["projections"][2]["result"]["state"]["snapshot"]["cash"] = json!("1.00");
    let raw = crate::dictionary_codec::encode(
        &target,
        json!({"kind":"EXECUTION_PREPARED","sequence":16,"input_id":target["input"]["input_id"]}),
        16,
        Some(&anchor),
    )
    .unwrap();
    h.store
        .connection
        .execute(
            "UPDATE records SET payload=?1,digest=?2 WHERE sequence=16",
            params![&raw, digest(raw.as_bytes())],
        )
        .unwrap();
    assert!(
        h.store
            .read_one(16)
            .unwrap_err()
            .0
            .contains("EXECUTION_PAYLOAD_HASH"),
        "a valid new physical frame must take the original complete logical verifier, never the old memo"
    );
    assert_eq!(dictionary_raw(&h.store, 16).0, raw);
    h.store
        .connection
        .execute(
            "UPDATE records SET payload=?1,digest=?2 WHERE sequence=16",
            params![&target_raw, &target_sha],
        )
        .unwrap();
    let last: String = h
        .store
        .connection
        .query_row("SELECT last_hash FROM state", [], |r| r.get(0))
        .unwrap();
    h.store
        .connection
        .execute("UPDATE state SET last_hash=?1", ["f".repeat(64)])
        .unwrap();
    assert!(h.store.head().is_err());
    h.store
        .connection
        .execute("UPDATE state SET last_hash=?1", [last])
        .unwrap();
    assert_eq!(h.store.read_records().unwrap(), h.reference.store.rows);
}

#[test]
fn dictionary_runtime_warm_reads_recheck_original_header_identity_and_unready_base_without_repair()
{
    let h = dictionary_history();
    let path = h.root.0.clone();
    drop(h.store);
    let runtime = crate::Runtime::open(&path, config(), &"b".repeat(64)).unwrap();
    let expected = runtime.state().unwrap();
    let records = runtime.records().unwrap();
    let db = Connection::open(path.join("runtime.sqlite3")).unwrap();
    for (pragma, changed, original) in [
        ("user_version", 3_i64, 4_i64),
        ("application_id", 0, APPLICATION),
    ] {
        db.pragma_update(None, pragma, changed).unwrap();
        assert!(
            runtime.state().is_err(),
            "warm state hid changed actual {pragma}"
        );
        assert!(
            runtime.records().is_err(),
            "warm records hid changed actual {pragma}"
        );
        assert_eq!(
            db.pragma_query_value(None, pragma, |row| row.get::<_, i64>(0))
                .unwrap(),
            changed,
            "read refusal rewrote actual header"
        );
        db.pragma_update(None, pragma, original).unwrap();
        assert_eq!(runtime.state().unwrap(), expected);
        assert_eq!(runtime.records().unwrap(), records);
    }
    let (payload, digest): (String, String) = db
        .query_row("SELECT payload,digest FROM meta", [], |row| {
            Ok((row.get(0)?, row.get(1)?))
        })
        .unwrap();
    let mut foreign: Value = serde_json::from_str(&payload).unwrap();
    foreign["configuration"]["generation"] = json!("f".repeat(64));
    let foreign = foreign.to_string();
    db.execute(
        "UPDATE meta SET payload=?1,digest=?2",
        params![
            &foreign,
            super::hash(&serde_json::from_str::<Value>(&foreign).unwrap())
        ],
    )
    .unwrap();
    assert!(runtime.state().is_err());
    assert!(runtime.records().is_err());
    assert_eq!(
        db.query_row("SELECT payload FROM meta", [], |row| row
            .get::<_, String>(0))
            .unwrap(),
        foreign
    );
    db.execute(
        "UPDATE meta SET payload=?1,digest=?2",
        params![payload, digest],
    )
    .unwrap();
    assert_eq!(runtime.state().unwrap(), expected);
    assert_eq!(runtime.records().unwrap(), records);
    db.execute(
        "UPDATE records SET ready=0,delivered=0 WHERE sequence=1",
        [],
    )
    .unwrap();
    assert!(
        runtime
            .state()
            .unwrap_err()
            .0
            .contains("UNREADY_PREDECESSOR"),
        "a warm actual base's current flags cannot borrow prior Ready proof"
    );
    assert!(runtime.records().is_err());
    assert_eq!(
        db.query_row("SELECT ready FROM records WHERE sequence=1", [], |row| row
            .get::<_, i64>(
            0
        ))
        .unwrap(),
        0
    );
    db.execute("UPDATE records SET ready=1 WHERE sequence=1", [])
        .unwrap();
    assert_eq!(runtime.state().unwrap(), expected);
    assert_eq!(runtime.records().unwrap(), records);
    drop(db);
    drop(runtime);
}
#[test]
fn dictionary_record_envelope_keeps_the_original_full_eight_mib_budget_before_expansion() {
    let h = dictionary_history();
    let (base_raw, base_sha) = dictionary_raw(&h.store, 1);
    let frame = crate::dictionary_codec::inspect(&base_raw, &base_sha, 1).unwrap();
    let (_, anchor) = crate::dictionary_codec::decode_anchor(&frame).unwrap();
    let (target_raw, target_sha) = dictionary_raw(&h.store, 16);
    let frame = crate::dictionary_codec::inspect(&target_raw, &target_sha, 16).unwrap();
    let mut target = crate::dictionary_codec::decode(&frame, Some(&anchor)).unwrap();
    target["projections"][2]["result"]["state"]["resource-bound-probe"] = json!("");
    let current = serde_json::to_vec(&target).unwrap().len();
    let envelope = serde_json::to_vec(
        &json!({"schema_version":1,"prepared":null,"ready":true,"delivered":false}),
    )
    .unwrap()
    .len()
        - 4;
    let size = crate::codec::LIMIT - envelope + 1;
    target["projections"][2]["result"]["state"]["resource-bound-probe"] =
        json!("x".repeat(size - current));
    assert_eq!(serde_json::to_vec(&target).unwrap().len(), size);
    let raw = crate::dictionary_codec::encode(
        &target,
        json!({"kind":"EXECUTION_PREPARED","sequence":16,"input_id":target["input"]["input_id"]}),
        16,
        Some(&anchor),
    )
    .unwrap();
    let header =
        crate::dictionary_codec::inspect(&raw, &super::digest(raw.as_bytes()), 16).unwrap();
    assert!(header.size <= crate::codec::LIMIT);
    assert_eq!(header.size + envelope, crate::codec::LIMIT + 1);
    h.store
        .connection
        .execute(
            "UPDATE records SET payload=?1,digest=?2 WHERE sequence=16",
            params![&raw, super::digest(raw.as_bytes())],
        )
        .unwrap();
    reset_encoded_work();
    assert_eq!(
        h.store.read_one(16).unwrap_err().0,
        "RUNTIME_STORE_RECORD_BOUND",
        "bounded Prepared bytes alone cannot enlarge the original complete Record budget"
    );
    assert_eq!(
        crate::codec::DECODED_BYTES.with(std::cell::Cell::get),
        0,
        "the declared full Record excess must be rejected before logical expansion"
    );
    assert_eq!(dictionary_raw(&h.store, 16).0, raw);
}

fn one_record_codec_history(version: u32) -> (SqliteStore, Components, Root, Record) {
    let root = Root::new();
    let mut store = match version {
        2 => legacy_store(&root.0, config(), &"b".repeat(64)),
        3 => zlib_store(&root.0, config(), &"b".repeat(64)),
        4 => SqliteStore::create(&root.0, config(), &"b".repeat(64)).unwrap(),
        _ => unreachable!(),
    };
    let mut components = Components::new(config()).unwrap();
    let prepared = components.prepare(&store, &open(1, "BUY")).unwrap();
    coordinate(&mut store, &mut components, &prepared).unwrap();
    let record = store.read_one(1).unwrap().unwrap().0;
    (store, components, root, record)
}
#[test]
fn encoded_commit_uses_original_prepared_bytes_without_building_a_legacy_record() {
    for version in [3, 4, 2] {
        let root = Root::new();
        let mut store = match version {
            2 => legacy_store(&root.0, config(), &"b".repeat(64)),
            3 => zlib_store(&root.0, config(), &"b".repeat(64)),
            4 => SqliteStore::create(&root.0, config(), &"b".repeat(64)).unwrap(),
            _ => unreachable!(),
        };
        let mut components = Components::new(config()).unwrap();
        let mut reference = Harness::new(config()).unwrap();
        for input in [
            open(1, "BUY"),
            stage(2, 1, "UNKNOWN"),
            fill(3, 1, "1", "10.00", "1.00"),
            terminal(4, 1, "CANCELLED"),
        ] {
            let prepared = components.prepare(&store, &input).unwrap();
            let expected_source = digest(&prepared.encode().unwrap());
            COMMIT_LEGACY_RECORD_CONSTRUCTIONS.with(|count| count.set(0));
            coordinate(&mut store, &mut components, &prepared).unwrap();
            assert_eq!(
                COMMIT_LEGACY_RECORD_CONSTRUCTIONS.with(std::cell::Cell::get),
                u64::from(version == 2),
                "new codec{version} built the complete legacy Record only to measure its envelope"
            );
            let actual = store.get(prepared.sequence()).unwrap().unwrap();
            assert_eq!(actual.prepared(), &prepared);
            assert!(actual.ready());
            assert!(!actual.delivered());
            let head: String = store
                .connection
                .query_row("SELECT last_hash FROM state", [], |row| row.get(0))
                .unwrap();
            assert_eq!(head, expected_source);
            assert_ne!(head, prepared.value()["payload_hash"].as_str().unwrap());
            let expected = reference.prepare(&input).unwrap();
            coordinate(&mut reference.store, &mut reference.components, &expected).unwrap();
        }
        assert_eq!(
            components.checkpoint().unwrap(),
            reference.components.checkpoint().unwrap()
        );
        let state = components.state(&store).unwrap();
        let rows = store.read_records().unwrap();
        let events = onlyalpha_execution::pending_events(&store, &components).unwrap();
        store.save_checkpoint(&components).unwrap();
        drop(store);
        let runtime = crate::Runtime::open(&root.0, config(), &"b".repeat(64)).unwrap();
        assert_eq!(runtime.records().unwrap(), rows);
        assert_eq!(runtime.state().unwrap(), state);
        assert_eq!(runtime.pending_events().unwrap(), events);
        drop(runtime);
    }
}
#[test]
fn cold_encoded_source_digest_reuses_only_the_fully_verified_complete_frame_body() {
    for version in [3, 4] {
        let (store, components, root, original) = one_record_codec_history(version);
        let expected = digest(&original.prepared().encode().unwrap());
        assert_ne!(
            expected,
            original.prepared().value()["payload_hash"]
                .as_str()
                .unwrap()
        );
        let raw: String = store
            .connection
            .query_row("SELECT payload FROM records WHERE sequence=1", [], |row| {
                row.get(0)
            })
            .unwrap();
        let physical = digest(raw.as_bytes());
        store.decoded_rows.borrow_mut().clear();
        PREPARED_SOURCE_ENCODINGS.with(|count| count.set(0));
        let (actual, source) = store.read_one(1).unwrap().unwrap();
        assert_eq!(
            PREPARED_SOURCE_ENCODINGS.with(std::cell::Cell::get),
            0,
            "codec{version} re-encoded a cold Prepared after already verifying its exact canonical full body SHA"
        );
        assert_eq!(actual, original);
        assert_eq!(source, expected);
        let mut false_header: Value = serde_json::from_str(&raw).unwrap();
        false_header["logical_sha256"] = json!(original.prepared().value()["payload_hash"]);
        let changed = false_header.to_string();
        store
            .connection
            .execute(
                "UPDATE records SET payload=?1,digest=?2 WHERE sequence=1",
                params![&changed, digest(changed.as_bytes())],
            )
            .unwrap();
        let before = fs::read(root.db()).unwrap();
        assert!(
            store.read_one(1).is_err(),
            "a rehashed physical header without its claimed logical bytes cannot supply the source digest"
        );
        assert_eq!(fs::read(root.db()).unwrap(), before);
        store
            .connection
            .execute(
                "UPDATE records SET payload=?1,digest=?2 WHERE sequence=1",
                params![&raw, &physical],
            )
            .unwrap();
        assert_eq!(store.read_one(1).unwrap().unwrap().1, expected);
        assert_eq!(store.read_records().unwrap(), vec![original]);
        assert_eq!(
            components.state(&store).unwrap()["account"]["snapshot"]["cash"],
            "1000.00"
        );
        drop(store);
    }
}

#[path = "prefix_work.rs"]
mod prefix_work;

#[test]
fn genesis_hash_memo_matches_full_checkpoint_and_returned_values_are_independent() {
    let root = Root::new();
    let store = SqliteStore::create(&root.0, config(), &"b".repeat(64)).unwrap();
    let expected = Components::new(config()).unwrap().checkpoint().unwrap()["components"]
        .as_array()
        .unwrap()
        .iter()
        .map(hash)
        .collect::<Vec<_>>();
    assert_eq!(store.genesis_hashes().unwrap(), expected);
    assert_eq!(
        store.genesis_hashes.get().unwrap(),
        &(config(), expected.clone())
    );
    let mut observed = store.genesis_hashes().unwrap();
    observed[0] = "f".repeat(64);
    assert_eq!(store.genesis_hashes().unwrap(), expected);
    assert_eq!(store.genesis_hashes.get().unwrap(), &(config(), expected));
}

#[test]
fn genesis_hash_memo_cannot_mask_changed_or_invalid_configuration() {
    let root = Root::new();
    let mut store = SqliteStore::create(&root.0, config(), &"b".repeat(64)).unwrap();
    let original = store.genesis_hashes().unwrap();
    let mut changed = config();
    changed["initial_cash"] = json!("2000.00");
    changed["capitals"]["cluster"] = json!("2000.00");
    let expected = Components::new(changed.clone())
        .unwrap()
        .checkpoint()
        .unwrap()["components"]
        .as_array()
        .unwrap()
        .iter()
        .map(hash)
        .collect::<Vec<_>>();
    assert_ne!(original, expected);
    store.identity["configuration"] = changed;
    assert_eq!(store.genesis_hashes().unwrap(), expected);
    assert_eq!(
        store.genesis_hashes.get().unwrap(),
        &(config(), original.clone())
    );
    store.identity["configuration"] = Value::Null;
    assert!(store.genesis_hashes().is_err());
    assert_eq!(
        store.genesis_hashes.get().unwrap(),
        &(config(), original.clone())
    );
    store.identity["configuration"] = config();
    assert_eq!(store.genesis_hashes().unwrap(), original);
}

#[test]
fn larger_sqlite_page_cache_observes_committed_external_flags_and_corrupt_bytes() {
    for read_only in [false, true] {
        let h = dictionary_history();
        drop(h.store);
        let store = if read_only {
            SqliteStore::read_only(&h.root.0, config(), &"b".repeat(64)).unwrap()
        } else {
            SqliteStore::open(&h.root.0, config(), &"b".repeat(64)).unwrap()
        };
        // Ensure this test covers the larger pager, then exercise real SQL coherence.
        let cache_kib: i64 = store
            .connection
            .pragma_query_value(None, "cache_size", |row| row.get(0))
            .unwrap();
        assert_eq!(cache_kib, -32768);
        let original = store.read_records().unwrap();
        assert_eq!(store.read_records().unwrap(), original);
        let external = Connection::open(h.root.db()).unwrap();
        external
            .execute("UPDATE records SET delivered=1 WHERE sequence=16", [])
            .unwrap();
        let changed = store.read_records().unwrap();
        assert!(changed[15].delivered());
        assert_eq!(changed[15].prepared(), original[15].prepared());
        assert!(!original[15].delivered());
        external
            .execute(
                "UPDATE records SET digest=?1 WHERE sequence=1",
                ["f".repeat(64)],
            )
            .unwrap();
        assert!(
            store.read_records().is_err(),
            "cached page hid a committed corrupt physical digest"
        );
        assert_eq!(
            external
                .query_row("SELECT digest FROM records WHERE sequence=1", [], |row| row
                    .get::<_, String>(0))
                .unwrap(),
            "f".repeat(64)
        );
        drop(external);
        drop(store);
    }
}

#[test]
fn new_large_pages_keep_original_sqlite_durability_and_header_contract() {
    let root = Root::new();
    let store = SqliteStore::create(&root.0, config(), &"b".repeat(64)).unwrap();
    for (name, expected) in [
        ("page_size", 65536_i64),
        ("cache_size", -32768),
        ("synchronous", 2),
        ("foreign_keys", 1),
        ("trusted_schema", 0),
    ] {
        let actual: i64 = store
            .connection
            .pragma_query_value(None, name, |row| row.get(0))
            .unwrap();
        assert_eq!(actual, expected, "{name}");
    }
    let journal: String = store
        .connection
        .pragma_query_value(None, "journal_mode", |row| row.get(0))
        .unwrap();
    assert_eq!(journal, "delete");
    assert_eq!(&fs::read(root.db()).unwrap()[16..18], &[0, 1]);
    drop(store);
    for read_only in [false, true] {
        let store = if read_only {
            SqliteStore::read_only(&root.0, config(), &"b".repeat(64)).unwrap()
        } else {
            SqliteStore::open(&root.0, config(), &"b".repeat(64)).unwrap()
        };
        assert!(store.read_records().unwrap().is_empty());
        assert_eq!(
            store
                .connection
                .pragma_query_value(None, "page_size", |row| row.get::<_, i64>(0))
                .unwrap(),
            65536
        );
    }
}

#[test]
fn ordinary_open_keeps_existing_small_page_facts_and_never_rewrites_the_database() {
    use std::os::unix::fs::MetadataExt;
    let h = dictionary_history();
    let records = h.store.read_records().unwrap();
    drop(h.store);
    // Construct a retained physical-layout fixture outside the owning session.
    // No production open or migration performs this operation.
    let fixture = Connection::open(h.root.db()).unwrap();
    fixture.pragma_update(None, "page_size", 4096).unwrap();
    fixture.execute_batch("VACUUM").unwrap();
    drop(fixture);
    let bytes = fs::read(h.root.db()).unwrap();
    let inode = fs::metadata(h.root.db()).unwrap().ino();
    assert_eq!(&bytes[16..18], &[16, 0]);
    assert!(SqliteStore::create(&h.root.0, config(), &"b".repeat(64)).is_err());
    assert_eq!(fs::read(h.root.db()).unwrap(), bytes);
    for read_only in [false, true] {
        let store = if read_only {
            SqliteStore::read_only(&h.root.0, config(), &"b".repeat(64)).unwrap()
        } else {
            SqliteStore::open(&h.root.0, config(), &"b".repeat(64)).unwrap()
        };
        assert_eq!(store.read_records().unwrap(), records);
        assert_eq!(
            store
                .connection
                .pragma_query_value(None, "page_size", |row| row.get::<_, i64>(0))
                .unwrap(),
            4096
        );
        drop(store);
        assert_eq!(fs::metadata(h.root.db()).unwrap().ino(), inode);
        assert_eq!(fs::read(h.root.db()).unwrap(), bytes);
    }
}
