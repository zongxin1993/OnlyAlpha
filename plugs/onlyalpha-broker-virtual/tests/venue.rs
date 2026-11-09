use onlyalpha_broker::*;
use onlyalpha_broker_virtual::VirtualBroker;
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBar, value::OnlyMoney};
use serde_json::{Value, json};

fn scope() -> Scope {
    Scope::decode(&json!({"engine":"engine","runtime":"runtime","gateway":"virtual","account":"account","generation":"a".repeat(64),"runtime_kind":"BACKTEST"})).unwrap()
}
fn cash() -> OnlyMoney {
    OnlyMoney::from_record(&json!({"schema_version":1,"amount":"100000.00","currency":{"schema_version":1,"code":"CNY","precision":2,"currency_type":"FIAT"}})).unwrap()
}
fn venue(config: &Value) -> VirtualBroker {
    let mut v = VirtualBroker::new(scope(), &"b".repeat(64), cash(), config).unwrap();
    v.connect().unwrap();
    v.authenticate().unwrap();
    v
}
fn submit(id: &str) -> BrokerCommand {
    let mut request =
        serde_json::from_str::<Value>(include_str!("../../../test-data/broker/domain-inputs.json"))
            .unwrap()["request"]
            .clone();
    request["quantity"]["value"] = json!("100");
    request["request_id"]["value"] = json!(id);
    BrokerCommand::decode(&json!({"schema_version":1,"scope":scope().record(),"operation":"SUBMIT","command_id":id,"order":format!("order-{id}"),"client":format!("client-{id}"),"request":request})).unwrap()
}
fn bar(minute: u8, low: &str) -> OnlyBar {
    let mut b = include_str!("../../../test-data/domain/fact-records-v1.jsonl")
        .lines()
        .map(|l| serde_json::from_str::<Value>(l).unwrap())
        .find(|v| v["id"] == "bar")
        .unwrap()["record"]
        .clone();
    b["bar_type"]["instrument_id"] = submit("s").record()["request"]["instrument_id"].clone();
    b["bar_start"] = json!(format!("2025-01-06T01:{:02}:00Z", minute));
    for k in ["bar_end", "ts_event", "ts_init"] {
        b[k] = json!(format!("2025-01-06T01:{:02}:00Z", minute + 1));
    }
    b["low"]["value"] = json!(low);
    OnlyBar::from_record(&b).unwrap()
}
fn queries(v: &VirtualBroker) -> Vec<Value> {
    v.orders(&scope(), false)
        .unwrap()
        .iter()
        .map(OrderView::record)
        .collect()
}
fn reopen_cut(config: &Value, cut: &Value) -> Result<VirtualBroker, Error> {
    VirtualBroker::restore(scope(), &"b".repeat(64), cash(), config, cut, &digest(cut))
}

#[test]
fn three_equal_due_orders_and_complete_trade_queries_replay_in_original_order() {
    let cfg = json!({"latency":{"submit_ns":2}});
    let mut v = venue(&cfg);
    v.on_bar(1, &bar(0, "9.00")).unwrap();
    let due = v.now() + 2;
    let ids = ["z", "a", "m"];
    for id in ids {
        assert_eq!(v.dispatch(&submit(id)).unwrap(), DispatchResult::Received);
    }
    v.advance(due - 1).unwrap();
    let pending = v.checkpoint();
    assert_eq!(
        pending["pending_actions"],
        json!([
            {"due":due,"serial":1,"command":"z"},
            {"due":due,"serial":2,"command":"a"},
            {"due":due,"serial":3,"command":"m"}
        ])
    );
    assert!(pending["facts"].as_array().unwrap().is_empty());
    let mut recovered = reopen_cut(&cfg, &pending).unwrap();
    for broker in [&mut v, &mut recovered] {
        broker.advance(due).unwrap();
        let cut = broker.checkpoint();
        let facts = cut["facts"].as_array().unwrap();
        assert_eq!(facts.len(), 3);
        for (i, id) in ids.iter().enumerate() {
            assert_eq!(facts[i]["kind"], "ACCEPTED");
            assert_eq!(facts[i]["causation"], *id);
            assert_eq!(facts[i]["payload"]["order"], format!("order-{id}"));
            assert_eq!(facts[i]["source_sequence"], i + 1);
        }
        broker.on_bar(2, &bar(1, "9.00")).unwrap();
    }
    let orders = queries(&v);
    let trades = v.trades(&scope(), None).unwrap();
    assert_eq!(orders.len(), 3);
    assert_eq!(trades.len(), 3);
    for (i, id) in ids.iter().enumerate() {
        assert_eq!(orders[i]["venue"], format!("virtual-order-{:08}", i + 1));
        assert_eq!(orders[i]["order"], format!("order-{id}"));
        assert_eq!(orders[i]["status"], "FILLED");
        let trade = trades[i].record();
        assert_eq!(trade["payload"]["order"], orders[i]["order"]);
        assert_eq!(trade["source_sequence"], i + 4);
    }
    let after_fill = reopen_cut(&cfg, &v.checkpoint()).unwrap();
    for broker in [&recovered, &after_fill] {
        assert_eq!(queries(broker), orders);
        assert_eq!(broker.trades(&scope(), None).unwrap(), trades);
        assert!(broker.orders(&scope(), true).unwrap().is_empty());
    }
}

#[test]
fn scheduled_cross_bar_fills_preserve_cursor_and_reject_rehashed_false_terminal_state() {
    let cfg = json!({"matching":{"partial_fill":{"mode":"SCHEDULE","dispatch_mode":"ONE_PER_BAR","steps":[
        {"bar_offset":1,"quantity":"30"},{"bar_offset":2,"quantity":"40"},{"bar_offset":3,"quantity":"30"}]}}});
    let mut v = venue(&cfg);
    v.on_bar(1, &bar(0, "9.00")).unwrap();
    v.dispatch(&submit("steps")).unwrap();
    v.advance(v.now()).unwrap();
    let plan = v.checkpoint()["orders"][0]["plan"]["id"].clone();
    for (i, (quantity, total)) in [("30", "30"), ("40", "70"), ("30", "100")]
        .into_iter()
        .enumerate()
    {
        let minute = i as u8 + 1;
        v.on_bar(u64::from(minute) + 1, &bar(minute, "9.00"))
            .unwrap();
        let trades = v.trades(&scope(), None).unwrap();
        assert_eq!(trades.len(), i + 1);
        assert_eq!(
            trades[i].record()["payload"]["fill"]["quantity"]["value"],
            quantity
        );
        let cut = v.checkpoint();
        let order = &cut["orders"][0];
        assert_eq!(order["filled"], total);
        assert_eq!(order["plan"]["id"], plan);
        assert_eq!(order["plan"]["cursor"], i + 1);
        assert_eq!(
            order["status"],
            if i == 2 { "FILLED" } else { "PARTIALLY_FILLED" }
        );
        if i == 0 {
            let mut forged = cut.clone();
            forged["orders"][0]["status"] = json!("FILLED");
            assert_eq!(
                reopen_cut(&cfg, &forged).err(),
                Some(Error::new("VIRTUAL_CHECKPOINT_STATE_CONFLICT"))
            );
        }
        v = reopen_cut(&cfg, &cut).unwrap();
        assert_eq!(v.trades(&scope(), None).unwrap(), trades);
    }
    let complete = v.trades(&scope(), None).unwrap();
    v.on_bar(5, &bar(4, "9.00")).unwrap();
    assert_eq!(v.trades(&scope(), None).unwrap(), complete);
}

