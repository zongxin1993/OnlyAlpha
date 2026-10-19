use onlyalpha_position::{Manager, Status, digest};
use serde_json::{Value, json};
fn config() -> Value {
    json!({"schema_version":1,"engine":"engine","runtime":"runtime","account":"account","gateway":"gateway","generation":"generation","currency":{"schema_version":1,"code":"USD","precision":2,"currency_type":"FIAT"},"clusters":["a","b"],"instruments":[{"schema_version":1,"id":"BTCUSDT.BINANCE","price_precision":2,"quantity_precision":0,"multiplier":"1"}]})
}
fn manager() -> Manager {
    Manager::new(config()).unwrap()
}
fn cmd(id: &str, op: &str, time: u64, payload: Value) -> Value {
    json!({"schema_version":1,"engine":"engine","runtime":"runtime","account":"account","gateway":"gateway","generation":"generation","command_id":id,"cause":"a".repeat(64),"time":time,"op":op,"payload":payload})
}
fn trade(id: &str, c: Option<&str>, side: &str, p: &str, q: &str, n: u64) -> Value {
    cmd(
        id,
        "TRADE",
        n,
        json!({"schema_version":1,"instrument":"BTCUSDT.BINANCE","cluster":c,"order":format!("order-{}",c.unwrap_or("external")),"trade":id,"venue_trade":format!("v-{id}"),"execution":format!("x-{id}"),"sequence":n,"side":side,"position_side":"LONG","position_mode":"NETTING","price":p,"quantity":q,"fee":"0.00","bucket":"SETTLED","terminal_fill":false}),
    )
}
fn reserve(id: &str, c: &str, q: &str, t: u64) -> Value {
    cmd(
        id,
        "RESERVE",
        t,
        json!({"schema_version":1,"instrument":"BTCUSDT.BINANCE","cluster":c,"order":format!("order-{c}"),"quantity":q}),
    )
}
fn close(id: &str, c: &str, p: &str, q: &str, t: u64, terminal: bool) -> Value {
    let mut v = trade(id, Some(c), "SELL", p, q, t);
    v["payload"]["terminal_fill"] = json!(terminal);
    v
}
fn roundtrip(m: &mut Manager) {
    let (b, h) = m.checkpoint().unwrap();
    let mut f = manager();
    f.restore(&b, &h).unwrap();
    assert_eq!(m.state(), f.state());
    *m = f;
}
#[test]
fn mixed_cluster_costs_close_attribution_and_cycles() {
    let mut m = manager();
    m.apply(&trade("t1", Some("a"), "BUY", "10.00", "2", 1))
        .unwrap();
    m.apply(&trade("t2", Some("b"), "BUY", "20.00", "2", 2))
        .unwrap();
    assert_eq!(m.account("BTCUSDT.BINANCE").unwrap()["cost"], "60");
    m.apply(&reserve("r1", "a", "2", 3)).unwrap();
    let o = m.apply(&close("t3", "a", "15.00", "1", 4, false)).unwrap();
    assert_eq!(o.status, Status::Applied);
    assert_eq!(o.fact.unwrap()["realized_pnl"], "5.00");
    assert_eq!(m.account("BTCUSDT.BINANCE").unwrap()["cost"], "50");
    assert_eq!(m.cluster("b", "BTCUSDT.BINANCE").unwrap()["cost"], "40");
    roundtrip(&mut m);
    m.apply(&close("t4", "a", "15.00", "1", 5, true)).unwrap();
    assert_eq!(m.account("BTCUSDT.BINANCE").unwrap()["cost"], "40");
    let old = m.cluster("a", "BTCUSDT.BINANCE").unwrap()["id"].clone();
    m.apply(&trade("t5", Some("a"), "BUY", "10.00", "1", 6))
        .unwrap();
    assert_ne!(old, m.cluster("a", "BTCUSDT.BINANCE").unwrap()["id"]);
}
#[test]
fn invalid_close_and_conflicting_receipts_never_partially_mutate() {
    let mut m = manager();
    let t = trade("t1", Some("a"), "BUY", "10.00", "2", 1);
    m.apply(&t).unwrap();
    let s = m.state();
    assert_eq!(m.apply(&t).unwrap().status, Status::Duplicate);
    let mut bad = t.clone();
    bad["payload"]["quantity"] = json!("3");
    assert_eq!(m.apply(&bad).unwrap().status, Status::Conflict);
    assert_eq!(m.state(), s);
    assert!(m.apply(&close("t2", "b", "11.00", "1", 2, true)).is_err());
    assert_eq!(m.state(), s);
    roundtrip(&mut m);
    assert_eq!(m.apply(&t).unwrap().status, Status::Duplicate);
}
#[test]
fn external_alias_conflicts_and_cross_context_are_rejected() {
    let mut m = manager();
    let t = trade("t1", Some("a"), "BUY", "10.00", "2", 1);
    m.apply(&t).unwrap();
    let mut bad = trade("t2", Some("b"), "BUY", "11.00", "1", 2);
    bad["payload"]["venue_trade"] = t["payload"]["venue_trade"].clone();
    assert_eq!(m.apply(&bad).unwrap().status, Status::Conflict);
    let s = m.state();
    bad["runtime"] = json!("other");
    assert!(m.apply(&bad).is_err());
    assert_eq!(s, m.state());
}
#[test]
fn reservation_partial_consumption_and_excess_terminal_release() {
    let mut m = manager();
    m.apply(&trade("t1", Some("a"), "BUY", "10.00", "5", 1))
        .unwrap();
    m.apply(&reserve("r1", "a", "4", 2)).unwrap();
    m.apply(&close("t2", "a", "12.00", "1", 3, false)).unwrap();
    assert_eq!(m.reservation("order-a").unwrap()["remaining"], "3");
    roundtrip(&mut m);
    m.apply(&close("t3", "a", "12.00", "1", 4, true)).unwrap();
    let r = m.reservation("order-a").unwrap();
    assert_eq!(r["remaining"], "0");
    assert_eq!(r["consumed"], "2");
    assert_eq!(r["released"], "2");
}
#[test]
fn all_recovery_mutations_are_atomic() {
    let mut m = manager();
    m.apply(&trade("t1", Some("a"), "BUY", "10.00", "2", 1))
        .unwrap();
    let s = m.state();
    let (b, h) = m.checkpoint().unwrap();
    assert!(m.restore(&b, &"0".repeat(64)).is_err());
    let mut v: Value = serde_json::from_slice(&b).unwrap();
    v["state"]["sequence"] = json!(999);
    let bad = serde_json::to_vec(&v).unwrap();
    assert!(m.restore(&bad, &digest(&bad)).is_err());
    assert_eq!(m.state(), s);
    let mut f = manager();
    f.restore(&b, &h).unwrap();
    assert_eq!(f.state(), s);
}

