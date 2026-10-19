use onlyalpha_risk::{Manager, Status, digest};
use serde_json::{Value, json};
fn cfg() -> Value {
    json!({"schema_version":1,"engine":"e","runtime":"r","account":"a","generation":"g","runtime_kind":"BACKTEST","admission_limits":{"schema_version":1,"commands":4096,"journal_bytes":8388608,"checkpoint_bytes":33554432,"reservations":1024},"currency":{"schema_version":1,"code":"USD","precision":2,"currency_type":"FIAT"},"clusters":{"c1":{"schema_version":1,"revision":"rev1","instruments":["BTCUSDT.BINANCE"],"rules":[]},"c2":{"schema_version":1,"revision":"rev2","instruments":["BTCUSDT.BINANCE"],"rules":[]}}})
}
fn cmd(n: u64, cluster: &str, op: &str, payload: Value) -> Value {
    json!({"schema_version":1,"engine":"e","runtime":"r","account":"a","generation":"g","cluster":cluster,"command_id":format!("cmd-{n}"),"causal": "a".repeat(64),"time":n,"runtime_sequence":n,"op":op,"payload":payload})
}
fn envelope(family: &str, cluster: &str, data: Value, n: u64) -> Value {
    json!({"schema_version":1,"family":family,"engine":"e","runtime":"r","account":"a","generation":"g","cluster":cluster,"instrument":"BTCUSDT.BINANCE","revision":if cluster=="c1"{"rev1"}else{"rev2"},"source_ref":format!("{family}-{cluster}-{n}"),"version":n,"as_of_sequence":n,"source_digest":"b".repeat(64),"data":data})
}
fn eval(n: u64, cluster: &str, request: &str) -> Value {
    let request = json!({"schema_version":1,"request_id":request,"instrument":"BTCUSDT.BINANCE","side":"BUY","effect":"OPEN","position_side":"LONG","position_mode":"NETTING","order_type":"LIMIT","quantity":"10","price":"10","notional":"100","fee":"1","cash_requirement":"100"});
    let mut c = cmd(
        n,
        cluster,
        "EVALUATE",
        json!({"schema_version":1,"request":request,"views":{}}),
    );
    let hash = digest(c["payload"]["request"].to_string().as_bytes());
    c["payload"]["views"] = json!({"schema_version":1,"account":envelope("ACCOUNT",cluster,json!({"schema_version":1,"status":"ACTIVE","cash":"1000"}),n),"ledger":envelope("LEDGER",cluster,json!({"schema_version":1,"status":"ACTIVE","cash":"1000"}),n),"position":envelope("POSITION",cluster,json!({"schema_version":1,"account_available":"100","allocation_available":"50","position_side":"LONG","position_mode":"NETTING"}),n),"market":envelope("MARKET",cluster,json!({"schema_version":1,"request_digest":hash,"verdict":"ACCEPT","code":"OK"}),n)});
    c
}
fn rebind(c: &mut Value) {
    c["payload"]["views"]["market"]["data"]["request_digest"] =
        json!(digest(c["payload"]["request"].to_string().as_bytes()));
}
fn decision(m: &mut Manager, c: &Value) -> Value {
    m.apply(c).unwrap().decision.unwrap()
}
fn reserve(n: u64, cluster: &str, request: &str, order: &str) -> Value {
    cmd(
        n,
        cluster,
        "RESERVE",
        json!({"schema_version":1,"request_id":request,"order":order}),
    )
}
fn staged(n: u64, op: &str, stage: &str) -> Value {
    cmd(
        n,
        "c1",
        op,
        json!({"schema_version":1,"order":"o1","stage":stage}),
    )
}
fn fill(n: u64, trade: &str, q: &str, a: &str, complete: bool) -> Value {
    cmd(
        n,
        "c1",
        "FILL",
        json!({"schema_version":1,"order":"o1","trade":trade,"source_ref":format!("source-{trade}"),"quantity":q,"notional":a,"final_fill":complete}),
    )
}
fn terminal(n: u64, outcome: &str) -> Value {
    cmd(
        n,
        "c1",
        "TERMINAL",
        json!({"schema_version":1,"order":"o1","outcome":outcome,"source_ref":format!("terminal-{outcome}")}),
    )
}
fn active() -> Manager {
    let mut m = Manager::new(cfg()).unwrap();
    assert_eq!(decision(&mut m, &eval(1, "c1", "r1"))["outcome"], "ACCEPT");
    m.apply(&reserve(2, "c1", "r1", "o1")).unwrap();
    m
}
fn assert_invalid(m: &mut Manager, c: &Value) {
    let before = m.state();
    assert!(m.apply(c).is_err());
    assert_eq!(m.state(), before);
}
#[test]
fn acceptance_does_not_create_order_or_reservation() {
    let mut m = Manager::new(cfg()).unwrap();
    let d = decision(&mut m, &eval(1, "c1", "r1"));
    assert_eq!(d["outcome"], "ACCEPT");
    assert_eq!(m.state()["reservations"], json!({}));
    assert_eq!(m.state()["audits"].as_array().unwrap().len(), 1);
}
#[test]
fn exact_command_and_request_replay_preserve_original_decision() {
    let mut m = Manager::new(cfg()).unwrap();
    let c = eval(1, "c1", "r1");
    let d = decision(&mut m, &c);
    assert_eq!(m.apply(&c).unwrap().status, Status::Duplicate);
    let mut repeated = c.clone();
    repeated["command_id"] = json!("ack");
    repeated["runtime_sequence"] = json!(2);
    repeated["time"] = json!(2);
    assert_eq!(decision(&mut m, &repeated), d);
    assert_eq!(m.state()["audits"].as_array().unwrap().len(), 1);
    let mut bad = eval(3, "c1", "r1");
    bad["payload"]["request"]["quantity"] = json!("11");
    rebind(&mut bad);
    assert_invalid(&mut m, &bad);
}
#[test]
fn equivalent_decimals_converge() {
    let mut a = Manager::new(cfg()).unwrap();
    let mut b = Manager::new(cfg()).unwrap();
    let c = eval(1, "c1", "r1");
    let mut d = c.clone();
    d["payload"]["request"]["quantity"] = json!("10.0");
    d["payload"]["request"]["notional"] = json!("100.00"); /* market binds normalized request */
    assert_eq!(decision(&mut a, &c), decision(&mut b, &d));
    assert_eq!(a.state(), b.state());
}
#[test]
fn fees_and_unknown_cost_are_not_free_cash() {
    for (cash, fee, outcome) in [
        ("100", "1", "REJECT"),
        ("101", "1", "ACCEPT"),
        ("1000", "unknown", "ERROR"),
    ] {
        let mut m = Manager::new(cfg()).unwrap();
        let mut c = eval(1, "c1", "r1");
        c["payload"]["views"]["account"]["data"]["cash"] = json!(cash);
        c["payload"]["request"]["fee"] = if fee == "unknown" {
            Value::Null
        } else {
            json!(fee)
        };
        rebind(&mut c);
        assert_eq!(decision(&mut m, &c)["outcome"], outcome);
        assert_eq!(m.state()["reservations"], json!({}));
    }
}
#[test]
fn missing_and_stale_views_fail_closed() {
    for name in ["account", "ledger", "position", "market"] {
        let mut m = active();
        let mut c = eval(3, "c1", "r2");
        c["payload"]["views"][name] = Value::Null;
        assert_eq!(decision(&mut m, &c)["outcome"], "ERROR");
    }
    let mut m = active();
    m.apply(&fill(3, "t1", "5", "50", false)).unwrap();
    let mut c = eval(4, "c1", "r2");
    c["payload"]["views"]["account"]["as_of_sequence"] = json!(2);
    assert_eq!(decision(&mut m, &c)["outcome"], "ERROR");
}
#[test]
fn wrong_context_or_owner_never_certifies_capacity() {
    for (field, value) in [
        ("runtime", "other"),
        ("account", "other"),
        ("generation", "other"),
        ("cluster", "c2"),
        ("instrument", "ETHUSDT.BINANCE"),
        ("revision", "other"),
        ("family", "POSITION"),
    ] {
        let mut m = Manager::new(cfg()).unwrap();
        let mut c = eval(1, "c1", "r1");
        c["payload"]["views"]["account"][field] = json!(value);
        assert_invalid(&mut m, &c);
    }
}
#[test]
fn complete_other_market_intent_cannot_authorize_request() {
    let mut m = Manager::new(cfg()).unwrap();
    let mut c = eval(1, "c1", "r1");
    c["payload"]["views"]["market"]["data"]["request_digest"] = json!("f".repeat(64));
    assert_invalid(&mut m, &c);
}
#[test]
fn successive_cash_holds_include_other_clusters() {
    let mut m = active();
    let mut c = eval(3, "c2", "r2");
    c["payload"]["views"]["account"]["data"]["cash"] = json!("150");
    let d = decision(&mut m, &c);
    assert_eq!(d["outcome"], "REJECT");
    assert_eq!(m.state()["reservations"].as_object().unwrap().len(), 1);
}
#[test]
fn unconsumed_acceptance_cannot_cross_intervening_reservation_epoch() {
    let mut m = Manager::new(cfg()).unwrap();
    decision(&mut m, &eval(1, "c1", "r1"));
    decision(&mut m, &eval(2, "c2", "r2"));
    m.apply(&reserve(3, "c1", "r1", "o1")).unwrap();
    assert_invalid(&mut m, &reserve(4, "c2", "r2", "o2"));
}
#[test]
fn accepted_request_has_one_exact_order() {
    let mut m = active();
    assert_invalid(&mut m, &reserve(3, "c1", "r1", "other"));
    assert_invalid(&mut m, &reserve(3, "c2", "r1", "o1"));
    assert_invalid(&mut m, &reserve(3, "c1", "missing", "o2"));
}
#[test]
fn partial_fill_preserves_remaining_exposure_and_final_releases_improvement() {
    let mut m = active();
    m.apply(&fill(3, "t1", "4", "36", false)).unwrap();
    let s = m.state();
    let h = &s["reservations"]["o1"];
    assert_eq!(h["remaining_quantity"], "6");
    assert_eq!(h["remaining_notional"], "64.00");
    assert_eq!(h["state"], "ACTIVE");
    m.apply(&fill(4, "t2", "6", "54", true)).unwrap();
    let s = m.state();
    let h = &s["reservations"]["o1"];
    assert_eq!(h["state"], "CONSUMED");
    assert_eq!(h["consumed_notional"], "90.00");
    assert_eq!(h["released_notional"], "10.00");
    assert_eq!(h["remaining_notional"], "0.00");
    assert_eq!(s["active_count"], 0);
}
#[test]
fn overfill_and_false_terminality_are_not_clipped() {
    for c in [
        fill(3, "t1", "11", "100", true),
        fill(3, "t1", "1", "101", false),
        fill(3, "t1", "5", "50", true),
        fill(3, "t1", "10", "100", false),
    ] {
        let mut m = active();
        assert_invalid(&mut m, &c);
    }
}
#[test]
fn unknown_and_cancel_pending_retain_holds_and_allow_fill() {
    let mut m = active();
    m.apply(&staged(3, "STAGE", "UNKNOWN")).unwrap();
    m.apply(&staged(4, "STAGE", "CANCEL_PENDING")).unwrap();
    m.apply(&staged(5, "STAGE", "ACKNOWLEDGED")).unwrap();
    assert_eq!(m.state()["reservations"]["o1"]["cancel_pending"], true);
    assert_invalid(&mut m, &terminal(6, "NOT_SENT"));
    m.apply(&fill(6, "t1", "5", "50", false)).unwrap();
    m.apply(&terminal(7, "CANCELLED")).unwrap();
    let s = m.state();
    assert_eq!(s["active_count"], 0);
    assert_eq!(s["reservations"]["o1"]["released_quantity"], "5");
    assert_eq!(s["reservations"]["o1"]["consumed_quantity"], "5");
}
#[test]
fn terminal_variants_release_only_once() {
    for outcome in ["CANCELLED", "REJECTED", "FAILED", "EXPIRED", "NOT_SENT"] {
        let mut m = active();
        let c = terminal(3, outcome);
        m.apply(&c).unwrap();
        assert_eq!(m.apply(&c).unwrap().status, Status::Duplicate);
        assert_eq!(m.state()["active_count"], 0);
        assert_eq!(
            m.state()["reservations"]["o1"]["released_notional"],
            "100.00"
        );
        assert_invalid(&mut m, &fill(4, "late", "1", "10", false));
    }
}
#[test]
fn fill_alias_conflict_is_atomic_across_orders_and_restore() {
    let mut m = active();
    let c = fill(3, "t1", "5", "50", false);
    m.apply(&c).unwrap();
    let mut repeat = c.clone();
    repeat["command_id"] = json!("ack");
    repeat["runtime_sequence"] = json!(4);
    repeat["time"] = json!(4);
    assert_eq!(m.apply(&repeat).unwrap().status, Status::Duplicate);
    let (b, h) = m.checkpoint().unwrap();
    let mut restored = Manager::new(cfg()).unwrap();
    restored.restore(&b, &h).unwrap();
    let mut bad = fill(5, "t1", "4", "40", false);
    bad["payload"]["source_ref"] = json!("source-t1");
    assert_invalid(&mut restored, &bad);
    assert_eq!(
        restored.state()["reservations"]["o1"]["consumed_quantity"],
        "5"
    );
}
#[test]
fn kill_switch_blocks_open_but_proven_close_and_observation_continue() {
    let mut m = active();
    m.apply(&cmd(
        3,
        "c1",
        "KILL",
        json!({"schema_version":1,"scope":"RUNTIME","active":true}),
    ))
    .unwrap();
    assert_eq!(decision(&mut m, &eval(4, "c1", "r2"))["outcome"], "REJECT");
    let mut c = eval(5, "c1", "close");
    c["payload"]["request"]["side"] = json!("SELL");
    c["payload"]["request"]["effect"] = json!("CLOSE");
    c["payload"]["views"]["account"] = Value::Null;
    c["payload"]["views"]["ledger"] = Value::Null;
    rebind(&mut c);
    assert_eq!(decision(&mut m, &c)["outcome"], "ACCEPT");
    m.apply(&staged(6, "STAGE", "UNKNOWN")).unwrap();
    m.apply(&terminal(7, "CANCELLED")).unwrap();
}
#[test]
fn close_requires_real_position_and_cluster_capacity() {
    let mut m = Manager::new(cfg()).unwrap();
    let mut c = eval(1, "c1", "close");
    c["payload"]["request"]["side"] = json!("SELL");
    c["payload"]["request"]["effect"] = json!("CLOSE");
    c["payload"]["views"]["position"]["data"]["allocation_available"] = json!("5");
    rebind(&mut c);
    assert_eq!(decision(&mut m, &c)["outcome"], "REJECT");
}
#[test]
fn unknown_effect_cannot_claim_risk_reduction() {
    let mut m = Manager::new(cfg()).unwrap();
    let mut c = eval(1, "c1", "r1");
    c["payload"]["request"]["effect"] = json!("AUTO");
    rebind(&mut c);
    assert_eq!(decision(&mut m, &c)["outcome"], "ERROR");
}
fn rule(id: &str, scope: &str, order: u64, mode: &str, kind: &str, limit: &str) -> Value {
    json!({"schema_version":1,"id":id,"scope":scope,"order":order,"mode":mode,"kind":kind,"limit":limit})
}
#[test]
fn rules_sort_by_scope_order_id_and_observing_does_not_stop() {
    let mut c = cfg();
    c["clusters"]["c1"]["rules"] = json!([
        rule("z", "CLUSTER", 1, "ENFORCING", "MAX_ORDER_QUANTITY", "5"),
        rule("a", "RUNTIME", 99, "OBSERVING", "MAX_ORDER_QUANTITY", "1"),
        rule("b", "CLUSTER", 1, "ENFORCING", "MAX_ORDER_QUANTITY", "4")
    ]);
    let mut m = Manager::new(c).unwrap();
    let d = decision(&mut m, &eval(1, "c1", "r1"));
    assert_eq!(d["outcome"], "REJECT");
    assert_eq!(d["code"], "MAX_ORDER_QUANTITY");
    assert_eq!(d["rule"], "b");
    assert_eq!(d["observations"], json!(["a"]));
    let e = d["evaluated"].as_array().unwrap();
    assert!(e.iter().position(|x| x == "a").unwrap() < e.iter().position(|x| x == "b").unwrap());
    assert!(!e.contains(&json!("z")));
}
#[test]
fn invalid_profile_cannot_replace_mandatory_or_duplicate_rules() {
    for rules in [
        json!([rule(
            "system.kill_switch",
            "SYSTEM",
            1,
            "OBSERVING",
            "MAX_ORDER_QUANTITY",
            "1"
        )]),
        json!([
            rule("x", "CLUSTER", 1, "ENFORCING", "MAX_ORDER_QUANTITY", "1"),
            rule("x", "CLUSTER", 2, "ENFORCING", "MAX_ORDER_QUANTITY", "2")
        ]),
    ] {
        let mut c = cfg();
        c["clusters"]["c1"]["rules"] = rules;
        assert!(Manager::new(c).is_err());
    }
}
#[test]
fn recovery_is_atomic_and_covers_decisions_holds_controls_and_aliases() {
    let mut m = active();
    m.apply(&fill(3, "t1", "4", "36", false)).unwrap();
    m.apply(&staged(4, "STAGE", "UNKNOWN")).unwrap();
    let (bytes, h) = m.checkpoint().unwrap();
    let mut b = Manager::new(cfg()).unwrap();
    b.restore(&bytes, &h).unwrap();
    assert_eq!(m.state(), b.state());
    let c = terminal(5, "CANCELLED");
    m.apply(&c).unwrap();
    b.apply(&c).unwrap();
    assert_eq!(m.state(), b.state());
    let before = b.state();
    for field in ["state", "config", "journal"] {
        let mut v: Value = serde_json::from_slice(&bytes).unwrap();
        v[field] = json!({});
        let corrupt = v.to_string().into_bytes();
        assert!(b.restore(&corrupt, &digest(&corrupt)).is_err());
        assert_eq!(b.state(), before);
    }
    assert!(b.restore(&bytes, &"0".repeat(64)).is_err());
}
#[test]
fn source_identity_conflict_and_sequence_regression_leave_state_unchanged() {
    let mut m = Manager::new(cfg()).unwrap();
    let c = eval(1, "c1", "r1");
    decision(&mut m, &c);
    let mut b = eval(2, "c1", "r2");
    b["payload"]["views"]["account"] = c["payload"]["views"]["account"].clone();
    b["payload"]["views"]["account"]["data"]["cash"] = json!("2000");
    assert_invalid(&mut m, &b);
    assert_invalid(&mut m, &eval(1, "c2", "r2"));
}
#[test]
fn input_bounds_and_closed_fields_are_enforced() {
    let mut m = Manager::new(cfg()).unwrap();
    let mut c = eval(1, "c1", "r1");
    c["payload"]["request"]["quantity"] = json!("1e100000000");
    assert_invalid(&mut m, &c);
    let mut c = eval(1, "c1", "r1");
    c["secret_fallback"] = json!(true);
    assert_invalid(&mut m, &c);
    let mut c = cfg();
    c["runtime_kind"] = json!("RESEARCH");
    assert!(Manager::new(c).is_err());
}

