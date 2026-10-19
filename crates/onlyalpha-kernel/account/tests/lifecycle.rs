use onlyalpha_account::{Manager, Status, digest};
use serde_json::{Value, json};
fn config() -> Value {
    json!({"schema_version":1,"engine":"engine","runtime":"runtime","account":"account","gateway":"gateway","generation":"generation","account_type":"CASH","currency":{"schema_version":1,"code":"USD","precision":2,"currency_type":"FIAT"},"initial_cash":"1000.00"})
}
fn manager() -> Manager {
    Manager::new(config()).unwrap()
}
fn cmd(id: &str, op: &str, t: i64, p: Value) -> Value {
    json!({"schema_version":1,"engine":"engine","runtime":"runtime","account":"account","gateway":"gateway","generation":"generation","command_id":id,"cause":"a".repeat(64),"time":t,"op":op,"payload":p})
}
fn reserve(id: &str, amount: &str, t: i64) -> Value {
    cmd(
        id,
        "RESERVE",
        t,
        json!({"schema_version":1,"reservation":id,"order":format!("order-{id}"),"amount":amount}),
    )
}
fn trade(
    id: &str,
    reservation: Option<&str>,
    side: &str,
    notional: &str,
    fees: (&str, &str),
    t: i64,
    terminal: bool,
) -> Value {
    let (charges, rebates) = fees;
    cmd(
        id,
        "TRADE",
        t,
        json!({"schema_version":1,"trade":id,"execution":format!("x-{id}"),"venue_trade":format!("v-{id}"),"order":reservation.map(|s|format!("order-{s}")).unwrap_or("sell-order".into()),"sequence":t,"side":side,"notional":notional,"fee_instruction":format!("fee-{id}"),"charges":charges,"rebates":rebates,"realized_pnl_delta":"0.00","position_evidence":"b".repeat(64),"market_value_delta": if side=="BUY" {notional.to_owned()}else{format!("-{notional}")},"unrealized_pnl":"0.00","reservation":reservation,"terminal_fill":terminal,"cash_withdrawable":true}),
    )
}
fn roundtrip(m: &mut Manager) {
    let (b, h) = m.checkpoint().unwrap();
    let mut f = manager();
    f.restore(&b, &h).unwrap();
    assert_eq!(m.state(), f.state());
    *m = f;
}
#[test]
fn partial_and_terminal_fills_conserve_cash_and_holds() {
    let mut m = manager();
    m.apply(&reserve("r", "600.00", 1)).unwrap();
    m.apply(&trade(
        "t1",
        Some("r"),
        "BUY",
        "200.00",
        ("1.00", "0.00"),
        2,
        false,
    ))
    .unwrap();
    assert_eq!(m.snapshot()["cash"], "799.00");
    assert_eq!(m.snapshot()["reserved"], "399.00");
    roundtrip(&mut m);
    m.apply(&trade(
        "t2",
        Some("r"),
        "BUY",
        "100.00",
        ("1.00", "0.00"),
        3,
        true,
    ))
    .unwrap();
    assert_eq!(m.snapshot()["cash"], "698.00");
    assert_eq!(m.snapshot()["reserved"], "0.00");
    assert_eq!(m.reservation("r").unwrap()["released"], "298.00");
    assert_eq!(m.snapshot()["fees"], "2.00");
}
#[test]
fn conflicting_aliases_and_invalid_inputs_are_atomic() {
    let mut m = manager();
    m.apply(&reserve("r", "500.00", 1)).unwrap();
    let t = trade("t", Some("r"), "BUY", "100.00", ("1.00", "0.00"), 2, false);
    m.apply(&t).unwrap();
    let s = m.state();
    assert_eq!(m.apply(&t).unwrap().status, Status::Duplicate);
    assert_eq!(s, m.state());
    let mut bad = t.clone();
    bad["payload"]["notional"] = json!("110.00");
    assert_eq!(m.apply(&bad).unwrap().status, Status::Conflict);
    assert_eq!(s, m.state());
    let mut bad = trade(
        "other",
        Some("r"),
        "BUY",
        "110.00",
        ("1.00", "0.00"),
        3,
        false,
    );
    bad["payload"]["fee_instruction"] = json!("fee-t");
    assert_eq!(m.apply(&bad).unwrap().status, Status::Conflict);
    assert_eq!(s, m.state());
    let mut bad = reserve("r2", "1.001", 3);
    assert!(m.apply(&bad).is_err());
    bad["runtime"] = json!("other");
    assert!(m.apply(&bad).is_err());
    assert_eq!(s, m.state());
    roundtrip(&mut m);
}
#[test]
fn new_cash_owner_starts_without_hidden_time_and_rejects_bad_config() {
    let mut m = manager();
    assert!(m.snapshot()["time"].is_null());
    m.apply(&reserve("r", "10.00", -10)).unwrap();
    assert_eq!(m.snapshot()["time"], -10);
    let mut c = config();
    c["account_type"] = json!("MARGIN");
    assert!(Manager::new(c).is_err());
    let mut c = config();
    c["currency"]["code"] = json!("usd");
    assert!(Manager::new(c).is_err());
}

