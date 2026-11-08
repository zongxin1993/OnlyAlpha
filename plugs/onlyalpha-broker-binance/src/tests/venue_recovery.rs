use super::*;
use onlyalpha_broker::*;
use onlyalpha_domain::{enums::OnlyCurrencyType, value::OnlyCurrency};
use onlyalpha_integration_contract::source::{Clock, SourceError};
use std::{
    cell::{Cell, RefCell},
    rc::Rc,
    sync::Arc,
};

struct Fixed;
impl Clock for Fixed {
    fn now_ns(&self) -> std::result::Result<i64, SourceError> {
        Ok(5_000_000_000)
    }
}
#[derive(Clone, Default)]
struct Log(Rc<RefCell<Vec<Record>>>, Rc<Cell<Option<(u64, bool)>>>);
impl Journal for Log {
    fn records(&self) -> Result<Vec<Record>> {
        Ok(self.0.borrow().clone())
    }
    fn append(&mut self, intent: &AppendIntent) -> Result<()> {
        let seq = self.0.borrow().len() as u64 + 1;
        if self.1.get() == Some((seq, false)) {
            return Err(err("STORE_UNAVAILABLE"));
        }
        self.0.borrow_mut().push(Record::new(intent));
        if self.1.get() == Some((seq, true)) {
            return Err(err("STORE_UNKNOWN"));
        }
        Ok(())
    }
}
#[derive(Clone, Default)]
struct Store(Rc<RefCell<Vec<Observation>>>);
impl ObservationStore for Store {
    fn len(&self, _: &str) -> Result<u64> {
        Ok(self.0.borrow().len() as u64)
    }
    fn read(&self, _: &str, n: u64) -> Result<Observation> {
        self.0
            .borrow()
            .get((n - 1) as usize)
            .cloned()
            .ok_or_else(|| err("MISSING"))
    }
    fn append(&self, r: &Observation) -> Result<()> {
        if self.0.borrow().len() as u64 + 1 != r.sequence {
            return Err(err("CONCURRENT_APPEND"));
        }
        self.0.borrow_mut().push(r.clone());
        Ok(())
    }
}
struct Runtime {
    view: RefCell<Option<OrderView>>,
    receipts: Cell<bool>,
    wrong: RefCell<Option<Fact>>,
    admitted: Cell<bool>,
}
impl RuntimeReader for Runtime {
    fn ready_intent(&self, c: &BrokerCommand) -> Result<ReadyIntent> {
        if !self.admitted.get() {
            return Err(err("RUNTIME_NOT_READY"));
        }
        ReadyIntent::new(c.clone(), format!("tx-{}", c.id()), "f".repeat(64))
    }
    fn application_receipt(&self, f: &Fact) -> Result<Option<ApplicationReceipt>> {
        if !self.receipts.get() {
            return Ok(None);
        }
        let wrong = self.wrong.borrow();
        ApplicationReceipt::new(
            wrong.as_ref().unwrap_or(f),
            "applied".into(),
            "b".repeat(64),
            ApplicationStatus::Applied,
        )
        .map(Some)
    }
    fn order_view(&self, _: &BrokerCommand) -> Result<Option<OrderView>> {
        Ok(self.view.borrow().clone())
    }
}
#[derive(Default)]
struct State {
    order: RefCell<Value>,
    submit_ack: RefCell<Option<Value>>,
    account_balances: RefCell<Option<Value>>,
    trades: RefCell<Vec<Value>>,
    frames: RefCell<Vec<Value>>,
    calls: RefCell<Vec<String>>,
    seq: Cell<u64>,
    lose_submit: Cell<bool>,
    lose_cancel: Cell<bool>,
}
struct Fake(Rc<State>);
impl Exchange for Fake {
    fn preflight(&self, _: &Budget) -> Result<()> {
        Ok(())
    }
    fn close(&self) {}
    fn subscribe(&self, id: &str, _: &Budget) -> Result<Vec<u8>> {
        let n = self.0.seq.get() + 1;
        self.0.seq.set(n);
        Ok(json!({"id":id,"status":200,"result":{"subscriptionId":n}})
            .to_string()
            .into_bytes())
    }
    fn next(&self, _: &Budget) -> Result<Vec<u8>> {
        self.0
            .frames
            .borrow_mut()
            .pop()
            .map(|f| f.to_string().into_bytes())
            .ok_or_else(|| err("DISCONNECTED"))
    }
    fn request(
        &self,
        m: &str,
        path: &str,
        p: &BTreeMap<String, String>,
        _: &Budget,
    ) -> Result<Response> {
        self.0.calls.borrow_mut().push(m.into());
        let mut status = 200;
        let v = match (m, path) {
            ("GET", "/api/v3/account") => {
                let balances = self.0.account_balances.borrow().clone().unwrap_or_else(
                    || json!([{"asset":"USDT","free":"100.00000000","locked":"2.00000000"}]),
                );
                json!({"uid":42,"permissions":["SPOT"],"canTrade":true,"accountType":"SPOT","balances":balances})
            }
            ("GET", "/api/v3/openOrders") => {
                let o = self.0.order.borrow();
                if matches!(o["status"].as_str(), Some("NEW" | "PARTIALLY_FILLED")) {
                    json!([*o])
                } else {
                    json!([])
                }
            }
            ("POST", "/api/v3/order") => {
                assert_eq!(p["symbol"], "BTCUSDT");
                assert_eq!(p["quantity"], "4");
                let venue_id = 16
                    + self
                        .0
                        .calls
                        .borrow()
                        .iter()
                        .filter(|m| m.as_str() == "POST")
                        .count();
                let o = json!({"symbol":"BTCUSDT","side":"BUY","type":"LIMIT","timeInForce":"GTC","price":p["price"],"origQty":"4","executedQty":"0","orderId":venue_id,"clientOrderId":p["newClientOrderId"],"status":"NEW","updateTime":1000});
                self.0.order.replace(o.clone());
                if self.0.lose_submit.get() {
                    return Err(err("REPLY_LOST"));
                }
                self.0.submit_ack.borrow_mut().take().unwrap_or(o)
            }
            ("DELETE", "/api/v3/order") => {
                assert_eq!(p["orderId"], "17");
                assert_eq!(p["origClientOrderId"], "client-1");
                let mut o = self.0.order.borrow_mut();
                o["status"] = json!("CANCELED");
                o["clientOrderId"] = json!(p["newClientOrderId"]);
                o["origClientOrderId"] = json!("client-1");
                o["updateTime"] = json!(1200);
                if self.0.lose_cancel.get() {
                    return Err(err("CANCEL_REPLY_LOST"));
                }
                o.clone()
            }
            ("GET", "/api/v3/order") => {
                let o = self.0.order.borrow();
                if o.is_null() {
                    status = 400;
                    json!({"code":-2013})
                } else {
                    if let Some(id) = p.get("orderId") {
                        assert_eq!(id, "17");
                    } else {
                        assert_eq!(p["origClientOrderId"], "client-1");
                    }
                    o.clone()
                }
            }
            ("GET", "/api/v3/myTrades") => {
                assert_eq!(p["orderId"], "17");
                assert_eq!(p["fromId"], "0");
                json!(*self.0.trades.borrow())
            }
            _ => panic!("unexpected {m} {path}"),
        };
        Ok(Response {
            status,
            bytes: v.to_string().into_bytes(),
            retry_after_ms: None,
        })
    }
}
struct Fixture {
    config: Config,
    store: Store,
    log: Log,
    state: Rc<State>,
    r: Runtime,
    c: BrokerCommand,
}
impl Fixture {
    fn new() -> Self {
        let scope=Scope::decode(&json!({"engine":"engine","runtime":"runtime","gateway":"spot","account":"account","generation":"c".repeat(64),"runtime_kind":"SIM"})).unwrap();
        let mut r = serde_json::from_str::<Value>(include_str!(
            "../../../../test-data/broker/domain-inputs.json"
        ))
        .unwrap()["request"]
            .clone();
        r["instrument_id"]["venue"]["value"] = json!("BINANCE");
        r["instrument_id"]["symbol"]["value"] = json!("BTCUSDT");
        r["time_in_force"] = json!("GTC");
        let c=BrokerCommand::decode(&json!({"schema_version":1,"scope":scope.record(),"operation":"SUBMIT","command_id":"submit-1","order":"order-1","client":"client-1","request":r})).unwrap();
        let config = Config {
            binding: Binding {
                access: crate::Access::Trading,
                artifact_sha256: "e".repeat(64),
                scope,
                environment: Environment::SpotTestnet,
                uid: 42,
                key_slot: "key-v1".into(),
                secret_slot: "secret-v1".into(),
            },
            currencies: BTreeMap::from([(
                "USDT".into(),
                OnlyCurrency::new("USDT", 8, OnlyCurrencyType::Crypto).unwrap(),
            )]),
            recv_window_ms: 5000,
            timeout_ms: 1000,
            max_bytes: 1024 * 1024,
            max_requests: 32,
        };
        Self {
            config,
            store: Store::default(),
            log: Log::default(),
            state: Rc::default(),
            r: Runtime {
                view: RefCell::new(None),
                receipts: Cell::new(true),
                admitted: Cell::new(true),
                wrong: RefCell::new(None),
            },
            c,
        }
    }
    fn open(&self, cp: Option<&Checkpoint>) -> Result<SpotBroker<Log>> {
        SpotBroker::restore(
            self.config.clone(),
            Arc::new(Fixed),
            self.log.clone(),
            Box::new(self.store.clone()),
            cp,
            16,
            Box::new(Fake(self.state.clone())),
        )
    }
    fn connect(&self, g: &mut SpotBroker<Log>) {
        g.connect().unwrap();
        g.authenticate().unwrap();
        g.subscribe().unwrap();
    }
    fn ready(&self) -> SpotBroker<Log> {
        let mut g = self.open(None).unwrap();
        self.connect(&mut g);
        g.synchronize(&self.r).unwrap();
        g
    }
    fn view(&self, status: &str, filled: &str) -> OrderView {
        OrderView::decode(&json!({"scope":self.c.scope().record(),"order":"order-1","client":"client-1","venue":"BINANCE:BTCUSDT:17","request":self.c.record()["request"],"filled":filled,"status":status})).unwrap()
    }
    fn count(&self, m: &str) -> usize {
        self.state
            .calls
            .borrow()
            .iter()
            .filter(|kind| kind.as_str() == m)
            .count()
    }
    fn new_risk(&self) -> BrokerCommand {
        let mut cmd = self.c.record();
        cmd["command_id"] = json!("new-risk");
        cmd["order"] = json!("order-2");
        cmd["client"] = json!("client-2");
        cmd["request"]["request_id"]["value"] = json!("request-2");
        BrokerCommand::decode(&cmd).unwrap()
    }
    fn cancel(&self) -> BrokerCommand {
        BrokerCommand::decode(&json!({"schema_version":1,"scope":self.c.scope().record(),"operation":"CANCEL","command_id":"cancel-1","client":"client-1","order":"order-1","request":{"schema_version":1,"request_id":{"schema_version":1,"value":"cancel-request"},"order_id":{"schema_version":1,"value":"order-1"},"reason":"manual","metadata":{}}})).unwrap()
    }
    fn accepted(&self, g: &mut SpotBroker<Log>) {
        g.reconcile(self.c.id()).unwrap();
        self.r.view.replace(Some(self.view("ACCEPTED", "0")));
        g.resolve(&self.r, self.c.id()).unwrap();
    }
}
#[test]
fn lost_submit_and_lost_cancel_restore_the_exact_original_operation_and_receipts() {
    let f = Fixture::new();
    let mut g = f.ready();
    f.r.admitted.set(false);
    assert!(g.dispatch(&f.r, &f.c).is_err());
    assert_eq!(f.count("POST"), 0);
    f.r.admitted.set(true);
    f.state.lose_submit.set(true);
    assert_eq!(g.dispatch(&f.r, &f.c).unwrap(), CommandState::Unknown);
    assert!(g.pending().is_empty());
    let cp = g.checkpoint().unwrap();
    drop(g);
    let mut g = f.open(Some(&cp)).unwrap();
    assert_eq!(g.dispatch(&f.r, &f.c).unwrap(), CommandState::Unknown);
    assert_eq!(f.count("POST"), 1);
    f.connect(&mut g);
    f.accepted(&mut g);
    g.synchronize(&f.r).unwrap();
    let cancel = f.cancel();
    f.state.lose_cancel.set(true);
    assert_eq!(g.dispatch(&f.r, &cancel).unwrap(), CommandState::Unknown);
    let cp = g.checkpoint().unwrap();
    drop(g);
    let mut g = f.open(Some(&cp)).unwrap();
    f.connect(&mut g);
    assert_eq!(g.dispatch(&f.r, &cancel).unwrap(), CommandState::Unknown);
    assert_eq!(f.count("DELETE"), 1);
    let right = f.state.order.borrow()["clientOrderId"].clone();
    f.state.order.borrow_mut()["clientOrderId"] = json!("foreign-cancel");
    assert!(g.reconcile(cancel.id()).is_err());
    assert_ne!(g.command_state(cancel.id()), Some(CommandState::Resolved));
    f.state.order.borrow_mut()["clientOrderId"] = right;
    g.reconcile(cancel.id()).unwrap();
    assert_eq!(g.pending().last().unwrap().record()["kind"], "CANCELLED");
    f.r.view.replace(Some(f.view("CANCELLED", "0")));
    f.r.receipts.set(false);
    assert!(g.resolve(&f.r, cancel.id()).is_err());
    f.r.receipts.set(true);
    g.resolve(&f.r, cancel.id()).unwrap();
    assert_eq!(g.command_state(cancel.id()), Some(CommandState::Resolved));
    assert_eq!(f.count("DELETE"), 1);
}
#[test]
fn fresh_fill_after_initial_resolution_requires_its_own_runtime_receipt() {
    let f = Fixture::new();
    let mut g = f.ready();
    g.dispatch(&f.r, &f.c).unwrap();
    g.reconcile(f.c.id()).unwrap();
    let accepted = g.pending()[0].clone();
    f.r.view.replace(Some(f.view("ACCEPTED", "0")));
    g.resolve(&f.r, f.c.id()).unwrap();
    {
        let mut o = f.state.order.borrow_mut();
        o["status"] = json!("PARTIALLY_FILLED");
        o["executedQty"] = json!("1");
    }
    f.state.trades.borrow_mut().push(json!({"symbol":"BTCUSDT","orderId":17,"id":7,"time":1050,"qty":"1.00000000","price":"10.00","isMaker":false,"isBuyer":true,"commission":"0.01000000","commissionAsset":"USDT"}));
    f.r.view.replace(Some(f.view("PARTIALLY_FILLED", "1")));
    f.r.wrong.replace(Some(accepted));
    assert!(
        g.synchronize(&f.r).is_err(),
        "foreign Accepted receipt cannot certify new Trade"
    );
    let fill = g
        .pending()
        .iter()
        .find(|f| f.record()["kind"] == "TRADE")
        .unwrap()
        .clone();
    assert!(g.acknowledge(&f.r, fill.identity()).is_err());
    f.r.wrong.replace(None);
    g.acknowledge(&f.r, fill.identity()).unwrap();
    g.synchronize(&f.r).unwrap();
    assert_eq!(
        g.fee_evidence(f.c.scope(), "order-1").unwrap()[0]["total"],
        "0.01"
    );
}
#[test]
fn absent_query_cannot_resolve_or_repost_and_checkpoint_rejects_wrong_generation() {
    let f = Fixture::new();
    let mut g = f.ready();
    f.state.lose_submit.set(true);
    g.dispatch(&f.r, &f.c).unwrap();
    f.state.order.replace(Value::Null);
    g.reconcile(f.c.id()).unwrap();
    assert!(g.resolve(&f.r, f.c.id()).is_err());
    assert_eq!(f.count("POST"), 1);
    let mut cp = g.checkpoint().unwrap();
    cp.binding = "x".repeat(64);
    assert!(f.open(Some(&cp)).is_err());
    let mut cp = g.checkpoint().unwrap();
    cp.observation_hash = "0".repeat(64);
    assert!(f.open(Some(&cp)).is_err());
}
#[test]
fn stream_reconnect_replays_trade_once_and_conflicting_payload_revokes_trust() {
    let f = Fixture::new();
    let mut g = f.ready();
    g.dispatch(&f.r, &f.c).unwrap();
    let event = json!({"e":"executionReport","E":6000,"s":"BTCUSDT","S":"BUY","o":"LIMIT","f":"GTC","q":"4.0","p":"10.00","c":"client-1","i":17,"x":"TRADE","X":"PARTIALLY_FILLED","t":9,"T":5999,"l":"1.00","L":"10.00","m":true});
    f.state
        .frames
        .borrow_mut()
        .push(json!({"subscriptionId":1,"event":event}));
    g.poll().unwrap();
    let fact = g.pending()[0].clone();
    assert_eq!(
        fact.record()["payload"]["fill"]["venue_trade_id"]["value"],
        "BINANCE:BTCUSDT:9"
    );
    assert_eq!(fact.record()["ts_event"], 5_999_000_000_i64);
    assert_eq!(fact.record()["ts_init"], fact.record()["ts_event"]);
    assert_eq!(
        fact.record()["quality"],
        json!(["PROVIDER_SEQUENCE_UNAVAILABLE", "PROVIDER_CLOCK_AHEAD"])
    );
    assert!(fact.record()["source_sequence"].is_null());
    assert!(g.poll().is_err());
    assert!(!g.ready());
    g.subscribe().unwrap();
    assert!(!g.ready());
    f.state
        .frames
        .borrow_mut()
        .push(json!({"subscriptionId":2,"event":event}));
    g.poll().unwrap();
    assert_eq!(g.pending().len(), 1);
    let mut conflict = event;
    conflict["L"] = json!("11.00");
    f.state
        .frames
        .borrow_mut()
        .push(json!({"subscriptionId":2,"event":conflict}));
    assert!(g.poll().is_err());
    assert!(!g.ready());
}
#[test]
fn late_terminal_is_delivered_while_runtime_still_shows_the_preceding_view() {
    let f = Fixture::new();
    let mut g = f.ready();
    g.dispatch(&f.r, &f.c).unwrap();
    f.accepted(&mut g);
    f.state.order.borrow_mut()["status"] = json!("EXPIRED");
    assert!(g.synchronize(&f.r).is_err());
    assert_eq!(g.command_state(f.c.id()), Some(CommandState::Resolved));
    let expired = g.pending().first().unwrap().clone();
    assert_eq!(expired.record()["kind"], "EXPIRED");
    f.r.receipts.set(false);
    assert!(g.acknowledge(&f.r, expired.identity()).is_err());
    f.r.receipts.set(true);
    g.acknowledge(&f.r, expired.identity()).unwrap();
    assert!(g.synchronize(&f.r).is_err());
    f.r.view.replace(Some(f.view("EXPIRED", "0")));
    g.synchronize(&f.r).unwrap();
    assert!(g.pending().is_empty());
    assert_eq!(f.count("POST"), 1);
}
#[test]
fn read_only_slot_queries_balances_and_cannot_write_command_intent_or_send() {
    let mut f = Fixture::new();
    f.config.binding.access = Access::ReadOnly;
    let mut g = f.open(None).unwrap();
    f.connect(&mut g);
    let spot = g.balances(f.c.scope()).unwrap();
    assert_eq!(spot[0].record()["payload"]["ledger_cash"]["amount"], "102");
    g.synchronize(&f.r).unwrap();
    let journal_before = f.log.0.borrow().len();
    let network_before = f.state.calls.borrow().len();
    assert!(g.dispatch(&f.r, &f.c).is_err());
    assert!(g.dispatch(&f.r, &f.cancel()).is_err());
    assert_eq!(f.log.0.borrow().len(), journal_before);
    assert_eq!(f.state.calls.borrow().len(), network_before);
    assert!(!g.ready());
    assert!(!g.capabilities().contains("SUBMIT_ORDER"));
    assert!(!g.capabilities().contains("CANCEL_ORDER"));
}
#[test]
fn checkpoint_selects_actual_native_artifact_even_for_same_release_and_scope() {
    let mut f = Fixture::new();
    let g = f.ready();
    let cp = g.checkpoint().unwrap();
    drop(g);
    f.config.binding.artifact_sha256 = "d".repeat(64);
    assert!(
        f.open(Some(&cp)).is_err(),
        "different native artifact must not acquire this checkpoint"
    );
    f.config.binding.artifact_sha256 = "e".repeat(64);
    assert!(f.open(Some(&cp)).is_ok());
    f.config.binding.access = Access::ReadOnly;
    assert!(f.open(Some(&cp)).is_err());
}
#[test]
fn terminated_subscription_is_recoverable_only_for_exact_epoch_id_and_event_time() {
    for (id, time, kind, legitimate) in [
        (1, json!(5000), "eventStreamTerminated", true),
        (2, json!(5000), "eventStreamTerminated", false),
        (1, Value::Null, "eventStreamTerminated", false),
        (1, json!(5000), "foreignEvent", false),
    ] {
        let f = Fixture::new();
        let mut g = f.ready();
        f.state
            .frames
            .borrow_mut()
            .push(json!({"subscriptionId":id,"event":{"e":kind,"E":time}}));
        assert!(g.poll().is_err());
        assert!(!g.ready());
        let cp = g.checkpoint().unwrap();
        drop(g);
        let restored = f.open(Some(&cp));
        if legitimate {
            let mut g = restored.unwrap();
            assert!(!g.ready());
            f.connect(&mut g);
            assert!(!g.ready());
            g.synchronize(&f.r).unwrap();
            assert!(g.ready());
            assert!(g.pending().is_empty());
        } else {
            assert!(restored.is_err());
        }
    }
}
#[test]
fn journal_failure_before_or_after_marker_never_dispatches_without_durable_proof() {
    for (seq, persisted) in [(1, false), (1, true), (2, true)] {
        let f = Fixture::new();
        let mut g = f.ready();
        let checkpoint = g.checkpoint().unwrap();
        f.log.1.set(Some((seq, persisted)));
        assert!(g.dispatch(&f.r, &f.c).is_err());
        assert_eq!(f.count("POST"), 0);
        drop(g);
        f.log.1.set(None);
        let mut recovered = f.open(Some(&checkpoint)).unwrap();
        f.connect(&mut recovered);
        if seq == 2 {
            assert_eq!(
                recovered.dispatch(&f.r, &f.c).unwrap(),
                CommandState::Unknown
            );
            assert_eq!(f.count("POST"), 0);
        } else {
            recovered.synchronize(&f.r).unwrap();
            assert_eq!(recovered.dispatch(&f.r, &f.c).unwrap(), CommandState::Known);
            assert_eq!(f.count("POST"), 1);
        }
    }
}
struct ParallelVenue {
    single: Fake,
    orders: Rc<RefCell<BTreeMap<String, Value>>>,
    wrong: Rc<Cell<bool>>,
}
impl Exchange for ParallelVenue {
    fn preflight(&self, b: &Budget) -> Result<()> {
        self.single.preflight(b)
    }
    fn subscribe(&self, id: &str, b: &Budget) -> Result<Vec<u8>> {
        self.single.subscribe(id, b)
    }
    fn next(&self, b: &Budget) -> Result<Vec<u8>> {
        self.single.next(b)
    }
    fn close(&self) {
        self.single.close()
    }
    fn request(
        &self,
        m: &str,
        path: &str,
        p: &BTreeMap<String, String>,
        b: &Budget,
    ) -> Result<Response> {
        let v = match (m, path) {
            ("POST", "/api/v3/order") => {
                let client = &p["newClientOrderId"];
                let venue = if client == "client-2" { 18 } else { 17 };
                let price = if p["type"] == "MARKET" {
                    assert!(!p.contains_key("price"));
                    assert!(!p.contains_key("timeInForce"));
                    "0"
                } else {
                    assert_eq!(p["timeInForce"], "GTC");
                    &p["price"]
                };
                let v = json!({"symbol":p["symbol"],"side":"BUY","type":p["type"],"price":price,"timeInForce":"GTC","origQty":"4","executedQty":"4","orderId":venue,"clientOrderId":client,"status":"FILLED","updateTime":3000});
                assert!(
                    self.orders
                        .borrow_mut()
                        .insert(client.clone(), v.clone())
                        .is_none()
                );
                v
            }
            ("GET", "/api/v3/order") => {
                let id = p["orderId"].parse::<u64>().unwrap();
                self.orders
                    .borrow()
                    .values()
                    .find(|o| o["symbol"] == p["symbol"] && o["orderId"].as_u64() == Some(id))
                    .unwrap()
                    .clone()
            }
            ("GET", "/api/v3/myTrades") => {
                assert_eq!(p["fromId"], "0");
                let num = p["orderId"].parse::<u64>().unwrap();
                json!([{"symbol":p["symbol"],"orderId":if self.wrong.get(){num+1}else{num},"id":if num==17{7}else{8},"price":"10.00","qty":"4","time":3000,"isMaker":true,"isBuyer":true,"commissionAsset":"USDT","commission":if num==17{"0.001"}else{"0.002"}}])
            }
            _ => return self.single.request(m, path, p, b),
        };
        Ok(Response {
            status: 200,
            bytes: v.to_string().into_bytes(),
            retry_after_ms: None,
        })
    }
}
#[test]
fn outstanding_orders_bind_trades_fees_and_symbol_scoped_venue_ids_independently() {
    let f = Fixture::new();
    let wrong = Rc::new(Cell::new(false));
    let wire = ParallelVenue {
        single: Fake(f.state.clone()),
        orders: Rc::default(),
        wrong: wrong.clone(),
    };
    let mut g = SpotBroker::restore(
        f.config.clone(),
        Arc::new(Fixed),
        f.log.clone(),
        Box::new(f.store.clone()),
        None,
        16,
        Box::new(wire),
    )
    .unwrap();
    f.connect(&mut g);
    g.synchronize(&f.r).unwrap();
    for (id, symbol) in [(1, "BTCUSDT"), (2, "BTCUSDT"), (3, "ETHUSDT")] {
        let mut raw = f.c.record();
        raw["order"] = json!(format!("order-{id}"));
        raw["client"] = json!(format!("client-{id}"));
        raw["command_id"] = json!(format!("submit-{id}"));
        raw["request"]["request_id"]["value"] = json!(format!("r-{id}"));
        raw["request"]["instrument_id"]["symbol"]["value"] = json!(symbol);
        if id == 3 {
            raw["request"]["order_type"] = json!("MARKET");
            raw["request"]["price"] = Value::Null;
        }
        assert_eq!(
            g.dispatch(&f.r, &BrokerCommand::decode(&raw).unwrap())
                .unwrap(),
            CommandState::Known
        );
    }
    let fills = g.trades(f.c.scope(), None).unwrap();
    {
        let evidence = f.store.0.borrow();
        let submissions = evidence
            .iter()
            .filter(|raw| raw.action["method"] == "POST")
            .map(|raw| &raw.action)
            .collect::<Vec<_>>();
        assert_eq!(submissions.len(), 3);
        assert_eq!(submissions[2]["path"], "/api/v3/order");
        assert_eq!(
            submissions[2]["params"],
            json!({"symbol":"ETHUSDT","type":"MARKET","quantity":"4","side":"BUY","newClientOrderId":"client-3","newOrderRespType":"ACK"})
        );
    }
    assert_eq!(
        fills
            .iter()
            .map(|f| f.record()["payload"]["fill"]["venue_trade_id"]["value"].clone())
            .collect::<Vec<_>>(),
        [
            json!("BINANCE:BTCUSDT:7"),
            json!("BINANCE:BTCUSDT:8"),
            json!("BINANCE:ETHUSDT:7")
        ]
    );
    assert_eq!(
        g.fee_evidence(f.c.scope(), "order-2").unwrap()[0]["total"],
        "0.002"
    );
    assert_eq!(
        g.fee_evidence(f.c.scope(), "order-3").unwrap()[0]["scope"]["id"],
        "BINANCE:ETHUSDT:7"
    );
    wrong.set(true);
    assert!(g.fee_evidence(f.c.scope(), "order-1").is_err());
}
fn report_event(kind: &str) -> Value {
    let mut e = json!({"e":"executionReport","E":1000,"s":"BTCUSDT","S":"BUY","o":"LIMIT","f":"GTC","p":"10.00","q":"4","c":"client-1","i":17,"x":"NEW","X":"NEW"});
    if kind == "TRADE" {
        e["x"] = json!("TRADE");
        e["X"] = json!("PARTIALLY_FILLED");
        e["t"] = json!(1);
        e["T"] = json!(1000);
        e["l"] = json!("1");
        e["L"] = json!("10");
        e["m"] = json!(true);
    }
    json!({"subscriptionId":1,"event":e})
}
#[test]
fn intent_alone_and_a_later_dispatch_marker_cannot_adopt_an_earlier_stream_fact() {
    let f = Fixture::new();
    let mut g = f.ready();
    f.log.1.set(Some((1, true)));
    assert!(g.dispatch(&f.r, &f.c).is_err());
    assert_eq!(f.count("POST"), 0);
    f.state.frames.borrow_mut().push(report_event("NEW"));
    assert!(
        g.poll().is_err(),
        "durable intent never sent to Binance cannot own a venue event"
    );
    assert!(g.pending().is_empty());
    f.log.1.set(None);
    f.connect(&mut g);
    g.synchronize(&f.r).unwrap();
    g.dispatch(&f.r, &f.c).unwrap();
    assert_eq!(f.count("POST"), 1);
    let cp = g.checkpoint().unwrap();
    drop(g);
    // 即使当前已有真实发送标记，当时未发送的关联在恢复时仍不合法。
    assert!(f.open(Some(&cp)).is_err());
    assert_eq!(f.count("POST"), 1);
}
#[test]
fn capacity_one_restores_unacked_head_and_delivers_the_second_durable_raw_after_ack() {
    let f = Fixture::new();
    let open = |cp: Option<&Checkpoint>| {
        SpotBroker::restore(
            f.config.clone(),
            Arc::new(Fixed),
            f.log.clone(),
            Box::new(f.store.clone()),
            cp,
            1,
            Box::new(Fake(f.state.clone())),
        )
    };
    let mut g = open(None).unwrap();
    f.connect(&mut g);
    g.synchronize(&f.r).unwrap();
    g.dispatch(&f.r, &f.c).unwrap();
    f.state.frames.borrow_mut().push(report_event("NEW"));
    g.poll().unwrap();
    f.state.frames.borrow_mut().push(report_event("TRADE"));
    assert!(g.poll().is_err());
    assert_eq!(g.pending().len(), 1);
    let cp = g.checkpoint().unwrap();
    drop(g);
    let mut restored = open(Some(&cp)).unwrap();
    assert!(!restored.ready());
    assert_eq!(restored.pending().len(), 1);
    let head = restored.pending()[0].clone();
    assert_eq!(head.record()["kind"], "ACCEPTED");
    restored.acknowledge(&f.r, head.identity()).unwrap();
    assert_eq!(restored.pending().len(), 1);
    let trade = restored.pending()[0].clone();
    assert_eq!(trade.record()["kind"], "TRADE");
    restored.acknowledge(&f.r, trade.identity()).unwrap();
    assert!(restored.pending().is_empty());
    let cp = restored.checkpoint().unwrap();
    drop(restored);
    assert!(open(Some(&cp)).unwrap().pending().is_empty());
    assert_eq!(f.count("POST"), 1);
}
/// 命令路径调用真实 Native 前置校验，其余响应由离线场所控制，禁止任何真实下单。
pub(super) fn verify_native_preflight(native: Native) {
    struct Gate {
        raw: Fake,
        native: Native,
    }
    impl Exchange for Gate {
        fn preflight(&self, b: &Budget) -> Result<()> {
            self.native.preflight(b)
        }
        fn request(
            &self,
            m: &str,
            p: &str,
            args: &BTreeMap<String, String>,
            b: &Budget,
        ) -> Result<Response> {
            self.raw.request(m, p, args, b)
        }
        fn subscribe(&self, id: &str, b: &Budget) -> Result<Vec<u8>> {
            self.raw.subscribe(id, b)
        }
        fn next(&self, b: &Budget) -> Result<Vec<u8>> {
            self.raw.next(b)
        }
        fn close(&self) {
            self.raw.close()
        }
    }
    let f = Fixture::new();
    f.state.lose_submit.set(true);
    let mut g = SpotBroker::restore(
        f.config.clone(),
        Arc::new(Fixed),
        f.log.clone(),
        Box::new(f.store.clone()),
        None,
        4,
        Box::new(Gate {
            raw: Fake(f.state.clone()),
            native,
        }),
    )
    .unwrap();
    f.connect(&mut g);
    g.synchronize(&f.r).unwrap();
    assert!(
        g.dispatch(&f.r, &f.c).is_err(),
        "known local blocker must precede durable dispatch"
    );
    assert!(f.log.0.borrow().is_empty());
    assert!(g.command_state(f.c.id()).is_none());
    assert_eq!(f.count("POST"), 0);
}

