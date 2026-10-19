use onlyalpha_strategy_ledger::{Manager, Status, digest};
use serde_json::{Value, json};
fn config() -> Value {
    json!({"schema_version":1,"engine":"e","runtime":"r","account":"a","generation":"g","runtime_kind":"BACKTEST","currency":{"schema_version":1,"code":"USD","precision":2,"currency_type":"FIAT"},"account_initial_cash":"2000.00","capitals":{"c1":"1000.00","c2":"1000.00"}})
}
fn manager() -> Manager {
    Manager::new(config()).unwrap()
}
fn command(cluster: &str, id: &str, seq: u64, op: &str, mut payload: Value) -> Value {
    if op == "TRADE" {
        for field in ["before", "after"] {
            let a = &mut payload[field];
            let version = a["version"].as_u64().unwrap();
            if a.get("identity").is_none() {
                a["identity"] = if version == 0 {
                    Value::Null
                } else {
                    json!(format!("allocation-{cluster}"))
                };
                a["cycle"] = json!(if version == 0 { 0 } else { 1 });
                a["realized_exact"] = a["realized"].clone();
            }
        }
    }

    json!({"schema_version":1,"engine":"e","runtime":"r","account":"a","generation":"g","cluster":cluster,"command_id":id,"cause":"a".repeat(64),"time":0,"runtime_sequence":seq,"trading_day":"2026-10-19","day_index":1,"op":op,"payload":payload})
}
fn active() -> Manager {
    let mut m = manager();
    for (c, s) in [("c1", 1), ("c2", 2)] {
        m.apply(&command(c, c, s, "ACTIVATE", json!({"schema_version":1})))
            .unwrap();
    }
    m
}
fn reserve(c: &str, id: &str, seq: u64, amount: &str) -> Value {
    command(
        c,
        id,
        seq,
        "RESERVE",
        json!({"schema_version":1,"reservation":id,"order":format!("o-{id}"),"amount":amount}),
    )
}
fn allocation(q: &str, cost: &str, realized: &str, version: u64) -> Value {
    json!({"schema_version":1,"quantity":q,"cost":cost,"realized":realized,"version":version})
}
fn buy(
    c: &str,
    id: &str,
    seq: u64,
    res: &str,
    before: Value,
    after: Value,
    notional: &str,
) -> Value {
    command(
        c,
        id,
        seq,
        "TRADE",
        json!({"schema_version":1,"trade":id,"execution":format!("x-{id}"),"venue_trade":format!("v-{id}"),"order":format!("o-{res}"),"fee_instruction":format!("f-{id}"),"source_sequence":seq,"side":"BUY","instrument":"BTCUSDT.BINANCE","notional":notional,"charges":"1.00","rebates":"0.00","reservation":res,"terminal_fill":true,"before":before,"after":after,"allocation_evidence":"b".repeat(64),"mark":"10","multiplier":"1"}),
    )
}
fn opened() -> Manager {
    let mut m = active();
    m.apply(&reserve("c1", "r1", 3, "500")).unwrap();
    m.apply(&buy(
        "c1",
        "t1",
        4,
        "r1",
        allocation("0", "0", "0", 0),
        allocation("10", "100", "0", 1),
        "100",
    ))
    .unwrap();
    m
}
fn snapshot(m: &Manager, c: &str) -> Value {
    m.snapshot(c).unwrap()
}
fn valuation(c: &str, id: &str, seq: u64, basis: u64, version: u64, price: &str) -> Value {
    command(
        c,
        id,
        seq,
        "VALUATION",
        json!({"schema_version":1,"valuation":id,"economic_version":basis,"version":version,"lines":[{"schema_version":1,"instrument":"BTCUSDT.BINANCE","allocation_version":1,"allocation_evidence":"b".repeat(64),"mark":price,"multiplier":"1"}]}),
    )
}
fn roundtrip(m: &mut Manager) {
    let (b, h) = m.checkpoint().unwrap();
    let mut fresh = manager();
    fresh.restore(&b, &h).unwrap();
    assert_eq!(m.state(), fresh.state());
    *m = fresh;
}
#[test]
fn exact_capital_and_context_are_required() {
    let mut c = config();
    c["capitals"]["c2"] = json!("999");
    assert!(Manager::new(c).is_err());
    let mut c = config();
    c["runtime_kind"] = json!("RESEARCH");
    assert!(Manager::new(c).is_err());
    let mut m = active();
    let s = m.state();
    let mut cmd = reserve("c1", "r1", 3, "10");
    cmd["account"] = json!("wrong");
    assert!(m.apply(&cmd).is_err());
    assert_eq!(s, m.state());
}
#[test]
fn two_clusters_do_not_share_cost_or_cash() {
    let mut m = opened();
    m.apply(&reserve("c2", "r2", 5, "500")).unwrap();
    let mut t = buy(
        "c2",
        "t2",
        6,
        "r2",
        allocation("0", "0", "0", 0),
        allocation("10", "200", "0", 1),
        "200",
    );
    t["payload"]["mark"] = json!("20");
    m.apply(&t).unwrap();
    assert_eq!(snapshot(&m, "c1")["cash"], "899.00");
    assert_eq!(snapshot(&m, "c2")["cash"], "799.00");
    m.apply(&valuation("c1", "val", 7, 1, 1, "20")).unwrap();
    assert_eq!(snapshot(&m, "c1")["unrealized_pnl"], "100.00");
    assert_eq!(snapshot(&m, "c2")["unrealized_pnl"], "0.00");
    roundtrip(&mut m);
}
#[test]
fn partial_fills_keep_hold_and_observed_fill_proves_sent() {
    let mut m = active();
    m.apply(&reserve("c1", "r1", 3, "500")).unwrap();
    let mut t = buy(
        "c1",
        "t1",
        4,
        "r1",
        allocation("0", "0", "0", 0),
        allocation("10", "100", "0", 1),
        "100",
    );
    t["payload"]["terminal_fill"] = json!(false);
    m.apply(&t).unwrap();
    assert_eq!(snapshot(&m, "c1")["reserved"], "399.00");
    roundtrip(&mut m);
    let s = m.state();
    assert!(
        m.apply(&command(
            "c1",
            "bad",
            5,
            "RELEASE",
            json!({"schema_version":1,"reservation":"r1","outcome":"NOT_SENT"})
        ))
        .is_err()
    );
    assert_eq!(s, m.state());
    let mut t = buy(
        "c1",
        "t2",
        5,
        "r1",
        allocation("10", "100", "0", 1),
        allocation("20", "200", "0", 2),
        "100",
    );
    t["payload"]["rebates"] = json!("5");
    m.apply(&t).unwrap();
    assert_eq!(snapshot(&m, "c1")["cash"], "803.00");
    assert_eq!(snapshot(&m, "c1")["reserved"], "0.00");
    assert_eq!(
        m.state()["ledgers"]["c1"]["reservations"]["r1"]["released"],
        "298.00"
    );
}
#[test]
fn unknown_and_cancel_request_never_release() {
    let mut m = active();
    m.apply(&reserve("c1", "r1", 3, "500")).unwrap();
    for (seq, stage) in [
        (4, "SUBMIT_UNKNOWN"),
        (5, "CANCEL_REQUESTED"),
        (6, "BROKER_ACKNOWLEDGED"),
    ] {
        m.apply(&command(
            "c1",
            stage,
            seq,
            "STAGE",
            json!({"schema_version":1,"reservation":"r1","stage":stage}),
        ))
        .unwrap();
    }
    assert_eq!(snapshot(&m, "c1")["reserved"], "500.00");
    assert_eq!(
        m.state()["ledgers"]["c1"]["reservations"]["r1"]["cancel_pending"],
        true
    );
    m.apply(&command(
        "c1",
        "rel",
        7,
        "RELEASE",
        json!({"schema_version":1,"reservation":"r1","outcome":"CANCELLED"}),
    ))
    .unwrap();
    assert_eq!(snapshot(&m, "c1")["reserved"], "0.00");
    roundtrip(&mut m);
}
#[test]
fn full_payload_conflicts_and_decimal_duplicates() {
    let mut m = active();
    let cmd = reserve("c1", "r1", 3, "500");
    m.apply(&cmd).unwrap();
    let mut eq = cmd.clone();
    eq["payload"]["amount"] = json!("500.00");
    assert_eq!(m.apply(&eq).unwrap().status, Status::Duplicate);
    let s = m.state();
    eq["payload"]["amount"] = json!("501");
    assert_eq!(m.apply(&eq).unwrap().status, Status::Conflict);
    assert_eq!(s, m.state());
    let mut alias = cmd;
    alias["command_id"] = json!("fresh");
    assert_eq!(m.apply(&alias).unwrap().status, Status::Duplicate);
    assert_eq!(m.state()["timeline"].as_array().unwrap().len(), 3);
    roundtrip(&mut m);
    alias["payload"]["amount"] = json!("502");
    assert_eq!(m.apply(&alias).unwrap().status, Status::Conflict);
}
#[test]
fn cross_cluster_aliases_cannot_reassign_trade_or_order() {
    let mut m = opened();
    let mut other = reserve("c2", "different", 5, "10");
    other["payload"]["order"] = json!("o-r1");
    assert_eq!(m.apply(&other).unwrap().status, Status::Conflict);
    let s = m.state();
    let mut t = buy(
        "c2",
        "t1",
        5,
        "other",
        allocation("0", "0", "0", 0),
        allocation("10", "100", "0", 1),
        "100",
    );
    t["command_id"] = json!("new-command");
    assert_eq!(m.apply(&t).unwrap().status, Status::Conflict);
    assert_eq!(s, m.state());
}
#[test]
fn wrong_allocation_or_cost_relation_is_atomic() {
    let mut m = active();
    m.apply(&reserve("c1", "r1", 3, "500")).unwrap();
    let s = m.state();
    for (before, after) in [
        (allocation("0", "0", "0", 0), allocation("10", "99", "0", 1)),
        (
            allocation("1", "10", "0", 0),
            allocation("11", "110", "0", 1),
        ),
        (
            allocation("0", "0", "0", 0),
            allocation("10", "100", "0", 0),
        ),
    ] {
        let t = buy("c1", "bad", 4, "r1", before, after, "100");
        assert!(m.apply(&t).is_err());
        assert_eq!(s, m.state());
    }
}
#[test]
fn sell_uses_attributed_removed_cost() {
    let mut m = opened();
    let mut t = buy(
        "c1",
        "sell",
        5,
        "none",
        allocation("10", "100", "0", 1),
        allocation("5", "50", "25", 2),
        "75",
    );
    t["payload"]["side"] = json!("SELL");
    t["payload"]["reservation"] = Value::Null;
    t["payload"]["mark"] = json!("15");
    m.apply(&t).unwrap();
    let s = snapshot(&m, "c1");
    assert_eq!(s["cash"], "973.00");
    assert_eq!(s["realized_pnl"], "25.00");
    assert_eq!(s["unrealized_pnl"], "25.00");
    assert_eq!(s["equity"], "1048.00");
    assert_eq!(s["pnl_equity"], "1048.00");
    roundtrip(&mut m);
}
#[test]
fn gross_reserve_cannot_be_offset_by_rebates() {
    let mut m = active();
    m.apply(&reserve("c1", "r1", 3, "100")).unwrap();
    let mut t = buy(
        "c1",
        "t",
        4,
        "r1",
        allocation("0", "0", "0", 0),
        allocation("10", "100", "0", 1),
        "100",
    );
    t["payload"]["rebates"] = json!("10");
    let s = m.state();
    assert!(m.apply(&t).is_err());
    assert_eq!(s, m.state());
}
#[test]
fn negative_net_fee_and_negative_sale_proceeds_are_valid() {
    let mut m = active();
    m.apply(&reserve("c1", "r1", 3, "200")).unwrap();
    let mut t = buy(
        "c1",
        "t",
        4,
        "r1",
        allocation("0", "0", "0", 0),
        allocation("10", "100", "0", 1),
        "100",
    );
    t["payload"]["rebates"] = json!("150");
    m.apply(&t).unwrap();
    assert_eq!(snapshot(&m, "c1")["cash"], "1049.00");
    let mut t = buy(
        "c1",
        "sell",
        5,
        "none",
        allocation("10", "100", "0", 1),
        allocation("0", "0", "-90", 2),
        "10",
    );
    t["payload"]["side"] = json!("SELL");
    t["payload"]["reservation"] = Value::Null;
    t["payload"]["charges"] = json!("20");
    m.apply(&t).unwrap();
    assert_eq!(snapshot(&m, "c1")["cash"], "1039.00");
    roundtrip(&mut m);
}
#[test]
fn valuation_requires_complete_current_allocation_basis() {
    let mut m = opened();
    let valid = valuation("c1", "v", 5, 1, 1, "15");
    for field in ["economic_version", "version"] {
        let mut v = valid.clone();
        v["payload"][field] = json!(0);
        let s = m.state();
        assert!(m.apply(&v).is_err());
        assert_eq!(s, m.state());
    }
    let mut v = valid.clone();
    v["payload"]["lines"] = json!([]);
    assert!(m.apply(&v).is_err());
    let mut v = valid.clone();
    v["payload"]["lines"][0]["allocation_evidence"] = json!("c".repeat(64));
    assert!(m.apply(&v).is_err());
    m.apply(&valid).unwrap();
    assert_eq!(snapshot(&m, "c1")["equity"], "1049.00");
    roundtrip(&mut m);
}
#[test]
fn late_trade_blocks_new_risk_but_preserves_safe_operations() {
    let mut m = opened();
    let mut t = buy(
        "c1",
        "late",
        5,
        "r1",
        allocation("10", "100", "0", 1),
        allocation("20", "200", "0", 2),
        "100",
    );
    t["payload"]["source_sequence"] = json!(1);
    assert_eq!(m.apply(&t).unwrap().status, Status::Stale);
    assert_eq!(snapshot(&m, "c1")["cash"], "899.00");
    assert!(m.apply(&reserve("c1", "blocked", 6, "10")).is_err());
    m.apply(&valuation("c1", "v", 6, 1, 1, "10")).unwrap();
    assert_eq!(snapshot(&m, "c1")["status"], "RECONCILING");
    assert_eq!(snapshot(&m, "c2")["status"], "ACTIVE");
    roundtrip(&mut m);
}
#[test]
fn explicit_days_external_flows_and_global_same_time_timeline() {
    let mut m = opened();
    m.apply(&valuation("c1", "v1", 5, 1, 1, "20")).unwrap();
    assert_eq!(snapshot(&m, "c1")["high_water_mark"], "1099.00");
    let mut v = valuation("c1", "v2", 6, 1, 2, "15");
    v["trading_day"] = json!("2026-10-20");
    v["day_index"] = json!(2);
    m.apply(&v).unwrap();
    let s = snapshot(&m, "c1");
    assert_eq!(s["day_start_equity"], "1099.00");
    assert_eq!(s["daily_pnl"], "-50.00");
    assert_eq!(s["drawdown"], "-0.04549591");
    let mut flow = command(
        "c1",
        "flow",
        7,
        "CASH_FLOW",
        json!({"schema_version":1,"cashflow":"flow","source_fact":"s-flow","amount":"100"}),
    );
    flow["trading_day"] = json!("2026-10-20");
    flow["day_index"] = json!(2);
    m.apply(&flow).unwrap();
    assert!(snapshot(&m, "c1")["simple_return"].is_null());
    let seqs: Vec<_> = m.state()["timeline"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v["sequence"].as_u64().unwrap())
        .collect();
    assert_eq!(seqs, vec![1, 2, 3, 4, 5, 6, 7]);
    roundtrip(&mut m);
}
#[test]
fn source_reuse_and_inadequate_cash_fail_atomically() {
    let mut m = active();
    let flow = command(
        "c1",
        "f",
        3,
        "CASH_FLOW",
        json!({"schema_version":1,"cashflow":"f","source_fact":"same","amount":"10"}),
    );
    m.apply(&flow).unwrap();
    let mut fee = command(
        "c1",
        "fee",
        4,
        "FEE",
        json!({"schema_version":1,"fee_instruction":"fee","source_fact":"same","order":"o","trade":"t","charges":"1","rebates":"0"}),
    );
    assert_eq!(m.apply(&fee).unwrap().status, Status::Conflict);
    fee["payload"]["source_fact"] = json!("other");
    fee["payload"]["charges"] = json!("9999");
    let s = m.state();
    assert!(m.apply(&fee).is_err());
    assert_eq!(s, m.state());
}
#[test]
fn close_requires_flat_and_cannot_reactivate() {
    let mut m = opened();
    assert!(
        m.apply(&command(
            "c1",
            "close",
            5,
            "CLOSE",
            json!({"schema_version":1})
        ))
        .is_err()
    );
    m.apply(&command(
        "c2",
        "close2",
        5,
        "CLOSE",
        json!({"schema_version":1}),
    ))
    .unwrap();
    assert!(
        m.apply(&command(
            "c2",
            "restart",
            6,
            "ACTIVATE",
            json!({"schema_version":1})
        ))
        .is_err()
    );
    assert!(m.apply(&reserve("c2", "r2", 6, "10")).is_err());
}
#[test]
fn corrupted_checkpoint_relations_and_digest_never_mutate() {
    let mut m = opened();
    roundtrip(&mut m);
    let (bytes, h) = m.checkpoint().unwrap();
    let original = m.state();
    assert!(m.restore(&bytes, &"0".repeat(64)).is_err());
    for field in ["config", "journal", "state"] {
        let mut v: Value = serde_json::from_slice(&bytes).unwrap();
        match field {
            "config" => v["config"]["capitals"]["c1"] = json!("999"),
            "journal" => v["journal"][3]["payload"]["after"]["cost"] = json!("99.00"),
            _ => v["state"]["timeline"][3]["sequence"] = json!(3),
        }
        let b = serde_json::to_vec(&v).unwrap();
        assert!(m.restore(&b, &digest(&b)).is_err());
        assert_eq!(original, m.state());
    }
    m.restore(&bytes, &h).unwrap();
}

