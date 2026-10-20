use onlyalpha_margin::{Manager, digest};
use serde_json::{Value, json};
fn fixture() -> Value {
    serde_json::from_str(include_str!("../../../../test-data/margin/common-v1.json")).unwrap()
}
fn manager(capacity: usize) -> Manager {
    Manager::new(fixture()["config"].clone(), capacity).unwrap()
}
fn reserve(q: &str) -> Value {
    let mut v = fixture()["reserve"].clone();
    v["quantity"] = json!(q);
    v
}
fn next(
    m: &Manager,
    id: &str,
    n: u64,
    action: &str,
    q: &str,
    amount: &str,
    maintenance: &str,
) -> Value {
    let s = m.snapshot(id).unwrap();
    let mut v = reserve("3");
    v["id"] = json!(format!("command-{n}"));
    v["source_ref"] = json!(format!("source-{n}"));
    v["reservation"] = json!(id);
    v["expected_version"] = s["version"].clone();
    v["before_hash"] = json!(digest(&s));
    v["time"] = json!(n);
    v["action"] = json!(action);
    v["quantity"] = json!(q);
    v["amount"] = json!(amount);
    v["maintenance"] = json!(maintenance);
    v["source_trade"] = if action == "RELEASE_RESERVED" {
        Value::Null
    } else {
        json!(format!("trade-{n}"))
    };
    if action == "RELEASE_OCCUPIED" {
        v["source_order"] = json!("closing-order");
    }
    v
}
#[test]
fn partial_fill_cancel_and_close_conserve_collateral_and_minor_units() {
    let mut m = manager(8);
    let e = m.apply(&reserve("3")).unwrap();
    let id = e.record()["after"]["id"].as_str().unwrap().to_owned();
    let occupy = next(&m, &id, 2, "OCCUPY", "2", "0.67", "0.53");
    m.apply(&occupy).unwrap();
    m.apply(&next(&m, &id, 3, "RELEASE_RESERVED", "1", "0.33", "0.00"))
        .unwrap();
    m.apply(&next(&m, &id, 4, "RELEASE_OCCUPIED", "1", "0.34", "0.26"))
        .unwrap();
    let before = m.checkpoint();
    m.apply(&next(&m, &id, 5, "RELEASE_OCCUPIED", "1", "0.33", "0.27"))
        .unwrap();
    assert_eq!(m.snapshot(&id).unwrap()["status"], "CLOSED");
    assert_eq!(m.snapshot(&id).unwrap()["released"], "1.00");
    let cp = m.checkpoint();
    let mut fresh = manager(8);
    fresh.restore(&cp, &digest(&cp)).unwrap();
    assert_eq!(fresh.checkpoint(), cp);
    assert_ne!(before, cp);
}
#[test]
fn duplicate_conflict_and_wrong_owner_are_atomic() {
    let mut m = manager(8);
    let c = reserve("3");
    let e = m.apply(&c).unwrap().record();
    let cp = m.checkpoint();
    assert_eq!(m.apply(&c).unwrap().record(), e);
    assert_eq!(m.checkpoint(), cp);
    let mut wrong = c.clone();
    wrong["amount"] = json!("2.00");
    assert!(m.apply(&wrong).is_err());
    assert_eq!(m.checkpoint(), cp);
    wrong = c.clone();
    wrong["scope"]["account"] = json!("foreign");
    assert!(m.apply(&wrong).is_err());
    assert_eq!(m.checkpoint(), cp);
}

