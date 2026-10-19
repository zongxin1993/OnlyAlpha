use onlyalpha_settlement::*;
use serde_json::{Value, json};
fn fixture() -> Value {
    serde_json::from_str(include_str!(
        "../../../../test-data/settlement/common-v1.json"
    ))
    .unwrap()
}
fn config() -> Value {
    let v = fixture();
    let mut c = json!({"currency":v["currency"]});
    for k in [
        "engine",
        "runtime",
        "account",
        "gateway",
        "generation",
        "runtime_kind",
    ] {
        c[k] = v["scope"][k].clone();
    }
    c
}
#[test]
fn t1_holiday_calendar_and_atomic_fresh_recovery() {
    let mut v = fixture();
    for k in [
        "asset_trade_available",
        "cash_withdrawable",
        "legal_settled",
    ] {
        v["policy"][k] = json!(1);
    }
    let i = compile(v).unwrap();
    assert_eq!(
        i.record()["schedule"]["asset_trade_available"],
        "2026-10-27"
    );
    let mut m = Authority::new(config(), 8).unwrap();
    record(&mut m, &i).unwrap();
    let before = m.checkpoint();
    assert!(m.mature(i.id(), "2026-10-26", json!(2), 1).is_err());
    assert_eq!(m.checkpoint(), before);
    let effect = m.mature(i.id(), "2026-10-27", json!(3), 1).unwrap();
    assert_eq!(effect.record()["asset_quantity"], "4");
    assert_eq!(
        m.mature(i.id(), "2026-10-27", json!(3), 1)
            .unwrap()
            .record(),
        effect.record()
    );
    let cp = m.checkpoint();
    let mut fresh = Authority::new(config(), 8).unwrap();
    fresh.restore(&cp, &digest(&cp)).unwrap();
    assert_eq!(fresh.checkpoint(), cp);
    assert!(fresh.due("2026-12-31").unwrap().is_empty());
}
#[test]
fn all_six_axes_complete_only_after_every_date() {
    let mut v = fixture();
    v["policy"]["asset_booked"] = json!(2);
    v["policy"]["cash_booked"] = json!(1);
    let i = compile(v).unwrap();
    let mut m = Authority::new(config(), 8).unwrap();
    record(&mut m, &i).unwrap();
    assert_eq!(m.snapshot(i.id()).unwrap()["status"], "PARTIALLY_EFFECTIVE");
    assert_eq!(m.due("2026-10-27").unwrap().len(), 1);
    m.mature(i.id(), "2026-10-27", json!(2), 1).unwrap();
    assert_eq!(m.snapshot(i.id()).unwrap()["status"], "PARTIALLY_EFFECTIVE");
    m.mature(i.id(), "2026-10-28", json!(3), 2).unwrap();
    assert_eq!(m.snapshot(i.id()).unwrap()["status"], "COMPLETED");
}
#[test]
fn duplicate_trade_and_whole_owner_mutations_fail_atomically() {
    let i = compile(fixture()).unwrap();
    let mut m = Authority::new(config(), 8).unwrap();
    record(&mut m, &i).unwrap();
    let cp = m.checkpoint();
    record(&mut m, &i).unwrap();
    assert_eq!(m.checkpoint(), cp);
    let mut v = fixture();
    v["order"] = json!("other");
    assert!(record(&mut m, &compile(v).unwrap()).is_err());
    assert_eq!(m.checkpoint(), cp);
    for k in [
        "engine",
        "runtime",
        "account",
        "gateway",
        "generation",
        "runtime_kind",
    ] {
        let mut v = fixture();
        v["scope"][k] = json!(if k == "generation" {
            "c".repeat(64)
        } else if k == "runtime_kind" {
            "SIM".into()
        } else {
            "other".into()
        });
        assert!(record(&mut m, &compile(v).unwrap()).is_err());
        assert_eq!(m.checkpoint(), cp);
    }
}
#[test]
fn bad_money_calendar_and_derived_checkpoint_are_rejected() {
    for key in ["quantity", "gross_notional", "charges", "rebates"] {
        let mut v = fixture();
        v[key] = json!("-1");
        assert!(compile(v).is_err());
    }
    let mut v = fixture();
    v["gross_notional"] = json!("40.001");
    assert!(compile(v).is_err());
    let mut v = fixture();
    v["trading_day"] = json!("2026-10-24");
    assert!(compile(v).is_err());
    let mut v = fixture();
    v["policy"]["legal_settled"] = json!(4096);
    assert!(compile(v).is_err());
    let i = compile(fixture()).unwrap();
    let mut m = Authority::new(config(), 8).unwrap();
    record(&mut m, &i).unwrap();
    let cp = m.checkpoint();
    let mut bad = cp.clone();
    bad["instructions"][i.id()]["flags"]["asset_trade_available"] = json!(false);
    let mut fresh = Authority::new(config(), 8).unwrap();
    assert!(fresh.restore(&bad, &digest(&bad)).is_err());
    assert!(fresh.snapshot(i.id()).is_err());
}