#[test]
fn runtime_sequence_gaps_and_maximum_are_exact() {
    let mut m = active();
    let r = reserve("c1", "r1", u64::MAX, "10");
    m.apply(&r).unwrap();
    let st = m.state();
    assert_eq!(st["timeline"][2]["sequence"], u64::MAX);
    assert_eq!(st["ledgers"]["c1"]["entries"][1]["sequence"], u64::MAX);
    let (b, h) = m.checkpoint().unwrap();
    let mut fresh = manager();
    fresh.restore(&b, &h).unwrap();
    assert_eq!(st, fresh.state());
}
#[test]
fn schema_owner_and_leaf_mutations_are_rejected_before_mutation() {
    let mut m = active();
    for field in [
        "engine",
        "runtime",
        "account",
        "generation",
        "cluster",
        "cause",
        "time",
        "runtime_sequence",
        "day_index",
        "trading_day",
        "op",
    ] {
        let mut v = reserve("c1", "r1", 3, "10");
        v[field] = json!("wrong");
        let s = m.state();
        assert!(m.apply(&v).is_err(), "{field}");
        assert_eq!(s, m.state());
    }
    let mut extra = reserve("c1", "r1", 3, "10");
    extra["payload"]["extra"] = Value::Null;
    assert!(m.apply(&extra).is_err());
}
#[test]
fn source_ids_and_fee_instructions_are_global_and_full_payload_bound() {
    let mut m = opened();
    let mut f = command(
        "c1",
        "fee",
        5,
        "FEE",
        json!({"schema_version":1,"fee_instruction":"adjustment","source_fact":"fee-source","order":"o-r1","trade":"t1","charges":"2","rebates":"5"}),
    );
    m.apply(&f).unwrap();
    assert_eq!(snapshot(&m, "c1")["cash"], "902.00");
    assert_eq!(snapshot(&m, "c1")["fees"], "-2.00");
    let s = m.state();
    f["command_id"] = json!("bad-fee");
    f["payload"]["charges"] = json!("3");
    assert_eq!(m.apply(&f).unwrap().status, Status::Conflict);
    assert_eq!(s, m.state());
    roundtrip(&mut m);
}
#[test]
fn every_open_line_is_required_and_duplicates_are_invalid() {
    let mut m = opened();
    m.apply(&reserve("c1", "r2", 5, "100")).unwrap();
    let mut t = buy(
        "c1",
        "t2",
        6,
        "r2",
        allocation("0", "0", "0", 0),
        allocation("1", "10", "0", 1),
        "10",
    );
    t["payload"]["instrument"] = json!("ETHUSDT.BINANCE");
    t["payload"]["after"]["identity"] = json!("allocation-c1-eth");
    m.apply(&t).unwrap();
    let mut v = valuation("c1", "v", 7, 2, 1, "10");
    let s = m.state();
    assert!(m.apply(&v).is_err());
    assert_eq!(s, m.state());
    let mut second = v["payload"]["lines"][0].clone();
    v["payload"]["lines"]
        .as_array_mut()
        .unwrap()
        .push(second.clone());
    assert!(m.apply(&v).is_err());
    second["instrument"] = json!("ETHUSDT.BINANCE");
    v["payload"]["lines"][1] = second;
    m.apply(&v).unwrap();
    roundtrip(&mut m);
}
#[test]
fn different_day_identity_cannot_reuse_or_reverse_calendar_ordinal() {
    let mut m = active();
    for (day, index) in [
        ("2026-10-20", 1),
        ("2026-10-18", 2),
        ("2026-10-19", 2),
        ("2026-10-18", 0),
    ] {
        let mut v = reserve("c1", "r1", 3, "10");
        v["trading_day"] = json!(day);
        v["day_index"] = json!(index);
        let s = m.state();
        assert!(m.apply(&v).is_err(), "{day}/{index}");
        assert_eq!(s, m.state());
    }
}
#[test]
fn zero_capital_and_roundtrip_cashflows_do_not_invent_return() {
    let mut c = config();
    c["capitals"]["c1"] = json!("0");
    c["account_initial_cash"] = json!("1000");
    let mut m = Manager::new(c).unwrap();
    m.apply(&command(
        "c1",
        "activate",
        1,
        "ACTIVATE",
        json!({"schema_version":1}),
    ))
    .unwrap();
    assert!(snapshot(&m, "c1")["simple_return"].is_null());
    for (seq, amount) in [(2, "10"), (3, "-10")] {
        m.apply(&command("c1",&format!("flow-{seq}"),seq,"CASH_FLOW",json!({"schema_version":1,"cashflow":format!("flow-{seq}"),"source_fact":format!("source-{seq}"),"amount":amount}))).unwrap();
    }
    assert_eq!(snapshot(&m, "c1")["cash"], "0.00");
    assert!(snapshot(&m, "c1")["simple_return"].is_null());
}
#[test]
fn every_admitted_money_config_can_restore_itself() {
    let mut c = config();
    let max = "9".repeat(126);
    c["capitals"] = json!({"c1":max});
    c["account_initial_cash"] = c["capitals"]["c1"].clone();
    let m = Manager::new(c.clone()).unwrap();
    let (b, h) = m.checkpoint().unwrap();
    let mut f = Manager::new(c).unwrap();
    f.restore(&b, &h).unwrap();
    assert_eq!(m.state(), f.state());
    let mut c = config();
    let too = "9".repeat(127);
    c["capitals"] = json!({"c1":too});
    c["account_initial_cash"] = c["capitals"]["c1"].clone();
    assert!(Manager::new(c).is_err());
}
#[test]
fn current_fill_and_release_continue_after_stale_observation() {
    let mut m = active();
    m.apply(&reserve("c1", "r1", 3, "500")).unwrap();
    let mut t = buy(
        "c1",
        "t1",
        4,
        "r1",
        allocation("0", "0", "0", 0),
        allocation("10", "100", "0", 1),
        "100",
    );
    t["payload"]["terminal_fill"] = json!(false);
    m.apply(&t).unwrap();
    let mut late = buy(
        "c1",
        "late",
        5,
        "r1",
        allocation("10", "100", "0", 1),
        allocation("20", "200", "0", 2),
        "100",
    );
    late["payload"]["source_sequence"] = json!(1);
    m.apply(&late).unwrap();
    let t = buy(
        "c1",
        "t2",
        6,
        "r1",
        allocation("10", "100", "0", 1),
        allocation("20", "200", "0", 2),
        "100",
    );
    m.apply(&t).unwrap();
    assert_eq!(snapshot(&m, "c1")["cash"], "798.00");
    assert_eq!(snapshot(&m, "c1")["status"], "RECONCILING");
    assert_eq!(snapshot(&m, "c1")["reserved"], "0.00");
    roundtrip(&mut m);
}