#[test]
fn capacity_one_rest_only_discovery_delivers_all_fills_and_resolves_the_original_unknown() {
    // 接续既可以先逐单调查，也可以先全账户同步。两条入口均使用已持久化的原命令。
    for start_with_sync in [false, true] {
        let f = Fixture::new();
        let open = |cp: Option<&Checkpoint>| {
            SpotBroker::restore(
                f.config.clone(),
                Arc::new(Fixed),
                f.log.clone(),
                Box::new(f.store.clone()),
                cp,
                1,
                Box::new(Fake(f.state.clone())),
            )
        };
        let mut g = open(None).unwrap();
        f.connect(&mut g);
        g.synchronize(&f.r).unwrap();
        f.state.lose_submit.set(true);
        assert_eq!(g.dispatch(&f.r, &f.c).unwrap(), CommandState::Unknown);
        let cp = g.checkpoint().unwrap();
        drop(g);
        {
            let mut o = f.state.order.borrow_mut();
            o["status"] = json!("FILLED");
            o["executedQty"] = json!("4");
            o["updateTime"] = json!(1200);
        }
        for (id, quantity) in [(70, "1"), (71, "3")] {
            f.state.trades.borrow_mut().push(json!({"symbol":"BTCUSDT","orderId":17,"id":id,"qty":quantity,"price":"10.00","time":1200,"isBuyer":true,"isMaker":true,"commissionAsset":"USDT","commission":"0.001"}));
        }
        let mut g = open(Some(&cp)).unwrap();
        f.connect(&mut g);
        let first = if start_with_sync {
            g.synchronize(&f.r)
        } else {
            g.reconcile(f.c.id())
        };
        assert!(first.is_err());
        assert!(!g.ready());
        assert_ne!(g.command_state(f.c.id()), Some(CommandState::Resolved));
        assert_eq!(
            g.pending().len(),
            1,
            "a full REST page larger than capacity must still expose its first unacknowledged fill"
        );
        let first = g.pending()[0].clone();
        assert_eq!(
            first.record()["payload"]["fill"]["venue_trade_id"]["value"],
            "BINANCE:BTCUSDT:70"
        );
        f.r.receipts.set(false);
        assert!(g.acknowledge(&f.r, first.identity()).is_err());
        f.r.receipts.set(true);
        g.acknowledge(&f.r, first.identity()).unwrap();
        let cp = g.checkpoint().unwrap();
        drop(g);
        let mut g = open(Some(&cp)).unwrap();
        f.connect(&mut g);
        g.reconcile(f.c.id()).unwrap();
        assert_eq!(g.pending().len(), 1);
        let second = g.pending()[0].clone();
        assert_eq!(
            second.record()["payload"]["fill"]["venue_trade_id"]["value"],
            "BINANCE:BTCUSDT:71"
        );
        let rows = f.log.records().unwrap();
        let discovery = rows
            .iter()
            .map(Record::record)
            .find(|v| v["event"]["kind"] == "DISCOVERY")
            .unwrap();
        let proof = &discovery["event"]["discovery"];
        assert_eq!(proof["command"], f.c.record());
        assert_eq!(proof["view"]["filled"], "4");
        assert_eq!(proof["facts"].as_array().unwrap().len(), 2);
        f.r.view.replace(Some(f.view("FILLED", "4")));
        f.r.wrong.replace(Some(first));
        assert!(g.resolve(&f.r, f.c.id()).is_err());
        f.r.wrong.replace(None);
        g.acknowledge(&f.r, second.identity()).unwrap();
        g.resolve(&f.r, f.c.id()).unwrap();
        g.synchronize(&f.r).unwrap();
        assert!(g.pending().is_empty());
        assert!(g.ready());
        assert_eq!(g.command_state(f.c.id()), Some(CommandState::Resolved));
        assert_eq!(f.count("POST"), 1);
        assert!(
            f.store
                .0
                .borrow()
                .iter()
                .any(|r| r.action["path"] == "/api/v3/myTrades"
                    && wire_json(&r.bytes).unwrap().as_array().unwrap().len() == 2)
        );
    }
}
fn rejects_stream_with_changed_limit_term(field: &str, value: &str) {
    let f = Fixture::new();
    let mut g = f.ready();
    g.dispatch(&f.r, &f.c).unwrap();
    let mut event = report_event("TRADE");
    // BUY 10 的成交可以发生在 9；p 是订单原价，L 是独立的本次成交价。
    event["event"]["L"] = json!("9");
    f.state.frames.borrow_mut().push(event.clone());
    g.poll().unwrap();
    let better = g.pending()[0].clone();
    assert_eq!(better.record()["payload"]["fill"]["price"]["value"], "9");
    g.acknowledge(&f.r, better.identity()).unwrap();
    event["event"][field] = json!(value);
    f.state.frames.borrow_mut().push(event);
    assert!(
        g.poll().is_err(),
        "stream order term {field} must match the exact submitted limit order"
    );
    assert!(g.pending().is_empty());
    assert!(!g.ready());
    assert_eq!(f.count("POST"), 1);
    let cp = g.checkpoint().unwrap();
    drop(g);
    assert!(f.open(Some(&cp)).is_err());
}
#[test]
fn stream_limit_order_price_mismatch_cannot_deliver_a_fill() {
    rejects_stream_with_changed_limit_term("p", "11.00");
}
#[test]
fn stream_time_in_force_mismatch_cannot_deliver_a_fill() {
    rejects_stream_with_changed_limit_term("f", "IOC");
}

