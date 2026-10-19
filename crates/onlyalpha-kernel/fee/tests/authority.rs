use onlyalpha_fee::*;
use serde_json::{Value, json};
fn fixture() -> Value {
    serde_json::from_str(include_str!("../../../../test-data/fee/common-v1.json")).unwrap()
}
fn scope() -> Value {
    fixture()["subject"].clone()
}
fn rule(scope: &str) -> Value {
    json!({"id":"commission","type":"BROKER_COMMISSION","authority":"BROKER","direction":"CHARGE","scope":scope,"resolution":"ORDER_FIXED","terms":[{"kind":"RATE","basis":"NOTIONAL","amount":"0.001"}],"minimum":"5","maximum":null,"quantum":"0.01","rounding":"HALF_EVEN","pipeline":"BOUNDS_THEN_ROUND","side":null,"offset":null,"liquidity":null})
}
fn catalog() -> Value {
    fixture()["catalog"].clone()
}
fn basis(n: &str) -> Value {
    json!({"notional":n,"quantity":"1","contracts":null,"currency":"USD"})
}
#[test]
fn cumulative_fee_has_one_owner_and_duplicate_conflict_is_atomic() {
    let registry = Catalog::new(catalog()).unwrap();
    let binding = registry.bind(scope(), 1).unwrap();
    let mut m=Manager::new(json!({"engine":"engine","runtime":"runtime","account":"account","gateway":"gateway","runtime_kind":"BACKTEST","generation":"a".repeat(64)}),64).unwrap();
    for (i, n, expected) in [
        (1, "1000", "5.00"),
        (2, "2000", "0.00"),
        (3, "7000", "2.00"),
    ] {
        let mut cum = basis(n);
        cum["quantity"] = json!(i.to_string());
        let a = registry
            .assess(
                &binding,
                i,
                &format!("t{i}"),
                i,
                basis(if i == 3 { "5000" } else { "1000" }),
                cum,
                None,
            )
            .unwrap();
        let p = m.apply(&a).unwrap();
        assert_eq!(p.record()["charges"], expected);
        assert_eq!(m.apply(&a).unwrap().record(), p.record());
    }
    let cp = m.checkpoint();
    let mut fresh = Manager::new(m.config().clone(), 64).unwrap();
    fresh.restore(&cp, &digest(&cp)).unwrap();
    assert_eq!(fresh.checkpoint(), cp);
    assert_eq!(fresh.query(&json!({"kind":"ORDER","id":"order","account":"account","broker":"broker","currency":"USD"})).unwrap().len(),3);
}
#[test]
fn bound_scope_and_missing_authorities_fail_closed() {
    let c = Catalog::new(catalog()).unwrap();
    let mut bad = scope();
    bad["account"] = json!("other");
    assert!(c.bind(bad, 1).is_err());
    let mut v = catalog();
    v["broker_contract"] = Value::Null;
    assert!(Catalog::new(v).is_err());
}
#[test]
fn explicit_fill_scope_and_negative_target_regression() {
    let mut v = catalog();
    v["schedules"][1]["rules"][0] = rule("FILL");
    let c = Catalog::new(v).unwrap();
    let b = c.bind(scope(), 1).unwrap();
    let mut m=Manager::new(json!({"engine":"engine","runtime":"runtime","account":"account","gateway":"gateway","runtime_kind":"BACKTEST","generation":"a".repeat(64)}),64).unwrap();
    for i in 1..=3 {
        let mut cum = basis(&(1000 * i).to_string());
        cum["quantity"] = json!(i.to_string());
        let a = c
            .assess(&b, i, &format!("t{i}"), i, basis("1000"), cum, None)
            .unwrap();
        assert_eq!(m.apply(&a).unwrap().record()["charges"], "5.00");
    }
}