#[test]
fn common_vector_outputs() {
    let mut outputs = vec![];
    for line in include_str!("../../../../test-data/risk/decisions-v1.jsonl").lines() {
        let c: Value = serde_json::from_str(line).unwrap();
        let mut config = cfg();
        config["clusters"]["c1"]["rules"] = json!([rule(
            "quantity",
            "CLUSTER",
            100,
            c["mode"].as_str().unwrap(),
            "MAX_ORDER_QUANTITY",
            c["limit"].as_str().unwrap()
        )]);
        let mut m = Manager::new(config).unwrap();
        let mut e = eval(1, "c1", c["case"].as_str().unwrap());
        e["payload"]["request"]["quantity"] = c["quantity"].clone();
        rebind(&mut e);
        let d = decision(&mut m, &e);
        let actual = json!({"case":c["case"],"outcome":d["outcome"],"observations":d["observations"].as_array().unwrap().len()});
        assert_eq!(
            actual,
            json!({"case":c["case"],"outcome":c["outcome"],"observations":c["observations"]})
        );
        outputs.push(actual);
    }
    for line in include_str!("../../../../test-data/risk/reservations-v1.jsonl").lines() {
        let c: Value = serde_json::from_str(line).unwrap();
        let mut m = active();
        for (n, f) in c["fills"].as_array().unwrap().iter().enumerate() {
            m.apply(&fill(
                n as u64 + 3,
                &format!("t{n}"),
                f["quantity"].as_str().unwrap(),
                f["notional"].as_str().unwrap(),
                f["complete"].as_bool().unwrap(),
            ))
            .unwrap();
        }
        if c["release"] == true {
            m.apply(&terminal(10, "CANCELLED")).unwrap();
        }
        let s = m.state();
        let h = &s["reservations"]["o1"];
        let mut actual = json!({"case":c["case"]});
        for (k, v) in c["expected"].as_object().unwrap() {
            assert_eq!(&h[k], v);
            actual[k] = h[k].clone();
        }
        outputs.push(actual);
    }
    println!("RISK_VECTOR_OUTPUT {}", json!(outputs));
}