fn stage(id: &str, s: &str, t: u64) -> Value {
    cmd(
        id,
        "STAGE",
        t,
        json!({"schema_version":1,"order":"order-a","cluster":"a","stage":s}),
    )
}
fn broker(id: &str, total: &str, settled: &str, avail: &str, frozen: &str, n: u64) -> Value {
    cmd(
        id,
        "BROKER",
        n,
        json!({"schema_version":1,"instrument":"BTCUSDT.BINANCE","snapshot_id":id,"sequence":n,"position_side":"LONG","total":total,"settled":settled,"unsettled":"0","available":avail,"frozen":frozen,"average":"10.00","quality":"VERIFIED"}),
    )
}
#[test]
fn acknowledged_hold_is_not_deducted_twice_and_cancel_waits_for_confirmation() {
    let mut m = manager();
    m.apply(&trade("t1", Some("a"), "BUY", "10.00", "10", 1))
        .unwrap();
    m.apply(&reserve("r1", "a", "4", 2)).unwrap();
    assert_eq!(m.account("BTCUSDT.BINANCE").unwrap()["available"], "6");
    m.apply(&stage("s1", "SENT_TO_BROKER", 3)).unwrap();
    m.apply(&stage("s2", "BROKER_ACKNOWLEDGED", 4)).unwrap();
    m.apply(&broker("b1", "10", "10", "6", "4", 5)).unwrap();
    assert_eq!(m.account("BTCUSDT.BINANCE").unwrap()["available"], "6");
    let release = cmd(
        "release",
        "RELEASE",
        6,
        json!({"schema_version":1,"order":"order-a","cluster":"a","broker_confirmed":false}),
    );
    m.apply(&release).unwrap();
    assert_eq!(m.reservation("order-a").unwrap()["remaining"], "4");
    assert_eq!(
        m.reservation("order-a").unwrap()["stage"],
        "RELEASE_PENDING"
    );
    roundtrip(&mut m);
    let mut confirm = release;
    confirm["command_id"] = json!("confirmed");
    confirm["time"] = json!(7);
    confirm["payload"]["broker_confirmed"] = json!(true);
    m.apply(&confirm).unwrap();
    assert_eq!(m.reservation("order-a").unwrap()["released"], "4");
}
#[test]
fn reservations_reject_cross_cluster_and_invalid_stage_atomically() {
    let mut m = manager();
    m.apply(&trade("t1", Some("a"), "BUY", "10.00", "3", 1))
        .unwrap();
    let s = m.state();
    assert!(m.apply(&reserve("r1", "b", "1", 2)).is_err());
    assert_eq!(m.state(), s);
    m.apply(&reserve("r2", "a", "2", 3)).unwrap();
    let s = m.state();
    assert!(m.apply(&stage("s1", "BROKER_ACKNOWLEDGED", 4)).is_err());
    assert_eq!(s, m.state());
}
#[test]
fn explicit_settlement_and_interval_restrictions_control_new_reservations() {
    let mut m = manager();
    let mut t = trade("t1", Some("a"), "BUY", "10.00", "4", 1);
    t["payload"]["bucket"] = json!("UNSETTLED");
    m.apply(&t).unwrap();
    assert!(m.apply(&reserve("r1", "a", "1", 2)).is_err());
    let settle = cmd(
        "settle",
        "SETTLE",
        3,
        json!({"schema_version":1,"instrument":"BTCUSDT.BINANCE","trading_day":"2026-10-19","source":"calendar-fact","buckets":[{"schema_version":1,"cluster":"a","quantity":"4"}]}),
    );
    m.apply(&settle).unwrap();
    let restriction = cmd(
        "restriction",
        "RESTRICTION",
        4,
        json!({"schema_version":1,"instrument":"BTCUSDT.BINANCE","id":"restriction-1","quantity":"2","kind":"SUSPENDED","source":"market-rule-fact","from":4,"until":8,"reason":"explicit restriction"}),
    );
    m.apply(&restriction).unwrap();
    assert_eq!(m.account("BTCUSDT.BINANCE").unwrap()["available"], "2");
    roundtrip(&mut m);
    m.apply(&cmd("clock", "TICK", 8, json!({"schema_version":1})))
        .unwrap();
    assert_eq!(m.account("BTCUSDT.BINANCE").unwrap()["available"], "4");
}
#[test]
fn broker_conflict_never_overwrites_cost_and_unavailable_cannot_clear_block() {
    let mut m = manager();
    m.apply(&trade("t1", Some("a"), "BUY", "10.00", "2", 1))
        .unwrap();
    m.apply(&broker("b1", "3", "3", "3", "0", 2)).unwrap();
    assert_eq!(m.account("BTCUSDT.BINANCE").unwrap()["quantity"], "2");
    assert_eq!(m.account("BTCUSDT.BINANCE").unwrap()["available"], "0");
    let mut bad = broker("b2", "2", "2", "2", "0", 3);
    bad["payload"]["quality"] = json!("UNKNOWN");
    let s = m.state();
    assert!(m.apply(&bad).is_err());
    assert_eq!(s, m.state());
    roundtrip(&mut m);
    m.apply(&broker("b3", "2", "2", "2", "0", 4)).unwrap();
    assert_eq!(m.account("BTCUSDT.BINANCE").unwrap()["available"], "2");
}
#[test]
fn stale_observation_is_recoverable_and_does_not_claim_fill_applied() {
    let mut m = manager();
    m.apply(&trade("t1", Some("a"), "BUY", "10.00", "2", 10))
        .unwrap();
    let stale = trade("t0", Some("a"), "BUY", "10.00", "1", 1);
    assert_eq!(m.apply(&stale).unwrap().status, Status::Stale);
    assert_eq!(m.account("BTCUSDT.BINANCE").unwrap()["quantity"], "2");
    roundtrip(&mut m);
    assert_eq!(m.apply(&stale).unwrap().status, Status::Duplicate);
    m.apply(&broker("b1", "2", "2", "2", "0", 11)).unwrap();
    assert_eq!(m.account("BTCUSDT.BINANCE").unwrap()["available"], "0");
}
#[test]
fn unallocated_never_becomes_cluster_allocation_or_sell_authority() {
    let mut m = manager();
    m.apply(&trade("t1", None, "BUY", "10.00", "2", 1)).unwrap();
    assert_eq!(
        m.unallocated("BTCUSDT.BINANCE").unwrap().unwrap()["quantity"],
        "2"
    );
    assert!(m.cluster("a", "BTCUSDT.BINANCE").is_err());
    assert!(m.apply(&reserve("r1", "a", "1", 2)).is_err());
    roundtrip(&mut m);
}
#[test]
fn resource_and_noncanonical_inputs_fail_before_mutation() {
    let mut m = manager();
    for (field, value) in [
        ("price", json!("1e65")),
        ("quantity", json!("1.1")),
        ("trade", json!(" t1")),
        ("position_mode", json!("HEDGING")),
    ] {
        let mut t = trade("t1", Some("a"), "BUY", "10.00", "2", 1);
        t["payload"][field] = value;
        let s = m.state();
        assert!(m.apply(&t).is_err(), "{field}");
        assert_eq!(s, m.state());
    }
    let mut t = trade("t1", Some("a"), "BUY", "10.00", "2", 1);
    t["unexpected"] = json!("x");
    assert!(m.apply(&t).is_err());
}