#[test]
fn common_vector_outputs() {
    let mut outputs = Vec::new();
    for line in include_str!("../../../../test-data/strategy-ledger/valuation-v1.jsonl").lines() {
        let case: Value = serde_json::from_str(line).unwrap();
        let mut m = active();
        let mut seq = 3;
        for item in case["trades"].as_array().unwrap() {
            let cluster = item["cluster"].as_str().unwrap();
            let rid = format!("r-{seq}");
            m.apply(&reserve(cluster, &rid, seq, "500")).unwrap();
            seq += 1;
            let id = format!("t-{seq}");
            let mut t = buy(
                cluster,
                &id,
                seq,
                &rid,
                allocation("0", "0", "0", 0),
                allocation(
                    item["quantity"].as_str().unwrap(),
                    item["cost"].as_str().unwrap(),
                    "0",
                    1,
                ),
                item["cost"].as_str().unwrap(),
            );
            t["payload"]["charges"] = item["fee"].clone();
            t["payload"]["mark"] = item["price"].clone();
            m.apply(&t).unwrap();
            seq += 1;
            m.apply(&valuation(
                cluster,
                &format!("v-{seq}"),
                seq,
                1,
                1,
                item["mark"].as_str().unwrap(),
            ))
            .unwrap();
            seq += 1;
            let snap = snapshot(&m, cluster);
            let mut out = json!({"case":case["case"],"cluster":cluster});
            for (k, v) in item["expected"].as_object().unwrap() {
                assert_eq!(&snap[k], v, "{}:{k}", case["case"]);
                out[k] = snap[k].clone();
            }
            outputs.push(out);
            roundtrip(&mut m);
        }
    }
    println!("STRATEGY-LEDGER_VECTOR_OUTPUT {}", json!(outputs));
}

