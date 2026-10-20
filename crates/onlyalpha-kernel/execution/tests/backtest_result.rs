const SETTLEMENT_FIXTURE: &str = include_str!("../../../../test-data/settlement/common-v1.json");
const FIXTURE: &str = include_str!("../../../../test-data/execution/domain-inputs.json");
mod support;
use onlyalpha_execution::{Components, Record, coordinate, recover};
use serde_json::{Value, json};
use support::*;
fn hash(v: &Value) -> String {
    onlyalpha_execution::digest(v.to_string().as_bytes())
}
fn apply(h: &mut Harness, v: &Value) {
    let p = h.prepare(v).unwrap();
    coordinate(&mut h.store, &mut h.components, &p).unwrap();
}
fn manifest(h: &Harness) -> Value {
    json!({"schema_version":1,"configuration":hash(&h.checkpoint().unwrap()["config"]),"kernel_artifact":"b".repeat(64),"input_pin":"c".repeat(64),"initial_time":{"schema_version":1,"unix_nanos":0},"final_time":{"schema_version":1,"unix_nanos":100},"inputs":h.store.rows.iter().map(|r|hash(r.prepared().input())).collect::<Vec<_>>()})
}
fn outcome(s: &str) -> Value {
    json!({"schema_version":1,"status":s,"reason":if s=="COMPLETED" {Value::Null} else {json!("driver-reason")}})
}
fn loaded() -> Harness {
    let mut h = Harness::new(config()).unwrap();
    for v in [
        open(1, "BUY"),
        stage(2, 1, "UNKNOWN"),
        fill(3, 1, "1", "10.00", "1.00"),
        terminal(4, 1, "CANCELLED"),
    ] {
        apply(&mut h, &v);
    }
    h
}
#[test]
fn complete_transcript_seals_actual_ready_facts_and_owner_values_without_writes() {
    let h = loaded();
    let before = h.checkpoint().unwrap();
    let result = h
        .components
        .backtest_result(&h.store, &manifest(&h), &outcome("COMPLETED"))
        .unwrap();
    let v = result.record();
    assert_eq!(v["run"]["status"], "COMPLETED");
    assert_eq!(v["completion_scope"], "EXECUTION_TRANSCRIPT");
    assert_eq!(v["execution"]["transaction_count"], 4);
    assert_eq!(v["execution"]["trade_count"], 1);
    assert_eq!(v["final_account"]["equity"], "999.00");
    assert_eq!(v["runtime_performance"]["summary"]["fees"], "1.00");
    assert_eq!(v["cluster_results"][0]["final_ledger"]["equity"], "999.00");
    assert_eq!(v["reconciliation"]["status"], "MATCHED");
    assert_eq!(v["facts"].as_array().unwrap().len(), 4);
    assert_eq!(v["trades"].as_array().unwrap().len(), 1);
    assert_eq!(
        v["final_seal"]["time"],
        json!({"schema_version":1,"unix_nanos":100})
    );
    assert_eq!(h.checkpoint().unwrap(), before);
    let mut detached = result.record();
    detached["run"]["status"] = json!("FAILED");
    assert_eq!(result.record(), v);
    assert_eq!(
        serde_json::from_slice::<Value>(&result.encode().unwrap()).unwrap(),
        v
    );
    let mut fresh = Components::new(config()).unwrap();
    let mut store = h.store.clone();
    recover(&mut store, &mut fresh).unwrap();
    assert_eq!(
        fresh
            .backtest_result(&store, &manifest(&h), &outcome("COMPLETED"))
            .unwrap(),
        result
    );
}
#[test]
fn matched_balances_do_not_certify_transcript_completion_or_unknown_orders() {
    let h = loaded();
    let mut m = manifest(&h);
    m["inputs"]
        .as_array_mut()
        .unwrap()
        .push(json!("d".repeat(64)));
    assert!(
        h.components
            .backtest_result(&h.store, &m, &outcome("COMPLETED"))
            .is_err()
    );
    for s in ["FAILED", "CANCELLED", "INCOMPLETE", "UNKNOWN"] {
        let v = h
            .components
            .backtest_result(&h.store, &m, &outcome(s))
            .unwrap()
            .record();
        assert_eq!(
            v["run"]["status"],
            if s == "UNKNOWN" { "INCOMPLETE" } else { s }
        );
        assert_eq!(v["closure"]["complete"], false);
    }
    let mut h = Harness::new(config()).unwrap();
    apply(&mut h, &open(1, "BUY"));
    apply(&mut h, &stage(2, 1, "UNKNOWN"));
    let v = h
        .components
        .backtest_result(&h.store, &manifest(&h), &outcome("COMPLETED"))
        .unwrap()
        .record();
    assert_eq!(v["run"]["status"], "FAILED");
    assert!(
        v["diagnostics"]
            .as_array()
            .unwrap()
            .iter()
            .any(|d| d["code"] == "UNRESOLVED_ORDER")
    );
}