#[test]
fn pending_stream_fill_blocks_new_risk_until_its_own_receipt_without_reconnecting() {
    let f = Fixture::new();
    let mut g = f.ready();
    g.dispatch(&f.r, &f.c).unwrap();
    g.reconcile(f.c.id()).unwrap();
    let accepted = g.pending()[0].clone();
    f.r.view.replace(Some(f.view("ACCEPTED", "0")));
    g.resolve(&f.r, f.c.id()).unwrap();
    g.synchronize(&f.r).unwrap();
    assert!(g.ready());

    f.state.frames.borrow_mut().push(report_event("TRADE"));
    g.poll().unwrap();
    let fill = g.pending()[0].clone();
    assert_eq!(fill.record()["kind"], "TRADE");
    f.r.receipts.set(false);
    assert!(g.acknowledge(&f.r, fill.identity()).is_err());
    f.r.receipts.set(true);
    f.r.wrong.replace(Some(accepted));
    assert!(g.acknowledge(&f.r, fill.identity()).is_err());

    let new_risk = f.new_risk();
    let before = f.log.records().unwrap();
    let ready = g.ready();
    let outcome = g.dispatch(&f.r, &new_risk);
    assert_eq!((ready, outcome.is_err(), f.count("POST")), (false, true, 1));
    assert_eq!(f.log.records().unwrap(), before);
    assert_eq!(g.command_state(f.c.id()), Some(CommandState::Resolved));
    assert_eq!(g.command_state(new_risk.id()), None);
    assert!(!g.orders(f.c.scope(), true).unwrap().is_empty());

    f.r.wrong.replace(None);
    g.acknowledge(&f.r, fill.identity()).unwrap();
    assert!(g.ready());
    assert_eq!(g.dispatch(&f.r, &new_risk).unwrap(), CommandState::Known);
    assert_eq!(f.count("POST"), 2);
}

