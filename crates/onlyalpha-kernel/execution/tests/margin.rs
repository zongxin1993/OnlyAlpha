const SETTLEMENT_FIXTURE: &str = include_str!("../../../../test-data/settlement/common-v1.json");
const FIXTURE: &str = include_str!("../../../../test-data/execution/domain-inputs.json");
const MARGIN_FIXTURE: &str = include_str!("../../../../test-data/margin/common-v1.json");
mod support;
use onlyalpha_execution::{Components, Record, coordinate, recover};
use serde_json::{Value, json};
use support::*;
fn apply(h: &mut Harness, v: &Value) {
    let p = h.prepare(v).unwrap();
    coordinate(&mut h.store, &mut h.components, &p).unwrap();
}
fn collateral(instruction: Value, allocation: Value) -> Value {
    let allocation = if allocation.is_null() {
        allocation
    } else {
        json!({"schema_version":1,"policy":allocation,"mode":"CROSS","isolation":null,"position_side":"LONG"})
    };
    json!({"schema_version":1,"kind":"MARGIN","instruction":instruction,"close_allocation":allocation})
}
fn sign(c: &mut Value) {
    c.as_object_mut().unwrap().remove("source_fingerprint");
    c["source_fingerprint"] = json!(onlyalpha_execution::digest(c.to_string().as_bytes()));
}
fn reserve_order(n: u64) -> Value {
    let mut v = open(n, "BUY");
    let mut c: Value = serde_json::from_str::<Value>(MARGIN_FIXTURE).unwrap()["reserve"].clone();
    c["scope"]["request"] = v["payload"]["request"]["request_id"]["value"].clone();
    c["source_order"] = v["payload"]["order"].clone();
    c["quantity"] = v["payload"]["request"]["quantity"]["value"].clone();
    c["id"] = json!(format!("margin-{n}"));
    c["time"] = v["time"].clone();
    c["source_ref"] = v["source_ref"].clone();
    c["amount"] = json!("10.00");
    sign(&mut c);
    v["payload"]["collateral"] = collateral(c, Value::Null);
    v
}
fn margin_state(h: &Harness) -> Value {
    h.state().unwrap()["execution"]["margin_authority"]["states"]
        .as_object()
        .unwrap()
        .values()
        .next()
        .unwrap()
        .clone()
}
fn occupied_fill(h: &Harness, n: u64, q: &str, amount: &str, maintenance: &str) -> Value {
    let mut v = fill(n, 1, q, "10.00", "1.00");
    let s = margin_state(h);
    let mut c: Value = serde_json::from_str::<Value>(MARGIN_FIXTURE).unwrap()["reserve"].clone();
    c["id"] = json!(format!("margin-{n}"));
    c["scope"] = s["scope"].clone();
    for k in ["mode", "isolation", "position_side"] {
        c[k] = s[k].clone();
    }
    c["source_order"] = v["payload"]["order"].clone();
    c["source_trade"] = v["payload"]["trade"].clone();
    c["reservation"] = s["id"].clone();
    c["action"] = json!("OCCUPY");
    c["quantity"] = json!(q);
    c["amount"] = json!(amount);
    c["maintenance"] = json!(maintenance);
    c["time"] = v["time"].clone();
    c["source_ref"] = v["source_ref"].clone();
    c["expected_version"] = s["version"].clone();
    c["before_hash"] = json!(onlyalpha_execution::digest(s.to_string().as_bytes()));
    sign(&mut c);
    v["payload"]["collateral"] = collateral(c, Value::Null);
    v
}
#[test]
fn margin_is_reserved_atomically_with_admission_before_broker_dispatch() {
    let mut h = Harness::new(config()).unwrap();
    apply(&mut h, &reserve_order(1));
    let s = h.state().unwrap();
    assert_eq!(s["account"]["snapshot"]["reserved_margin"], "10.00");
    assert_eq!(s["account"]["snapshot"]["withdrawable"], "949.00");
    assert_eq!(margin_state(&h)["reserved"], "10.00");
    apply(&mut h, &stage(2, 1, "UNKNOWN"));
    let cp = h.checkpoint().unwrap();
    let mut cancelled = terminal(3, 1, "CANCELLED");
    cancelled["payload"]["collateral"] = collateral(Value::Null, Value::Null);
    // UNKNOWN is not terminal; requesting cancellation never releases collateral.
    let cancel = input(
        3,
        "CANCEL",
        json!({"schema_version":1,"order":order(1),"request_id":"cancel-request","reason":"user-cancel"}),
    );
    apply(&mut h, &cancel);
    assert_eq!(margin_state(&h)["reserved"], "10.00");
    assert_ne!(h.checkpoint().unwrap(), cp);
    cancelled["runtime_sequence"] = json!(4);
    cancelled["time"] = json!(4);
    cancelled["input_id"] = json!("input-4");
    cancelled["source_ref"] = json!("source-4");
    apply(&mut h, &cancelled);
    assert_eq!(margin_state(&h)["reserved"], "0.00");
    assert_eq!(
        h.state().unwrap()["account"]["snapshot"]["withdrawable"],
        "1000.00"
    );
}
#[test]
fn partial_fill_cancel_and_real_close_release_only_their_collateral() {
    let mut h = Harness::new(config()).unwrap();
    apply(&mut h, &reserve_order(1));
    apply(&mut h, &stage(2, 1, "UNKNOWN"));
    let v = occupied_fill(&h, 3, "2", "5.00", "4.00");
    apply(&mut h, &v);
    let mut t = terminal(4, 1, "CANCELLED");
    t["payload"]["collateral"] = collateral(Value::Null, Value::Null);
    apply(&mut h, &t);
    assert_eq!(margin_state(&h)["occupied"], "5.00");
    assert_eq!(margin_state(&h)["reserved"], "0.00");
    let mut sell = open(5, "SELL");
    sell["payload"]["request"]["quantity"]["value"] = json!("2");
    refresh_market(&mut sell);
    apply(&mut h, &sell);
    apply(&mut h, &stage(6, 2, "UNKNOWN"));
    let mut close = fill(7, 2, "1", "12.00", "1.00");
    close["payload"]["collateral"] = collateral(Value::Null, json!("RESERVATION_ID_ASCENDING"));
    let p = h.prepare(&close).unwrap();
    coordinate(&mut h.store, &mut h.components, &p).unwrap();
    coordinate(&mut h.store, &mut h.components, &p).unwrap();
    assert_eq!(margin_state(&h)["occupied"], "2.50");
    assert_eq!(margin_state(&h)["maintenance"], "2.00");
    assert_eq!(
        h.state().unwrap()["account"]["snapshot"]["occupied_margin"],
        "2.50"
    );
    let mut close = fill(8, 2, "1", "12.00", "1.00");
    close["payload"]["collateral"] = collateral(Value::Null, json!("RESERVATION_ID_ASCENDING"));
    apply(&mut h, &close);
    assert_eq!(margin_state(&h)["status"], "CLOSED");
    assert_eq!(
        h.state().unwrap()["account"]["snapshot"]["occupied_margin"],
        "0.00"
    );

    let performance = h
        .components
        .performance(
            &h.store,
            &onlyalpha_domain::time::OnlyTimestamp::from_unix_nanos(0.into()),
        )
        .unwrap()
        .record();
    let points = performance["performance"]["timeline"].as_array().unwrap();
    let last = points.iter().rfind(|p| p["source"] == "MARGIN").unwrap();
    assert_eq!(last["snapshot"]["occupied_margin"], "0.00");
    assert_eq!(last["snapshot"]["reserved_margin"], "0.00");
    assert!(points.iter().any(|p| p["source"] == "RELEASE"));
    assert_eq!(
        performance["performance"]["summary"]["final_equity"],
        h.state().unwrap()["account"]["snapshot"]["equity"]
    );
}
#[test]
fn missing_funding_and_wrong_trade_proofs_fail_before_any_state_change() {
    let mut h = Harness::new(config()).unwrap();
    let mut bad = reserve_order(1);
    bad["payload"]["collateral"]["instruction"]["amount"] = json!("1000.00");
    sign(&mut bad["payload"]["collateral"]["instruction"]);
    let cp = h.checkpoint().unwrap();
    assert!(h.prepare(&bad).is_err());
    assert_eq!(h.checkpoint().unwrap(), cp);
    apply(&mut h, &reserve_order(1));
    apply(&mut h, &stage(2, 1, "UNKNOWN"));
    let cp = h.checkpoint().unwrap();
    assert!(h.prepare(&fill(3, 1, "1", "10.00", "1.00")).is_err());
    assert_eq!(h.checkpoint().unwrap(), cp);
    let mut bad = occupied_fill(&h, 3, "1", "2.50", "2.00");
    bad["payload"]["collateral"]["instruction"]["source_trade"] = json!("foreign");
    sign(&mut bad["payload"]["collateral"]["instruction"]);
    assert!(h.prepare(&bad).is_err());
    assert_eq!(h.checkpoint().unwrap(), cp);
}
#[test]
fn every_margin_projection_cut_recovers_to_one_exact_effect() {
    for cut in 1..=6 {
        let mut h = Harness::new(config()).unwrap();
        apply(&mut h, &reserve_order(1));
        apply(&mut h, &stage(2, 1, "UNKNOWN"));
        let v = occupied_fill(&h, 3, "2", "5.00", "4.00");
        let p = h.prepare(&v).unwrap();
        for i in 0..cut {
            h.install_projection(&p, i).unwrap();
        }
        assert!(h.state().is_err());
        let mut fresh = Components::new(config()).unwrap();
        recover(&mut h.store, &mut fresh).unwrap();
        coordinate(&mut h.store, &mut fresh, &p).unwrap();
        assert_eq!(
            fresh.state(&h.store).unwrap()["account"]["snapshot"]["occupied_margin"],
            "5.00"
        );
    }
}