fn manager() -> Manager {
    Manager::new(json!({"engine":"engine","runtime":"runtime","account":"account","gateway":"gateway","runtime_kind":"BACKTEST","generation":"a".repeat(64)}),64).unwrap()
}
fn first() -> (Catalog, Binding, Manager) {
    let c = Catalog::new(catalog()).unwrap();
    let b = c.bind(scope(), 1).unwrap();
    let mut m = manager();
    let a = c
        .assess(&b, 1, "t1", 1, basis("1000"), basis("1000"), None)
        .unwrap();
    m.apply(&a).unwrap();
    (c, b, m)
}
fn seal_statement(s: &mut Value) {
    s.as_object_mut().unwrap().remove("fingerprint");
    s["fingerprint"] = json!(digest(s));
}
fn order_scope() -> Value {
    json!({"kind":"ORDER","id":"order","account":"account","broker":"broker","currency":"USD"})
}
fn policy(action: &str) -> Value {
    json!({"id":"reconciliation","version":"1","currency":"USD","precision":2,"threshold":"0.01","unknown_action":action,"incomplete_action":"BLOCK","component_action":action})
}
fn report(reference: &str, sequence: u64, previous: Value, commission: &str) -> Value {
    json!({"id":format!("{reference}-{sequence}"),"reference":reference,"revision":sequence,"supersedes":previous,"scope":order_scope(),"mode":"DETAILED","complete":true,"total":commission,"components":[{"identity":{"type":"EXCHANGE_FEE","authority":"MARKET","direction":"CHARGE","component":"MARKET:market-zero:zero"},"amount":"0.00"},{"identity":{"type":"BROKER_COMMISSION","authority":"BROKER","direction":"CHARGE","component":"BROKER:commission:commission"},"amount":commission}]})
}
#[test]
fn schedule_registration_order_and_decimal_spelling_do_not_change_binding() {
    let v = catalog();
    let a = Catalog::new(v.clone()).unwrap().bind(scope(), 1).unwrap();
    let mut reordered = v;
    reordered["schedules"].as_array_mut().unwrap().reverse();
    reordered["schedules"][0]["rules"][0]["minimum"] = json!("5.00");
    let b = Catalog::new(reordered).unwrap().bind(scope(), 1).unwrap();
    assert_eq!(a.fingerprint(), b.fingerprint());
}
#[test]
fn fixed_binding_survives_expired_schedule_and_registry_addition() {
    let mut v = catalog();
    v["schedules"][1]["to"] = json!(2);
    let c = Catalog::new(v.clone()).unwrap();
    let b = c.bind(scope(), 1).unwrap();
    let mut next = v["schedules"][1].clone();
    next["version"] = json!("2");
    next["from"] = json!(2);
    next["to"] = Value::Null;
    next["rules"][0]["minimum"] = json!("99");
    v["schedules"].as_array_mut().unwrap().push(next);
    let newer = Catalog::new(v).unwrap();
    let a = newer
        .assess(&b, 3, "t", 1, basis("1000"), basis("1000"), None)
        .unwrap();
    let mut m = manager();
    assert_eq!(m.apply(&a).unwrap().record()["charges"], "5.00");
}
#[test]
fn fixed_resolution_does_not_require_current_applicability() {
    let mut v = catalog();
    v["schedules"][1]["to"] = json!(2);
    let c = Catalog::new(v).unwrap();
    let b = c.bind(scope(), 1).unwrap();
    assert!(
        c.assess(&b, 3, "t", 1, basis("1000"), basis("1000"), None)
            .is_ok()
    );
}
#[test]
fn effective_family_selects_exact_unique_version_and_rejects_scope_drift() {
    let mut v = catalog();
    v["schedules"][1]["rules"][0]["resolution"] = json!("FILL_EFFECTIVE");
    v["schedules"][1]["to"] = json!(2);
    let c = Catalog::new(v.clone()).unwrap();
    let b = c.bind(scope(), 1).unwrap();
    assert!(
        c.assess(&b, 3, "t", 1, basis("1000"), basis("1000"), None)
            .is_err()
    );
    let mut next = v["schedules"][1].clone();
    next["version"] = json!("2");
    next["from"] = json!(2);
    next["to"] = Value::Null;
    next["rules"][0]["minimum"] = json!("6");
    v["schedules"].as_array_mut().unwrap().push(next);
    let newer = Catalog::new(v.clone()).unwrap();
    let a = newer
        .assess(&b, 3, "t", 1, basis("1000"), basis("1000"), None)
        .unwrap();
    assert_eq!(manager().apply(&a).unwrap().record()["charges"], "6.00");
    v["schedules"][2]["scope"]["account"] = json!("different");
    assert!(Catalog::new(v).is_err());
}
#[test]
fn ambiguous_schedule_never_selects_first_or_latest() {
    let mut v = catalog();
    let mut duplicate = v["schedules"][1].clone();
    duplicate["version"] = json!("2");
    v["schedules"].as_array_mut().unwrap().push(duplicate);
    let c = Catalog::new(v).unwrap();
    assert!(c.bind(scope(), 1).is_err());
}
#[test]
fn exact_rounding_modes_and_formula_terms() {
    for (mode, expected) in [
        ("HALF_EVEN", "1.00"),
        ("HALF_UP", "1.01"),
        ("CEILING", "1.01"),
        ("FLOOR", "1.00"),
    ] {
        let mut v = catalog();
        let r = &mut v["schedules"][1]["rules"][0];
        r["minimum"] = Value::Null;
        r["terms"] = json!([{"kind":"FIXED","amount":"1.005"}]);
        r["rounding"] = json!(mode);
        let c = Catalog::new(v).unwrap();
        let b = c.bind(scope(), 1).unwrap();
        let a = c
            .assess(&b, 1, "t", 1, basis("1000"), basis("1000"), None)
            .unwrap();
        assert_eq!(manager().apply(&a).unwrap().record()["charges"], expected);
    }
}
#[test]
fn estimate_reserves_gross_charges_and_requires_split_bound() {
    let mut v = catalog();
    v["schedules"][1]["rules"][0] = rule("FILL");
    let c = Catalog::new(v).unwrap();
    let b = c.bind(scope(), 1).unwrap();
    assert!(
        c.estimate(&b, 1, basis("1000"), basis("3000"), 2, None)
            .is_err()
    );
    let e = c
        .estimate(&b, 1, basis("1000"), basis("3000"), 2, Some(3))
        .unwrap();
    assert_eq!(e["expected"]["charges"], "10.00");
    assert_eq!(e["maximum"]["charges"], "15.00");
    assert_eq!(e["reservation_charge"], "15.00");
}
#[test]
fn floor_linear_fill_estimate_uses_full_order_basis() {
    let mut v = catalog();
    let r = &mut v["schedules"][1]["rules"][0];
    *r = rule("FILL");
    r["minimum"] = Value::Null;
    r["rounding"] = json!("FLOOR");
    let c = Catalog::new(v).unwrap();
    let b = c.bind(scope(), 1).unwrap();
    let e = c
        .estimate(&b, 1, basis("1000"), basis("5000"), 5, None)
        .unwrap();
    assert_eq!(e["reservation_charge"], "5.00");
}
#[test]
fn unsupported_basis_and_unbounded_numbers_fail_before_mutation() {
    for s in ["NaN", "Infinity", "1e999999999", "-1"] {
        let mut v = catalog();
        v["schedules"][1]["rules"][0]["minimum"] = json!(s);
        assert!(Catalog::new(v).is_err());
    }
    let mut v = catalog();
    v["schedules"][1]["rules"][0]["terms"] =
        json!([{"kind":"PER_UNIT","basis":"CONTRACTS","amount":"2"}]);
    let c = Catalog::new(v).unwrap();
    let b = c.bind(scope(), 1).unwrap();
    assert!(
        c.assess(&b, 1, "t", 1, basis("1000"), basis("1000"), None)
            .is_err()
    );
}
#[test]
fn changed_duplicate_and_corrupt_replay_leave_owner_unchanged() {
    let (c, b, mut m) = first();
    let cp = m.checkpoint();
    let mut changed = basis("2000");
    changed["quantity"] = json!("2");
    let a = c
        .assess(&b, 1, "t1", 1, basis("1000"), changed, None)
        .unwrap();
    assert!(m.apply(&a).is_err());
    assert_eq!(m.checkpoint(), cp);
    let mut bad = cp.clone();
    bad["history"][0]["input"]["components"][0]["target"] = json!("999.00");
    assert!(m.restore(&bad, &digest(&bad)).is_err());
    assert_eq!(m.checkpoint(), cp);
}
#[test]
fn detailed_reconciliation_is_component_bound_and_idempotent() {
    let (_, _, mut m) = first();
    let e = report("statement", 1, Value::Null, "5.23");
    let d = m.reconcile(e.clone(), policy("ADJUST")).unwrap();
    assert_eq!(d["status"], "RECONCILED_WITH_ADJUSTMENT");
    assert_eq!(d["adjustments"][0]["amount"], "0.23");
    let cp = m.checkpoint();
    assert_eq!(m.reconcile(e, policy("ADJUST")).unwrap(), d);
    assert_eq!(m.checkpoint(), cp);
    let d = m
        .reconcile(
            report("statement", 2, json!("statement-1"), "5.00"),
            policy("ADJUST"),
        )
        .unwrap();
    assert_eq!(d["adjustments"][0]["direction"], "REFUND");
    assert_eq!(d["adjustments"][0]["amount"], "0.23");
    let cp = m.checkpoint();
    let mut fresh = manager();
    fresh.restore(&cp, &digest(&cp)).unwrap();
    assert_eq!(fresh.adjustments(), m.adjustments());
}
#[test]
fn unrelated_match_cannot_clear_blocker_and_multiple_families_survive_restart() {
    let (_, _, mut m) = first();
    for name in ["a", "b"] {
        assert_eq!(
            m.reconcile(report(name, 1, Value::Null, "5.23"), policy("BLOCK"))
                .unwrap()["status"],
            "TRADING_BLOCKED"
        );
    }
    assert_eq!(m.active_blockers().len(), 2);
    m.reconcile(report("unrelated", 1, Value::Null, "5.00"), policy("BLOCK"))
        .unwrap();
    assert_eq!(m.active_blockers().len(), 2);
    assert!(m.permits("RISK_REDUCING").unwrap());
    for risk in ["RISK_NEUTRAL", "RISK_INCREASING", "UNKNOWN"] {
        assert!(!m.permits(risk).unwrap());
    }
    m.reconcile(report("a", 2, json!("a-1"), "5.00"), policy("BLOCK"))
        .unwrap();
    assert_eq!(m.active_blockers().len(), 1);
    let cp = m.checkpoint();
    let mut fresh = manager();
    fresh.restore(&cp, &digest(&cp)).unwrap();
    assert_eq!(fresh.active_blockers(), m.active_blockers());
}
#[test]
fn missing_component_is_not_explicit_zero_and_bad_revision_is_atomic() {
    let (_, _, mut m) = first();
    let mut e = report("x", 1, Value::Null, "5.00");
    e["components"].as_array_mut().unwrap().remove(0);
    let d = m.reconcile(e, policy("BLOCK")).unwrap();
    assert_eq!(d["status"], "TRADING_BLOCKED");
    let cp = m.checkpoint();
    assert!(
        m.reconcile(report("x", 3, json!("x-1"), "5.00"), policy("BLOCK"))
            .is_err()
    );
    assert_eq!(m.checkpoint(), cp);
}
#[test]
fn changed_same_evidence_identity_latches_conflict_without_rewriting_applications() {
    let (_, _, mut m) = first();
    m.reconcile(report("x", 1, Value::Null, "5.00"), policy("BLOCK"))
        .unwrap();
    let apps = m.query(&order_scope()).unwrap();
    let d = m
        .reconcile(report("x", 1, Value::Null, "6.00"), policy("BLOCK"))
        .unwrap();
    assert_eq!(d["status"], "EVIDENCE_CONFLICT");
    assert!(!m.permits("RISK_INCREASING").unwrap());
    assert_eq!(m.query(&order_scope()).unwrap(), apps);
}
#[test]
fn query_scope_is_typed_and_statement_end_is_exclusive() {
    let (_, _, m) = first();
    let mut s = json!({"kind":"STATEMENT","id":"s","account":"account","broker":"broker","currency":"USD","fingerprint":"c".repeat(64),"from":0,"to":1});
    seal_statement(&mut s);
    assert!(m.query(&s).unwrap().is_empty());
    s["to"] = json!(2);
    seal_statement(&mut s);
    assert_eq!(m.query(&s).unwrap().len(), 1);
    s["account"] = json!("foreign");
    seal_statement(&mut s);
    assert!(m.query(&s).is_err());
    let mut s = order_scope();
    s["trade"] = json!("t1");
    assert!(m.query(&s).is_err());
}