fn valuation(h: &Harness, n: u64, mark: &str) -> Value {
    let s = h.state().unwrap();
    input(
        n,
        "VALUATION",
        json!({"schema_version":1,"valuation":format!("valuation-{n}"),"version":n,"position_evidence":hash(&h.checkpoint().unwrap()["components"][1]),"economic_version":s["account"]["snapshot"]["economic_version"],"marks":[{"schema_version":1,"instrument":"600000.XSHG","mark":mark,"source_ref":format!("mark-{n}"),"family":"CLOSED_BAR","version":n,"time":n,"as_of_sequence":n}]}),
    )
}
#[test]
fn strict_manifest_outcome_and_time_proofs_cannot_be_omitted_or_substituted() {
    let h = loaded();
    let m = manifest(&h);
    let good = outcome("COMPLETED");
    for field in [
        "configuration",
        "kernel_artifact",
        "input_pin",
        "initial_time",
        "final_time",
        "inputs",
    ] {
        let mut bad = m.clone();
        bad.as_object_mut().unwrap().remove(field);
        assert!(
            h.components.backtest_result(&h.store, &bad, &good).is_err(),
            "{field}"
        );
    }
    let mut mutations = vec![];
    for field in ["configuration", "kernel_artifact", "input_pin"] {
        let mut bad = m.clone();
        bad[field] = json!("not-a-fingerprint");
        mutations.push(bad);
    }
    let mut bad = m.clone();
    bad["configuration"] = json!("d".repeat(64));
    mutations.push(bad);
    let mut bad = m.clone();
    bad["initial_time"]["unix_nanos"] = json!(2);
    mutations.push(bad);
    let mut bad = m.clone();
    bad["final_time"]["unix_nanos"] = json!(3);
    mutations.push(bad);
    let mut bad = m.clone();
    bad["initial_time"]["unix_nanos"] = json!("0");
    mutations.push(bad);
    let mut bad = m.clone();
    bad["extra"] = json!(true);
    mutations.push(bad);
    let mut bad = m.clone();
    bad["inputs"].as_array_mut().unwrap().swap(0, 1);
    mutations.push(bad);
    let mut bad = m.clone();
    bad["inputs"][2] = bad["inputs"][0].clone();
    mutations.push(bad);
    let mut bad = m.clone();
    bad["inputs"][2] = json!("e".repeat(64));
    mutations.push(bad);
    let mut bad = m.clone();
    bad["inputs"].as_array_mut().unwrap().pop();
    mutations.push(bad);
    for bad in mutations {
        assert!(
            h.components.backtest_result(&h.store, &bad, &good).is_err(),
            "{bad}"
        );
    }
    for bad in [
        json!({"schema_version":1,"status":"COMPLETED","reason":"pretend-success"}),
        json!({"schema_version":1,"status":"CANCELLED","reason":null}),
        json!({"schema_version":1,"status":"SUCCESS","reason":null}),
    ] {
        assert!(h.components.backtest_result(&h.store, &m, &bad).is_err());
    }
    for field in ["kernel_artifact", "input_pin"] {
        let original = h.components.backtest_result(&h.store, &m, &good).unwrap();
        let mut other = m.clone();
        other[field] = json!("d".repeat(64));
        assert_ne!(
            h.components
                .backtest_result(&h.store, &other, &good)
                .unwrap(),
            original
        );
    }
}
#[test]
fn every_projection_cut_refuses_finalization_then_reconstructs_the_same_result() {
    let mut baseline = loaded();
    let mark = valuation(&baseline, 5, "12.00");
    apply(&mut baseline, &mark);
    let m = manifest(&baseline);
    let out = outcome("COMPLETED");
    let expected = baseline
        .components
        .backtest_result(&baseline.store, &m, &out)
        .unwrap();
    for cut in 0..=6 {
        let mut h = loaded();
        let p = h.prepare(&mark).unwrap();
        h.commit_only(&p).unwrap();
        for i in 0..cut {
            h.install_projection(&p, i).unwrap();
        }
        for s in ["COMPLETED", "FAILED", "CANCELLED", "INCOMPLETE", "UNKNOWN"] {
            assert!(
                h.components
                    .backtest_result(&h.store, &m, &outcome(s))
                    .is_err()
            );
        }
        let cp = h.checkpoint().unwrap();
        let mut fresh = Components::new(config()).unwrap();
        fresh.restore(&cp, &hash(&cp)).unwrap();
        assert!(fresh.backtest_result(&h.store, &m, &out).is_err());
        recover(&mut h.store, &mut fresh).unwrap();
        assert_eq!(fresh.backtest_result(&h.store, &m, &out).unwrap(), expected);
    }
}
#[test]
fn missing_unready_foreign_and_rehashed_owner_proofs_are_unavailable_not_empty() {
    let h = loaded();
    let m = manifest(&h);
    let good = outcome("COMPLETED");
    let before = h.checkpoint().unwrap();
    let mut missing = h.store.clone();
    missing.rows.remove(0);
    assert!(h.components.backtest_result(&missing, &m, &good).is_err());
    for index in [0, h.store.rows.len() - 1] {
        let mut unready = h.store.clone();
        let mut r = unready.rows[index].record();
        r["ready"] = json!(false);
        unready.rows[index] = Record::decode(&r).unwrap();
        assert!(h.components.backtest_result(&unready, &m, &good).is_err());
        for component in 0..6 {
            let mut changed = h.store.clone();
            let mut r = changed.rows[index].record();
            let p = &mut r["prepared"];
            p["projections"][component]["result"]["wrong_owner"] = json!(true);
            p["projections"][component]["result_hash"] =
                json!(hash(&p["projections"][component]["result"]));
            p.as_object_mut().unwrap().remove("payload_hash");
            p["payload_hash"] = json!(hash(p));
            changed.rows[index] = Record::decode(&r).unwrap();
            assert!(h.components.backtest_result(&changed, &m, &good).is_err());
        }
    }
    for field in ["generation", "runtime", "account", "gateway"] {
        let mut cfg = config();
        cfg[field] = json!(if field == "generation" {
            "d".repeat(64)
        } else {
            "foreign".into()
        });
        let c = Components::new(cfg).unwrap();
        assert!(c.backtest_result(&h.store, &m, &good).is_err());
    }
    let mut cfg = config();
    cfg["runtime_kind"] = json!("SIM");
    let h2 = Harness::new(cfg).unwrap();
    assert!(
        h2.components
            .backtest_result(&h2.store, &manifest(&h2), &good)
            .is_err()
    );
    assert_eq!(h.checkpoint().unwrap(), before);
}
#[test]
fn delivery_receipts_and_repeated_reads_do_not_change_semantic_fingerprint_or_history() {
    use onlyalpha_execution::Store;
    let mut h = loaded();
    let m = manifest(&h);
    let out = outcome("COMPLETED");
    let a = h.components.backtest_result(&h.store, &m, &out).unwrap();
    let saved = a.record();
    for n in 1..=h.store.rows.len() as u64 {
        h.store.acknowledge(n).unwrap();
    }
    assert_eq!(h.components.backtest_result(&h.store, &m, &out).unwrap(), a);
    apply(&mut h, &valuation(&loaded(), 5, "11.00"));
    assert_eq!(a.record(), saved);
    assert!(h.components.backtest_result(&h.store, &m, &out).is_err());
    let b = h
        .components
        .backtest_result(&h.store, &manifest(&h), &out)
        .unwrap()
        .record();
    assert_ne!(
        b["determinism_fingerprint"],
        saved["determinism_fingerprint"]
    );
}