fn stage(id: &str, s: &str, t: i64) -> Value {
    cmd(
        id,
        "STAGE",
        t,
        json!({"schema_version":1,"reservation":"r","stage":s}),
    )
}
fn release(id: &str, s: &str, t: i64) -> Value {
    cmd(
        id,
        "RELEASE",
        t,
        json!({"schema_version":1,"reservation":"r","outcome":s}),
    )
}
fn broker(id: &str, m: &Manager, seq: u64, t: i64) -> Value {
    let s = m.snapshot();
    cmd(
        id,
        "BROKER",
        t,
        json!({"schema_version":1,"snapshot":id,"sequence":seq,"basis_sequence":s["sequence"],"quality":"VERIFIED","cash":s["cash"],"reserved":s["reserved"],"trade_available":s["trade_available"],"withdrawable":s["withdrawable"],"equity":s["equity"]}),
    )
}
#[test]
fn uncertain_release_retains_funds_and_late_ack_preserves_cancel() {
    let mut m = manager();
    m.apply(&reserve("r", "600.00", 1)).unwrap();
    m.apply(&stage("send", "SENT_TO_BROKER", 2)).unwrap();
    m.apply(&release("unknown", "UNKNOWN", 3)).unwrap();
    roundtrip(&mut m);
    assert_eq!(m.snapshot()["reserved"], "600.00");
    let s = m.state();
    assert!(m.apply(&release("bad", "NOT_SENT", 4)).is_err());
    assert_eq!(s, m.state());
    m.apply(&stage("ack", "BROKER_ACKNOWLEDGED", 4)).unwrap();
    assert_eq!(m.reservation("r").unwrap()["cancel_pending"], true);
    m.apply(&release("cancel", "CANCELLED", 5)).unwrap();
    assert_eq!(m.snapshot()["reserved"], "0.00");
    roundtrip(&mut m);
}
#[test]
fn rebates_and_sell_pnl_are_consumed_without_recomputing() {
    let mut m = manager();
    m.apply(&reserve("r", "500.00", 1)).unwrap();
    m.apply(&trade(
        "buy",
        Some("r"),
        "BUY",
        "300.00",
        ("1.00", "0.25"),
        2,
        true,
    ))
    .unwrap();
    let mut sell = trade("sell", None, "SELL", "320.00", ("2.00", "0.50"), 3, true);
    sell["payload"]["market_value_delta"] = json!("-300.00");
    sell["payload"]["realized_pnl_delta"] = json!("20.00");
    m.apply(&sell).unwrap();
    assert_eq!(m.snapshot()["cash"], "1017.75");
    assert_eq!(m.snapshot()["realized_pnl"], "20.00");
    assert_eq!(m.snapshot()["fees"], "2.25");
    assert_eq!(m.snapshot()["market_value"], "0.00");
    roundtrip(&mut m);
}
#[test]
fn fill_cannot_borrow_other_orders_hold_and_rejection_is_atomic() {
    let mut m = manager();
    m.apply(&reserve("r", "300.00", 1)).unwrap();
    m.apply(&reserve("other", "700.00", 2)).unwrap();
    let s = m.state();
    assert!(
        m.apply(&trade(
            "t",
            Some("r"),
            "BUY",
            "301.00",
            ("0.00", "0.00"),
            3,
            true
        ))
        .is_err()
    );
    assert_eq!(m.state(), s);
}
#[test]
fn conflicting_broker_does_not_overwrite_and_only_new_matching_proof_clears() {
    let mut m = manager();
    let mut b = broker("b1", &m, 1, 1);
    b["payload"]["cash"] = json!("999.00");
    m.apply(&b).unwrap();
    assert_eq!(m.snapshot()["cash"], "1000.00");
    assert_eq!(m.snapshot()["status"], "RECONCILING");
    assert!(m.apply(&reserve("r", "1.00", 2)).is_err());
    let mut bad = broker("b2", &m, 2, 2);
    bad["payload"]["quality"] = json!("UNKNOWN");
    m.apply(&bad).unwrap();
    roundtrip(&mut m);
    assert_eq!(m.snapshot()["status"], "RECONCILING");
    let good = broker("b3", &m, 3, 3);
    m.apply(&good).unwrap();
    assert_eq!(m.snapshot()["status"], "ACTIVE");
}
#[test]
fn stale_trade_is_observed_once_but_not_economically_applied_or_cleared() {
    let mut m = manager();
    m.apply(&reserve("r", "500.00", 1)).unwrap();
    m.apply(&trade(
        "buy",
        Some("r"),
        "BUY",
        "100.00",
        ("0.00", "0.00"),
        3,
        false,
    ))
    .unwrap();
    let mut old = trade("old", Some("r"), "BUY", "10.00", ("0.00", "0.00"), 2, false);
    assert_eq!(m.apply(&old).unwrap().status, Status::Stale);
    assert_eq!(m.snapshot()["cash"], "900.00");
    roundtrip(&mut m);
    let b = broker("b", &m, 1, 4);
    m.apply(&b).unwrap();
    assert_eq!(m.snapshot()["status"], "RECONCILING");
    old["payload"]["notional"] = json!("11.00");
    assert_eq!(m.apply(&old).unwrap().status, Status::Conflict);
    // New current facts continue the safety path under reconciliation.
    m.apply(&trade(
        "fill",
        Some("r"),
        "BUY",
        "10.00",
        ("0.00", "0.00"),
        5,
        false,
    ))
    .unwrap();
    assert_eq!(m.snapshot()["cash"], "890.00");
}
#[test]
fn valuation_requires_current_financial_basis_and_increasing_version() {
    let mut m = manager();
    let v = cmd(
        "val",
        "VALUATION",
        1,
        json!({"schema_version":1,"valuation":"v1","version":1,"economic_version":0,"position_evidence":"b".repeat(64),"market_value":"0.00","unrealized_pnl":"0.00"}),
    );
    m.apply(&v).unwrap();
    let s = m.state();
    let mut bad = v.clone();
    bad["command_id"] = json!("next");
    bad["payload"]["valuation"] = json!("v2");
    assert!(m.apply(&bad).is_err());
    assert_eq!(m.state(), s);
    let deposit = cmd(
        "deposit",
        "CASH_CHANGE",
        2,
        json!({"schema_version":1,"change":"c1","kind":"DEPOSIT","amount":"1.00","source_fact":"deposit-source"}),
    );
    m.apply(&deposit).unwrap();
    bad["time"] = json!(3);
    bad["payload"]["version"] = json!(2);
    assert!(m.apply(&bad).is_err());
    bad["payload"]["economic_version"] = json!(1);
    m.apply(&bad).unwrap();
    roundtrip(&mut m);
}
#[test]
fn settlement_is_explicit_source_scoped_and_cannot_double_release() {
    let mut m = manager();
    m.apply(&reserve("r", "100.00", 1)).unwrap();
    m.apply(&trade(
        "buy",
        Some("r"),
        "BUY",
        "100.00",
        ("0.00", "0.00"),
        2,
        true,
    ))
    .unwrap();
    let mut t = trade("sell", None, "SELL", "110.00", ("1.00", "0.00"), 3, true);
    t["payload"]["market_value_delta"] = json!("-100.00");
    t["payload"]["realized_pnl_delta"] = json!("10.00");
    t["payload"]["cash_withdrawable"] = json!(false);
    m.apply(&t).unwrap();
    assert_eq!(m.snapshot()["unsettled"], "109.00");
    assert_eq!(m.snapshot()["withdrawable"], "900.00");
    let settle = cmd(
        "settle",
        "SETTLE",
        4,
        json!({"schema_version":1,"instruction":"s1","source_trade":"sell","amount":"109.00"}),
    );
    m.apply(&settle).unwrap();
    assert_eq!(m.snapshot()["unsettled"], "0.00");
    let s = m.state();
    let mut bad = settle.clone();
    bad["command_id"] = json!("other");
    bad["payload"]["instruction"] = json!("s2");
    assert!(m.apply(&bad).is_err());
    assert_eq!(s, m.state());
    roundtrip(&mut m);
}
#[test]
fn duplicate_acknowledgements_bind_identity_after_restore() {
    let mut m = manager();
    let a = reserve("r", "100.00", 1);
    m.apply(&a).unwrap();
    let mut b = a.clone();
    b["command_id"] = json!("ack");
    assert_eq!(m.apply(&b).unwrap().status, Status::Duplicate);
    roundtrip(&mut m);
    b["payload"]["amount"] = json!("101.00");
    assert_eq!(m.apply(&b).unwrap().status, Status::Conflict);
}
#[test]
fn complete_recovery_rejects_mutations_without_partial_installation() {
    let mut m = manager();
    m.apply(&reserve("r", "500.00", 1)).unwrap();
    m.apply(&trade(
        "t",
        Some("r"),
        "BUY",
        "100.00",
        ("1.00", "0.00"),
        2,
        false,
    ))
    .unwrap();
    let s = m.state();
    let (b, h) = m.checkpoint().unwrap();
    assert!(m.restore(&b, &"0".repeat(64)).is_err());
    for field in [
        "receipts",
        "semantic",
        "reservations",
        "snapshot",
        "receivables",
    ] {
        let mut v: Value = serde_json::from_slice(&b).unwrap();
        v["state"][field] = json!({"tampered":true});
        let bad = serde_json::to_vec(&v).unwrap();
        assert!(m.restore(&bad, &digest(&bad)).is_err());
        assert_eq!(m.state(), s);
    }
    let mut v: Value = serde_json::from_slice(&b).unwrap();
    let first = v["journal"][0].clone();
    v["journal"].as_array_mut().unwrap().push(first);
    let bad = serde_json::to_vec(&v).unwrap();
    assert!(m.restore(&bad, &digest(&bad)).is_err());
    assert_eq!(m.state(), s);
    roundtrip(&mut m);
    assert_eq!(m.checkpoint().unwrap(), (b, h));
}