#[derive(Clone, Copy)]
enum RestQuery {
    OriginalOrder,
    OpenOrders,
    Trades,
    Fee,
}

fn check_rest_conflict(query: RestQuery) {
    let f = Fixture::new();
    let mut g = f.ready();
    g.dispatch(&f.r, &f.c).unwrap();
    f.accepted(&mut g);
    g.synchronize(&f.r).unwrap();
    assert!(g.ready());

    let original = f.state.order.borrow().clone();
    let scope = f.c.scope();
    match query {
        RestQuery::OriginalOrder => {
            f.state.order.borrow_mut()["orderId"] = json!(301);
            assert!(g.orders(scope, false).is_err());
        }
        RestQuery::OpenOrders => {
            f.state.order.borrow_mut()["clientOrderId"] = json!("foreign-client");
            assert!(g.orders(scope, true).is_err());
        }
        RestQuery::Trades | RestQuery::Fee => {
            let (symbol, order) = if matches!(query, RestQuery::Fee) {
                ("BTCUSDT", 301)
            } else {
                ("ETHUSDT", 17)
            };
            f.state.trades.borrow_mut().push(json!({"symbol":symbol,"orderId":order,"id":7,"qty":"1","price":"10","time":1500,"isMaker":false,"isBuyer":true,"commissionAsset":"USDT","commission":"0.01"}));
            if matches!(query, RestQuery::Fee) {
                assert!(g.fee_evidence(scope, f.c.order()).is_err());
            } else {
                assert!(g.trades(scope, None).is_err());
            }
        }
    }
    let before = f.log.records().unwrap();
    let next = f.new_risk();
    let ready = g.ready();
    let submission = g.dispatch(&f.r, &next);
    assert_eq!(
        (ready, submission.is_err(), f.count("POST")),
        (false, true, 1)
    );
    assert_eq!(f.log.records().unwrap(), before);
    assert_eq!(g.command_state(next.id()), None);
    assert_eq!(g.command_state(f.c.id()), Some(CommandState::Resolved));

    // 后续普通查询发现一致关系仍不能单独恢复交易信任。
    f.state.order.replace(original);
    f.state.trades.borrow_mut().clear();
    assert_eq!(g.orders(scope, false).unwrap().len(), 1);
    assert!(g.trades(scope, None).unwrap().is_empty());
    assert!(!g.ready());
    if matches!(query, RestQuery::OriginalOrder) {
        let cancel = f.cancel();
        assert_eq!(g.dispatch(&f.r, &cancel).unwrap(), CommandState::Known);
        assert_eq!(f.count("DELETE"), 1);
        assert!(!g.ready());
        g.reconcile(cancel.id()).unwrap();
        f.r.view.replace(Some(f.view("CANCELLED", "0")));
        g.resolve(&f.r, cancel.id()).unwrap();
        assert!(!g.ready());
    }
    g.synchronize(&f.r).unwrap();
    assert!(g.ready());
    assert_eq!(g.dispatch(&f.r, &next).unwrap(), CommandState::Known);
    assert_eq!(f.count("POST"), 2);
}