fn rounded_two_cluster_source() -> Harness {
    let mut cfg = config();
    cfg["capitals"] = json!({"cluster":"500.00","other":"500.00"});
    cfg["profiles"]["other"] = cfg["profiles"]["cluster"].clone();
    cfg["instruments"][0]["price_precision"] = json!(3);
    let mut h = Harness::new(cfg).unwrap();
    let mut first = open(1, "BUY");
    first["payload"]["request"]["price"]["precision"] = json!(3);
    first["payload"]["request"]["price"]["value"] = json!("10.000");
    refresh_market(&mut first);
    for v in [
        first,
        stage(2, 1, "UNKNOWN"),
        fill(3, 1, "1", "9.995", "1.00"),
    ] {
        apply(&mut h, &v);
    }
    let contract: Value = serde_json::from_str(include_str!(
        "../../../../test-data/position/valuation-order-contract.json"
    ))
    .unwrap();
    let mut v = open(4, "BUY");
    v["cluster"] = json!("other");
    v["payload"]["order"] = json!(order(2));
    v["payload"]["request"]["request_id"]["value"] = json!("request-2");
    v["payload"]["fee_contract"] = contract.clone();
    v["payload"]["request"]["price"]["precision"] = json!(3);
    v["payload"]["request"]["price"]["value"] = json!("10.000");
    refresh_market(&mut v);
    apply(&mut h, &v);
    let mut v = stage(5, 2, "UNKNOWN");
    v["cluster"] = json!("other");
    apply(&mut h, &v);
    let mut v = fill(6, 2, "1", "9.995", "1.00");
    v["cluster"] = json!("other");
    for key in ["fees", "settlement", "valuation"] {
        let p = &mut v["payload"][key];
        p["scope"]["cluster"] = json!("other");
        if key == "fees" {
            p["policy"] = contract["binding"]["fingerprint"].clone();
        }
        p.as_object_mut().unwrap().remove("source_digest");
        p["source_digest"] = json!(onlyalpha_execution::digest(p.to_string().as_bytes()));
    }
    apply(&mut h, &v);
    h
}