#[test]
fn scenario_configuration_order_is_canonical_and_rehashed_pending_command_swap_is_refused() {
    let cfg = json!({"latency":{"submit_ns":1},"simulation":{"submissions":[
        {"submission_index":1,"action":"reject_before_accepted","reason":"denied","rejection_code":"SCENARIO_REJECTED"},
        {"submission_index":2,"action":"accept_then_expire","reason":"EXPIRED_BY_SCENARIO"}]}});
    let mut reversed = cfg.clone();
    reversed["simulation"]["submissions"]
        .as_array_mut()
        .unwrap()
        .reverse();
    let mut v = venue(&cfg);
    let other = venue(&reversed);
    assert_eq!(
        v.checkpoint()["binding"]["configuration"],
        other.checkpoint()["binding"]["configuration"]
    );
    for id in ["first", "second"] {
        v.dispatch(&submit(id)).unwrap();
    }
    let cut = v.checkpoint();
    assert_eq!(cut["pending_actions"][0]["command"], "first");
    assert_eq!(cut["pending_actions"][1]["command"], "second");
    let mut forged = cut.clone();
    forged["pending_actions"][0]["command"] = json!("second");
    forged["pending_actions"][1]["command"] = json!("first");
    assert_eq!(
        reopen_cut(&cfg, &forged).err(),
        Some(Error::new("VIRTUAL_CHECKPOINT_STATE_CONFLICT"))
    );
    let mut changed_binding = cut.clone();
    let controls = changed_binding["binding"]["configuration"]["controls"]
        .as_array_mut()
        .unwrap();
    assert_eq!(controls[0]["action"], "REJECT_BEFORE_ACCEPTED");
    controls[0]["action"] = json!("ACCEPT_THEN_EXPIRE");
    controls[0]["rejection_code"] = Value::Null;
    assert_eq!(
        reopen_cut(&cfg, &changed_binding).err(),
        Some(Error::new("VIRTUAL_CHECKPOINT_BINDING"))
    );
    let mut restored = reopen_cut(&reversed, &cut).unwrap();
    restored.advance(1).unwrap();
    let orders = queries(&restored);
    assert_eq!(orders[0]["order"], "order-first");
    assert_eq!(orders[0]["status"], "REJECTED");
    assert_eq!(orders[1]["order"], "order-second");
    assert_eq!(orders[1]["status"], "EXPIRED");
}
#[derive(Default)]
struct Memory {
    rows: Vec<Record>,
    fail: bool,
}
impl Journal for Memory {
    fn records(&self) -> Result<Vec<Record>, Error> {
        Ok(self.rows.clone())
    }
    fn append(&mut self, i: &AppendIntent) -> Result<(), Error> {
        self.rows.push(Record::new(i));
        if std::mem::take(&mut self.fail) {
            Err(Error::new("COMMIT_UNKNOWN"))
        } else {
            Ok(())
        }
    }
}
#[test]
fn ack_reservation_delayed_publish_and_fresh_restore() {
    let cfg = json!({"latency":{"fill_ns":60_000_000_000_i64}});
    let mut v = venue(&cfg);
    v.on_bar(1, &bar(0, "9.00")).unwrap();
    let c = submit("s");
    assert_eq!(v.dispatch(&c).unwrap(), DispatchResult::Received);
    assert!(v.orders(&scope(), false).is_err());
    v.advance(v.now()).unwrap();
    assert_eq!(
        v.account(&scope()).unwrap().record()["payload"]["order_reserved_cash"]["amount"],
        "1000.00"
    );
    let mut j = Memory::default();
    let mut broker = Broker::recover(scope(), &j, 1).unwrap();
    assert_eq!(v.publish(&mut broker, &mut j).unwrap(), 1);
    v.on_bar(2, &bar(1, "9.00")).unwrap();
    assert_eq!(v.trades(&scope(), None).unwrap().len(), 1);
    assert_eq!(v.publish(&mut broker, &mut j).unwrap(), 0);
    let original = v.checkpoint();
    let sha = digest(&original);
    let mut r =
        VirtualBroker::restore(scope(), &"b".repeat(64), cash(), &cfg, &original, &sha).unwrap();
    assert_eq!(
        r.account(&scope()).unwrap().record()["payload"]["ledger_cash"]["amount"],
        "99000.00"
    );
    r.advance(r.now() + 60_000_000_000).unwrap();
    assert!(r.publish(&mut broker, &mut j).is_err());
    let accepted = broker.pending()[0].identity().to_owned();
    let reader = Reader::applied_accept(&c);
    broker.acknowledge(&mut j, &reader, &accepted).unwrap();
    let before = r.checkpoint();
    j.fail = true;
    assert!(r.publish(&mut broker, &mut j).is_err());
    assert_eq!(r.checkpoint(), before);
    let mut broker = Broker::recover(scope(), &j, 1).unwrap();
    assert_eq!(r.publish(&mut broker, &mut j).unwrap(), 1);
    assert_eq!(broker.pending().len(), 1);
    assert_eq!(
        broker.pending()[0].identity(),
        r.trades(&scope(), None).unwrap()[0].identity()
    );
    assert_eq!(r.publish(&mut broker, &mut j).unwrap(), 0);
    assert_eq!(r.trades(&scope(), None).unwrap().len(), 1);
    for (artifact, cfg, cut, expected) in [
        ("c".repeat(64), cfg.clone(), original.clone(), sha.clone()),
        ("b".repeat(64), json!({}), original.clone(), sha.clone()),
        (
            "b".repeat(64),
            cfg.clone(),
            original.clone(),
            "c".repeat(64),
        ),
    ] {
        assert!(VirtualBroker::restore(scope(), &artifact, cash(), &cfg, &cut, &expected).is_err());
    }
    let mut corrupt = original.clone();
    corrupt["orders"][0]["plan"]["cursor"] = json!(0);
    assert!(
        VirtualBroker::restore(
            scope(),
            &"b".repeat(64),
            cash(),
            &cfg,
            &corrupt,
            &digest(&corrupt)
        )
        .is_err()
    );
}