#[test]
fn conflicting_original_order_revokes_risk_until_full_reconciliation() {
    check_rest_conflict(RestQuery::OriginalOrder);
}

#[test]
fn conflicting_open_order_revokes_risk_until_full_reconciliation() {
    check_rest_conflict(RestQuery::OpenOrders);
}

#[test]
fn conflicting_trade_revokes_risk_until_full_reconciliation() {
    check_rest_conflict(RestQuery::Trades);
}

#[test]
fn conflicting_fee_trade_revokes_risk_until_full_reconciliation() {
    check_rest_conflict(RestQuery::Fee);
}

#[test]
fn local_query_errors_preserve_verified_trading_trust() {
    let f = Fixture::new();
    let mut g = f.ready();
    let scope = f.c.scope();
    let mut wrong = scope.record();
    wrong["account"] = json!("other-account");
    let wrong = Scope::decode(&wrong).unwrap();
    let before = f.state.calls.borrow().len();
    assert!(g.orders(&wrong, false).is_err());
    assert!(g.trades(scope, Some(0)).is_err());
    assert!(g.fee_evidence(scope, "not-an-original-order").is_err());
    assert_eq!(f.state.calls.borrow().len(), before);
    assert!(g.ready());
    assert_eq!(g.dispatch(&f.r, &f.c).unwrap(), CommandState::Known);
}