fn another(mut v: Value, n: u64) -> Value {
    v["order"] = json!(format!("order-{n}"));
    v["scope"]["request"] = json!(format!("request-{n}"));
    v["trade"] = json!(format!("trade-{n}"));
    v["provenance"]["reference"] = json!(format!("source-{n}"));
    v["provenance"]["instruction"] = json!(format!("claim-{n}"));
    v
}
#[test]
fn scope_identifiers_and_calendar_venue_cannot_be_silently_reinterpreted() {
    for k in [
        "engine",
        "runtime",
        "account",
        "gateway",
        "cluster",
        "revision",
        "request",
        "instrument",
    ] {
        let mut v = fixture();
        v["scope"][k] = json!(format!(" {}", v["scope"][k].as_str().unwrap()));
        assert!(compile(v).is_err(), "{k}");
    }
    let mut v = fixture();
    v["calendar"]["venue_id"]["value"] = json!("OTHER");
    assert!(compile(v).is_err());
    let mut v = fixture();
    v["scope"]["instrument"] = json!("not-an-instrument");
    assert!(compile(v).is_err());
}
#[test]
fn capacity_blocks_new_order_admission_not_existing_safety_progress() {
    let mut v = fixture();
    v["policy"]["asset_trade_available"] = json!(1);
    let i = compile(v.clone()).unwrap();
    let mut m = Authority::new(config(), 4).unwrap();
    record(&mut m, &i).unwrap();
    let cp = m.checkpoint();
    assert!(record(&mut m, &compile(another(v, 2)).unwrap()).is_err());
    assert_eq!(cp, m.checkpoint());
    m.mature(i.id(), "2026-10-27", json!(2), 1).unwrap();
    assert_eq!(m.snapshot(i.id()).unwrap()["status"], "COMPLETED");
}
#[test]
fn named_policy_and_calendar_versions_cannot_be_redefined() {
    let i = compile(fixture()).unwrap();
    let mut m = Authority::new(config(), 8).unwrap();
    record(&mut m, &i).unwrap();
    let cp = m.checkpoint();
    for kind in ["policy", "calendar"] {
        let mut v = another(fixture(), 2);
        if kind == "policy" {
            v["policy"]["legal_settled"] = json!(1);
        } else {
            v["calendar"]["holidays"]
                .as_array_mut()
                .unwrap()
                .push(json!("2026-10-27"));
        }
        assert!(record(&mut m, &compile(v).unwrap()).is_err());
        assert_eq!(m.checkpoint(), cp);
    }
    let mut v = another(fixture(), 2);
    v["policy"]["version"] = json!("2");
    v["policy"]["legal_settled"] = json!(1);
    record(&mut m, &compile(v).unwrap()).unwrap();
}
#[test]
fn due_order_is_deterministic_and_query_values_are_detached() {
    let mut a = fixture();
    a["policy"]["asset_trade_available"] = json!(1);
    let mut b = another(a.clone(), 2);
    b["trading_day"] = json!("2026-10-22");
    let a = compile(a).unwrap();
    let b = compile(b).unwrap();
    let mut m = Authority::new(config(), 8).unwrap();
    record(&mut m, &a).unwrap();
    record(&mut m, &b).unwrap();
    let rows = m.due("2026-10-27").unwrap();
    assert_eq!(rows[0]["effective_on"], "2026-10-23");
    assert_eq!(rows[1]["effective_on"], "2026-10-27");
    let cp = m.checkpoint();
    let mut values = m.snapshots();
    values[0]["version"] = json!(99);
    assert_eq!(cp, m.checkpoint());
    assert_eq!(m.sequence_head(), 0);
}
#[test]
fn corrupt_maturity_receipt_and_nonfresh_restore_leave_receiver_unchanged() {
    let mut v = fixture();
    v["policy"]["cash_withdrawable"] = json!(1);
    v["side"] = json!("SELL");
    let i = compile(v).unwrap();
    let mut m = Authority::new(config(), 8).unwrap();
    record(&mut m, &i).unwrap();
    let initial = m.checkpoint();
    m.mature(i.id(), "2026-10-27", json!(2), 1).unwrap();
    let cp = m.checkpoint();
    assert!(m.restore(&initial, &digest(&initial)).is_err());
    assert_eq!(m.checkpoint(), cp);
    for field in ["cash_amount", "asset_quantity", "before_hash", "scope"] {
        let mut bad = cp.clone();
        bad["instructions"][i.id()]["maturities"][0]["result"][field] = json!("wrong");
        let mut fresh = Authority::new(config(), 8).unwrap();
        let before = fresh.checkpoint();
        assert!(fresh.restore(&bad, &digest(&bad)).is_err());
        assert_eq!(fresh.checkpoint(), before);
    }
}
#[test]
fn monetary_spelling_and_exact_signed_domain_time_preserve_identity() {
    let a = compile(fixture()).unwrap();
    let mut v = fixture();
    v["gross_notional"] = json!("40.0");
    v["quantity"] = json!("4.00");
    assert_eq!(compile(v).unwrap().id(), a.id());
    let mut v = fixture();
    v["time"] = serde_json::from_str("-99999999999999999999999999999999999").unwrap();
    v["policy"]["legal_settled"] = json!(1);
    let i = compile(v).unwrap();
    let mut m = Authority::new(config(), 8).unwrap();
    record(&mut m, &i).unwrap();
    let huge: Value = serde_json::from_str("99999999999999999999999999999999999").unwrap();
    m.mature(i.id(), "2026-10-27", huge, 1).unwrap();
    let cp = m.checkpoint();
    let mut fresh = Authority::new(config(), 8).unwrap();
    fresh.restore(&cp, &digest(&cp)).unwrap();
    assert_eq!(fresh.checkpoint(), cp);
}
#[test]
fn malformed_nested_values_and_calendar_exhaustion_are_bounded_errors() {
    for key in ["scope", "currency", "calendar", "policy", "provenance"] {
        let mut v = fixture();
        v[key] = json!([]);
        assert!(std::panic::catch_unwind(|| compile(v)).unwrap().is_err());
    }
    let mut v = fixture();
    v["calendar"]["effective_to"] = json!("2026-10-24");
    v["policy"]["legal_settled"] = json!(1);
    assert!(compile(v).is_err());
    let mut v = fixture();
    v["calendar"]["special_schedules"] = json!([{"schema_version":1,"trading_day":{"schema_version":1,"value":"2026-10-27"},"sessions":[],"is_closed":true}]);
    v["policy"]["legal_settled"] = json!(1);
    assert_eq!(
        compile(v).unwrap().record()["schedule"]["legal_settled"],
        "2026-10-28"
    );
}