fn change(c: &BrokerCommand, edit: impl FnOnce(&mut Value)) -> BrokerCommand {
    let mut row = c.record();
    edit(&mut row);
    BrokerCommand::decode(&row).unwrap()
}
fn cancel(c: &BrokerCommand) -> BrokerCommand {
    BrokerCommand::decode(&json!({"schema_version":1,"scope":scope().record(),"operation":"CANCEL","command_id":"cancel",
        "order":c.order(),"client":c.client(),"request":{"schema_version":1,"request_id":{"schema_version":1,"value":"cancel-request"},
        "order_id":{"schema_version":1,"value":c.order()},"reason":"user","metadata":{}}})).unwrap()
}
#[test]
fn same_bar_steps_wait_for_price_then_cancel_preserves_both_distinct_fills() {
    let cfg = json!({"matching":{"partial_fill":{"mode":"SCHEDULE","dispatch_mode":"ALL_DUE","steps":[
        {"bar_offset":1,"quantity":"30"},{"bar_offset":1,"quantity":"40"},{"bar_offset":2,"quantity":"30"}]}}});
    let mut v = venue(&cfg);
    let c = change(&submit("s"), |r| {
        r["request"]["price"]["value"] = json!("9.80")
    });
    v.on_bar(1, &bar(0, "9.00")).unwrap();
    v.dispatch(&c).unwrap();
    v.advance(v.now()).unwrap();
    v.on_bar(2, &bar(1, "9.90")).unwrap();
    assert!(v.trades(&scope(), None).unwrap().is_empty());
    // ALL_DUE 此时三步都已到期，用下一次有资格 Bar 一次完成。
    v.on_bar(3, &bar(2, "9.70")).unwrap();
    let trades = v.trades(&scope(), None).unwrap();
    assert_eq!(
        trades
            .iter()
            .map(|f| f.record()["payload"]["fill"]["quantity"]["value"].clone())
            .collect::<Vec<_>>(),
        [json!("30"), json!("40"), json!("30")]
    );
    assert_eq!(queries(&v)[0]["status"], "FILLED");
    let mut v = venue(&cfg);
    v.on_bar(1, &bar(0, "9.00")).unwrap();
    v.dispatch(&c).unwrap();
    v.advance(v.now()).unwrap();
    v.on_bar(2, &bar(1, "9.70")).unwrap();
    let fills = v.trades(&scope(), None).unwrap();
    assert_eq!(fills.len(), 2);
    assert_ne!(fills[0].identity(), fills[1].identity());
    assert_eq!(
        fills[1].record()["source_sequence"].as_u64(),
        fills[0].record()["source_sequence"].as_u64().map(|n| n + 1)
    );
    let cut = v.checkpoint();
    let id = digest(&cut);
    let mut v = VirtualBroker::restore(scope(), &"b".repeat(64), cash(), &cfg, &cut, &id).unwrap();
    v.connect().unwrap();
    v.authenticate().unwrap();
    v.dispatch(&cancel(&c)).unwrap();
    v.advance(v.now()).unwrap();
    v.on_bar(3, &bar(2, "9.70")).unwrap();
    assert_eq!(queries(&v)[0]["status"], "CANCELLED");
    assert_eq!(queries(&v)[0]["filled"], "70");
    assert_eq!(v.trades(&scope(), None).unwrap(), fills);
    assert_eq!(
        v.account(&scope()).unwrap().record()["payload"]["order_reserved_cash"]["amount"],
        "0.00"
    );
}

#[test]
fn one_per_bar_catches_up_one_step_and_continues_original_plan_after_restart() {
    let cfg = json!({"maximum_fill_quantity":"40"});
    let mut v = venue(&cfg);
    let c = submit("s");
    v.on_bar(1, &bar(0, "9.00")).unwrap();
    v.dispatch(&c).unwrap();
    v.advance(v.now()).unwrap();
    v.on_bar(2, &bar(1, "9.00")).unwrap();
    let cut = v.checkpoint();
    let hash = digest(&cut);
    assert_eq!(cut["orders"][0]["plan"]["version"], 2);
    assert_eq!(queries(&v)[0]["status"], "PARTIALLY_FILLED");
    let mut v =
        VirtualBroker::restore(scope(), &"b".repeat(64), cash(), &cfg, &cut, &hash).unwrap();
    for i in 2..4 {
        v.on_bar(i as u64 + 1, &bar(i, "9.00")).unwrap();
    }
    assert_eq!(
        v.trades(&scope(), None)
            .unwrap()
            .iter()
            .map(|f| f.record()["payload"]["fill"]["quantity"]["value"].clone())
            .collect::<Vec<_>>(),
        [json!("40"), json!("40"), json!("20")]
    );
    assert_eq!(
        v.checkpoint()["orders"][0]["plan"]["id"],
        cut["orders"][0]["plan"]["id"]
    );
    assert_eq!(queries(&v)[0]["status"], "FILLED");
}
#[test]
fn delayed_original_submission_controls_keep_order_without_reservations() {
    let cfg = json!({"latency":{"submit_ns":1,"acceptance_ns":2},"simulation":{"submissions":[
        {"submission_index":2,"action":"accept_then_expire","reason":"EXPIRED_BY_SCENARIO"},
        {"submission_index":1,"action":"reject_before_accepted","reason":"denied","rejection_code":"SCENARIO_REJECTED"}]}});
    let mut v = venue(&cfg);
    v.dispatch(&submit("z")).unwrap();
    v.dispatch(&submit("a")).unwrap();
    v.advance(2).unwrap();
    assert!(v.orders(&scope(), false).is_err());
    let cut = v.checkpoint();
    let mut r = VirtualBroker::restore(scope(), &"b".repeat(64), cash(), &cfg, &cut, &digest(&cut))
        .unwrap();
    r.advance(3).unwrap();
    let facts = r.checkpoint()["facts"].as_array().unwrap().clone();
    assert_eq!(
        facts.iter().map(|f| f["kind"].clone()).collect::<Vec<_>>(),
        [json!("REJECTED"), json!("ACCEPTED"), json!("EXPIRED")]
    );
    assert!(
        facts[0]["payload"]["reason"]
            .as_str()
            .unwrap()
            .contains("SCENARIO_REJECTED")
    );
    let o = queries(&r);
    assert_eq!(o[0]["order"], "order-z");
    assert_eq!(o[1]["order"], "order-a");
    assert_eq!(o[0]["status"], "REJECTED");
    assert_eq!(o[1]["status"], "EXPIRED");
    assert_eq!(
        r.checkpoint()["orders"][1]["detail"]["reason"],
        "EXPIRED_BY_SCENARIO"
    );
    assert!(r.orders(&scope(), true).unwrap().is_empty());
    assert!(r.trades(&scope(), None).unwrap().is_empty());
    assert_eq!(
        r.account(&scope()).unwrap().record()["payload"]["order_reserved_cash"]["amount"],
        "0.00"
    );
}
#[test]
fn market_price_slips_exactly_and_short_close_uses_venue_position() {
    let cfg = json!({"slippage":{"type":"FIXED","price_offset":"0.01"}});
    let mut v = venue(&cfg);
    v.on_bar(1, &bar(0, "9.00")).unwrap();
    let market = |name, side: &str, effect: &str| {
        change(&submit(name), |r| {
            let q = &mut r["request"];
            q["side"] = json!(side);
            q["offset"] = json!(effect);
            q["order_type"] = json!("MARKET");
            q["price"] = Value::Null;
            q["execution_intent"]["position_side"] = json!("SHORT");
            q["execution_intent"]["side"] = json!(side);
            q["execution_intent"]["position_effect"] = json!(effect);
        })
    };
    v.dispatch(&market("a", "SELL", "OPEN")).unwrap();
    v.advance(v.now()).unwrap();
    v.on_bar(2, &bar(1, "9.00")).unwrap();
    let p = v.positions(&scope()).unwrap()[0].record();
    assert_eq!(p["payload"]["side"], "SHORT");
    assert_eq!(p["payload"]["available"]["value"], "100");
    let first = v.trades(&scope(), None).unwrap()[0].record();
    assert_eq!(first["payload"]["fill"]["price"]["value"], "9.99000000");
    v.dispatch(&market("b", "BUY", "CLOSE")).unwrap();
    v.advance(v.now()).unwrap();
    v.on_bar(3, &bar(2, "9.00")).unwrap();
    let trades = v.trades(&scope(), None).unwrap();
    assert_eq!(
        trades[1].record()["payload"]["fill"]["price"]["value"],
        "10.01000000"
    );
    assert_eq!(
        v.positions(&scope()).unwrap()[0].record()["payload"]["quantity"]["value"],
        "0"
    );
    assert_eq!(
        v.account(&scope()).unwrap().record()["payload"]["ledger_cash"]["amount"],
        "99998.00"
    );
}