#[test]
fn maximum_estimate_remains_a_bound_when_counts_are_equal() {
    let mut v = catalog();
    v["schedules"][1]["rules"][0] = rule("FILL");
    let c = Catalog::new(v).unwrap();
    let b = c.bind(scope(), 1).unwrap();
    let e = c
        .estimate(&b, 1, basis("1000"), basis("10000"), 1, Some(1))
        .unwrap();
    assert_eq!(e["maximum"]["charges"], "10.00");
}
#[test]
fn order_capacity_does_not_stop_existing_fee_facts() {
    let c = Catalog::new(catalog()).unwrap();
    let b = c.bind(scope(), 1).unwrap();
    let mut m = Manager::new(manager().config().clone(), 1).unwrap();
    for i in 1..=3 {
        let mut cum = basis(&(1000 * i).to_string());
        cum["quantity"] = json!(i.to_string());
        let a = c
            .assess(&b, 1, &format!("t{i}"), i, basis("1000"), cum, None)
            .unwrap();
        m.apply(&a).unwrap();
    }
    assert_eq!(m.query(&order_scope()).unwrap().len(), 3);
    let mut other = scope();
    other["order"] = json!("second");
    let b = c.bind(other, 1).unwrap();
    let a = c
        .assess(&b, 1, "next", 1, basis("1000"), basis("1000"), None)
        .unwrap();
    assert!(m.apply(&a).is_err());
}
#[test]
fn absent_local_proof_and_bad_precision_never_become_match_or_adjustment() {
    let mut m = manager();
    let mut e = report("empty", 1, Value::Null, "0.00");
    e["components"] = json!([]);
    let d = m.reconcile(e, policy("BLOCK")).unwrap();
    assert_ne!(d["status"], "MATCHED");
    assert!(!m.permits("RISK_INCREASING").unwrap());
    let (_, _, mut m) = first();
    let mut p = policy("ADJUST");
    p["precision"] = json!(0);
    assert!(m.reconcile(report("x", 1, Value::Null, "5.23"), p).is_err());
}
#[test]
fn canonical_report_modes_are_explicit_and_preserve_lineage() {
    let (_, _, mut m) = first();
    for mode in ["ALL_IN", "COMMISSION_ONLY", "ORDER_CUMULATIVE"] {
        let mut e = report(mode, 1, Value::Null, "5.00");
        e["mode"] = json!(mode);
        e["components"] = json!([]);
        let d = m.reconcile(e, policy("BLOCK")).unwrap();
        assert_eq!(d["status"], "MATCHED");
    }
}
#[test]
fn gross_fee_reservation_is_not_netted_against_rebate() {
    let mut v = catalog();
    let mut r = rule("ORDER_CUMULATIVE");
    r["id"] = json!("rebate");
    r["direction"] = json!("REBATE");
    r["minimum"] = json!("9");
    v["schedules"][1]["rules"].as_array_mut().unwrap().push(r);
    let c = Catalog::new(v).unwrap();
    let b = c.bind(scope(), 1).unwrap();
    let e = c
        .estimate(&b, 1, basis("1000"), basis("1000"), 1, Some(1))
        .unwrap();
    assert_eq!(e["reservation_charge"], "5.00");
    assert_eq!(e["expected"]["rebates"], "9.00");
}
#[test]
fn malformed_catalog_values_return_errors_without_panicking() {
    for v in [json!(true), json!(1), json!("bad"), json!([]), Value::Null] {
        assert!(
            std::panic::catch_unwind(|| Catalog::new(v))
                .unwrap()
                .is_err()
        );
    }
}

