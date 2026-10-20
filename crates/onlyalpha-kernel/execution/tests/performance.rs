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

fn at(n: i64) -> onlyalpha_domain::time::OnlyTimestamp {
    onlyalpha_domain::time::OnlyTimestamp::from_unix_nanos(n.into())
}
#[test]
fn actual_fill_mark_and_recovery_preserve_exact_account_performance() {
    let mut h = loaded();
    let mark = valuation(&h, 4, "12.00");
    apply(&mut h, &mark);
    let before = h.checkpoint().unwrap();
    let p = h.components.performance(&h.store, &at(0)).unwrap();
    let v = p.record();
    assert_eq!(v["performance"]["summary"]["final_equity"], "1007.00");
    assert_eq!(
        v["performance"]["summary"]["return_since_start"],
        "0.00700000"
    );
    assert_eq!(v["performance"]["summary"]["fees"], "1.00");
    assert_eq!(v["source"]["sequence"], 4);
    let mut fresh = Components::new(config()).unwrap();
    recover(&mut h.store, &mut fresh).unwrap();
    assert_eq!(fresh.performance(&h.store, &at(0)).unwrap(), p);
    assert_eq!(h.checkpoint().unwrap(), before);
    let mut detached = p.record();
    detached["performance"]["summary"]["final_equity"] = json!("0.00");
    assert_eq!(p.record(), v);
    assert_eq!(
        serde_json::from_slice::<Value>(&p.encode().unwrap()).unwrap(),
        v
    );
}
#[test]
fn every_pending_projection_cut_is_unavailable_until_recovered() {
    for cut in 0..=6 {
        let mut h = loaded();
        let mark = valuation(&h, 4, "12.00");
        let p = h.prepare(&mark).unwrap();
        h.commit_only(&p).unwrap();
        for i in 0..cut {
            h.install_projection(&p, i).unwrap();
        }
        assert!(h.components.performance(&h.store, &at(0)).is_err());
        let mut fresh = Components::new(config()).unwrap();
        recover(&mut h.store, &mut fresh).unwrap();
        assert_eq!(
            fresh.performance(&h.store, &at(0)).unwrap().record()["performance"]["summary"]["final_equity"],
            "1007.00"
        );
    }
}
#[test]
fn missing_foreign_unready_and_changed_cause_are_never_performance_sources() {
    let h = loaded();
    let before = h.checkpoint().unwrap();
    let mut missing = h.store.clone();
    missing.rows.remove(0);
    assert!(h.components.performance(&missing, &at(0)).is_err());
    let mut foreign = config();
    foreign["generation"] = json!("b".repeat(64));
    assert!(
        Components::new(foreign)
            .unwrap()
            .performance(&h.store, &at(0))
            .is_err()
    );
    let mut unready = h.store.clone();
    let mut v = unready.rows[0].record();
    v["ready"] = json!(false);
    unready.rows[0] = Record::decode(&v).unwrap();
    assert!(h.components.performance(&unready, &at(0)).is_err());
    let mut changed = h.store.clone();
    let mut v = changed.rows[0].record();
    let p = &mut v["prepared"];
    p["input"]["time"] = json!(99);
    let id = format!(
        "ETX-{}",
        onlyalpha_execution::digest(p["input"].to_string().as_bytes())
    );
    p["transaction_id"] = json!(id);
    p["events"] = json!([{"schema_version":1,"event_id":format!("{id}-EVENT-1"),"transaction_id":id,"sequence":p["sequence"],"input":p["input"]}]);
    p.as_object_mut().unwrap().remove("payload_hash");
    p["payload_hash"] = json!(onlyalpha_execution::digest(p.to_string().as_bytes()));
    changed.rows[0] = Record::decode(&v).unwrap();
    assert!(h.components.performance(&changed, &at(0)).is_err());
    assert_eq!(h.checkpoint().unwrap(), before);
}
#[test]
fn fresh_performance_recovery_child() {
    let Ok(path) = std::env::var("ONLYALPHA_PERFORMANCE_RECOVERY_FILE") else {
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
    assert_eq!(
        c.performance(&store, &at(0)).unwrap().record(),
        v["expected"]
    );
    println!("PERFORMANCE_FRESH_PROCESS: PASS");
}
#[test]
fn actual_file_and_new_process_reproduce_the_exact_report() {
    let mut h = loaded();
    let v = valuation(&h, 4, "12.00");
    apply(&mut h, &v);
    let path =
        std::env::temp_dir().join(format!("onlyalpha-performance-{}.json", std::process::id()));
    assert!(!path.exists());
    std::fs::write(&path,serde_json::to_vec(&json!({"rows":h.store.rows.iter().map(Record::record).collect::<Vec<_>>(),"expected":h.components.performance(&h.store, &at(0)).unwrap().record()})).unwrap()).unwrap();
    let child = std::process::Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "fresh_performance_recovery_child", "--nocapture"])
        .env("ONLYALPHA_PERFORMANCE_RECOVERY_FILE", &path)
        .output()
        .unwrap();
    std::fs::remove_file(path).unwrap();
    assert!(
        child.status.success(),
        "{}",
        String::from_utf8_lossy(&child.stderr)
    );
    assert!(String::from_utf8_lossy(&child.stdout).contains("PERFORMANCE_FRESH_PROCESS: PASS"));
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
fn consolidated_account_path_is_not_a_cluster_drawdown() {
    let mut h = rounded_two_cluster_source();
    let v = valuation(&h, 7, "9.985");
    apply(&mut h, &v);
    let report = h.components.performance(&h.store, &at(0)).unwrap().record();
    let summary = &report["performance"]["summary"];
    assert_eq!(summary["final_equity"], "997.97");
    assert_eq!(summary["maximum_drawdown"], "-0.00203000");
    let state = h.state().unwrap();
    for cluster in ["cluster", "other"] {
        let ledger = &state["ledger"]["ledgers"][cluster]["snapshot"];
        assert_eq!(ledger["maximum_drawdown"], "-0.00204000");
        assert_ne!(ledger["maximum_drawdown"], summary["maximum_drawdown"]);
    }
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
fn missing_and_unavailable_store_never_becomes_an_empty_timeline() {
    let h = loaded();
    let before = h.checkpoint().unwrap();
    for missing in [false, true] {
        assert!(
            h.components
                .performance(
                    &Unavailable {
                        inner: &h.store,
                        missing
                    },
                    &at(0)
                )
                .is_err()
        );
    }
    assert_eq!(h.checkpoint().unwrap(), before);
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
        assert!(h.components.performance(&store, &at(0)).is_err());
        assert_eq!(h.checkpoint().unwrap(), before);
    }
}