#[test]
fn cancel_intent_append_failure_keeps_original_order_open_without_sending_delete() {
    let f = Fixture::new();
    let mut gateway = f.ready();
    assert_eq!(gateway.dispatch(&f.r, &f.c).unwrap(), CommandState::Known);
    f.accepted(&mut gateway);
    let before = f.log.records().unwrap();
    let next = before.len() as u64 + 1;
    f.log.1.set(Some((next, false)));
    let cancel = f.cancel();
    let error = gateway.dispatch(&f.r, &cancel).unwrap_err();
    assert_eq!(error, err("STORE_UNAVAILABLE"));
    assert_eq!(f.log.records().unwrap(), before);
    assert_eq!(f.count("DELETE"), 0);
    assert_eq!(f.count("POST"), 1);
    assert_eq!(f.state.order.borrow()["status"], "NEW");
    assert_eq!(gateway.command_state(cancel.id()), None);
}

#[test]
fn malformed_successful_submit_ack_stays_unknown_after_reopen_without_another_post() {
    for ack in [
        json!({}),
        json!({"symbol":"BTCUSDT","clientOrderId":"unrelated","orderId":17}),
    ] {
        let f = Fixture::new();
        f.state.submit_ack.replace(Some(ack.clone()));
        let mut gateway = f.ready();
        assert_eq!(gateway.dispatch(&f.r, &f.c).unwrap(), CommandState::Unknown);
        assert!(!gateway.ready());
        assert!(gateway.pending().is_empty());
        {
            let stored = f.store.0.borrow();
            let raw = stored.last().unwrap();
            assert_eq!(raw.status, 200);
            assert_eq!(raw.bytes, ack.to_string().as_bytes());
            assert_eq!(raw.action["command"], f.c.record());
        }
        assert_eq!(gateway.dispatch(&f.r, &f.c).unwrap(), CommandState::Unknown);
        let checkpoint = gateway.checkpoint().unwrap();
        drop(gateway);
        let mut recovered = f.open(Some(&checkpoint)).unwrap();
        assert_eq!(
            recovered.dispatch(&f.r, &f.c).unwrap(),
            CommandState::Unknown
        );
        assert_eq!(f.count("POST"), 1);
        assert!(!recovered.ready());
        f.connect(&mut recovered);
        f.accepted(&mut recovered);
        assert_eq!(
            recovered.command_state(f.c.id()),
            Some(CommandState::Resolved)
        );
        assert_eq!(f.count("POST"), 1);
    }
}