#[test]
fn common_vector_outputs() {
    let mut outputs = vec![];
    for line in include_str!("../../../../test-data/account/cash-v1.jsonl").lines() {
        let v: Value = serde_json::from_str(line).unwrap();
        let mut c = config();
        c["initial_cash"] = v["initial"].clone();
        let mut m = Manager::new(c).unwrap();
        m.apply(&reserve("r", v["reserve"].as_str().unwrap(), 1))
            .unwrap();
        let mut observed = vec![];
        for (i, fill) in v["fills"].as_array().unwrap().iter().enumerate() {
            let side = fill[0].as_str().unwrap();
            let mut t = trade(
                &format!("trade-{i}"),
                if side == "BUY" { Some("r") } else { None },
                side,
                fill[1].as_str().unwrap(),
                (fill[2].as_str().unwrap(), fill[3].as_str().unwrap()),
                i as i64 + 2,
                fill[5].as_bool().unwrap(),
            );
            t["payload"]["realized_pnl_delta"] = fill[4].clone();
            if side == "SELL" {
                t["payload"]["market_value_delta"] = json!(format!(
                    "-{}",
                    m.snapshot()["market_value"].as_str().unwrap()
                ));
            }
            m.apply(&t).unwrap();
            let s = m.snapshot();
            observed.push(json!([
                s["cash"],
                s["reserved"],
                s["fees"],
                s["realized_pnl"],
                s["equity"]
            ]));
            roundtrip(&mut m);
        }
        assert_eq!(json!(observed), v["expected"]);
        outputs.push(json!({"case":v["case"],"observed":observed}));
    }
    println!("ACCOUNT_VECTOR_OUTPUT {}", json!(outputs));
}

