const SETTLEMENT_FIXTURE: &str = include_str!("../../../../test-data/settlement/common-v1.json");
const FIXTURE: &str = include_str!("../../../../test-data/execution/domain-inputs.json");
mod support;
use onlyalpha_execution::{Components, Record, coordinate, recover};
use serde_json::{Value, json};
use support::*;
fn apply(h: &mut Harness, v: &Value) {
    let p = h.prepare(v).unwrap();
    coordinate(&mut h.store, &mut h.components, &p).unwrap();
}
fn loaded() -> Harness {
    let mut h = Harness::new(config()).unwrap();
    for v in [
        open(1, "BUY"),
        stage(2, 1, "UNKNOWN"),
        fill(3, 1, "4", "10.00", "1.00"),
    ] {
        apply(&mut h, &v);
    }
    h
}
fn valuation(h: &Harness, n: u64, mark: &str) -> Value {
    let s = h.state().unwrap();
    input(
        n,
        "VALUATION",
        json!({"schema_version":1,"valuation":format!("valuation-{n}"),"version":n,"position_evidence":onlyalpha_execution::digest(h.checkpoint().unwrap()["components"][1].to_string().as_bytes()),"economic_version":s["account"]["snapshot"]["economic_version"],"marks":[{"schema_version":1,"instrument":"600000.XSHG","mark":mark,"source_ref":format!("mark-{n}"),"family":"CLOSED_BAR","version":n,"time":n,"as_of_sequence":n}]}),
    )
}
#[test]
fn complete_genesis_is_matched_and_read_only() {
    let h = Harness::new(config()).unwrap();
    let before = h.checkpoint().unwrap();
    let result = h.components.reconcile(&h.store).unwrap();
    let report = result.record();
    let mut content = report.clone();
    let identity = content.as_object_mut().unwrap().remove("id").unwrap();
    assert_eq!(
        identity,
        format!(
            "RLR-{}",
            onlyalpha_execution::digest(content.to_string().as_bytes())
        )
    );
    assert_eq!(report["status"], "MATCHED");
    assert_eq!(report["differences"], json!([]));
    assert_eq!(report["source"]["sequence"], 0);
    assert_eq!(report["source"]["time"], Value::Null);
    assert_eq!(report["scope"]["runtime"], "runtime");
    assert_eq!(
        serde_json::from_slice::<Value>(&result.encode().unwrap()).unwrap(),
        report
    );
    assert_eq!(h.checkpoint().unwrap(), before);
}
#[test]
fn actual_fill_and_market_only_valuation_reconcile_without_mutation() {
    let mut h = loaded();
    let v = valuation(&h, 4, "12.00");
    apply(&mut h, &v);
    let before = h.checkpoint().unwrap();
    let report = h.components.reconcile(&h.store).unwrap().record();
    assert_eq!(report["status"], "MATCHED");
    assert_eq!(report["trade_count"], 1);
    assert_eq!(report["totals"]["equity"]["account_value"], "1007.00");
    assert_eq!(report["totals"]["fees"]["ledger_total"], "1.00");
    assert_eq!(h.checkpoint().unwrap(), before);
    let mut detached = report.clone();
    detached["status"] = json!("MISMATCHED");
    assert_eq!(h.components.reconcile(&h.store).unwrap().record(), report);
}
#[test]
fn every_committed_projection_prefix_is_unavailable_until_exact_recovery() {
    for cut in 0..=6 {
        let mut h = loaded();
        let v = valuation(&h, 4, "12.00");
        let p = h.prepare(&v).unwrap();
        h.commit_only(&p).unwrap();
        for i in 0..cut {
            h.install_projection(&p, i).unwrap();
        }
        assert!(h.components.reconcile(&h.store).is_err());
        let cp = h.checkpoint().unwrap();
        let mut fresh = Components::new(config()).unwrap();
        fresh
            .restore(&cp, &onlyalpha_execution::digest(cp.to_string().as_bytes()))
            .unwrap();
        assert!(fresh.reconcile(&h.store).is_err());
        recover(&mut h.store, &mut fresh).unwrap();
        let a = fresh.reconcile(&h.store).unwrap().record();
        let mut again = Components::new(config()).unwrap();
        recover(&mut h.store, &mut again).unwrap();
        assert_eq!(again.reconcile(&h.store).unwrap().record(), a);
    }
}
#[test]
fn missing_unready_foreign_and_unapplied_source_never_becomes_matched() {
    let mut h = loaded();
    let before = h.checkpoint().unwrap();
    let mut missing = h.store.clone();
    missing.rows.remove(0);
    assert!(h.components.reconcile(&missing).is_err());
    let mut unready = h.store.clone();
    let mut record = unready.rows[0].record();
    record["ready"] = json!(false);
    unready.rows[0] = Record::decode(&record).unwrap();
    assert!(h.components.reconcile(&unready).is_err());
    let mut other = config();
    other["generation"] = json!("b".repeat(64));
    assert!(Components::new(other).unwrap().reconcile(&h.store).is_err());
    let p = h.prepare(&valuation(&h, 4, "12.00")).unwrap();
    h.install_projection(&p, 0).unwrap();
    let mut stale = Components::new(config()).unwrap();
    stale
        .restore(
            &before,
            &onlyalpha_execution::digest(before.to_string().as_bytes()),
        )
        .unwrap();
    assert!(stale.reconcile(&h.store).is_err());
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
fn real_complete_multi_cluster_rounding_difference_is_reported_and_never_repaired() {
    let mut h = rounded_two_cluster_source();
    let v = valuation(&h, 7, "9.985");
    apply(&mut h, &v);
    let before = h.checkpoint().unwrap();
    let report = h.components.reconcile(&h.store).unwrap().record();
    assert_eq!(report["status"], "MISMATCHED");
    assert_eq!(report["cluster_ids"], json!(["cluster", "other"]));
    assert_eq!(
        report["totals"]["position_market_value"],
        json!({"account_value":"19.97","ledger_total":"19.96","difference":"0.01"})
    );
    let fields: Vec<_> = report["differences"]
        .as_array()
        .unwrap()
        .iter()
        .map(|d| d["field"].as_str().unwrap())
        .collect();
    assert_eq!(
        fields,
        vec!["position_market_value", "unrealized_pnl", "equity"]
    );
    assert_eq!(h.checkpoint().unwrap(), before);
    let mut fresh = Components::new(before["config"].clone()).unwrap();
    recover(&mut h.store, &mut fresh).unwrap();
    assert_eq!(fresh.reconcile(&h.store).unwrap().record(), report);
}
#[test]
fn cumulative_fee_targets_negative_net_rebates_and_zero_fees_are_exact() {
    for rebate in [false, true] {
        let mut h = Harness::new(config()).unwrap();
        for v in [open(1, "BUY"), stage(2, 1, "UNKNOWN")] {
            apply(&mut h, &v);
        }
        for (n, target) in [(3, "2.00"), (4, "3.00")] {
            let mut v = fill(n, 1, "1", "10.00", if rebate { "1.00" } else { "0.00" });
            if rebate {
                let p = &mut v["payload"]["fees"];
                p["rebate_target"] = json!(target);
                p.as_object_mut().unwrap().remove("source_digest");
                p["source_digest"] = json!(onlyalpha_execution::digest(p.to_string().as_bytes()));
            }
            apply(&mut h, &v);
        }
        let report = h.components.reconcile(&h.store).unwrap().record();
        assert_eq!(report["status"], "MATCHED");
        assert_eq!(report["trade_count"], 2);
        assert_eq!(
            report["totals"]["fees"]["account_value"],
            if rebate { "-2.00" } else { "0.00" }
        );
    }
}
#[test]
fn complete_zero_capital_clusters_are_retained_in_the_proof() {
    let mut cfg = config();
    for n in 1..32 {
        let c = format!("empty-{n:02}");
        cfg["capitals"][&c] = json!("0.00");
        cfg["profiles"][&c] = cfg["profiles"]["cluster"].clone();
    }
    let h = Harness::new(cfg).unwrap();
    let report = h.components.reconcile(&h.store).unwrap().record();
    assert_eq!(report["status"], "MATCHED");
    assert_eq!(report["cluster_ids"].as_array().unwrap().len(), 32);
    assert_eq!(report["source"]["owners"].as_array().unwrap().len(), 6);
}
#[test]
fn fresh_reconciliation_recovery_child() {
    let Ok(path) = std::env::var("ONLYALPHA_RECONCILIATION_RECOVERY_FILE") else {
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
    assert_eq!(c.reconcile(&store).unwrap().record(), v["expected"]);
    println!("RECONCILIATION_FRESH_PROCESS: PASS");
}
#[test]
fn actual_file_and_new_process_reproduce_the_exact_report() {
    let mut h = loaded();
    let v = valuation(&h, 4, "12.00");
    apply(&mut h, &v);
    let path = std::env::temp_dir().join(format!(
        "onlyalpha-reconciliation-{}.json",
        std::process::id()
    ));
    assert!(!path.exists());
    std::fs::write(&path,serde_json::to_vec(&json!({"rows":h.store.rows.iter().map(Record::record).collect::<Vec<_>>(),"expected":h.components.reconcile(&h.store).unwrap().record()})).unwrap()).unwrap();
    let child = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "fresh_reconciliation_recovery_child",
            "--nocapture",
        ])
        .env("ONLYALPHA_RECONCILIATION_RECOVERY_FILE", &path)
        .output()
        .unwrap();
    std::fs::remove_file(path).unwrap();
    assert!(
        child.status.success(),
        "{}",
        String::from_utf8_lossy(&child.stderr)
    );
    assert!(String::from_utf8_lossy(&child.stdout).contains("RECONCILIATION_FRESH_PROCESS: PASS"));
}