#[test]
fn worst_case_fill_slots_are_reserved_before_order_admission() {
    let v = fixture();
    let mut m = Authority::new(config(), 8).unwrap();
    let cp = m.checkpoint();
    assert!(
        m.admit_order(v["scope"].clone(), "order", "BUY", "12", 0)
            .is_err()
    );
    assert_eq!(m.checkpoint(), cp);
    m.admit_order(v["scope"].clone(), "order", "BUY", "8", 0)
        .unwrap();
    let mut v = v;
    v["quantity"] = json!("8");
    let i = compile(v).unwrap();
    record(&mut m, &i).unwrap();
    // A whole fill consumes one slot and proves the other seven are no longer needed.
    let v = another(fixture(), 2);
    m.admit_order(v["scope"].clone(), "order-2", "BUY", "7", 0)
        .unwrap();
    for n in 0..7 {
        let mut row = another(v.clone(), n + 10);
        row["order"] = json!("order-2");
        row["scope"] = v["scope"].clone();
        row["quantity"] = json!("1");
        record(&mut m, &compile(row).unwrap()).unwrap();
    }
    assert_eq!(m.snapshots().len(), 8);
    let cp = m.checkpoint();
    let mut fresh = Authority::new(config(), 8).unwrap();
    fresh.restore(&cp, &digest(&cp)).unwrap();
    assert_eq!(fresh.checkpoint(), cp);
}