#[test]
fn fee_time_preserves_negative_and_beyond_machine_width_domain_instants() {
    let c = Catalog::new(catalog()).unwrap();
    let b = c.bind(scope(), 1).unwrap();
    let a = c
        .assess(
            &b,
            1,
            "before-epoch",
            -1_i64,
            basis("1000"),
            basis("1000"),
            None,
        )
        .unwrap();
    assert_eq!(manager().apply(&a).unwrap().record()["time"], -1);
    let big = bigdecimal::num_bigint::BigInt::from(u64::MAX) + 1_u8;
    let a = c
        .assess(
            &b,
            1,
            "large-time",
            big.clone(),
            basis("1000"),
            basis("1000"),
            None,
        )
        .unwrap();
    assert_eq!(
        manager().apply(&a).unwrap().record()["time"].to_string(),
        big.to_string()
    );
}

#[test]
fn whole_context_mutation_cannot_cross_gateway_or_runtime_kind() {
    let c = Catalog::new(catalog()).unwrap();
    for field in ["gateway", "runtime_kind"] {
        let mut subject = scope();
        subject[field] = json!(if field == "gateway" { "foreign" } else { "SIM" });
        let b = c.bind(subject, 1).unwrap();
        let a = c
            .assess(&b, 1, "t", 1, basis("1000"), basis("1000"), None)
            .unwrap();
        assert!(manager().apply(&a).is_err());
    }
}