#[test]
fn partial_rebates_do_not_release_gross_reservation_authority() {
    let mut m = manager();
    m.apply(&reserve("r", "600.00", 1)).unwrap();
    m.apply(&trade(
        "t",
        Some("r"),
        "BUY",
        "200.00",
        ("1.00", "0.25"),
        2,
        false,
    ))
    .unwrap();
    assert_eq!(m.snapshot()["cash"], "799.25");
    assert_eq!(m.snapshot()["reserved"], "399.00");
    assert_eq!(m.reservation("r").unwrap()["consumed"], "201.00");
    roundtrip(&mut m);
}
#[test]
fn malformed_stale_trade_cannot_become_an_accepted_observation() {
    let mut m = manager();
    m.apply(&reserve("r", "500.00", 1)).unwrap();
    m.apply(&trade(
        "t",
        Some("r"),
        "BUY",
        "100.00",
        ("0.00", "0.00"),
        3,
        false,
    ))
    .unwrap();
    let s = m.state();
    let mut stale = trade("bad", Some("r"), "BUY", "-1.00", ("0.00", "0.00"), 2, false);
    assert!(m.apply(&stale).is_err());
    assert_eq!(s, m.state());
    stale["payload"]["notional"] = json!("1.00");
    stale["payload"]["side"] = json!("SHORT");
    assert!(m.apply(&stale).is_err());
    assert_eq!(s, m.state());
}
#[test]
fn free_cash_does_not_expand_an_orders_original_reservation() {
    let mut m = manager();
    m.apply(&reserve("r", "100.00", 1)).unwrap();
    let s = m.state();
    assert!(
        m.apply(&trade(
            "t",
            Some("r"),
            "BUY",
            "101.00",
            ("0.00", "0.00"),
            2,
            true
        ))
        .is_err()
    );
    assert_eq!(s, m.state());
}