#[test]
fn fee_must_bind_exact_existing_trade_and_order_relation() {
    let mut m = opened();
    m.apply(&reserve("c1", "r2", 5, "100")).unwrap();
    m.apply(&buy(
        "c1",
        "t2",
        6,
        "r2",
        allocation("10", "100", "0", 1),
        allocation("11", "110", "0", 2),
        "10",
    ))
    .unwrap();
    for (trade, order) in [("missing", "o-r1"), ("t1", "missing-order"), ("t1", "o-r2")] {
        let fee = command(
            "c1",
            "fee-invalid",
            7,
            "FEE",
            json!({"schema_version":1,"fee_instruction":"adjustment-invalid","source_fact":"source-invalid","order":order,"trade":trade,"charges":"2","rebates":"0"}),
        );
        let before = m.state();
        assert!(m.apply(&fee).is_err(), "{trade}/{order}");
        assert_eq!(before, m.state());
    }
}

#[test]
fn stale_trade_retains_order_owner_without_granting_economic_authority() {
    let mut m = opened();
    let mut late = buy(
        "c1",
        "late-sell",
        5,
        "unused",
        allocation("10", "100", "0", 1),
        allocation("5", "50", "25", 2),
        "75",
    );
    late["payload"]["side"] = json!("SELL");
    late["payload"]["reservation"] = Value::Null;
    late["payload"]["order"] = json!("o-late");
    late["payload"]["source_sequence"] = json!(1);
    assert_eq!(m.apply(&late).unwrap().status, Status::Stale);
    assert_eq!(snapshot(&m, "c1")["cash"], "899.00");
    for restored in [false, true] {
        if restored {
            roundtrip(&mut m);
        }
        let mut other = reserve("c2", "steal", 6, "10");
        other["payload"]["order"] = json!("o-late");
        let before = m.state();
        assert_eq!(m.apply(&other).unwrap().status, Status::Conflict);
        assert_eq!(before, m.state());
        let fee = command(
            "c1",
            "stale-fee",
            6,
            "FEE",
            json!({"schema_version":1,"fee_instruction":"stale-adjustment","source_fact":"stale-source","order":"o-late","trade":"late-sell","charges":"1","rebates":"0"}),
        );
        assert!(m.apply(&fee).is_err());
        assert_eq!(before, m.state());
    }
}