#[test]
fn current_catalog_cannot_rewrite_an_already_bound_schedule_version() {
    let mut v = catalog();
    v["schedules"][1]["rules"][0]["resolution"] = json!("FILL_EFFECTIVE");
    let c = Catalog::new(v.clone()).unwrap();
    let b = c.bind(scope(), 1).unwrap();
    v["schedules"][1]["rules"][0]["minimum"] = json!("99");
    let altered = Catalog::new(v).unwrap();
    assert!(
        altered
            .assess(&b, 1, "t", 1, basis("1000"), basis("1000"), None)
            .is_err()
    );
}
#[test]
fn restore_is_fresh_only_and_checkpoint_binds_derived_economics() {
    let (c, b, mut m) = first();
    let before = m.checkpoint();
    let mut cum = basis("2000");
    cum["quantity"] = json!("2");
    let a = c.assess(&b, 1, "t2", 2, basis("1000"), cum, None).unwrap();
    m.apply(&a).unwrap();
    assert!(m.restore(&before, &digest(&before)).is_err());
    assert!(before["state_hash"].is_string());
    let mut v = catalog();
    v["schedules"][1]["rules"][0]["minimum"] = json!("9");
    let new = Catalog::new(v).unwrap();
    let a = new
        .assess(
            &new.bind(scope(), 1).unwrap(),
            1,
            "t1",
            1,
            basis("1000"),
            basis("1000"),
            None,
        )
        .unwrap();
    let mut changed = before;
    changed["history"][0]["input"] = a.record();
    assert!(manager().restore(&changed, &digest(&changed)).is_err());
}
#[test]
fn role_dependent_estimate_cannot_silently_ignore_fees() {
    let mut v = catalog();
    v["schedules"][1]["rules"][0]["liquidity"] = json!("TAKER");
    let c = Catalog::new(v).unwrap();
    let b = c.bind(scope(), 1).unwrap();
    assert!(
        c.estimate(&b, 1, basis("1000"), basis("1000"), 1, Some(1))
            .is_err()
    );
}
#[test]
fn statement_scope_fingerprint_is_a_relation_proof() {
    let (_, _, m) = first();
    let s = json!({"kind":"STATEMENT","id":"s","account":"account","broker":"broker","currency":"USD","fingerprint":"f".repeat(64),"from":0,"to":2});
    assert!(m.query(&s).is_err());
}
#[test]
fn cumulative_contract_basis_cannot_disagree_with_fill_history() {
    let mut v = catalog();
    v["schedules"][1]["rules"][0]["terms"] =
        json!([{"kind":"PER_UNIT","basis":"CONTRACTS","amount":"2"}]);
    let c = Catalog::new(v).unwrap();
    let b = c.bind(scope(), 1).unwrap();
    let mut fill = basis("1000");
    fill["contracts"] = json!("1");
    let mut cumulative = fill.clone();
    cumulative["contracts"] = json!("99");
    let a = c.assess(&b, 1, "t", 1, fill, cumulative, None).unwrap();
    assert!(manager().apply(&a).is_err());
}

