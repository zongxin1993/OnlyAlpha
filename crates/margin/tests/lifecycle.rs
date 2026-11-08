use onlyalpha_margin::{Manager, digest};
use serde_json::{Value, json};
fn fixture() -> Value {
    serde_json::from_str(include_str!("../../../test-data/margin/common-v1.json")).unwrap()
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

#[test]
fn maintenance_observations_preserve_admitted_lifecycle_capacity() {
    // 原 schema 1 的独立固定哈希来自 common-v1 和原有空历史 envelope。
    let legacy = json!({"schema_version":1,"config":fixture()["config"],"capacity":8,"states":{},"records":[]});
    let mut legacy_owner = manager(8);
    legacy_owner
        .restore(
            &legacy,
            "b4cdef10e1b25a7b6f02f009259a7a75642e2d324383e5c8d9eca597db722d22",
        )
        .unwrap();
    assert_eq!(legacy_owner.checkpoint(), legacy);
    let mut config = fixture()["config"].clone();
    config["observation_capacity"] = json!(8);
    let mut m = Manager::new(config.clone(), 8).unwrap();
    let reserve = m.apply(&reserve("3")).unwrap().record();
    let id = reserve["after"]["id"].as_str().unwrap();
    m.apply(&next(&m, id, 2, "OCCUPY", "1", "0.33", "0.20"))
        .unwrap();
    let mark = |m: &Manager, n: u64| {
        let mut v = next(
            m,
            id,
            n,
            "MARK_MAINTENANCE",
            "1",
            "0.00",
            if n.is_multiple_of(2) { "0.21" } else { "0.20" },
        );
        v["schema_version"] = json!(2);
        v["source_trade"] = Value::Null;
        v
    };
    for n in 3..=10 {
        m.apply(&mark(&m, n)).unwrap();
    }
    let full = m.checkpoint();
    assert_eq!(
        m.apply(&mark(&m, 11)).unwrap_err().0,
        "MARGIN_OBSERVATION_HISTORY_LIMIT"
    );
    assert_eq!(m.checkpoint(), full);
    assert_eq!(full["schema_version"], 2);
    assert!(manager(8).restore(&full, &digest(&full)).is_err());
    let mut fresh = Manager::new(config, 8).unwrap();
    fresh.restore(&full, &digest(&full)).unwrap();
    for owner in [&mut m, &mut fresh] {
        owner
            .apply(&next(owner, id, 12, "OCCUPY", "1", "0.33", "0.20"))
            .unwrap();
        owner
            .apply(&next(owner, id, 13, "OCCUPY", "1", "0.34", "0.20"))
            .unwrap();
        owner
            .apply(&next(
                owner,
                id,
                14,
                "RELEASE_RESERVED",
                "0",
                "0.00",
                "0.00",
            ))
            .unwrap();
        let close = owner.release_quote(id, "3").unwrap();
        owner
            .apply(&next(
                owner,
                id,
                15,
                "RELEASE_OCCUPIED",
                "3",
                close["amount"].as_str().unwrap(),
                close["maintenance"].as_str().unwrap(),
            ))
            .unwrap();
        assert_eq!(owner.snapshot(id).unwrap()["status"], "CLOSED");
    }
    assert_eq!(m.checkpoint(), fresh.checkpoint());
}

fn entry_profile_config() -> Value {
    let mut config = fixture()["config"].clone();
    config["observation_capacity"] = json!(8);
    config["entry_profile"] = json!("LINEAR_LONG_NETTING_CROSS_OPEN");
    config
}
fn entry_order(
    m: &mut Manager,
    order: &str,
    sequence: u64,
    scope_change: Option<(&str, &str)>,
    amount: &str,
) -> String {
    let mut command = reserve("1");
    command["id"] = json!(format!("entry-reserve-{sequence}"));
    command["source_ref"] = json!(format!("entry-source-{sequence}"));
    command["source_order"] = json!(order);
    command["scope"]["request"] = json!(format!("entry-request-{sequence}"));
    command["amount"] = json!(amount);
    command["time"] = json!(sequence);
    if let Some((key, value)) = scope_change {
        command["scope"][key] = json!(value);
    }
    m.apply(&command).unwrap().record()["after"]["id"]
        .as_str()
        .unwrap()
        .to_owned()
}
fn entry_occupy(m: &Manager, id: &str, sequence: u64, amount: &str, maintenance: &str) -> Value {
    let state = m.snapshot(id).unwrap();
    let mut command = next(m, id, sequence, "OCCUPY", "1", amount, maintenance);
    command["scope"] = state["scope"].clone();
    command["source_order"] = state["order"].clone();
    command
}

#[test]
fn explicit_entry_profile_shares_only_the_same_cross_pool() {
    for difference in [
        None,
        Some(("cluster", "another-cluster")),
        Some(("revision", "another-revision")),
        Some(("instrument", "600001.XSHG")),
    ] {
        let mut manager = Manager::new(entry_profile_config(), 512).unwrap();
        let first = entry_order(&mut manager, "entry-order-1", 1, None, "0.10");
        manager
            .apply(&entry_occupy(&manager, &first, 2, "0.10", "0.00"))
            .unwrap();
        let second = entry_order(&mut manager, "entry-order-2", 3, difference, "0.01");
        let before = manager.checkpoint();
        let command = entry_occupy(&manager, &second, 4, "0.00", "0.01");
        if difference.is_none() {
            manager.apply(&command).unwrap();
            assert_eq!(manager.snapshot(&first).unwrap()["occupied"], "0.10");
            assert_eq!(manager.snapshot(&second).unwrap()["occupied"], "0.00");
            assert_eq!(
                manager.snapshot(&second).unwrap()["entry_maintenance"],
                "0.01"
            );
        } else {
            assert_eq!(manager.apply(&command).unwrap_err().0, "MARGIN_OCCUPY");
            assert_eq!(manager.checkpoint(), before);
        }
    }
}

#[test]
fn retained_profiles_keep_the_original_delta_guard_and_positive_reservation() {
    for observations in [false, true] {
        let mut config = fixture()["config"].clone();
        if observations {
            config["observation_capacity"] = json!(8);
        }
        let mut manager = Manager::new(config, 512).unwrap();
        let first = entry_order(&mut manager, "entry-order-1", 1, None, "0.10");
        manager
            .apply(&entry_occupy(&manager, &first, 2, "0.10", "0.00"))
            .unwrap();
        let second = entry_order(&mut manager, "entry-order-2", 3, None, "0.01");
        let before = manager.checkpoint();
        assert_eq!(
            manager
                .apply(&entry_occupy(&manager, &second, 4, "0.00", "0.01"))
                .unwrap_err()
                .0,
            "MARGIN_OCCUPY"
        );
        assert_eq!(manager.checkpoint(), before);
        assert!(
            manager
                .snapshot(&first)
                .unwrap()
                .get("entry_maintenance")
                .is_none()
        );
        assert!(manager.release_quote(&first, "1").is_ok());
    }
    let mut manager = Manager::new(entry_profile_config(), 512).unwrap();
    let mut zero = reserve("1");
    zero["amount"] = json!("0.00");
    assert_eq!(manager.apply(&zero).unwrap_err().0, "MARGIN_RESERVE");
    assert!(
        manager.checkpoint()["records"]
            .as_array()
            .unwrap()
            .is_empty()
    );
}

#[test]
fn entry_profile_replays_entry_requirements_and_rejects_close_and_rehashed_state() {
    let config = entry_profile_config();
    let mut manager = Manager::new(config.clone(), 512).unwrap();
    let id = entry_order(&mut manager, "entry-order-1", 1, None, "0.10");
    manager
        .apply(&entry_occupy(&manager, &id, 2, "0.10", "0.01"))
        .unwrap();
    let mut mark = next(&manager, &id, 3, "MARK_MAINTENANCE", "1", "0.00", "0.50");
    mark["schema_version"] = json!(2);
    mark["scope"] = manager.snapshot(&id).unwrap()["scope"].clone();
    mark["source_order"] = manager.snapshot(&id).unwrap()["order"].clone();
    mark["source_trade"] = Value::Null;
    manager.apply(&mark).unwrap();
    assert_eq!(manager.snapshot(&id).unwrap()["entry_maintenance"], "0.01");
    assert_eq!(manager.snapshot(&id).unwrap()["maintenance"], "0.50");
    let checkpoint = manager.checkpoint();
    let mut restored = Manager::new(config.clone(), 512).unwrap();
    restored.restore(&checkpoint, &digest(&checkpoint)).unwrap();
    assert_eq!(restored.checkpoint(), checkpoint);
    let mut changed = checkpoint.clone();
    changed["states"][&id]["entry_maintenance"] = json!("0.00");
    let mut fresh = Manager::new(config, 512).unwrap();
    assert!(fresh.restore(&changed, &digest(&changed)).is_err());
    assert_eq!(
        manager.release_quote(&id, "1").unwrap_err().0,
        "MARGIN_ENTRY_PROFILE_CLOSE_UNSUPPORTED"
    );
    assert_eq!(
        manager
            .apply(&next(
                &manager,
                &id,
                4,
                "RELEASE_OCCUPIED",
                "1",
                "0.10",
                "0.50"
            ))
            .unwrap_err()
            .0,
        "MARGIN_ENTRY_PROFILE_CLOSE_UNSUPPORTED"
    );
    assert_eq!(manager.checkpoint(), checkpoint);
    let mut missing_observations = entry_profile_config();
    missing_observations
        .as_object_mut()
        .unwrap()
        .remove("observation_capacity");
    assert!(Manager::new(missing_observations, 512).is_err());
}