#[test]
fn offsetting_external_flows_keep_daily_return_absent_until_new_day() {
    let mut m = active();
    m.apply(&command("c1", "deposit", 3, "CASH_FLOW", json!({"schema_version":1,"cashflow":"deposit","source_fact":"deposit-source","amount":"1000"}))).unwrap();
    m.apply(&reserve("c1", "r1", 4, "500")).unwrap();
    m.apply(&buy(
        "c1",
        "t1",
        5,
        "r1",
        allocation("0", "0", "0", 0),
        allocation("10", "100", "0", 1),
        "100",
    ))
    .unwrap();
    m.apply(&valuation("c1", "v1", 6, 2, 1, "20")).unwrap();
    m.apply(&command("c1", "withdraw", 7, "CASH_FLOW", json!({"schema_version":1,"cashflow":"withdraw","source_fact":"withdraw-source","amount":"-1000"}))).unwrap();
    assert_eq!(snapshot(&m, "c1")["daily_pnl"], "99.00");
    assert!(snapshot(&m, "c1")["daily_return"].is_null());
    roundtrip(&mut m);
    assert!(snapshot(&m, "c1")["daily_return"].is_null());
    let mut next = valuation("c1", "v2", 8, 3, 2, "20");
    next["trading_day"] = json!("2026-10-20");
    next["day_index"] = json!(2);
    m.apply(&next).unwrap();
    assert_eq!(snapshot(&m, "c1")["daily_return"], "0.00000000");
    assert!(snapshot(&m, "c1")["simple_return"].is_null());
    roundtrip(&mut m);
}