#[test]
fn common_vector_outputs() {
    let cases = include_str!("../../../../test-data/position/lifecycle-v1.jsonl");
    let mut outputs = vec![];
    for line in cases.lines() {
        let case: Value = serde_json::from_str(line).unwrap();
        let mut observed = vec![];
        let mut m = manager();
        if case["case"].as_str().unwrap().starts_with("opens") {
            for (n, fill) in case["fills"].as_array().unwrap().iter().enumerate() {
                m.apply(&trade(
                    &format!("t{n}"),
                    Some("a"),
                    "BUY",
                    fill[0].as_str().unwrap(),
                    fill[1].as_str().unwrap(),
                    n as u64 + 1,
                ))
                .unwrap();
                let a = m.account("BTCUSDT.BINANCE").unwrap();
                observed.push(json!([a["quantity"], a["cost"], a["average"]]));
                roundtrip(&mut m);
            }
        } else {
            if case["case"] == "close" {
                m.apply(&trade("open", Some("a"), "BUY", "15.00", "4", 1))
                    .unwrap();
            } else {
                m.apply(&trade("open1", Some("a"), "BUY", "30.00", "1", 1))
                    .unwrap();
                m.apply(&trade("open2", Some("a"), "BUY", "35.00", "2", 2))
                    .unwrap();
            }
            m.apply(&reserve(
                "reserve",
                "a",
                case["quantity"].as_str().unwrap(),
                3,
            ))
            .unwrap();
            let fills = case["fills"].as_array().unwrap();
            for (n, fill) in fills.iter().enumerate() {
                let result = m
                    .apply(&close(
                        &format!("close{n}"),
                        "a",
                        "40.00",
                        fill.as_str().unwrap(),
                        n as u64 + 4,
                        n + 1 == fills.len(),
                    ))
                    .unwrap();
                let fact = result.fact.unwrap();
                let a = m.account("BTCUSDT.BINANCE").unwrap();
                observed.push(json!([fact["details"]["released_cost"], a["cost"]]));
                roundtrip(&mut m);
            }
        }
        assert_eq!(json!(observed), case["expected"]);
        outputs.push(json!({"case":case["case"],"observed":observed}));
    }
    println!("POSITION_VECTOR_OUTPUT {}", json!(outputs));
}