// Test fixture setup includes explicit pre-Fill resource admission; failed combined setup is atomic.
fn record(m: &mut Authority, i: &Instruction) -> Result<(), Error> {
    let mut candidate = m.clone();
    let v = i.record();
    let input = &v["input"];
    if candidate.checkpoint()["orders"]
        .get(input["order"].as_str().unwrap())
        .is_none()
    {
        candidate.admit_order(
            input["scope"].clone(),
            input["order"].as_str().unwrap(),
            input["side"].as_str().unwrap(),
            input["quantity"].as_str().unwrap(),
            0,
        )?;
    }
    candidate.register(i)?;
    *m = candidate;
    Ok(())
}

#[test]
fn escaped_identity_receipt_budget_is_proved_before_registration() {
    let mut v = fixture();
    for key in ["order", "trade", "position", "allocation"] {
        v[key] = json!("\0".repeat(128));
    }
    for key in [
        "asset_booked",
        "asset_trade_available",
        "cash_booked",
        "cash_trade_available",
        "cash_withdrawable",
        "legal_settled",
    ] {
        v["policy"][key] = json!(1);
    }
    let instruction = compile(v).unwrap();
    let mut authority = Authority::new(config(), 8).unwrap();
    let input = instruction.record()["input"].clone();
    authority
        .admit_order(
            input["scope"].clone(),
            input["order"].as_str().unwrap(),
            "BUY",
            "4",
            0,
        )
        .unwrap();
    let before = authority.checkpoint();
    assert!(authority.register(&instruction).is_err());
    assert_eq!(authority.checkpoint(), before);
}

#[test]
fn reserved_receipt_accepts_large_economics_time_and_six_transitions() {
    let mut v = fixture();
    for key in ["order", "trade", "position", "allocation"] {
        v[key] = json!("\0".repeat(32));
    }
    for key in [
        "asset_booked",
        "asset_trade_available",
        "cash_booked",
        "cash_trade_available",
        "cash_withdrawable",
        "legal_settled",
    ] {
        v["policy"][key] = json!(1);
    }
    v["side"] = json!("SELL");
    v["gross_notional"] = json!(format!("{}.00", "9".repeat(120)));
    let i = compile(v).unwrap();
    let mut a = Authority::new(config(), 8).unwrap();
    record(&mut a, &i).unwrap();
    let at: Value = serde_json::from_str(&"9".repeat(256)).unwrap();
    let effect = a.mature(i.id(), "2026-10-27", at, 1).unwrap();
    assert_eq!(effect.record()["transitions"].as_array().unwrap().len(), 6);
    let cp = a.checkpoint();
    let mut fresh = Authority::new(config(), 8).unwrap();
    fresh.restore(&cp, &digest(&cp)).unwrap();
    assert_eq!(fresh.checkpoint(), cp);
}