#[test]
fn explicit_cash_requirement_is_not_assumed_equal_to_notional() {
    let mut m = Manager::new(cfg()).unwrap();
    let mut c = eval(1, "c1", "margin");
    c["payload"]["request"]["notional"] = json!("10000");
    c["payload"]["request"]["cash_requirement"] = json!("100");
    rebind(&mut c);
    assert_eq!(decision(&mut m, &c)["outcome"], "ACCEPT");
    m.apply(&reserve(2, "c1", "margin", "o1")).unwrap();
    assert_eq!(m.state()["reservations"]["o1"]["cash_hold"], "101.00");
}

#[test]
fn scoped_snapshot_does_not_mix_cluster_exposure() {
    let mut m = active();
    decision(&mut m, &eval(3, "c2", "r2"));
    m.apply(&reserve(4, "c2", "r2", "o2")).unwrap();
    let a = m.snapshot("c1").unwrap();
    let b = m.snapshot("c2").unwrap();
    assert_eq!(a["active_count"], 1);
    assert_eq!(b["active_count"], 1);
    assert_eq!(a["reserved_notional"], "100.00");
    assert_eq!(a["cluster"], "c1");
    assert!(m.snapshot("unknown").is_err());
}
#[test]
fn profile_semantic_order_and_decimal_spelling_converge() {
    let mut a = cfg();
    a["clusters"]["c1"]["rules"] = json!([
        rule("b", "CLUSTER", 2, "ENFORCING", "MAX_ORDER_NOTIONAL", "1000"),
        rule("a", "CLUSTER", 1, "ENFORCING", "MAX_ORDER_QUANTITY", "20")
    ]);
    let mut b = a.clone();
    b["clusters"]["c1"]["rules"] = json!([
        rule("a", "CLUSTER", 1, "ENFORCING", "MAX_ORDER_QUANTITY", "20.0"),
        rule(
            "b",
            "CLUSTER",
            2,
            "ENFORCING",
            "MAX_ORDER_NOTIONAL",
            "1000.00"
        )
    ]);
    let mut x = Manager::new(a).unwrap();
    let mut y = Manager::new(b).unwrap();
    assert_eq!(
        decision(&mut x, &eval(1, "c1", "r1")),
        decision(&mut y, &eval(1, "c1", "r1"))
    );
    assert_eq!(x.checkpoint().unwrap(), y.checkpoint().unwrap());
}