#[test]
fn settlement_source_fact_cannot_be_consumed_twice_under_new_command_id() {
    let mut m = manager();
    let mut t = trade("t1", Some("a"), "BUY", "10.00", "4", 1);
    t["payload"]["bucket"] = json!("UNSETTLED");
    m.apply(&t).unwrap();
    let settle = cmd(
        "settle1",
        "SETTLE",
        2,
        json!({"schema_version":1,"instrument":"BTCUSDT.BINANCE","trading_day":"2026-10-19","source":"settlement-fact-1","buckets":[{"schema_version":1,"cluster":"a","quantity":"2"}]}),
    );
    m.apply(&settle).unwrap();
    let s = m.state();
    let mut repeated = settle.clone();
    repeated["command_id"] = json!("settle2");
    repeated["time"] = json!(3);
    let economics = m.account("BTCUSDT.BINANCE").unwrap();
    assert_eq!(m.apply(&repeated).unwrap().status, Status::Duplicate);
    assert_eq!(m.account("BTCUSDT.BINANCE").unwrap(), economics);
    assert_eq!(m.state()["now"], s["now"]);
    assert!(m.state()["commands"].get("settle2").is_some());
    let s = m.state();
    assert_eq!(m.apply(&repeated).unwrap().status, Status::Duplicate);
    assert_eq!(m.state(), s);
    repeated["payload"]["buckets"][0]["quantity"] = json!("1");
    assert_eq!(m.apply(&repeated).unwrap().status, Status::Conflict);
    assert_eq!(m.state(), s);
    roundtrip(&mut m);
    assert_eq!(m.apply(&settle).unwrap().status, Status::Duplicate);
}
#[test]
fn broker_older_than_local_economics_cannot_supply_available_proof() {
    let mut m = manager();
    m.apply(&trade("t1", Some("a"), "BUY", "10.00", "4", 10))
        .unwrap();
    let stale = broker("old", "4", "4", "0", "4", 5);
    assert_eq!(m.apply(&stale).unwrap().status, Status::Stale);
    assert!(m.state()["brokers"].as_object().unwrap().is_empty());
}
#[test]
fn checkpoint_structure_mutations_never_replace_current_state() {
    let mut m = manager();
    m.apply(&trade("t1", Some("a"), "BUY", "10.00", "4", 1))
        .unwrap();
    m.apply(&reserve("r1", "a", "2", 2)).unwrap();
    let (b, _) = m.checkpoint().unwrap();
    let original: Value = serde_json::from_slice(&b).unwrap();
    for n in 0..7 {
        let mut v = original.clone();
        match n {
            0 => {
                v.as_object_mut().unwrap().remove("config");
            }
            1 => v["config"]["account"] = json!("other"),
            2 => {
                let t = v["journal"][0].clone();
                v["journal"].as_array_mut().unwrap().push(t);
            }
            3 => v["journal"][1]["payload"]["cluster"] = json!("b"),
            4 => v["state"]["reservations"][0]["remaining"] = json!("1"),
            5 => v["state"]["allocations"][0]["snapshot"]["cycle"] = json!(99),
            _ => v["state"]["receipts"] = json!({}),
        }
        let bad = serde_json::to_vec(&v).unwrap();
        let s = m.state();
        assert!(m.restore(&bad, &digest(&bad)).is_err(), "mutation {n}");
        assert_eq!(s, m.state());
    }
}
#[test]
fn exact_order_hold_cannot_borrow_another_orders_authority() {
    let mut m = manager();
    m.apply(&trade("t1", Some("a"), "BUY", "10.00", "5", 1))
        .unwrap();
    m.apply(&reserve("r1", "a", "2", 2)).unwrap();
    let mut second = reserve("r2", "a", "2", 3);
    second["payload"]["order"] = json!("other-order");
    m.apply(&second).unwrap();
    let s = m.state();
    assert!(m.apply(&close("t2", "a", "11.00", "3", 4, true)).is_err());
    assert_eq!(s, m.state());
    m.apply(&close("t3", "a", "11.00", "2", 5, true)).unwrap();
    assert_eq!(m.reservation("other-order").unwrap()["remaining"], "2");
}
#[test]
fn configuration_bounds_and_wrong_owners_fail_closed() {
    let mut bad = config();
    bad["clusters"] = json!((0..33).map(|n| format!("cluster-{n}")).collect::<Vec<_>>());
    assert!(Manager::new(bad).is_err());
    let mut m = manager();
    let t = trade("t1", Some("a"), "BUY", "10.00", "2", 1);
    for key in [
        "engine",
        "runtime",
        "account",
        "gateway",
        "generation",
        "cause",
        "payload",
    ] {
        let mut bad = t.clone();
        bad.as_object_mut().unwrap().remove(key);
        let s = m.state();
        assert!(m.apply(&bad).is_err(), "{key}");
        assert_eq!(m.state(), s);
    }
    let oversized = vec![b' '; 16 * 1024 * 1024 + 1];
    assert!(m.restore(&oversized, &digest(&oversized)).is_err());
}