#[test]
fn isolated_collateral_requires_an_explicit_matching_close_pool() {
    let mut h = Harness::new(config()).unwrap();
    let mut v = reserve_order(1);
    let c = &mut v["payload"]["collateral"]["instruction"];
    c["mode"] = json!("ISOLATED");
    c["isolation"] = json!("instrument-long");
    sign(c);
    apply(&mut h, &v);
    apply(&mut h, &stage(2, 1, "UNKNOWN"));
    let v = occupied_fill(&h, 3, "4", "10.00", "8.00");
    apply(&mut h, &v);
    let mut v = open(5, "SELL");
    apply(&mut h, &v);
    apply(&mut h, &stage(6, 2, "UNKNOWN"));
    v = fill(7, 2, "4", "12.00", "1.00");
    v["payload"]["collateral"] = collateral(Value::Null, json!("RESERVATION_ID_ASCENDING"));
    let cp = h.checkpoint().unwrap();
    assert!(h.prepare(&v).is_err());
    assert_eq!(h.checkpoint().unwrap(), cp);
    v["payload"]["collateral"]["close_allocation"]["mode"] = json!("ISOLATED");
    v["payload"]["collateral"]["close_allocation"]["isolation"] = json!("instrument-long");
    apply(&mut h, &v);
    assert_eq!(margin_state(&h)["status"], "CLOSED");
}
#[test]
fn fresh_margin_recovery_child() {
    let Ok(path) = std::env::var("ONLYALPHA_MARGIN_RECOVERY_FILE") else {
        return;
    };
    let v: Value = serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();
    let mut store = MemoryStore::default();
    store.rows = v
        .as_array()
        .unwrap()
        .iter()
        .map(|r| Record::decode(r).unwrap())
        .collect();
    let mut c = Components::new(config()).unwrap();
    recover(&mut store, &mut c).unwrap();
    assert_eq!(
        c.state(&store).unwrap()["account"]["snapshot"]["occupied_margin"],
        "5.00"
    );
    println!("MARGIN_FRESH_PROCESS_RECOVERY: PASS");
}
#[test]
fn committed_margin_recovers_from_real_file_in_a_new_process() {
    let mut h = Harness::new(config()).unwrap();
    apply(&mut h, &reserve_order(1));
    apply(&mut h, &stage(2, 1, "UNKNOWN"));
    let p = h
        .prepare(&occupied_fill(&h, 3, "2", "5.00", "4.00"))
        .unwrap();
    h.install_projection(&p, 0).unwrap();
    let path = std::env::temp_dir().join(format!(
        "onlyalpha-margin-recovery-{}.json",
        std::process::id()
    ));
    assert!(!path.exists());
    std::fs::write(
        &path,
        serde_json::to_vec(&h.store.rows.iter().map(Record::record).collect::<Vec<_>>()).unwrap(),
    )
    .unwrap();
    let out = std::process::Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "fresh_margin_recovery_child", "--nocapture"])
        .env("ONLYALPHA_MARGIN_RECOVERY_FILE", &path)
        .output()
        .unwrap();
    std::fs::remove_file(path).unwrap();
    assert!(
        out.status.success(),
        "{} {}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    );
    assert!(String::from_utf8_lossy(&out.stdout).contains("MARGIN_FRESH_PROCESS_RECOVERY: PASS"));
}