#[test]
fn repeated_reservation_fact_is_idempotent_after_other_activity() {
    let mut m = active();
    decision(&mut m, &eval(3, "c2", "r2"));
    let before = m.snapshot("c1").unwrap();
    let o = m.apply(&reserve(4, "c1", "r1", "o1")).unwrap();
    assert_eq!(o.status, Status::Duplicate);
    let after = m.snapshot("c1").unwrap();
    assert_eq!(before["admission_epoch"], after["admission_epoch"]);
    assert_eq!(after["active_count"], 1);
    let mut bad = reserve(5, "c1", "r1", "other");
    assert_invalid(&mut m, &bad);
    bad["cluster"] = json!("c2");
    assert_invalid(&mut m, &bad);
}
#[test]
fn source_leaf_and_whole_context_mutations_never_create_holds() {
    for field in ["engine", "runtime", "account", "generation", "cluster"] {
        let mut m = Manager::new(cfg()).unwrap();
        let mut c = eval(1, "c1", "r1");
        c[field] = json!("other");
        assert_invalid(&mut m, &c);
        assert_eq!(m.state()["reservations"], json!({}));
    }
    let mut m = Manager::new(cfg()).unwrap();
    let mut c = eval(1, "c1", "r1");
    c["payload"]["views"]["market"]["data"]["verdict"] = json!("ERROR");
    assert_eq!(decision(&mut m, &c)["outcome"], "ERROR");
}
#[test]
fn explicit_max_runtime_sequence_is_valid_without_hidden_increment() {
    let mut m = Manager::new(cfg()).unwrap();
    let c = eval(u64::MAX, "c1", "r1");
    assert_eq!(decision(&mut m, &c)["outcome"], "ACCEPT");
    let (b, h) = m.checkpoint().unwrap();
    let mut other = Manager::new(cfg()).unwrap();
    other.restore(&b, &h).unwrap();
    assert_eq!(m.state(), other.state());
}