#[test]
fn all_clusters_and_real_rounding_mismatch_are_retained_and_force_failure() {
    let mut h = rounded_two_cluster_source();
    let v = valuation(&h, 7, "9.985");
    apply(&mut h, &v);
    let result = h
        .components
        .backtest_result(&h.store, &manifest(&h), &outcome("COMPLETED"))
        .unwrap()
        .record();
    assert_eq!(result["run"]["status"], "FAILED");
    assert_eq!(result["reconciliation"]["status"], "MISMATCHED");
    assert_eq!(result["cluster_results"].as_array().unwrap().len(), 2);
    assert_eq!(result["final_ledgers"].as_array().unwrap().len(), 2);
    assert_eq!(
        result["cluster_equity_timelines"].as_array().unwrap().len(),
        2
    );
    assert_eq!(
        result["runtime_performance"]["summary"]["maximum_drawdown"],
        "-0.00203000"
    );
    for c in result["cluster_results"].as_array().unwrap() {
        assert_eq!(
            c["cluster_performance"]["summary"]["maximum_drawdown"],
            "-0.00204000"
        );
    }
    assert!(
        result["diagnostics"]
            .as_array()
            .unwrap()
            .iter()
            .any(|d| d["code"] == "LEDGER_RECONCILIATION_MISMATCH")
    );
    for status in ["FAILED", "CANCELLED", "INCOMPLETE", "UNKNOWN"] {
        let r = h
            .components
            .backtest_result(&h.store, &manifest(&h), &outcome(status))
            .unwrap()
            .record();
        assert_eq!(r["run"]["status"], "FAILED");
        assert_eq!(r["diagnostics"][0]["code"], "DRIVER_TERMINATION");
        assert_eq!(r["run"]["requested_outcome"]["status"], status);
    }
}
#[test]
fn fresh_result_recovery_child() {
    let Ok(path) = std::env::var("ONLYALPHA_BACKTEST_RESULT_RECOVERY_FILE") else {
        return;
    };
    let v: Value = serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();
    let mut store = MemoryStore::default();
    store.rows = v["rows"]
        .as_array()
        .unwrap()
        .iter()
        .map(|r| Record::decode(r).unwrap())
        .collect();
    let mut c = Components::new(config()).unwrap();
    recover(&mut store, &mut c).unwrap();
    let result = c
        .backtest_result(&store, &v["manifest"], &v["outcome"])
        .unwrap();
    assert_eq!(result.record(), v["expected"]);
    println!("BACKTEST_RESULT_FRESH_PROCESS: PASS");
}
#[test]
fn real_file_and_new_process_reproduce_canonical_result_bytes() {
    let h = loaded();
    let m = manifest(&h);
    let out = outcome("COMPLETED");
    let path = std::env::temp_dir().join(format!(
        "onlyalpha-backtest-result-{}.json",
        std::process::id()
    ));
    assert!(!path.exists());
    std::fs::write(&path,serde_json::to_vec(&json!({"rows":h.store.rows.iter().map(Record::record).collect::<Vec<_>>(),"manifest":m,"outcome":out,"expected":h.components.backtest_result(&h.store,&m,&out).unwrap().record()})).unwrap()).unwrap();
    let child = std::process::Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "fresh_result_recovery_child", "--nocapture"])
        .env("ONLYALPHA_BACKTEST_RESULT_RECOVERY_FILE", &path)
        .output()
        .unwrap();
    std::fs::remove_file(path).unwrap();
    assert!(
        child.status.success(),
        "{}",
        String::from_utf8_lossy(&child.stderr)
    );
    assert!(String::from_utf8_lossy(&child.stdout).contains("BACKTEST_RESULT_FRESH_PROCESS: PASS"));
}