#[test]
fn rehashed_owner_leaf_or_historical_source_cannot_substitute_for_current_ready() {
    let mut h = loaded();
    let v = valuation(&h, 4, "12.00");
    apply(&mut h, &v);
    let before = h.checkpoint().unwrap();
    for index in [0, h.store.rows.len() - 1] {
        let mut store = h.store.clone();
        let mut record = store.rows[index].record();
        let projection = &mut record["prepared"]["projections"][2];
        projection["result"]["state"]["snapshot"]["cash"] = json!("999999.00");
        projection["result_hash"] = json!(onlyalpha_execution::digest(
            projection["result"].to_string().as_bytes()
        ));
        let prepared = &mut record["prepared"];
        prepared.as_object_mut().unwrap().remove("payload_hash");
        prepared["payload_hash"] =
            json!(onlyalpha_execution::digest(prepared.to_string().as_bytes()));
        store.rows[index] = Record::decode(&record).unwrap();
        assert!(h.components.reconcile(&store).is_err());
        assert_eq!(h.checkpoint().unwrap(), before);
    }
}

#[test]
fn rehashed_historical_input_with_unchanged_projections_is_not_the_same_cause() {
    let h = loaded();
    let mut store = h.store.clone();
    let mut record = store.rows[0].record();
    let p = &mut record["prepared"];
    p["input"]["time"] = json!(99);
    let id = format!(
        "ETX-{}",
        onlyalpha_execution::digest(p["input"].to_string().as_bytes())
    );
    p["transaction_id"] = json!(id);
    p["events"] = json!([{"schema_version":1,"event_id":format!("{id}-EVENT-1"),"transaction_id":id,"sequence":p["sequence"],"input":p["input"]}]);
    p.as_object_mut().unwrap().remove("payload_hash");
    p["payload_hash"] = json!(onlyalpha_execution::digest(p.to_string().as_bytes()));
    store.rows[0] = Record::decode(&record).unwrap();
    assert!(h.components.reconcile(&store).is_err());
}