#[test]
fn terminal_release_has_one_economic_occurrence_across_new_commands() {
    let mut m = manager();
    m.apply(&reserve("r", "100.00", 1)).unwrap();
    m.apply(&release("first", "NOT_SENT", 2)).unwrap();
    let before = m.snapshot();
    let o = m.apply(&release("again", "NOT_SENT", 3)).unwrap();
    assert_eq!(o.status, Status::Duplicate);
    assert!(o.fact.is_none());
    assert_eq!(m.snapshot(), before);
    roundtrip(&mut m);
}
#[test]
fn same_source_fact_cannot_credit_cash_in_two_economic_families() {
    let mut m = manager();
    let c = cmd(
        "cash",
        "CASH_CHANGE",
        1,
        json!({"schema_version":1,"change":"c1","kind":"DEPOSIT","amount":"10.00","source_fact":"source"}),
    );
    m.apply(&c).unwrap();
    let s = m.state();
    let e = cmd(
        "economic",
        "ECONOMIC",
        2,
        json!({"schema_version":1,"cashflow":"f1","kind":"FUNDING","amount":"10.00","source_fact":"source","instrument":"BTCUSDT.BINANCE"}),
    );
    assert_eq!(m.apply(&e).unwrap().status, Status::Conflict);
    assert_eq!(s, m.state());
}
#[test]
fn checkpoint_rejects_noncanonical_replay_commands_even_with_same_economics() {
    let mut m = manager();
    m.apply(&reserve("r", "100.00", 1)).unwrap();
    let (b, _) = m.checkpoint().unwrap();
    let s = m.state();
    let mut v: Value = serde_json::from_slice(&b).unwrap();
    v["journal"][0]["payload"]["amount"] = json!("100.0");
    let bad = serde_json::to_vec(&v).unwrap();
    assert!(m.restore(&bad, &digest(&bad)).is_err());
    assert_eq!(m.state(), s);
}
#[test]
fn cash_events_and_withdrawal_checks_remain_exact_and_source_bound() {
    let mut m = manager();
    let c = cmd(
        "deposit",
        "CASH_CHANGE",
        1,
        json!({"schema_version":1,"change":"c1","kind":"DEPOSIT","amount":"10.00","source_fact":"source"}),
    );
    m.apply(&c).unwrap();
    m.apply(&reserve("r", "1000.00", 2)).unwrap();
    let bad = cmd(
        "withdraw",
        "CASH_CHANGE",
        3,
        json!({"schema_version":1,"change":"c2","kind":"WITHDRAWAL","amount":"11.00","source_fact":"out"}),
    );
    let s = m.state();
    assert!(m.apply(&bad).is_err());
    assert_eq!(m.state(), s);
    let e = cmd(
        "funding",
        "ECONOMIC",
        3,
        json!({"schema_version":1,"cashflow":"f1","kind":"FUNDING","amount":"-1.00","source_fact":"funding-source","instrument":"BTCUSDT.BINANCE"}),
    );
    m.apply(&e).unwrap();
    assert_eq!(m.snapshot()["cash"], "1009.00");
    assert_eq!(m.snapshot()["realized_pnl"], "0.00");
    roundtrip(&mut m);
}
#[test]
fn numeric_and_schema_bounds_fail_before_installation() {
    let mut m = manager();
    let s = m.state();
    for amount in ["NaN", "Infinity", "1E100000", "-1.00", "1.001"] {
        assert!(m.apply(&reserve("r", amount, 1)).is_err());
        assert_eq!(s, m.state());
    }
    let mut bad = reserve("r", "1.00", 1);
    bad["payload"]["unknown"] = json!(true);
    assert!(m.apply(&bad).is_err());
    assert_eq!(s, m.state());
    let mut bad = reserve("r", "1.00", 1);
    bad["cause"] = json!("A".repeat(64));
    assert!(m.apply(&bad).is_err());
    assert_eq!(s, m.state());
}
#[test]
fn query_retains_exact_account_scope_and_returned_values_are_detached() {
    let m = manager();
    let mut s = m.snapshot();
    for field in [
        "engine",
        "runtime",
        "account",
        "gateway",
        "generation",
        "currency",
        "account_type",
    ] {
        assert_eq!(s[field], config()[field]);
    }
    s["cash"] = json!("0.00");
    assert_eq!(m.snapshot()["cash"], "1000.00");
}
#[test]
fn whole_context_and_owner_mutations_never_advance_cash() {
    let mut m = manager();
    let s = m.state();
    for field in ["engine", "runtime", "account", "gateway", "generation"] {
        let mut bad = reserve("r", "100.00", 1);
        bad[field] = json!("other");
        assert!(m.apply(&bad).is_err());
        assert_eq!(s, m.state());
    }
    let mut c = config();
    c["extra"] = json!(true);
    assert!(Manager::new(c).is_err());
    m.apply(&reserve("r", "100.00", 1)).unwrap();
    let mut bad = trade("t", Some("r"), "BUY", "10.00", ("0.00", "0.00"), 2, false);
    bad["payload"]["order"] = json!("different-order");
    let s = m.state();
    assert!(m.apply(&bad).is_err());
    assert_eq!(s, m.state());
}
#[test]
fn semantic_family_capacity_fails_atomically_before_receipt_installation() {
    let mut m = manager();
    for n in 0..1024 {
        m.apply(&cmd(&format!("c-{n}"),"CASH_CHANGE",n,json!({"schema_version":1,"change":format!("change-{n}"),"kind":"DEPOSIT","amount":"0.00","source_fact":format!("source-{n}")}))).unwrap();
    }
    let s = m.state();
    assert!(m.apply(&cmd("overflow","CASH_CHANGE",1024,json!({"schema_version":1,"change":"extra","kind":"DEPOSIT","amount":"0.00","source_fact":"extra-source"}))).is_err());
    assert_eq!(m.state(), s);
}