struct Unavailable<'a> {
    inner: &'a MemoryStore,
    missing: bool,
}
impl onlyalpha_execution::Store for Unavailable<'_> {
    fn head(&self) -> Result<u64, onlyalpha_execution::Error> {
        Ok(self.inner.rows.len() as u64)
    }
    fn get(&self, _: u64) -> Result<Option<Record>, onlyalpha_execution::Error> {
        if self.missing {
            Ok(None)
        } else {
            Err(onlyalpha_execution::Error("UNAVAILABLE".into()))
        }
    }
    fn commit(
        &mut self,
        _: &onlyalpha_execution::CommitIntent,
    ) -> Result<Record, onlyalpha_execution::Error> {
        Err(onlyalpha_execution::Error("READ_ONLY".into()))
    }
    fn mark_ready(&mut self, _: u64) -> Result<(), onlyalpha_execution::Error> {
        Err(onlyalpha_execution::Error("READ_ONLY".into()))
    }
    fn acknowledge(&mut self, _: u64) -> Result<(), onlyalpha_execution::Error> {
        Err(onlyalpha_execution::Error("READ_ONLY".into()))
    }
}
#[test]
fn inaccessible_store_never_certifies_an_empty_result_for_any_outcome() {
    let h = loaded();
    let m = manifest(&h);
    for missing in [false, true] {
        for status in ["COMPLETED", "FAILED", "CANCELLED", "INCOMPLETE", "UNKNOWN"] {
            assert!(
                h.components
                    .backtest_result(
                        &Unavailable {
                            inner: &h.store,
                            missing
                        },
                        &m,
                        &outcome(status)
                    )
                    .is_err()
            );
        }
    }
}

#[test]
fn common_vector_outputs() {
    let vectors = include_str!("../../../../test-data/execution/backtest-result-v1.jsonl");
    let mut outputs = vec![];
    for line in vectors.lines() {
        let v: Value = serde_json::from_str(line).unwrap();
        let h = if v["loaded"] == true {
            loaded()
        } else {
            let mut cfg = config();
            cfg["initial_cash"] = v["initial"].clone();
            cfg["capitals"] = v["capitals"].clone();
            if cfg["capitals"].get("other").is_some() {
                cfg["profiles"]["other"] = cfg["profiles"]["cluster"].clone();
            }
            Harness::new(cfg).unwrap()
        };
        let result = h
            .components
            .backtest_result(&h.store, &manifest(&h), &outcome("COMPLETED"))
            .unwrap()
            .record();
        let equities: serde_json::Map<_, _> = result["cluster_results"]
            .as_array()
            .unwrap()
            .iter()
            .map(|c| {
                (
                    c["cluster"].as_str().unwrap().into(),
                    c["final_ledger"]["equity"].clone(),
                )
            })
            .collect();
        let p = &result["runtime_performance"]["summary"];
        let observed = json!({"status":result["run"]["status"],"order_count":result["execution"]["order_count"],"trade_count":result["execution"]["trade_count"],"initial_equity":p["initial_equity"],"final_equity":p["final_equity"],"fees":p["fees"],"return_since_start":p["return_since_start"],"cluster_equities":equities});
        assert_eq!(observed, v["expected"]);
        outputs.push(json!({"case":v["case"],"observed":observed,"result":result}));
    }
    println!("BACKTEST_RESULT_VECTOR_OUTPUT {}", json!(outputs));
}