#[test]
fn exact_owner_content_and_bar_identity_fail_closed() {
    let mut v = venue(&json!({}));
    let c = submit("a");
    v.dispatch(&c).unwrap();
    let first_cut = v.checkpoint();
    assert_eq!(v.dispatch(&c).unwrap(), DispatchResult::Received);
    assert_eq!(v.checkpoint(), first_cut);
    for changed in [
        change(&c, |r| r["request"]["quantity"]["value"] = json!("101")),
        change(&c, |r| {
            r["command_id"] = json!("new");
            r["client"] = json!("other");
        }),
        change(&c, |r| {
            r["command_id"] = json!("new");
            r["order"] = json!("other");
        }),
        change(&c, |r| r["scope"]["generation"] = json!("d".repeat(64))),
    ] {
        assert!(v.dispatch(&changed).is_err());
        assert_eq!(v.checkpoint(), first_cut);
    }
    let mut foreign = scope().record();
    foreign["engine"] = json!("other");
    let foreign = Scope::decode(&foreign).unwrap();
    assert!(v.orders(&foreign, false).is_err());
    assert!(
        VirtualBroker::restore(
            foreign,
            &"b".repeat(64),
            cash(),
            &json!({}),
            &first_cut,
            &digest(&first_cut)
        )
        .is_err()
    );
    let b = bar(0, "9.00");
    v.on_bar(1, &b).unwrap();
    let cut = v.checkpoint();
    v.on_bar(1, &b).unwrap();
    assert!(v.on_bar(2, &b).is_err());
    assert!(v.on_bar(1, &bar(0, "9.20")).is_err());
    assert!(v.advance(v.now() - 1).is_err());
    assert_eq!(v.checkpoint(), cut);
    let mut old = cut.clone();
    old["schema_version"] = json!(3);
    assert!(
        VirtualBroker::restore(
            scope(),
            &"b".repeat(64),
            cash(),
            &json!({}),
            &old,
            &digest(&old)
        )
        .is_err()
    );
    let mut live = scope().record();
    live["runtime_kind"] = json!("LIVE");
    assert!(
        VirtualBroker::new(
            Scope::decode(&live).unwrap(),
            &"b".repeat(64),
            cash(),
            &json!({})
        )
        .is_err()
    );
}

#[test]
fn invalid_or_contradictory_configurations_are_rejected_at_creation() {
    for cfg in [
        json!({"matching":{"type":"IMMEDIATE"}}),
        json!({"slippage":{"type":"RANDOM"}}),
        json!({"latency":{"submit_ns":-1}}),
        json!({"simulation":{"submissions":[{"submission_index":0,"action":"REJECT_BEFORE_ACCEPTED"}]}}),
        json!({"simulation":{"submissions":[{"submission_index":1,"action":"REJECT_RANDOMLY"}]}}),
        json!({"simulation":{"submissions":[{"submission_index":1,"action":"ACCEPT_THEN_EXPIRE","rejection_code":"bad"}]}}),
        json!({"simulation":{"submissions":[{"submission_index":1,"action":"ACCEPT_THEN_EXPIRE"},{"submission_index":1,"action":"ACCEPT_THEN_EXPIRE"}]}}),
        json!({"maximum_fill_quantity":"10","matching":{"maximum_fill_quantity":"11"}}),
    ] {
        assert!(VirtualBroker::new(scope(), &"b".repeat(64), cash(), &cfg).is_err());
    }
}