#[test]
fn malformed_records_return_errors_without_panicking_or_mutating() {
    let base = eval(1, "c1", "r1");
    for path in [
        vec!["payload"],
        vec!["payload", "request"],
        vec!["payload", "views"],
        vec!["payload", "views", "account"],
        vec!["payload", "views", "account", "data"],
    ] {
        for wrong in [json!(7), json!([]), json!(true)] {
            let mut c = base.clone();
            let mut slot = &mut c;
            for part in &path {
                slot = &mut slot[*part];
            }
            *slot = wrong;
            let mut m = Manager::new(cfg()).unwrap();
            let before = m.state();
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| m.apply(&c)));
            assert!(result.is_ok(), "panic on {path:?}");
            assert!(result.unwrap().is_err());
            assert_eq!(m.state(), before);
        }
    }
}
#[test]
fn position_proof_must_bind_exact_position_direction_and_mode() {
    for (field, value) in [("position_side", "SHORT"), ("position_mode", "HEDGING")] {
        let mut c = eval(1, "c1", "close");
        c["payload"]["request"]["effect"] = json!("CLOSE");
        c["payload"]["request"]["side"] = json!(if field == "position_side" {
            "BUY"
        } else {
            "SELL"
        });
        c["payload"]["request"][field] = json!(value);
        rebind(&mut c);
        let mut m = Manager::new(cfg()).unwrap();
        assert_invalid(&mut m, &c);
    }
}