fn add_btc(f: &mut Fixture) {
    f.config.currencies.insert(
        "BTC".into(),
        OnlyCurrency::new("BTC", 8, OnlyCurrencyType::Crypto).unwrap(),
    );
}

fn assert_balances(rows: &[Value], observed: i64) {
    assert_eq!(rows.len(), 2);
    for (row, (code, total, free, reserved)) in rows
        .iter()
        .zip([("BTC", "0.01", "0.01", "0"), ("USDT", "102", "100", "2")])
    {
        assert_eq!(row["kind"], "BALANCE");
        assert_eq!(row["snapshot_time"], observed);
        assert_eq!(row["payload"]["currency"]["code"], code);
        for (field, amount) in [
            ("ledger_cash", total),
            ("trade_available_cash", free),
            ("order_reserved_cash", reserved),
        ] {
            assert_eq!(row["payload"][field]["amount"], amount);
            assert_eq!(row["payload"][field]["currency"]["code"], code);
        }
    }
}

#[test]
fn spot_rest_ports_preserve_balance_totals_partial_order_and_original_cancel_parameters() {
    let mut f = Fixture::new();
    add_btc(&mut f);
    f.state.account_balances.replace(Some(json!([
        {"asset":"USDT","free":"100.00000000","locked":"2.00000000"},
        {"asset":"BTC","free":"0.01000000","locked":"0.00000000"}
    ])));
    let mut command = f.c.record();
    command["request"]["price"]["value"] = json!("25000.10");
    f.c = BrokerCommand::decode(&command).unwrap();
    let mut g = f.ready();
    let start = f.store.0.borrow().len();
    let rows = g
        .balances(f.c.scope())
        .unwrap()
        .iter()
        .map(Snapshot::record)
        .collect::<Vec<_>>();
    assert_balances(&rows, 5_000_000_000);
    assert_eq!(g.dispatch(&f.r, &f.c).unwrap(), CommandState::Known);
    {
        let mut order = f.state.order.borrow_mut();
        order["executedQty"] = json!("0.00400000");
        order["status"] = json!("PARTIALLY_FILLED");
    }
    f.state.trades.borrow_mut().push(json!({"symbol":"BTCUSDT","orderId":17,"id":777,"price":"25010.00","qty":"0.00400000","time":1000,"isMaker":true,"isBuyer":true}));
    let orders = g.orders(f.c.scope(), false).unwrap();
    assert_eq!(orders.len(), 1);
    let view = orders[0].record();
    assert_eq!(view["status"], "PARTIALLY_FILLED");
    assert_eq!(view["filled"], "0.004");
    assert_eq!(view["order"], f.c.order());
    assert_eq!(view["client"], f.c.client());
    assert_eq!(view["venue"], "BINANCE:BTCUSDT:17");
    assert_eq!(g.orders(f.c.scope(), true).unwrap(), orders);
    let trades = g.trades(f.c.scope(), None).unwrap();
    assert_eq!(trades.len(), 1);
    assert_eq!(
        trades[0].record()["payload"]["fill"]["venue_trade_id"]["value"],
        "BINANCE:BTCUSDT:777"
    );
    let cancel = f.cancel();
    assert_eq!(g.dispatch(&f.r, &cancel).unwrap(), CommandState::Known);
    let observations = f.store.0.borrow();
    let calls = &observations[start..];
    let paths = calls
        .iter()
        .map(|o| {
            (
                o.action["method"].as_str().unwrap(),
                o.action["path"].as_str().unwrap(),
            )
        })
        .collect::<Vec<_>>();
    assert_eq!(
        paths,
        [
            ("GET", "/api/v3/account"),
            ("POST", "/api/v3/order"),
            ("GET", "/api/v3/order"),
            ("GET", "/api/v3/openOrders"),
            ("GET", "/api/v3/order"),
            ("GET", "/api/v3/myTrades"),
            ("GET", "/api/v3/order"),
            ("DELETE", "/api/v3/order")
        ]
    );
    assert_eq!(
        calls[1].action["params"],
        json!({"symbol":"BTCUSDT","side":"BUY","type":"LIMIT","quantity":"4","price":"25000.10","timeInForce":"GTC","newOrderRespType":"ACK","newClientOrderId":"client-1"})
    );
    assert_eq!(
        calls[5].action["params"],
        json!({"symbol":"BTCUSDT","orderId":"17","fromId":"0","limit":"1000"})
    );
    assert_eq!(
        calls[7].action["params"],
        json!({"symbol":"BTCUSDT","orderId":"17","origClientOrderId":"client-1","newClientOrderId":cancel_client(&cancel)})
    );
}