#[derive(Default)]
struct Reader {
    view: Option<OrderView>,
    receipts: Vec<(Fact, ApplicationReceipt)>,
}
impl Reader {
    // 由原委托和场所第一个订单的固定身份构建本地预期，不读 venue 的查询投影。
    fn applied_accept(c: &BrokerCommand) -> Self {
        let venue = "virtual-order-00000001";
        let fact = Fact::decode(
            &json!({"scope":c.scope().record(),"session":"independent-runtime",
            "update_id":"committed-accept","source_sequence":1,"ts_event":0,"ts_init":0,
            "correlation":c.order(),"causation":c.id(),"quality":[],"kind":"ACCEPTED",
            "payload":{"order":c.order(),"venue":venue}}),
        )
        .unwrap();
        let receipt = ApplicationReceipt::new(
            &fact,
            "applied".into(),
            "c".repeat(64),
            ApplicationStatus::Applied,
        )
        .unwrap();
        let view = OrderView::decode(
            &json!({"scope":c.scope().record(),"order":c.order(),"client":c.client(),
            "venue":venue,"request":c.record()["request"],"filled":"0","status":"ACCEPTED"}),
        )
        .unwrap();
        Self {
            view: Some(view),
            receipts: vec![(fact, receipt)],
        }
    }
}
impl RuntimeReader for Reader {
    fn ready_intent(&self, c: &BrokerCommand) -> Result<ReadyIntent, Error> {
        ReadyIntent::new(c.clone(), "tx".into(), "f".repeat(64))
    }
    fn application_receipt(&self, f: &Fact) -> Result<Option<ApplicationReceipt>, Error> {
        Ok(self
            .receipts
            .iter()
            .find(|(expected, _)| {
                expected.scope() == f.scope()
                    && expected.identity() == f.identity()
                    && expected.fingerprint() == f.fingerprint()
            })
            .map(|(_, receipt)| receipt.clone()))
    }
    fn order_view(&self, _: &BrokerCommand) -> Result<Option<OrderView>, Error> {
        Ok(self.view.clone())
    }
}
struct LostAck<'a>(&'a mut VirtualBroker, DispatchResult);
impl TradingPort for LostAck<'_> {
    fn capabilities(&self) -> Capabilities {
        self.0.capabilities()
    }
    fn dispatch(&mut self, c: &BrokerCommand) -> Result<DispatchResult, Error> {
        assert_eq!(self.0.dispatch(c)?, self.1);
        Err(Error::new("LOST_ACK"))
    }
}
#[test]
fn unknown_submit_is_queried_and_resolved_only_with_the_original_facts_and_receipts() {
    let cfg = json!({});
    let mut v = venue(&cfg);
    let mut j = Memory::default();
    let mut b = Broker::recover(scope(), &j, 8).unwrap();
    b.set_connection(Connection::Ready);
    b.set_health(true, true, true);
    let mut reader = Reader::default();
    let c = submit("original");
    assert_eq!(
        b.dispatch(
            &mut j,
            &reader,
            &mut LostAck(&mut v, DispatchResult::Received),
            &c
        )
        .unwrap(),
        CommandState::Unknown
    );
    let cut = v.checkpoint();
    let expected = digest(&cut);
    let mut v =
        VirtualBroker::restore(scope(), &"b".repeat(64), cash(), &cfg, &cut, &expected).unwrap();
    let mut b = Broker::recover(scope(), &j, 8).unwrap();
    assert_eq!(
        b.dispatch(&mut j, &reader, &mut v, &c).unwrap(),
        CommandState::Unknown
    );
    assert_eq!(v.checkpoint(), cut);
    v.reconcile(&mut b, &mut j, c.id()).unwrap();
    assert!(v.resolve(&mut b, &mut j, &reader, c.id()).is_err());
    v.advance(0).unwrap();
    v.reconcile(&mut b, &mut j, c.id()).unwrap();
    assert_eq!(b.pending().len(), 1);
    assert!(v.resolve(&mut b, &mut j, &reader, c.id()).is_err());
    reader = Reader::applied_accept(&c);
    v.resolve(&mut b, &mut j, &reader, c.id()).unwrap();
    assert_eq!(b.command_state(c.id()), Some(CommandState::Resolved));
    assert!(b.pending().is_empty());
    assert_eq!(v.orders(&scope(), false).unwrap().len(), 1);
}
#[test]
fn same_day_long_sell_reserves_quantity_and_releases_only_unfilled_units() {
    let mut v = venue(&json!({"maximum_fill_quantity":"40"}));
    let buy = submit("buy");
    v.dispatch(&buy).unwrap();
    v.advance(0).unwrap();
    for min in 0..3 {
        v.on_bar(min as u64 + 1, &bar(min, "9.00")).unwrap();
    }
    let sell = change(&submit("sell"), |r| {
        let q = &mut r["request"];
        q["side"] = json!("SELL");
        q["offset"] = json!("CLOSE");
        q["execution_intent"]["side"] = json!("SELL");
        q["execution_intent"]["position_effect"] = json!("CLOSE");
    });
    v.dispatch(&sell).unwrap();
    v.advance(v.now()).unwrap();
    assert_eq!(
        v.positions(&scope()).unwrap()[0].record()["payload"]["frozen"]["value"],
        "100"
    );
    v.on_bar(4, &bar(3, "9.00")).unwrap();
    v.dispatch(&cancel(&sell)).unwrap();
    v.advance(v.now()).unwrap();
    let p = v.positions(&scope()).unwrap()[0].record();
    assert_eq!(p["payload"]["available"]["value"], "60");
    assert_eq!(p["payload"]["frozen"]["value"], "0");
    let capability = v.capabilities();
    let fees = fee_evidence_port(&capability, Some(&v)).unwrap();
    assert!(
        fees.fee_evidence(&scope(), sell.order())
            .unwrap()
            .is_empty()
    );
}

#[test]
fn limit_price_caps_slippage_and_market_without_a_reference_is_rejected() {
    let cfg = json!({"slippage":{"type":"FIXED","price_offset":"1.00"}});
    let mut v = venue(&cfg);
    let absent = change(&submit("market"), |r| {
        r["request"]["order_type"] = json!("MARKET");
        r["request"]["price"] = Value::Null;
    });
    v.dispatch(&absent).unwrap();
    v.advance(0).unwrap();
    assert_eq!(queries(&v)[0]["status"], "REJECTED");
    v.dispatch(&submit("limit")).unwrap();
    v.advance(0).unwrap();
    v.on_bar(1, &bar(0, "9.00")).unwrap();
    let fill = v.trades(&scope(), None).unwrap()[0].record();
    assert_eq!(fill["payload"]["fill"]["price"]["value"], "10.00000000");
}

fn marked(min: u8, close: &str, instrument: &Value) -> OnlyBar {
    let mut b = bar(min, "9.00").to_record();
    b["bar_type"]["instrument_id"] = instrument.clone();
    b["close"]["value"] = json!(close);
    OnlyBar::from_record(&b).unwrap()
}