#[test]
fn sent_unacknowledged_cancel_preserves_hold_fresh_and_restored() {
    let mut m = manager();
    m.apply(&trade("t1", Some("a"), "BUY", "10.00", "10", 1))
        .unwrap();
    m.apply(&reserve("r1", "a", "4", 2)).unwrap();
    m.apply(&stage("s1", "SENT_TO_BROKER", 3)).unwrap();
    let cancel = cmd(
        "cancel",
        "RELEASE",
        4,
        json!({"schema_version":1,"order":"order-a","cluster":"a","broker_confirmed":false}),
    );
    m.apply(&cancel).unwrap();
    assert_eq!(m.reservation("order-a").unwrap()["remaining"], "4");
    assert_eq!(m.account("BTCUSDT.BINANCE").unwrap()["available"], "6");
    roundtrip(&mut m);
    assert_eq!(m.account("BTCUSDT.BINANCE").unwrap()["available"], "6");
    m.apply(&stage("late-ack", "BROKER_ACKNOWLEDGED", 5))
        .unwrap();
    assert_eq!(
        m.reservation("order-a").unwrap()["stage"],
        "RELEASE_PENDING"
    );
    assert_eq!(m.reservation("order-a").unwrap()["remaining"], "4");
    roundtrip(&mut m);
}
#[test]
fn stale_broker_receipt_reuse_is_conflict_fresh_and_restored() {
    let mut m = manager();
    m.apply(&trade("t1", Some("a"), "BUY", "10.00", "2", 1))
        .unwrap();
    m.apply(&broker("b1", "2", "2", "2", "0", 10)).unwrap();
    let stale = broker("stale", "2", "2", "0", "2", 5);
    assert_eq!(m.apply(&stale).unwrap().status, Status::Stale);
    for restored in [false, true] {
        if restored {
            roundtrip(&mut m);
        }
        let mut changed = broker("stale", "2", "2", "2", "0", 11);
        changed["command_id"] = json!("new-command");
        let before = m.state();
        assert_eq!(m.apply(&changed).unwrap().status, Status::Conflict);
        assert_eq!(before, m.state());
    }
}
#[test]
fn account_and_cluster_account_label_never_share_position_identity() {
    let mut cfg = config();
    cfg["clusters"] = json!(["ACCOUNT", "a", "b"]);
    let mut m = Manager::new(cfg.clone()).unwrap();
    m.apply(&trade("t1", Some("ACCOUNT"), "BUY", "10.00", "2", 1))
        .unwrap();
    assert_ne!(
        m.account("BTCUSDT.BINANCE").unwrap()["id"],
        m.cluster("ACCOUNT", "BTCUSDT.BINANCE").unwrap()["id"]
    );
    let (b, h) = m.checkpoint().unwrap();
    let mut fresh = Manager::new(cfg).unwrap();
    fresh.restore(&b, &h).unwrap();
    assert_eq!(m.state(), fresh.state());
}
#[test]
fn independent_restriction_and_acknowledged_hold_remain_additive() {
    let mut m = manager();
    m.apply(&trade("t1", Some("a"), "BUY", "10.00", "50", 1))
        .unwrap();
    m.apply(&trade("t2", Some("b"), "BUY", "10.00", "50", 2))
        .unwrap();
    m.apply(&reserve("r1", "a", "50", 3)).unwrap();
    m.apply(&stage("s1", "SENT_TO_BROKER", 4)).unwrap();
    m.apply(&stage("s2", "BROKER_ACKNOWLEDGED", 5)).unwrap();
    m.apply(&broker("b1", "100", "100", "50", "50", 6)).unwrap();
    m.apply(&cmd("restriction","RESTRICTION",7,json!({"schema_version":1,"instrument":"BTCUSDT.BINANCE","id":"restriction-1","quantity":"50","kind":"SUSPENDED","source":"independent-rule","from":7,"until":null,"reason":"independent limit"}))).unwrap();
    for restored in [false, true] {
        if restored {
            roundtrip(&mut m);
        }
        assert_eq!(m.account("BTCUSDT.BINANCE").unwrap()["available"], "0");
        let before = m.state();
        assert!(m.apply(&reserve("r2", "b", "1", 8)).is_err());
        assert_eq!(m.state(), before);
    }
}