#[test]
fn common_vector_outputs() {
    let mut profit = loaded();
    let v = valuation(&profit, 4, "12.00");
    apply(&mut profit, &v);
    let mut loss = loaded();
    let v = valuation(&loss, 4, "8.00");
    apply(&mut loss, &v);
    let mut rounding = rounded_two_cluster_source();
    let v = valuation(&rounding, 7, "9.985");
    apply(&mut rounding, &v);
    let closed = closed_source();
    let cases = [
        ("genesis", Harness::new(config()).unwrap()),
        ("filled", loaded()),
        ("profit", profit),
        ("loss", loss),
        ("closed", closed),
        ("rounding", rounding),
    ];
    let vectors: Vec<Value> =
        include_str!("../../../../test-data/execution/reconciliation-v1.jsonl")
            .lines()
            .map(|line| serde_json::from_str(line).unwrap())
            .collect();
    assert_eq!(cases.len(), vectors.len());
    let mut outputs = vec![];
    for ((name, h), v) in cases.into_iter().zip(vectors) {
        let report = h.components.reconcile(&h.store).unwrap().record();
        let fields: Vec<_> = report["differences"]
            .as_array()
            .unwrap()
            .iter()
            .map(|d| d["field"].clone())
            .collect();
        assert_eq!(v["case"], name);
        assert_eq!(report["totals"], v["totals"]);
        assert_eq!(report["status"], v["status"]);
        assert_eq!(json!(fields), v["difference_fields"]);
        outputs.push(json!({"case":name,"totals":report["totals"],"status":report["status"],"difference_fields":fields}));
    }
    println!("RECONCILIATION_VECTOR_OUTPUT {}", json!(outputs));
}