#[test]
fn short_equity_tracks_only_unrealized_profit_and_realizes_once_at_close() {
    let cfg = json!({});
    let mut v = venue(&cfg);
    let short = change(&submit("short"), |r| {
        let q = &mut r["request"];
        q["side"] = json!("SELL");
        q["offset"] = json!("OPEN");
        q["execution_intent"]["side"] = json!("SELL");
        q["execution_intent"]["position_side"] = json!("SHORT");
    });
    let inst = short.record()["request"]["instrument_id"].clone();
    let equity = |v: &VirtualBroker| {
        v.account(&scope()).unwrap().record()["payload"]["equity"]["amount"].clone()
    };
    v.dispatch(&short).unwrap();
    v.advance(0).unwrap();
    v.on_bar(1, &marked(0, "10.00", &inst)).unwrap();
    assert_eq!(equity(&v), "100000.00");
    v.on_bar(2, &marked(1, "11.00", &inst)).unwrap();
    assert_eq!(equity(&v), "99900.00");
    let close = change(&submit("close-short"), |r| {
        let q = &mut r["request"];
        q["price"]["value"] = json!("9.00");
        q["offset"] = json!("CLOSE");
        q["execution_intent"]["position_side"] = json!("SHORT");
        q["execution_intent"]["position_effect"] = json!("CLOSE");
    });
    v.dispatch(&close).unwrap();
    v.advance(v.now()).unwrap();
    v.on_bar(3, &marked(2, "9.00", &inst)).unwrap();
    assert_eq!(equity(&v), "100100.00");
    assert_eq!(
        v.account(&scope()).unwrap().record()["payload"]["ledger_cash"]["amount"],
        "100100.00"
    );

    // 两个标的的多空投影分开；0.005 货币单位按 HALF_EVEN 在账户精度舍入。
    let mut v = venue(&cfg);
    let long = change(&submit("long"), |r| {
        r["request"]["instrument_id"]["symbol"]["value"] = json!("SECOND");
        r["request"]["quantity"]["value"] = json!("1");
        r["request"]["price"] = json!({"schema_version":1,"value":"10.005","precision":3});
    });
    v.dispatch(&short).unwrap();
    v.dispatch(&long).unwrap();
    v.advance(0).unwrap();
    v.on_bar(1, &marked(0, "11.00", &inst)).unwrap();
    let second = long.record()["request"]["instrument_id"].clone();
    v.on_bar(2, &marked(1, "11.00", &second)).unwrap();
    assert_eq!(
        v.account(&scope()).unwrap().record()["payload"]["ledger_cash"]["amount"],
        "99990.00"
    );
    assert_eq!(equity(&v), "99901.00");
}

#[test]
fn rejected_submit_still_binds_its_original_order_client_and_request() {
    let mut v = venue(&json!({}));
    let rejected = change(&submit("first"), |r| {
        r["request"]["time_in_force"] = json!("IOC")
    });
    assert_eq!(v.dispatch(&rejected).unwrap(), DispatchResult::Rejected);
    let cut = v.checkpoint();
    assert_eq!(v.dispatch(&rejected).unwrap(), DispatchResult::Rejected);
    assert!(v.orders(&scope(), false).unwrap().is_empty());
    for alias in [
        change(&submit("next"), |r| r["order"] = json!(rejected.order())),
        change(&submit("next"), |r| r["client"] = json!(rejected.client())),
        change(&submit("next"), |r| {
            r["request"]["request_id"] = rejected.record()["request"]["request_id"].clone()
        }),
        change(&rejected, |r| r["request"]["time_in_force"] = json!("GTC")),
    ] {
        assert!(v.dispatch(&alias).is_err());
        assert_eq!(v.checkpoint(), cut);
    }
}

#[test]
fn usdt_precision_eight_zero_holds_and_small_fills_use_typed_records() {
    let money = OnlyMoney::from_record(&json!({"schema_version":1,"amount":"1.00000000",
        "currency":{"schema_version":1,"code":"USDT","precision":8,"currency_type":"CRYPTO"}}))
    .unwrap();
    let mut v = VirtualBroker::new(scope(), &"b".repeat(64), money, &json!({})).unwrap();
    v.connect().unwrap();
    v.authenticate().unwrap();
    assert_eq!(
        v.account(&scope()).unwrap().record()["payload"]["order_reserved_cash"]["amount"],
        "0E-8"
    );
    let c = change(&submit("tiny"), |r| {
        r["request"]["quantity"] = json!({"schema_version":1,"value":"1E-8","precision":8})
    });
    v.dispatch(&c).unwrap();
    v.advance(0).unwrap();
    assert_eq!(
        v.account(&scope()).unwrap().record()["payload"]["order_reserved_cash"]["amount"],
        "1.0E-7"
    );
    v.on_bar(1, &bar(0, "9.00")).unwrap();
    let fill = v.trades(&scope(), None).unwrap()[0].record();
    assert_eq!(fill["payload"]["fill"]["quantity"]["value"], "1E-8");
    let p = v.positions(&scope()).unwrap()[0].record();
    assert_eq!(p["payload"]["available"]["value"], "1E-8");
    assert_eq!(p["payload"]["frozen"]["value"], "0E-8");
    assert_eq!(
        v.account(&scope()).unwrap().record()["payload"]["ledger_cash"]["amount"],
        "0.99999990"
    );
}

#[test]
fn due_callback_observes_advanced_clock_while_delayed_trade_keeps_original_bar_time() {
    let cfg = json!({"latency":{"acceptance_ns":3,"fill_ns":7}});
    let mut v = venue(&cfg);
    v.dispatch(&submit("advance")).unwrap();
    v.advance(7).unwrap();
    assert_eq!(v.checkpoint()["facts"][0]["ts_event"], 7);
    let mut journal = Memory::default();
    let mut broker = Broker::recover(scope(), &journal, 8).unwrap();
    v.publish(&mut broker, &mut journal).unwrap();
    v.on_bar(1, &bar(0, "9.00")).unwrap();
    let event = v.now();
    v.advance(event + 10).unwrap();
    v.publish(&mut broker, &mut journal).unwrap();
    assert_eq!(broker.pending()[1].record()["ts_event"], event);
    assert_eq!(
        broker.pending()[1].record()["payload"]["fill"]["ts_event"]["unix_nanos"],
        event
    );
}

#[test]
fn numeric_factory_decimals_preserve_exact_plan_and_configuration_identity() {
    // 通过原始 JSON 读取，长小数不能先经过二进制浮点转换。
    let cases = [
        (
            r#"{"maximum_fill_quantity":40,"slippage":{"type":"FIXED","price_offset":1e-2}}"#,
            json!({"maximum_fill_quantity":"40.00","slippage":{"type":"FIXED","price_offset":"0.01"}}),
        ),
        (
            r#"{"matching":{"partial_fill":{"mode":"SCHEDULE","steps":[{"bar_offset":1,"quantity":30},{"bar_offset":2,"quantity":70}]}}}"#,
            json!({"matching":{"partial_fill":{"mode":"SCHEDULE","steps":[{"bar_offset":1,"quantity":"30.00"},{"bar_offset":2,"quantity":"70"}]}}}),
        ),
        (
            r#"{"matching":{"partial_fill":{"mode":"SCHEDULE","steps":[{"bar_offset":1,"ratio":0.123456789012345678},{"bar_offset":2,"ratio":0.876543210987654322}]}}}"#,
            json!({"matching":{"partial_fill":{"mode":"SCHEDULE","steps":[{"bar_offset":1,"ratio":"0.123456789012345678"},{"bar_offset":2,"ratio":"0.876543210987654322"}]}}}),
        ),
    ];
    for (numeric, strings) in cases {
        let numeric: Value = serde_json::from_str(numeric).unwrap();
        let mut v = venue(&numeric);
        let mut expected = venue(&strings);
        for x in [&mut v, &mut expected] {
            x.dispatch(&submit("identical")).unwrap();
            x.advance(0).unwrap();
        }
        let actual = v.checkpoint();
        let reference = expected.checkpoint();
        assert_eq!(
            actual["binding"]["configuration"],
            reference["binding"]["configuration"]
        );
        assert_eq!(
            digest(&actual["binding"]["configuration"]),
            digest(&reference["binding"]["configuration"])
        );
        assert_eq!(actual["orders"][0]["plan"], reference["orders"][0]["plan"]);
        if numeric
            .pointer("/matching/partial_fill/steps/0/ratio")
            .is_some()
        {
            assert_eq!(
                actual["binding"]["configuration"]["fill"]["steps"][0]["ratio"],
                "0.123456789012345678"
            );
            assert_eq!(
                actual["orders"][0]["plan"]["steps"],
                json!([[1, "12"], [2, "88"]])
            );
        }
    }
}