#[test]
fn duplicate_acknowledgement_binds_new_command_identity_across_restore() {
    let mut m = manager();
    m.apply(&trade("t1", Some("a"), "BUY", "10.00", "10", 1))
        .unwrap();
    m.apply(&reserve("r1", "a", "2", 2)).unwrap();
    let mut acknowledged = reserve("acknowledged", "a", "2", 3);
    let before = m.account("BTCUSDT.BINANCE").unwrap();
    assert_eq!(m.apply(&acknowledged).unwrap().status, Status::Duplicate);
    assert_eq!(before, m.account("BTCUSDT.BINANCE").unwrap());
    roundtrip(&mut m);
    let state = m.state();
    acknowledged["payload"]["order"] = json!("different-order");
    acknowledged["time"] = json!(4);
    assert_eq!(m.apply(&acknowledged).unwrap().status, Status::Conflict);
    assert_eq!(m.state(), state);
    let original = trade("t2", Some("a"), "BUY", "10.00", "1", 5);
    m.apply(&original).unwrap();
    let mut copy = original.clone();
    copy["command_id"] = json!("external-duplicate-command");
    assert_eq!(m.apply(&copy).unwrap().status, Status::Duplicate);
    roundtrip(&mut m);
    copy["payload"]["trade"] = json!("new-trade");
    copy["payload"]["venue_trade"] = json!("new-venue");
    copy["payload"]["execution"] = json!("new-execution");
    copy["payload"]["sequence"] = json!(6);
    copy["time"] = json!(6);
    let state = m.state();
    assert_eq!(m.apply(&copy).unwrap().status, Status::Conflict);
    assert_eq!(m.state(), state);
}

#[test]
fn signed_historical_time_initializes_from_first_input_and_recovers() {
    let mut m = manager();
    let mut t = trade("old-trade", Some("a"), "BUY", "10.00", "4", 1);
    t["time"] = json!(-10);
    m.apply(&t).unwrap();
    assert_eq!(m.state()["now"], "-10");
    let mut r = reserve("old-reserve", "a", "2", 1);
    r["time"] = json!(-9);
    m.apply(&r).unwrap();
    roundtrip(&mut m);
    assert_eq!(m.state()["now"], "-9");
    let before = m.state();
    let mut stale = cmd("regressing-local", "TICK", 1, json!({"schema_version":1}));
    stale["time"] = json!(-11);
    assert!(m.apply(&stale).is_err());
    assert_eq!(before, m.state());
}