#[test]
fn full_journal_never_blocks_existing_order_safety() {
    for (dimension, limit) in [
        ("commands", 4),
        ("journal_bytes", 3500),
        ("checkpoint_bytes", 12000),
    ] {
        let mut config = cfg();
        config["admission_limits"][dimension] = json!(limit);
        let mut m = Manager::new(config.clone()).unwrap();
        decision(&mut m, &eval(1, "c1", "r1"));
        m.apply(&reserve(2, "c1", "r1", "o1")).unwrap();
        for n in 3..=32 {
            m.apply(&cmd(
                n,
                "c1",
                "KILL",
                json!({"schema_version":1,"scope":"RUNTIME","active":false}),
            ))
            .unwrap();
        }
        let (b, _) = m.checkpoint().unwrap();
        let checkpoint: Value = serde_json::from_slice(&b).unwrap();
        let used = match dimension {
            "commands" => checkpoint["journal"].as_array().unwrap().len(),
            "journal_bytes" => checkpoint["journal"].to_string().len(),
            _ => b.len(),
        };
        assert!(used > limit, "boundary not reached: {dimension}");
        assert_invalid(&mut m, &eval(33, "c1", "new-open"));
        m.apply(&staged(33, "STAGE", "UNKNOWN")).unwrap();
        m.apply(&staged(34, "STAGE", "CANCEL_PENDING")).unwrap();
        m.apply(&fill(35, "t1", "4", "36", false)).unwrap();
        m.apply(&cmd(
            36,
            "c1",
            "KILL",
            json!({"schema_version":1,"scope":"RUNTIME","active":true}),
        ))
        .unwrap();
        let (b, h) = m.checkpoint().unwrap();
        let mut restored = Manager::new(config).unwrap();
        restored.restore(&b, &h).unwrap();
        assert_eq!(m.state(), restored.state());
        restored.apply(&terminal(37, "CANCELLED")).unwrap();
        assert_eq!(restored.state()["active_count"], 0);
        let mut close = eval(38, "c1", "close");
        close["payload"]["request"]["effect"] = json!("CLOSE");
        close["payload"]["request"]["side"] = json!("SELL");
        close["payload"]["views"]["account"] = Value::Null;
        close["payload"]["views"]["ledger"] = Value::Null;
        rebind(&mut close);
        assert_eq!(decision(&mut restored, &close)["outcome"], "ACCEPT");
        restored
            .apply(&reserve(39, "c1", "close", "close-order"))
            .unwrap();
        assert_eq!(restored.state()["active_count"], 1);
        let (b, h) = restored.checkpoint().unwrap();
        let mut fresh = Manager::new(cfg_with_limit(dimension, limit)).unwrap();
        fresh.restore(&b, &h).unwrap();
        assert_eq!(fresh.state(), restored.state());
    }
}
fn cfg_with_limit(dimension: &str, limit: usize) -> Value {
    let mut config = cfg();
    config["admission_limits"][dimension] = json!(limit);
    config
}
#[test]
fn admission_limits_are_explicit_immutable_policy() {
    for value in [0, 4097] {
        let mut c = cfg();
        c["admission_limits"]["commands"] = json!(value);
        assert!(Manager::new(c).is_err());
    }
    let m = Manager::new(cfg()).unwrap();
    let (b, _) = m.checkpoint().unwrap();
    let mut other = Manager::new(cfg_with_limit("commands", 4)).unwrap();
    assert!(other.restore(&b, &digest(&b)).is_err());
}