fn changed_input_record(record: &Record, input: Value) -> Record {
    let mut r = record.record();
    let p = &mut r["prepared"];
    let id = format!("ETX-{}", hash(&input));
    p["input"] = input.clone();
    p["transaction_id"] = json!(id);
    p["events"] = json!([{"schema_version":1,"event_id":format!("{id}-EVENT-1"),"transaction_id":id,"sequence":p["sequence"],"input":input}]);
    p.as_object_mut().unwrap().remove("payload_hash");
    p["payload_hash"] = json!(hash(p));
    Record::decode(&r).unwrap()
}
#[test]
fn rehashed_whole_context_nested_relation_source_ref_and_leaf_never_replace_an_occurrence() {
    let h = loaded();
    let original = h.store.rows[2].prepared().input();
    let mut variants = vec![];
    for field in ["runtime", "account", "cluster", "revision", "source_ref"] {
        let mut i = original.clone();
        i[field] = json!("other");
        variants.push(i);
    }
    let mut i = original.clone();
    i["op"] = json!("SUBMISSION");
    variants.push(i);
    let mut i = original.clone();
    i["payload"]["trade"] = json!("another-trade");
    variants.push(i);
    let mut i = original.clone();
    i["payload"]["fees"]["scope"]["cluster"] = json!("other");
    variants.push(i);
    let mut i = original.clone();
    i["payload"]["fees"]["source_ref"] = json!("another-source");
    variants.push(i);
    for input in variants {
        let mut changed = h.store.clone();
        changed.rows[2] = changed_input_record(&changed.rows[2], input.clone());
        let mut m = manifest(&h);
        m["inputs"][2] = json!(hash(&input));
        assert!(
            h.components
                .backtest_result(&changed, &m, &outcome("COMPLETED"))
                .is_err()
        );
    }
    let mut cp = h.checkpoint().unwrap();
    cp["config"]["generation"] = json!("f".repeat(64));
    let foreign = Components::new(cp["config"].clone()).unwrap();
    let mut m = manifest(&h);
    m["configuration"] = json!(hash(&cp["config"]));
    assert!(
        foreign
            .backtest_result(&h.store, &m, &outcome("COMPLETED"))
            .is_err()
    );
    let mut store = h.store.clone();
    let mut r = store.rows[2].record();
    let p = &mut r["prepared"];
    p["projections"][3]["result"] = p["projections"][2]["result"].clone();
    p["projections"][3]["result_hash"] = json!(hash(&p["projections"][3]["result"]));
    p.as_object_mut().unwrap().remove("payload_hash");
    p["payload_hash"] = json!(hash(p));
    store.rows[2] = Record::decode(&r).unwrap();
    assert!(
        h.components
            .backtest_result(&store, &manifest(&h), &outcome("COMPLETED"))
            .is_err()
    );
}

#[test]
fn admitted_large_capital_and_fee_round_at_the_single_owning_business_boundary() {
    let initial = format!("3{}.00", "0".repeat(120));
    let fee = format!("15{}.01", "0".repeat(111));
    let mut cfg = config();
    cfg["initial_cash"] = json!(initial);
    cfg["capitals"]["cluster"] = json!(initial);
    let mut h = Harness::new(cfg).unwrap();
    let mut admit = open(1, "BUY");
    admit["payload"]["fee_budget"] = json!(fee);
    apply(&mut h, &admit);
    apply(&mut h, &stage(2, 1, "UNKNOWN"));
    apply(&mut h, &fill(3, 1, "4", "10.00", &fee));
    let v = h
        .components
        .backtest_result(&h.store, &manifest(&h), &outcome("COMPLETED"))
        .unwrap()
        .record();
    assert_eq!(v["run"]["status"], "COMPLETED");
    assert_eq!(
        v["runtime_performance"]["summary"]["return_since_start"],
        "-0.00000001"
    );
    let p = &v["cluster_results"][0]["cluster_performance"]["summary"];
    assert_eq!(p["simple_return"], "-0.00000001");
    assert_eq!(p["drawdown"], "-0.00000001");
    assert_eq!(p["maximum_drawdown"], "-0.00000001");
    // A self-consistent hash cannot make a historically wrong derived rate current truth.
    let mut corrupt = h.checkpoint().unwrap();
    corrupt["components"][3]["state"]["ledgers"]["cluster"]["snapshot"]["simple_return"] =
        json!("0.00000000");
    let mut fresh = Components::new(corrupt["config"].clone()).unwrap();
    assert!(fresh.restore(&corrupt, &hash(&corrupt)).is_err());
}