struct UnavailableSource {
    inner: MemoryStore,
    missing: bool,
}
impl onlyalpha_execution::Store for UnavailableSource {
    fn head(&self) -> Result<u64, onlyalpha_execution::Error> {
        onlyalpha_execution::Store::head(&self.inner)
    }
    fn get(&self, n: u64) -> Result<Option<Record>, onlyalpha_execution::Error> {
        if n == 2 {
            if self.missing {
                Ok(None)
            } else {
                Err(onlyalpha_execution::Error("STORE_READ_UNAVAILABLE".into()))
            }
        } else {
            onlyalpha_execution::Store::get(&self.inner, n)
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
fn unavailable_or_missing_record_with_matching_head_is_an_error_not_a_difference() {
    let h = loaded();
    let before = h.checkpoint().unwrap();
    for missing in [false, true] {
        let source = UnavailableSource {
            inner: h.store.clone(),
            missing,
        };
        assert!(h.components.reconcile(&source).is_err());
        assert_eq!(h.checkpoint().unwrap(), before);
    }
}

fn closed_source() -> Harness {
    let mut h = loaded();
    for v in [
        open(5, "SELL"),
        stage(6, 2, "UNKNOWN"),
        fill(7, 2, "4", "12.00", "1.00"),
    ] {
        apply(&mut h, &v);
    }
    h
}
#[test]
fn realized_close_pnl_and_two_orders_fees_reconcile_from_real_facts() {
    let mut h = closed_source();
    let before = h.checkpoint().unwrap();
    let report = h.components.reconcile(&h.store).unwrap().record();
    assert_eq!(report["status"], "MATCHED");
    assert_eq!(report["trade_count"], 2);
    for (field, value) in [
        ("realized_pnl", "8.00"),
        ("position_market_value", "0.00"),
        ("unrealized_pnl", "0.00"),
        ("fees", "2.00"),
        ("equity", "1006.00"),
    ] {
        assert_eq!(report["totals"][field]["account_value"], value);
        assert_eq!(report["totals"][field]["difference"], "0.00");
    }
    assert_eq!(h.checkpoint().unwrap(), before);
    let mut fresh = Components::new(config()).unwrap();
    recover(&mut h.store, &mut fresh).unwrap();
    assert_eq!(fresh.reconcile(&h.store).unwrap().record(), report);
}