#[test]
fn user_stream_deduplicates_new_and_keeps_balances_cancel_and_late_trade_with_original_order() {
    let mut f = Fixture::new();
    add_btc(&mut f);
    let mut g = f.ready();
    g.dispatch(&f.r, &f.c).unwrap();
    let deliver = |gateway: &mut SpotBroker<Log>, frame: Value| {
        f.state.frames.borrow_mut().push(frame);
        gateway.poll()
    };
    let new = report_event("NEW");
    deliver(&mut g, new.clone()).unwrap();
    let first = g.pending()[0].clone();
    deliver(&mut g, new).unwrap();
    assert_eq!(g.pending(), std::slice::from_ref(&first));
    assert_eq!(first.record()["kind"], "ACCEPTED");
    assert!(first.record()["source_sequence"].is_null());
    deliver(
        &mut g,
        json!({"subscriptionId":1,"event":{"e":"outboundAccountPosition","E":1200,"B":[
        {"a":"USDT","f":"100","l":"2"},{"a":"BTC","f":"0.01","l":"0"}]}}),
    )
    .unwrap();
    let balances = g.pending()[1].record();
    assert_eq!(balances["kind"], "BALANCES");
    assert_balances(balances["payload"].as_array().unwrap(), 1_200_000_000);
    let mut cancel = report_event("NEW");
    cancel["event"]["x"] = json!("CANCELED");
    cancel["event"]["X"] = json!("CANCELED");
    cancel["event"]["E"] = json!(1500);
    cancel["event"]["C"] = json!("client-1");
    cancel["event"]["c"] = json!("venue-generated-cancel-id");
    deliver(&mut g, cancel.clone()).unwrap();
    let mut trade = report_event("TRADE");
    trade["event"]["t"] = json!(778);
    trade["event"]["E"] = json!(1600);
    trade["event"]["T"] = json!(1450);
    deliver(&mut g, trade).unwrap();
    assert_eq!(g.pending().len(), 4);
    let cancelled = &g.pending()[2];
    let trade = &g.pending()[3];
    assert_eq!(cancelled.record()["kind"], "CANCELLED");
    assert_eq!(cancelled.record()["payload"]["order"], "order-1");
    assert_eq!(cancelled.record()["correlation"], "client-1");
    assert_eq!(trade.record()["kind"], "TRADE");
    assert_ne!(cancelled.identity(), trade.identity());
    assert_eq!(
        trade.record()["payload"]["fill"]["venue_order_id"]["value"],
        cancelled.record()["payload"]["venue"]
    );
    assert_eq!(
        trade.record()["payload"]["fill"]["venue_trade_id"]["value"],
        "BINANCE:BTCUSDT:778"
    );
    let preserved = g.pending().to_vec();
    cancel["event"]["C"] = json!("unrelated-client");
    cancel["event"]["c"] = json!("client-1");
    assert!(deliver(&mut g, cancel).is_err());
    assert_eq!(g.pending(), preserved);
    assert!(!g.ready());
}

#[cfg(target_os = "linux")]
#[path = "cash_execution.rs"]
mod cash_execution;