#[test]
fn original_dispatch_outcome_and_identity_survive_disconnect_and_restore() {
    let cfg = json!({});
    let mut v = venue(&cfg);
    let received = submit("received");
    v.dispatch(&received).unwrap();
    v.advance(0).unwrap();
    let economics = v.account(&scope()).unwrap().record()["payload"].clone();
    v.disconnect().unwrap();
    let snapshot = v.checkpoint();
    assert_eq!(v.dispatch(&received).unwrap(), DispatchResult::Received);
    assert_eq!(v.checkpoint(), snapshot);
    assert!(
        v.dispatch(&change(&received, |r| r["scope"]["generation"] =
            json!("c".repeat(64))))
            .is_err()
    );
    let offline = submit("offline");
    assert_eq!(v.dispatch(&offline).unwrap(), DispatchResult::Rejected);
    let cut = v.checkpoint();
    for mut instance in [
        v,
        VirtualBroker::restore(scope(), &"b".repeat(64), cash(), &cfg, &cut, &digest(&cut))
            .unwrap(),
    ] {
        assert_eq!(
            instance.dispatch(&received).unwrap(),
            DispatchResult::Received
        );
        assert_eq!(
            instance.dispatch(&offline).unwrap(),
            DispatchResult::Rejected
        );
        for other in [
            change(&submit("new"), |r| r["order"] = json!(offline.order())),
            change(&submit("new"), |r| r["client"] = json!(offline.client())),
            change(&submit("new"), |r| {
                r["request"]["request_id"] = offline.record()["request"]["request_id"].clone()
            }),
            change(&offline, |r| {
                r["request"]["quantity"]["value"] = json!("50")
            }),
        ] {
            assert!(instance.dispatch(&other).is_err());
        }
        instance.connect().unwrap();
        instance.authenticate().unwrap();
        assert_eq!(
            instance.dispatch(&offline).unwrap(),
            DispatchResult::Rejected
        );
        assert_eq!(instance.checkpoint(), cut);
        assert_eq!(instance.trades(&scope(), None).unwrap().len(), 0);
        assert_eq!(instance.orders(&scope(), false).unwrap().len(), 1);
        assert_eq!(
            instance.account(&scope()).unwrap().record()["payload"],
            economics
        );
    }
}

#[test]
fn signed_fixed_slippage_preserves_price_improvement_limits_and_nonpositive_guard() {
    let request = |side: &str, kind: &str| {
        change(&submit("slip"), |r| {
            let q = &mut r["request"];
            q["order_type"] = json!(kind);
            if kind == "MARKET" {
                q["price"] = Value::Null;
            }
            q["offset"] = json!("OPEN");
            q["side"] = json!(side);
            q["execution_intent"]["side"] = json!(side);
            q["execution_intent"]["position_side"] =
                json!(if side == "BUY" { "LONG" } else { "SHORT" });
        })
    };
    for (side, kind, offset, expected) in [
        ("BUY", "MARKET", "-0.01", "9.99000000"),
        ("SELL", "MARKET", "-0.01", "10.01000000"),
        ("BUY", "LIMIT", "-0.01", "9.99000000"),
        ("SELL", "LIMIT", "-0.01", "10.01000000"),
        ("BUY", "LIMIT", "0.01", "10.00000000"),
        ("SELL", "LIMIT", "0.01", "10.00000000"),
    ] {
        let mut v = venue(&json!({"slippage":{"type":"FIXED","price_offset":offset}}));
        v.on_bar(1, &bar(0, "9.00")).unwrap();
        v.dispatch(&request(side, kind)).unwrap();
        v.advance(v.now()).unwrap();
        v.on_bar(2, &bar(1, "9.00")).unwrap();
        assert_eq!(
            v.trades(&scope(), None).unwrap()[0].record()["payload"]["fill"]["price"]["value"],
            expected
        );
    }
    let mut v = venue(&json!({"slippage":{"type":"FIXED","price_offset":"-10.00"}}));
    v.on_bar(1, &bar(0, "9.00")).unwrap();
    v.dispatch(&request("BUY", "MARKET")).unwrap();
    v.advance(v.now()).unwrap();
    let before = v.checkpoint();
    assert!(v.on_bar(2, &bar(1, "9.00")).is_err());
    assert_eq!(v.checkpoint(), before);
    assert!(v.trades(&scope(), None).unwrap().is_empty());
}

#[test]
fn optional_factory_nulls_preserve_defaults_and_none_validates_ignored_offset() {
    let binding = |cfg: &Value| venue(cfg).checkpoint()["binding"].clone();
    assert_eq!(
        binding(&json!({"matching":{"partial_fill":null}})),
        binding(&json!({}))
    );
    assert_eq!(
        binding(&json!({"slippage":{"type":"FIXED","price_offset":null}})),
        binding(&json!({"slippage":{"type":"FIXED","price_offset":"0"}}))
    );
    for offset in [Value::Null, json!("-0.01"), json!(1)] {
        assert_eq!(
            binding(&json!({"slippage":{"type":"NONE","price_offset":offset}})),
            binding(&json!({}))
        );
    }
    for offset in [json!("NaN"), json!({}), json!("1e9999999999")] {
        assert!(
            VirtualBroker::new(
                scope(),
                &"b".repeat(64),
                cash(),
                &json!({"slippage":{"type":"NONE","price_offset":offset}})
            )
            .is_err()
        );
    }
}