fn admitted(trade: &str, order: &str) -> Value {
    let mut s = scope();
    let mut context = json!({"schema_version":1,"request":"request"});
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
    ] {
        context[k] = s[k].take();
    }
    let mut p = json!({"schema_version":1,"instruction":format!("instruction-{order}"),"source_ref":format!("source-{order}"),"policy":"b".repeat(64),"order":order,"trade":trade,"currency":scope()["currency"],"charge_target":"5.00","rebate_target":"0.00","scope":context,"family":"ORDER_FEE_ACCRUAL","version":1,"as_of_sequence":1});
    p["source_digest"] = json!(digest(&p));
    p
}
#[test]
fn split_rounding_estimate_covers_actual_and_requires_known_count() {
    for rounding in ["HALF_UP", "HALF_EVEN", "CEILING"] {
        let mut v = catalog();
        let r = &mut v["schedules"][1]["rules"][0];
        *r = rule("FILL");
        r["minimum"] = Value::Null;
        r["rounding"] = json!(rounding);
        let c = Catalog::new(v).unwrap();
        let b = c.bind(scope(), 1).unwrap();
        let estimate = c
            .estimate(&b, 1, basis("5"), basis("10"), 2, Some(2))
            .unwrap();
        let mut m = manager();
        let mut actual = bigdecimal::BigDecimal::from(0);
        for i in 1..=2 {
            let mut cumulative = basis(&(5 * i).to_string());
            cumulative["quantity"] = json!(i.to_string());
            let a = c
                .assess(
                    &b,
                    1,
                    &format!("split-{i}"),
                    i,
                    basis("5"),
                    cumulative,
                    None,
                )
                .unwrap();
            actual += m.apply(&a).unwrap().record()["charges"]
                .as_str()
                .unwrap()
                .parse::<bigdecimal::BigDecimal>()
                .unwrap();
        }
        assert!(
            estimate["reservation_charge"]
                .as_str()
                .unwrap()
                .parse::<bigdecimal::BigDecimal>()
                .unwrap()
                >= actual,
            "{rounding}"
        );
        assert!(c.estimate(&b, 1, basis("5"), basis("10"), 2, None).is_err());
    }
}
#[test]
fn unknown_liquidity_is_not_a_proven_rule_mismatch() {
    let mut v = catalog();
    v["schedules"][1]["rules"][0]["liquidity"] = json!("TAKER");
    let c = Catalog::new(v.clone()).unwrap();
    let b = c.bind(scope(), 1).unwrap();
    assert!(
        c.assess(&b, 1, "t", 1, basis("1000"), basis("1000"), None)
            .is_err()
    );
    assert_eq!(
        manager()
            .apply(
                &c.assess(&b, 1, "t", 1, basis("1000"), basis("1000"), Some("TAKER"))
                    .unwrap()
            )
            .unwrap()
            .record()["charges"],
        "5.00"
    );
    v["schedules"][1]["rules"][0]["side"] = json!("SELL");
    let c = Catalog::new(v).unwrap();
    let b = c.bind(scope(), 1).unwrap();
    assert!(
        c.assess(&b, 1, "t", 1, basis("1000"), basis("1000"), None)
            .is_ok()
    );
}
#[test]
fn sub_currency_external_and_admitted_amounts_are_atomic_errors() {
    let (_, _, mut m) = first();
    let cp = m.checkpoint();
    assert!(
        m.reconcile(report("subcent", 1, Value::Null, "5.005"), policy("ADJUST"))
            .is_err()
    );
    assert_eq!(m.checkpoint(), cp);
    let mut m = manager();
    let cp = m.checkpoint();
    let mut p = admitted("other", "other");
    p["charge_target"] = json!("5.005");
    p.as_object_mut().unwrap().remove("source_digest");
    p["source_digest"] = json!(digest(&p));
    assert!(m.apply_admitted_target(&p).is_err());
    assert_eq!(m.checkpoint(), cp);
}
#[test]
fn aggregate_admission_cannot_certify_absence_without_query_proof() {
    let mut m = manager();
    m.apply_admitted_target(&admitted("t", "other")).unwrap();
    assert!(m.query(&order_scope()).is_err());
    let cp = m.checkpoint();
    let mut fresh = manager();
    fresh.restore(&cp, &digest(&cp)).unwrap();
    assert!(fresh.query(&order_scope()).is_err());
}
#[test]
fn trade_identity_is_unique_across_producer_ports_and_orders() {
    let (c, b, mut m) = first();
    let cp = m.checkpoint();
    assert!(m.apply_admitted_target(&admitted("t1", "other")).is_err());
    assert_eq!(m.checkpoint(), cp);
    let mut m = manager();
    m.apply_admitted_target(&admitted("t1", "other")).unwrap();
    let cp = m.checkpoint();
    let a = c
        .assess(&b, 1, "t1", 1, basis("1000"), basis("1000"), None)
        .unwrap();
    assert!(m.apply(&a).is_err());
    assert_eq!(m.checkpoint(), cp);
}