#[test]
fn saturated_history_keeps_existing_trade_and_fresh_recovery_available() {
    let mut m = active();
    m.apply(&reserve("c1", "r1", 3, "100")).unwrap();
    for n in 4..=4100 {
        m.apply(&command("c1",&format!("flow-{n}"),n,"CASH_FLOW",json!({"schema_version":1,"cashflow":format!("cashflow-{n}"),"source_fact":format!("source-{n}"),"amount":"0.00"}))).unwrap();
    }
    m.apply(&buy(
        "c1",
        "fill",
        5000,
        "r1",
        allocation("0", "0", "0", 0),
        allocation("1", "10", "0", 1),
        "10",
    ))
    .unwrap();
    roundtrip(&mut m);
    assert_eq!(snapshot(&m, "c1")["cash"], "989.00");
}

#[test]
fn allocation_cycle_restarts_preserve_lifetime_realized_and_exact_owner() {
    let mut m = opened();
    let old = allocation("10", "100", "0", 1);
    let closed = allocation("0", "0", "10", 2);
    m.apply(&command("c1","sell",5,"TRADE",json!({"schema_version":1,"trade":"sell","execution":"sell-x","venue_trade":"sell-v","order":"sell-order","fee_instruction":"sell-fee","source_sequence":5,"side":"SELL","instrument":"BTCUSDT.BINANCE","notional":"110.00","charges":"1.00","rebates":"0.00","reservation":null,"terminal_fill":true,"before":old,"after":closed,"allocation_evidence":"b".repeat(64),"mark":"11","multiplier":"1"}))).unwrap();
    m.apply(&reserve("c1", "r2", 6, "100")).unwrap();
    let mut after = allocation("1", "10", "0", 1);
    after["identity"] = json!("new-cycle-allocation");
    after["cycle"] = json!(2);
    after["realized_exact"] = json!("0.00");
    m.apply(&buy(
        "c1",
        "new-buy",
        7,
        "r2",
        allocation("0", "0", "10", 2),
        after,
        "10",
    ))
    .unwrap();
    assert_eq!(snapshot(&m, "c1")["realized_pnl"], "10.00");
    assert_eq!(snapshot(&m, "c1")["status"], "ACTIVE");
    roundtrip(&mut m);
}