#[test]
fn capacity_rejects_new_risk_but_keeps_every_admitted_fill_and_release() {
    let mut m = manager(8);
    let e = m.apply(&reserve("3")).unwrap();
    let id = e.record()["after"]["id"].as_str().unwrap().to_owned();
    let cp = m.checkpoint();
    let mut new = reserve("1");
    new["id"] = json!("other");
    new["source_ref"] = json!("other");
    new["source_order"] = json!("other");
    new["scope"]["request"] = json!("other");
    assert!(m.apply(&new).is_err());
    assert_eq!(m.checkpoint(), cp);
    for n in 2..=4 {
        m.apply(&next(
            &m,
            &id,
            n,
            "OCCUPY",
            "1",
            if n == 4 { "0.34" } else { "0.33" },
            "0.20",
        ))
        .unwrap();
    }
    m.apply(&next(&m, &id, 5, "RELEASE_RESERVED", "0", "0.00", "0.00"))
        .unwrap();
    for (n, a, maint) in [
        (6, "0.33", "0.20"),
        (7, "0.34", "0.20"),
        (8, "0.33", "0.20"),
    ] {
        m.apply(&next(&m, &id, n, "RELEASE_OCCUPIED", "1", a, maint))
            .unwrap();
    }
    assert_eq!(m.checkpoint()["records"].as_array().unwrap().len(), 8);
    assert_eq!(m.snapshot(&id).unwrap()["status"], "CLOSED");
    let cp = m.checkpoint();
    let mut fresh = manager(8);
    fresh.restore(&cp, &digest(&cp)).unwrap();
    assert_eq!(fresh.checkpoint(), cp);
}
#[test]
fn multiple_openings_require_explicit_same_scope_release_allocations() {
    let mut m = manager(16);
    let first = m.apply(&reserve("2")).unwrap().record()["after"]["id"]
        .as_str()
        .unwrap()
        .to_owned();
    let mut c = reserve("2");
    c["id"] = json!("second");
    c["source_ref"] = json!("second");
    c["source_order"] = json!("opening-two");
    c["scope"]["request"] = json!("request-two");
    let second = m.apply(&c).unwrap().record()["after"]["id"]
        .as_str()
        .unwrap()
        .to_owned();
    m.apply(&next(&m, &first, 2, "OCCUPY", "2", "1.00", "0.80"))
        .unwrap();
    let mut fill = next(&m, &second, 3, "OCCUPY", "2", "1.00", "0.80");
    fill["source_order"] = json!("opening-two");
    fill["scope"] = m.snapshot(&second).unwrap()["scope"].clone();
    m.apply(&fill).unwrap();
    for (n, id) in [(4, &first), (5, &second)] {
        let mut close = next(&m, id, n, "RELEASE_OCCUPIED", "1", "0.50", "0.40");
        close["scope"] = m.snapshot(id).unwrap()["scope"].clone();
        close["source_trade"] = json!("one-close-trade");
        m.apply(&close).unwrap();
    }
    assert_eq!(m.snapshot(&first).unwrap()["occupied"], "0.50");
    assert_eq!(m.snapshot(&second).unwrap()["occupied"], "0.50");
}
#[test]
fn scope_family_and_complete_different_identity_mutations_fail_atomically() {
    let mut m = manager(12);
    let i = m.apply(&reserve("3")).unwrap().record()["after"]["id"]
        .as_str()
        .unwrap()
        .to_owned();
    let c = next(&m, &i, 2, "OCCUPY", "1", "0.30", "0.20");
    for k in [
        "engine",
        "runtime",
        "account",
        "gateway",
        "generation",
        "runtime_kind",
        "cluster",
        "revision",
        "instrument",
        "request",
    ] {
        let mut bad = c.clone();
        bad["scope"][k] = json!("other");
        let cp = m.checkpoint();
        assert!(m.apply(&bad).is_err(), "{k}");
        assert_eq!(m.checkpoint(), cp);
    }
    for (k, v) in [
        ("mode", json!("ISOLATED")),
        ("isolation", json!("other")),
        ("position_side", json!("SHORT")),
        ("quantity_precision", json!(1)),
        ("source_order", json!("other")),
        ("reservation", json!("MRES-foreign")),
        ("before_hash", json!("a".repeat(64))),
        ("expected_version", json!(9)),
        ("source_fingerprint", Value::Null),
    ] {
        let mut bad = c.clone();
        bad[k] = v;
        let cp = m.checkpoint();
        assert!(m.apply(&bad).is_err(), "{k}");
        assert_eq!(m.checkpoint(), cp);
    }
    m.apply(&c).unwrap();
    let mut detached = m.snapshot(&i).unwrap();
    detached["occupied"] = json!("999.00");
    assert_eq!(m.snapshot(&i).unwrap()["occupied"], "0.30");
}
#[test]
fn isolated_short_collateral_cannot_be_released_from_cross_or_long_scope() {
    let mut m = manager(12);
    let mut c = reserve("3");
    c["mode"] = json!("ISOLATED");
    c["isolation"] = json!("instrument-short");
    c["position_side"] = json!("SHORT");
    let i = m.apply(&c).unwrap().record()["after"]["id"]
        .as_str()
        .unwrap()
        .to_owned();
    let mut c = next(&m, &i, 2, "OCCUPY", "3", "1.00", "0.80");
    c["mode"] = json!("ISOLATED");
    c["isolation"] = json!("instrument-short");
    c["position_side"] = json!("SHORT");
    m.apply(&c).unwrap();
    let mut c = next(&m, &i, 3, "RELEASE_OCCUPIED", "3", "1.00", "0.80");
    let cp = m.checkpoint();
    assert!(m.apply(&c).is_err());
    assert_eq!(m.checkpoint(), cp);
    c["mode"] = json!("ISOLATED");
    c["isolation"] = json!("instrument-short");
    c["position_side"] = json!("SHORT");
    m.apply(&c).unwrap();
    assert_eq!(m.snapshot(&i).unwrap()["occupied"], "0.00");
}
#[test]
fn history_and_derived_state_cannot_be_spliced_or_partially_restored() {
    let mut m = manager(12);
    let i = m.apply(&reserve("3")).unwrap().record()["after"]["id"]
        .as_str()
        .unwrap()
        .to_owned();
    let old = m.checkpoint();
    m.apply(&next(&m, &i, 2, "OCCUPY", "1", "0.30", "0.20"))
        .unwrap();
    let cp = m.checkpoint();
    for field in ["states", "records"] {
        let mut bad = cp.clone();
        if field == "states" {
            bad["states"][&i]["occupied"] = json!("0.31");
        } else {
            bad["records"][1]["result"]["after"]["scope"]["cluster"] = json!("foreign");
        }
        let mut fresh = manager(12);
        let empty = fresh.checkpoint();
        assert!(fresh.restore(&bad, &digest(&bad)).is_err());
        assert_eq!(fresh.checkpoint(), empty);
    }
    let mut missing = cp.clone();
    missing["records"].as_array_mut().unwrap().pop();
    let mut fresh = manager(12);
    assert!(fresh.restore(&missing, &digest(&missing)).is_err());
    assert!(m.restore(&old, &digest(&old)).is_err());
    assert_eq!(m.checkpoint(), cp);
}
#[test]
fn monetary_spelling_and_wide_time_are_exact_and_future_receipts_fit() {
    let mut m = manager(8);
    let mut c = reserve("1");
    c["source_order"] = json!("\0".repeat(128));
    c["scope"]["cluster"] = json!("\0".repeat(64));
    c["amount"] = json!("2e64");
    c["time"] = json!(-1);
    let e = m.apply(&c).unwrap().record();
    let i = e["after"]["id"].as_str().unwrap().to_owned();
    let mut d = next(
        &m,
        &i,
        2,
        "OCCUPY",
        "1",
        &format!("2{}.00", "0".repeat(64)),
        "0.00",
    );
    d["scope"] = e["after"]["scope"].clone();
    d["source_order"] = c["source_order"].clone();
    m.apply(&d).unwrap();
    let mut d = next(
        &m,
        &i,
        3,
        "RELEASE_OCCUPIED",
        "1",
        &format!("2{}.00", "0".repeat(64)),
        "0.00",
    );
    d["scope"] = e["after"]["scope"].clone();
    d["source_order"] = json!("\u{1}".repeat(128));
    d["time"] = serde_json::from_str(&"9".repeat(256)).unwrap();
    m.apply(&d).unwrap();
    let cp = m.checkpoint();
    let mut fresh = manager(8);
    fresh.restore(&cp, &digest(&cp)).unwrap();
    assert_eq!(fresh.checkpoint(), cp);
}

#[test]
fn an_explicit_zero_increment_can_follow_a_front_loaded_collateral_fill() {
    let mut m = manager(6);
    let id = m.apply(&reserve("2")).unwrap().record()["after"]["id"]
        .as_str()
        .unwrap()
        .to_owned();
    m.apply(&next(&m, &id, 2, "OCCUPY", "1", "1.00", "0.80"))
        .unwrap();
    m.apply(&next(&m, &id, 3, "OCCUPY", "1", "0.00", "0.00"))
        .unwrap();
    assert_eq!(m.snapshot(&id).unwrap()["open"], "2");
    assert_eq!(m.snapshot(&id).unwrap()["occupied"], "1.00");
}