#[test]
fn exhausted_order_inventory_blocks_only_new_exposure() {
    let config = cfg_with_limit("reservations", 1);
    let mut m = Manager::new(config.clone()).unwrap();
    decision(&mut m, &eval(1, "c1", "r1"));
    m.apply(&reserve(2, "c1", "r1", "o1")).unwrap();
    decision(&mut m, &eval(3, "c1", "new-open"));
    assert_invalid(&mut m, &reserve(4, "c1", "new-open", "open-2"));
    let mut c = eval(4, "c1", "close");
    c["payload"]["request"]["effect"] = json!("CLOSE");
    c["payload"]["request"]["side"] = json!("SELL");
    rebind(&mut c);
    assert_eq!(decision(&mut m, &c)["outcome"], "ACCEPT");
    m.apply(&reserve(5, "c1", "close", "close-order")).unwrap();
    assert_eq!(m.state()["active_count"], 2);
    m.apply(&terminal(6, "CANCELLED")).unwrap();
    let mut f = fill(7, "close-trade", "10", "100", true);
    f["payload"]["order"] = json!("close-order");
    m.apply(&f).unwrap();
    assert_eq!(m.state()["active_count"], 0);
    let (b, h) = m.checkpoint().unwrap();
    let mut restored = Manager::new(config).unwrap();
    restored.restore(&b, &h).unwrap();
    assert_eq!(restored.state(), m.state());
}

#[test]
fn normalized_financial_boundary_remains_readable_in_fresh_recovery() {
    for value in [format!("{}e64", "1".repeat(64)), "9".repeat(128)] {
        let mut c = cfg();
        c["clusters"]["c1"]["rules"] = json!([rule(
            "limit",
            "CLUSTER",
            100,
            "ENFORCING",
            "MAX_ORDER_NOTIONAL",
            &value
        )]);
        let owner = Manager::new(c.clone()).unwrap();
        let (bytes, h) = owner.checkpoint().unwrap();
        let mut restored = Manager::new(c).unwrap();
        restored.restore(&bytes, &h).unwrap();
        assert_eq!(owner.state(), restored.state());
    }
    let mut c = cfg();
    let expanded = format!("{}e64", "1".repeat(65));
    c["clusters"]["c1"]["rules"] = json!([rule(
        "limit",
        "CLUSTER",
        100,
        "ENFORCING",
        "MAX_ORDER_NOTIONAL",
        &expanded
    )]);
    assert!(
        Manager::new(c).is_err(),
        "canonical coefficient exceeds its own reader bound"
    );
}