#[test]
fn observed_partial_fill_proves_submission_without_send_callback() {
    for restored in [false, true] {
        let mut m = manager();
        m.apply(&reserve("r", "600.00", 1)).unwrap();
        m.apply(&trade(
            "t",
            Some("r"),
            "BUY",
            "200.00",
            ("1.00", "0.00"),
            2,
            false,
        ))
        .unwrap();
        if restored {
            roundtrip(&mut m);
        }
        let s = m.state();
        assert!(m.apply(&release("not-sent", "NOT_SENT", 3)).is_err());
        assert_eq!(m.state(), s);
        assert_eq!(m.snapshot()["reserved"], "399.00");
        m.apply(&stage("cancel", "CANCEL_REQUESTED", 3)).unwrap();
        assert_eq!(m.reservation("r").unwrap()["cancel_pending"], true);
        roundtrip(&mut m);
    }
}
#[test]
fn signed_net_cash_effects_do_not_drop_valid_observed_fills() {
    let mut m = manager();
    m.apply(&reserve("r", "100.00", 1)).unwrap();
    m.apply(&trade(
        "buy",
        Some("r"),
        "BUY",
        "100.00",
        ("0.00", "0.00"),
        2,
        true,
    ))
    .unwrap();
    let mut sell = trade("sell", None, "SELL", "1.00", ("2.00", "0.00"), 3, true);
    sell["payload"]["market_value_delta"] = json!("-100.00");
    sell["payload"]["realized_pnl_delta"] = json!("-99.00");
    m.apply(&sell).unwrap();
    assert_eq!(m.snapshot()["cash"], "899.00");
    assert_eq!(m.snapshot()["realized_pnl"], "-99.00");
    roundtrip(&mut m);
}
#[test]
fn rebate_larger_than_purchase_still_consumes_gross_reserve() {
    let mut m = manager();
    m.apply(&reserve("r", "1.00", 1)).unwrap();
    m.apply(&trade(
        "rebate",
        Some("r"),
        "BUY",
        "1.00",
        ("0.00", "2.00"),
        2,
        true,
    ))
    .unwrap();
    assert_eq!(m.snapshot()["cash"], "1001.00");
    assert_eq!(m.snapshot()["fees"], "-2.00");
    assert_eq!(m.snapshot()["reserved"], "0.00");
    roundtrip(&mut m);
}
#[test]
fn negative_sale_net_never_creates_a_negative_settlement_claim() {
    let mut m = manager();
    m.apply(&reserve("r", "100.00", 1)).unwrap();
    m.apply(&trade(
        "buy",
        Some("r"),
        "BUY",
        "100.00",
        ("0.00", "0.00"),
        2,
        true,
    ))
    .unwrap();
    let mut sell = trade("sell", None, "SELL", "1.00", ("2.00", "0.00"), 3, true);
    sell["payload"]["market_value_delta"] = json!("-100.00");
    sell["payload"]["realized_pnl_delta"] = json!("-99.00");
    sell["payload"]["cash_withdrawable"] = json!(false);
    m.apply(&sell).unwrap();
    assert_eq!(m.snapshot()["cash"], "899.00");
    assert_eq!(m.snapshot()["unsettled"], "0.00");
    assert_eq!(m.snapshot()["withdrawable"], "899.00");
    roundtrip(&mut m);
}
#[test]
fn canonical_monetary_boundary_is_recoverable_or_rejected_at_admission() {
    let mut c = config();
    c["initial_cash"] = json!("1".repeat(126));
    let m = Manager::new(c.clone()).unwrap();
    let (b, h) = m.checkpoint().unwrap();
    let mut fresh = Manager::new(c).unwrap();
    fresh.restore(&b, &h).unwrap();
    assert_eq!(m.state(), fresh.state());
    let mut c = config();
    c["initial_cash"] = json!("1".repeat(127));
    assert!(Manager::new(c).is_err());
}