#[test]
fn cluster_capital_cannot_borrow_other_clusters_cash_for_collateral() {
    let mut c = config();
    c["capitals"]["cluster"] = json!("500.00");
    c["capitals"]["other"] = json!("500.00");
    c["profiles"]["other"] = c["profiles"]["cluster"].clone();
    let h = Harness::new(c).unwrap();
    let mut v = reserve_order(1);
    v["payload"]["collateral"]["instruction"]["amount"] = json!("480.00");
    sign(&mut v["payload"]["collateral"]["instruction"]);
    let cp = h.checkpoint().unwrap();
    assert!(h.prepare(&v).is_err());
    assert_eq!(h.checkpoint().unwrap(), cp);
}

fn sign_fee(v: &mut Value, ordinal: u64) {
    let f: Value = serde_json::from_str(MARGIN_FIXTURE).unwrap();
    v["payload"]["fees"]["policy"] =
        f["fee_contracts"][ordinal.to_string()]["binding"]["fingerprint"].clone();
    let p = &mut v["payload"]["fees"];
    p.as_object_mut().unwrap().remove("source_digest");
    p["source_digest"] = json!(onlyalpha_execution::digest(p.to_string().as_bytes()));
}
#[test]
fn two_real_opening_orders_and_one_partial_close_release_exact_aggregate_collateral() {
    let mut h = Harness::new(config()).unwrap();
    apply(&mut h, &reserve_order(1));
    apply(&mut h, &stage(2, 1, "UNKNOWN"));
    let v = occupied_fill(&h, 3, "4", "10.00", "8.00");
    apply(&mut h, &v);
    let f: Value = serde_json::from_str(MARGIN_FIXTURE).unwrap();
    let mut second = reserve_order(4);
    second["payload"]["order"] = json!(order(2));
    second["payload"]["request"]["request_id"]["value"] = json!("request-2");
    second["payload"]["fee_contract"] = f["fee_contracts"]["2"].clone();
    refresh_market(&mut second);
    let c = &mut second["payload"]["collateral"]["instruction"];
    c["source_order"] = json!(order(2));
    c["scope"]["request"] = json!("request-2");
    sign(c);
    apply(&mut h, &second);
    apply(&mut h, &stage(5, 2, "UNKNOWN"));
    let state = h.state().unwrap()["execution"]["margin_authority"]["states"]
        .as_object()
        .unwrap()
        .values()
        .find(|s| s["order"] == order(2))
        .unwrap()
        .clone();
    let mut v = fill(6, 2, "4", "10.00", "1.00");
    sign_fee(&mut v, 2);
    let mut c = second["payload"]["collateral"]["instruction"].clone();
    c["id"] = json!("margin-6");
    c["source_ref"] = v["source_ref"].clone();
    c["source_trade"] = v["payload"]["trade"].clone();
    c["reservation"] = state["id"].clone();
    c["action"] = json!("OCCUPY");
    c["time"] = json!(6);
    c["maintenance"] = json!("8.00");
    c["expected_version"] = state["version"].clone();
    c["before_hash"] = json!(onlyalpha_execution::digest(state.to_string().as_bytes()));
    sign(&mut c);
    v["payload"]["collateral"] = collateral(c, Value::Null);
    apply(&mut h, &v);
    let mut sell = open(7, "SELL");
    sell["payload"]["order"] = json!(order(3));
    sell["payload"]["request"]["request_id"]["value"] = json!("request-3");
    sell["payload"]["request"]["quantity"]["value"] = json!("8");
    sell["payload"]["fee_contract"] = f["fee_contracts"]["3"].clone();
    refresh_market(&mut sell);
    apply(&mut h, &sell);
    apply(&mut h, &stage(8, 3, "UNKNOWN"));
    let mut close = fill(9, 3, "5", "12.00", "1.00");
    sign_fee(&mut close, 3);
    close["payload"]["collateral"] = collateral(Value::Null, json!("RESERVATION_ID_ASCENDING"));
    apply(&mut h, &close);
    let s = h.state().unwrap();
    assert_eq!(s["account"]["snapshot"]["occupied_margin"], "7.50");
    assert_eq!(s["account"]["snapshot"]["maintenance_required"], "6.00");
    assert_eq!(
        s["execution"]["margin_authority"]["records"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|r| r["command"]["action"] == "RELEASE_OCCUPIED")
            .count(),
        2
    );
}