#[test]
fn cancellation_due_before_acceptance_is_terminal_after_restart() {
    let cfg = json!({"latency":{"acceptance_ns":10,"cancel_ns":2}});
    let mut v = venue(&cfg);
    let c = submit("early");
    v.dispatch(&c).unwrap();
    v.dispatch(&cancel(&c)).unwrap();
    v.advance(2).unwrap();
    assert_eq!(queries(&v)[0]["status"], "CANCELLED");
    assert_eq!(v.checkpoint()["orders"][0]["plan"], Value::Null);
    let cut = v.checkpoint();
    let mut r = VirtualBroker::restore(scope(), &"b".repeat(64), cash(), &cfg, &cut, &digest(&cut))
        .unwrap();
    r.advance(10).unwrap();
    r.on_bar(1, &bar(0, "9.00")).unwrap();
    let journal = r.checkpoint()["facts"].clone();
    assert_eq!(journal.as_array().unwrap().len(), 1);
    assert_eq!(journal[0]["kind"], "CANCELLED");
    assert_eq!(queries(&r)[0]["status"], "CANCELLED");
    assert!(r.trades(&scope(), None).unwrap().is_empty());
    assert_eq!(
        r.account(&scope()).unwrap().record()["payload"]["ledger_cash"]["amount"],
        "100000.00"
    );
    assert_eq!(
        r.account(&scope()).unwrap().record()["payload"]["order_reserved_cash"]["amount"],
        "0.00"
    );
}

fn reconcile_original_rejected_cancel(terminal: bool) {
    let cfg = if terminal {
        json!({"simulation":{"submissions":[{"submission_index":1,"action":"ACCEPT_THEN_EXPIRE"}]}})
    } else {
        json!({})
    };
    let mut v = venue(&cfg);
    let mut journal = Memory::default();
    let mut broker = Broker::recover(scope(), &journal, 8).unwrap();
    broker.set_connection(Connection::Ready);
    broker.set_health(true, true, true);
    let order = submit("original-order");
    let cancellation = cancel(&order);
    assert_eq!(
        broker
            .dispatch(&mut journal, &Reader::default(), &mut v, &order)
            .unwrap(),
        CommandState::Known
    );
    v.advance(0).unwrap();
    if !terminal {
        v.disconnect().unwrap();
    }
    assert_eq!(
        broker
            .dispatch(
                &mut journal,
                &Reader::default(),
                &mut LostAck(&mut v, DispatchResult::Rejected),
                &cancellation
            )
            .unwrap(),
        CommandState::Unknown
    );

    let cut = v.checkpoint();
    let mut v = VirtualBroker::restore(scope(), &"b".repeat(64), cash(), &cfg, &cut, &digest(&cut))
        .unwrap();
    let mut broker = Broker::recover(scope(), &journal, 8).unwrap();
    // 同一个 command_id 的查询关系不得通过改 Scope、order、client 或载荷来重绑定。
    for changed in [
        change(&cancellation, |r| {
            r["scope"]["generation"] = json!("f".repeat(64))
        }),
        change(&cancellation, |r| {
            r["order"] = json!("other");
            r["request"]["order_id"]["value"] = json!("other");
        }),
        change(&cancellation, |r| r["client"] = json!("other")),
        change(&cancellation, |r| r["request"]["reason"] = json!("changed")),
    ] {
        assert!(
            broker
                .dispatch(&mut journal, &Reader::default(), &mut v, &changed)
                .is_err()
        );
    }
    v.reconcile(&mut broker, &mut journal, cancellation.id())
        .unwrap();
    assert_eq!(broker.pending().len(), if terminal { 2 } else { 1 });
    assert!(
        v.resolve(
            &mut broker,
            &mut journal,
            &Reader::default(),
            cancellation.id()
        )
        .is_err()
    );

    let mut reader = Reader::applied_accept(&order);
    if terminal {
        let expired=Fact::decode(&json!({"scope":scope().record(),"session":"independent-runtime","update_id":"expiry-observation",
            "source_sequence":2,"ts_event":0,"ts_init":0,"correlation":order.order(),"causation":order.id(),"quality":[],
            "kind":"EXPIRED","payload":{"order":order.order(),"venue":"virtual-order-00000001","reason":""}})).unwrap();
        let receipt = ApplicationReceipt::new(
            &expired,
            "expiry-applied".into(),
            "d".repeat(64),
            ApplicationStatus::Applied,
        )
        .unwrap();
        let mut view = reader.view.as_ref().unwrap().record();
        view["status"] = json!("EXPIRED");
        reader.view = Some(OrderView::decode(&view).unwrap());
        reader.receipts.push((expired, receipt));
    }
    v.resolve(&mut broker, &mut journal, &reader, cancellation.id())
        .unwrap();
    assert_eq!(
        broker.command_state(cancellation.id()),
        Some(CommandState::Resolved)
    );
    assert!(broker.pending().is_empty());
    assert_eq!(v.checkpoint(), cut);
}
#[test]
fn rejected_cancel_recovers_the_existing_open_order_after_lost_ack() {
    reconcile_original_rejected_cancel(false);
}
#[test]
fn rejected_cancel_recovers_the_existing_terminal_order_after_lost_ack() {
    reconcile_original_rejected_cancel(true);
}

#[test]
fn large_finite_weighted_average_and_short_close_preserve_the_half_cent_boundary() {
    let mut v = venue(&json!({}));
    // N=10^110；均价 (0.03N-0.01)/(2N) 严格小于 0.015。
    let first = format!("1{}1", "0".repeat(109));
    let second = "9".repeat(110);
    for (i, (id, units, price)) in [
        ("first", first.as_str(), "0.01"),
        ("second", second.as_str(), "0.02"),
    ]
    .into_iter()
    .enumerate()
    {
        let opening = change(&submit(id), |r| {
            let q = &mut r["request"];
            q["quantity"]["value"] = json!(units);
            q["price"]["value"] = json!(price);
            q["side"] = json!("SELL");
            q["offset"] = json!("OPEN");
            q["execution_intent"]["side"] = json!("SELL");
            q["execution_intent"]["position_side"] = json!("SHORT");
        });
        v.dispatch(&opening).unwrap();
        v.advance(v.now()).unwrap();
        v.on_bar(i as u64 + 1, &bar(i as u8, "0.01")).unwrap();
    }
    let avg =
        v.positions(&scope()).unwrap()[0].record()["payload"]["average_price"]["value"].clone();
    let close = change(&submit("close"), |r| {
        let q = &mut r["request"];
        q["offset"] = json!("CLOSE");
        q["price"]["value"] = json!("0.01");
        q["execution_intent"]["position_side"] = json!("SHORT");
        q["execution_intent"]["position_effect"] = json!("CLOSE");
    });
    v.dispatch(&close).unwrap();
    v.advance(v.now()).unwrap();
    v.on_bar(3, &bar(2, "0.01")).unwrap();
    let cash = v.account(&scope()).unwrap().record()["payload"]["ledger_cash"]["amount"].clone();
    assert_eq!((avg, cash), (json!("0.01"), json!("100000.00")));
}