#[test]
fn one_partial_order_can_close_and_reopen_a_new_position_cycle() {
    let mut h = Harness::new(config()).unwrap();
    apply(&mut h, &reserve_order(1));
    apply(&mut h, &stage(2, 1, "UNKNOWN"));
    let v = occupied_fill(&h, 3, "2", "5.00", "4.00");
    apply(&mut h, &v);
    let mut sell = open(5, "SELL");
    sell["payload"]["request"]["quantity"]["value"] = json!("2");
    refresh_market(&mut sell);
    apply(&mut h, &sell);
    apply(&mut h, &stage(6, 2, "UNKNOWN"));
    let mut close = fill(7, 2, "2", "12.00", "1.00");
    close["payload"]["collateral"] = collateral(Value::Null, json!("RESERVATION_ID_ASCENDING"));
    apply(&mut h, &close);
    assert_eq!(margin_state(&h)["open"], "0");
    let mut v = occupied_fill(&h, 8, "2", "5.00", "4.00");
    v["time"] = json!(7);
    v["payload"]["collateral"]["instruction"]["time"] = json!(7);
    sign(&mut v["payload"]["collateral"]["instruction"]);
    apply(&mut h, &v);
    let f: Value = serde_json::from_str(MARGIN_FIXTURE).unwrap();
    let mut sell = open(9, "SELL");
    sell["time"] = json!(7);
    sell["payload"]["order"] = json!(order(3));
    sell["payload"]["request"]["request_id"]["value"] = json!("request-3");
    sell["payload"]["request"]["quantity"]["value"] = json!("2");
    sell["payload"]["fee_contract"] = f["fee_contracts"]["3"].clone();
    refresh_market(&mut sell);
    apply(&mut h, &sell);
    let mut st = stage(10, 3, "UNKNOWN");
    st["time"] = json!(7);
    apply(&mut h, &st);
    let mut close = fill(11, 3, "2", "12.00", "1.00");
    close["time"] = json!(7);
    sign_fee(&mut close, 3);
    close["payload"]["collateral"] = collateral(Value::Null, json!("RESERVATION_ID_ASCENDING"));
    apply(&mut h, &close);
    assert_eq!(margin_state(&h)["occupied"], "0.00");
    assert_eq!(margin_state(&h)["released"], "10.00");
}
