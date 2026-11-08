//! 现金 Execution 的受控离线消费者。场所替身只拥有外部订单，不能签发 Ready 或应用回执。
use super::{Fake, Fixed, Fixture};
use crate::{
    Budget, Checkpoint, Exchange, Observation, ObservationStore, Response, Result, SpotBroker, err,
    wire_client,
};
use onlyalpha_broker::{
    AppendIntent, ApplicationReceipt, ApplicationStatus, Broker, BrokerCommand, CommandState,
    ConnectionPort, Fact, Journal, ObservedFact, Operation, OrderView, ReadyIntent, Record,
    RuntimeReader, Scope, digest,
};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    calendar::OnlyTradingCalendar,
    enums::OnlyCurrencyType,
    fee::*,
    value::{OnlyCurrency, OnlyMoney},
};
use onlyalpha_execution::{Components, Store as ExecutionStore, coordinate, recover};
use onlyalpha_runtime::SqliteStore;
use serde_json::{Value, json};
use std::{
    cell::{Cell, RefCell},
    collections::BTreeMap,
    fs::{self, File, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
    rc::Rc,
    sync::{
        Arc,
        atomic::{AtomicU64, Ordering},
    },
};

const ORDER: &str = "runtime-ORDER-000001";
const DOMAIN: &str = include_str!("../../../../test-data/execution/domain-inputs.json");
const SETTLEMENT: &str = include_str!("../../../../test-data/settlement/common-v1.json");
static NEXT: AtomicU64 = AtomicU64::new(0);

struct Root(PathBuf);
impl Root {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "oa-cash-spot-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        for name in ["journal", "observations", "execution"] {
            fs::create_dir(path.join(name)).unwrap();
        }
        Self(path)
    }
}
impl Drop for Root {
    fn drop(&mut self) {
        if std::thread::panicking() {
            eprintln!("保留现金恢复测试现场 {}", self.0.display());
        } else {
            fs::remove_dir_all(&self.0).unwrap();
        }
    }
}

fn storage(_: impl std::fmt::Display) -> onlyalpha_broker::Error {
    err("OFFLINE_STORE_UNAVAILABLE")
}

// 每条记录使用独立序号文件。写满并 sync 后以 hard_link 原子发布，已有序号不能被替换。
#[derive(Clone)]
struct Logs(PathBuf);
impl Logs {
    fn dir(&self, name: &str) -> PathBuf {
        self.0.join(name)
    }
    fn count(&self, name: &str) -> Result<u64> {
        let mut n = 0;
        for file in fs::read_dir(self.dir(name)).map_err(storage)? {
            let file = file.map_err(storage)?;
            if file.file_name() != "pending" {
                n += 1;
            }
        }
        Ok(n)
    }
    fn read(&self, name: &str, n: u64) -> Result<Value> {
        let bytes = fs::read(self.dir(name).join(n.to_string())).map_err(storage)?;
        serde_json::from_slice(&bytes).map_err(storage)
    }
    fn write(&self, name: &str, n: u64, row: &Value) -> Result<()> {
        if n != self.count(name)? + 1 {
            return Err(err("OFFLINE_APPEND_CONFLICT"));
        }
        let dir = self.dir(name);
        let pending = dir.join("pending");
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&pending)
            .map_err(storage)?;
        file.write_all(&serde_json::to_vec(row).map_err(storage)?)
            .map_err(storage)?;
        file.sync_all().map_err(storage)?;
        fs::hard_link(&pending, dir.join(n.to_string())).map_err(storage)?;
        fs::remove_file(pending).map_err(storage)?;
        File::open(dir).and_then(|f| f.sync_all()).map_err(storage)
    }
}
impl Journal for Logs {
    fn records(&self) -> Result<Vec<Record>> {
        (1..=self.count("journal")?)
            .map(|n| Record::decode(&self.read("journal", n)?))
            .collect()
    }
    fn append(&mut self, i: &AppendIntent) -> Result<()> {
        let row = Record::new(i).record();
        self.write(
            "journal",
            row["sequence"]
                .as_u64()
                .ok_or_else(|| err("JOURNAL_SEQUENCE"))?,
            &row,
        )
    }
}
impl ObservationStore for Logs {
    fn len(&self, _: &str) -> Result<u64> {
        self.count("observations")
    }
    fn read(&self, binding: &str, n: u64) -> Result<Observation> {
        let row = self.read("observations", n)?;
        let (owner, sequence, previous, action, status, at_ns, bytes, hash) =
            serde_json::from_value(row).map_err(storage)?;
        if owner != binding || sequence != n {
            return Err(err("OBSERVATION_OWNER"));
        }
        Ok(Observation {
            binding: owner,
            sequence,
            previous,
            action,
            status,
            at_ns,
            bytes,
            hash,
        })
    }
    fn append(&self, r: &Observation) -> Result<()> {
        self.write(
            "observations",
            r.sequence,
            &json!([
                r.binding, r.sequence, r.previous, r.action, r.status, r.at_ns, r.bytes, r.hash
            ]),
        )
    }
}

struct VenueState {
    order: RefCell<Value>,
    posts: Cell<usize>,
    requests: RefCell<Vec<Value>>,
    filled: bool,
}
struct LostAck {
    base: Fake,
    venue: Rc<VenueState>,
}
impl Exchange for LostAck {
    fn preflight(&self, b: &Budget) -> Result<()> {
        self.base.preflight(b)
    }
    fn close(&self) {
        self.base.close()
    }
    fn subscribe(&self, id: &str, b: &Budget) -> Result<Vec<u8>> {
        self.base.subscribe(id, b)
    }
    fn next(&self, b: &Budget) -> Result<Vec<u8>> {
        self.base.next(b)
    }
    fn request(
        &self,
        m: &str,
        path: &str,
        p: &BTreeMap<String, String>,
        b: &Budget,
    ) -> Result<Response> {
        let response = match (m, path) {
            ("POST", "/api/v3/order") => {
                assert!(self.venue.order.borrow().is_null());
                self.venue.posts.set(self.venue.posts.get() + 1);
                let row = json!({"symbol":p["symbol"],"side":p["side"],"type":p["type"],"timeInForce":p["timeInForce"],"price":p["price"],"origQty":p["quantity"],"orderId":9001,"clientOrderId":p["newClientOrderId"],"executedQty":if self.venue.filled{p["quantity"].as_str()}else{"0"},"status":if self.venue.filled{"FILLED"}else{"NEW"},"updateTime":3000});
                self.venue.order.replace(row);
                return Err(err("SENT_BUT_ACK_LOST"));
            }
            ("GET", "/api/v3/openOrders") => {
                let order = self.venue.order.borrow();
                if order["status"] == "NEW" {
                    json!([*order])
                } else {
                    json!([])
                }
            }
            ("GET", "/api/v3/order") => {
                self.venue.requests.borrow_mut().push(json!(p));
                let order = self.venue.order.borrow();
                assert_eq!(p["symbol"], order["symbol"]);
                if let Some(venue) = p.get("orderId") {
                    assert_eq!(venue, "9001");
                } else {
                    assert_eq!(p["origClientOrderId"], order["clientOrderId"]);
                }
                order.clone()
            }
            ("GET", "/api/v3/myTrades") => {
                let order = self.venue.order.borrow();
                assert_eq!(p["symbol"], order["symbol"]);
                assert_eq!(p["orderId"], "9001");
                assert_eq!(p["fromId"], "0");
                if self.venue.filled {
                    json!([{"symbol":order["symbol"],"orderId":9001,"id":7001,"price":order["price"],"qty":order["origQty"],"time":3000,"isMaker":false,"isBuyer":true,"commission":"0","commissionAsset":"USDT"}])
                } else {
                    json!([])
                }
            }
            _ => return self.base.request(m, path, p, b),
        };
        Ok(Response {
            status: 200,
            bytes: response.to_string().into_bytes(),
            retry_after_ms: None,
        })
    }
}

fn currency() -> OnlyCurrency {
    OnlyCurrency::new("USDT", 8, OnlyCurrencyType::Crypto).unwrap()
}
fn money(value: &str) -> Value {
    let amount = value
        .parse::<bigdecimal::BigDecimal>()
        .unwrap()
        .with_scale(8)
        .to_plain_string();
    json!({"schema_version":1,"amount":amount,"currency":currency().to_record()})
}
fn configuration(scope: &Scope, symbol: &str) -> Value {
    let mut cfg = scope.record();
    let instrument = format!("{symbol}.BINANCE");
    cfg.as_object_mut().unwrap().extend(json!({"schema_version":1,"currency":currency().to_record(),"initial_cash":"1000.00000000","capitals":{"cluster":"1000.00000000"},"profiles":{"cluster":{"schema_version":1,"revision":"revision","instruments":[instrument],"rules":[]}},"instruments":[{"schema_version":1,"id":instrument,"price_precision":2,"quantity_precision":2,"multiplier":"1"}]}).as_object().unwrap().clone());
    cfg
}

fn zero_fees(template: &Value, instrument: &Value) -> Value {
    let mut binding = OnlyOrderFeePolicyBinding::from_record(&template["binding"])
        .unwrap()
        .input();
    let id = onlyalpha_domain::identifiers::OnlyInstrumentId::from_record(instrument).unwrap();
    let mut scope = binding.applicability_scope.input();
    scope.instrument_id = id.clone();
    scope.charge_currency = currency();
    scope.fingerprint.clear();
    binding.applicability_scope = OnlyOrderFeeApplicabilityScopeIdentity::create(scope).unwrap();
    binding.instrument_id = id.clone();
    binding.charge_currency = currency();
    binding.fingerprint.clear();
    let binding = OnlyOrderFeePolicyBinding::create(binding).unwrap();
    let mut estimate = OnlyOrderFeeEstimate::from_record(&template["estimate"])
        .unwrap()
        .input();
    let zero = OnlyMoney::from_record(&money("0")).unwrap();
    let mut assessment = estimate.expected.input();
    let mut subject = assessment.subject.input();
    subject.instrument_id = id;
    assessment.subject = OnlyFeeSubject::new(subject).unwrap();
    assessment.binding = binding.clone();
    assessment.policy_fingerprint = binding.fingerprint().clone();
    assessment.total_charges = zero.clone();
    assessment.total_rebates = zero.clone();
    let assessment = OnlyFeeAssessment::new(assessment).unwrap();
    estimate.expected = assessment.clone();
    estimate.maximum = assessment;
    estimate.reservation_charge = zero.clone();
    estimate.estimated_rebate = zero.clone();
    let estimate = OnlyOrderFeeEstimate::new(estimate).unwrap();
    let mut funding = OnlyOrderFundingPlan::from_record(&template["funding"])
        .unwrap()
        .input();
    funding.binding_fingerprint = binding.fingerprint().clone();
    funding.principal_reservation = OnlyMoney::from_record(&money("250.001")).unwrap();
    funding.total_reservation = funding.principal_reservation.clone();
    funding.fee_reservation = zero;
    json!({"binding":binding.to_record(),"estimate":estimate.to_record(),"funding":OnlyOrderFundingPlan::new(funding).unwrap().to_record()})
}

fn input(scope: &Scope, n: u64, op: &str, payload: Value) -> Value {
    let mut row = scope.record();
    row.as_object_mut().unwrap().extend(json!({"schema_version":1,"cluster":"cluster","revision":"revision","input_id":format!("input-{n}"),"time":n,"runtime_sequence":n,"trading_day":"2026-10-19","day_index":1,"source_ref":format!("source-{n}"),"op":op,"payload":payload}).as_object().unwrap().clone());
    row
}
fn admission(scope: &Scope, symbol: &str) -> Value {
    let fixture: Value = serde_json::from_str(DOMAIN).unwrap();
    let mut request = fixture["request"].clone();
    request["instrument_id"]["symbol"]["value"] = json!(symbol);
    request["instrument_id"]["venue"]["value"] = json!("BINANCE");
    request["time_in_force"] = json!("GTC");
    request["price"]["value"] = json!("25000.10");
    request["quantity"] = json!({"schema_version":1,"value":"0.01","precision":2});
    let contract = zero_fees(&fixture["fee_contract"], &request["instrument_id"]);
    input(
        scope,
        1,
        "ADMIT",
        json!({"schema_version":1,"request":request,"order":ORDER,"fee_contract":contract,"fee_budget":"0","market":{"schema_version":1,"verdict":"ACCEPT","source_ref":"controlled-spot-market","request_digest":digest(&request),"notional":money("250.001"),"rounding":"HALF_EVEN"},"collateral":{"schema_version":1,"kind":"NONE","instruction":null,"close_allocation":null}}),
    )
}

struct Cash {
    owners: Components,
    store: SqliteStore,
}
impl Cash {
    fn open(dir: &Path, cfg: &Value, fresh: bool) -> Self {
        let artifact = "a".repeat(64);
        let mut store = if fresh {
            SqliteStore::create(dir, cfg.clone(), &artifact)
        } else {
            SqliteStore::open(dir, cfg.clone(), &artifact)
        }
        .unwrap();
        let mut owners = Components::new(cfg.clone()).unwrap();
        recover(&mut store, &mut owners).unwrap();
        Self { owners, store }
    }
    fn apply(&mut self, row: &Value) -> onlyalpha_execution::Prepared {
        let p = self.owners.prepare(&self.store, row).unwrap();
        coordinate(&mut self.store, &mut self.owners, &p).unwrap();
        p
    }
    fn snapshot(&self) -> Result<Value> {
        self.owners
            .order_snapshot(&self.store, "cluster", ORDER)
            .map(|s| s.to_record())
            .map_err(storage)
    }
    fn submission(&self) -> Result<String> {
        self.owners
            .order_submission(&self.store, "cluster", ORDER)
            .map_err(storage)
    }
    fn command(&self, scope: &Scope, admit: &Value) -> BrokerCommand {
        let snapshot = self.snapshot().unwrap();
        let mut request = admit["payload"]["request"].clone();
        request["account_id"] = snapshot["account_id"].clone();
        BrokerCommand::decode(&json!({"schema_version":1,"operation":"SUBMIT","scope":scope.record(),"command_id":"submit-original","order":ORDER,"client":snapshot["client_order_id"]["value"],"request":request})).unwrap()
    }
}

fn source_input(observed: &ObservedFact, admit: &Value, n: u64) -> Result<Value> {
    let fact = observed.fact();
    let raw = fact.record();
    let payload = &raw["payload"];
    let scope = fact.scope();
    let order = payload["order"]
        .as_str()
        .ok_or_else(|| err("OBSERVED_ORDER"))?;
    let (op, body) = match raw["kind"].as_str() {
        Some("ACCEPTED") => (
            "ACCEPT",
            json!({"schema_version":1,"order":order,"venue_order":payload["venue"]}),
        ),
        Some("TRADE") => {
            let fill = &payload["fill"];
            let trade = &fill["trade_id"]["value"];
            let request = &admit["payload"]["request"];
            let instrument = &request["instrument_id"];
            let currency = currency().to_record();
            let gross = crate::wire_decimal(&fill["price"]["value"])?
                * crate::wire_decimal(&fill["quantity"]["value"])?;
            let mut proof_scope = scope.record();
            proof_scope.as_object_mut().unwrap().extend(json!({"schema_version":1,"cluster":"cluster","revision":"revision","instrument":format!("{}.{}",instrument["symbol"]["value"].as_str().unwrap(),instrument["venue"]["value"].as_str().unwrap()),"request":request["request_id"]["value"]}).as_object().unwrap().clone());
            let settlement: Value = serde_json::from_str(SETTLEMENT)?;
            let calendar = OnlyTradingCalendar::from_record(&json!({
                "schema_version": 1,
                "calendar_id": {"schema_version": 1, "value": "controlled-spot-continuous"},
                "venue_id": instrument["venue"],
                "timezone": {"schema_version": 1, "name": "UTC"},
                "sessions": [{
                    "schema_version": 1, "name": "continuous",
                    "opens_at": "00:00:00", "closes_at": "00:00:00",
                    "session_type": "CONTINUOUS", "belongs_to_trading_day_offset": 0,
                    "allows_orders": true, "allows_market_data": true
                }],
                "holidays": [], "weekend_days": [], "session_profile_id": null,
                "special_schedules": [], "calendar_version": 1,
                "effective_from": null, "effective_to": null
            }))
            .map_err(|_| err("CASH_SETTLEMENT_CALENDAR"))?;
            let mut p = json!({"schema_version":1,"order":order,"trade":trade,"venue_trade":fill["venue_trade_id"]["value"],"venue_order":fill["venue_order_id"]["value"],"quantity":fill["quantity"]["value"],"price":fill["price"]["value"],
                "fees":{"schema_version":1,"instruction":"controlled-fee","source_ref":"controlled-fee-source","policy":admit["payload"]["fee_contract"]["binding"]["fingerprint"],"order":order,"trade":trade,"currency":currency,"charge_target":"0.00000000","rebate_target":"0.00000000"},
                "settlement":{"schema_version":1,"instruction":"controlled-settlement","source_ref":"controlled-settlement-source","order":order,"trade":trade,"currency":currency,"model":"CASH_SETTLEMENT","gross_notional":money(&gross.to_plain_string()),"rounding":"HALF_EVEN","calendar":calendar.to_record(),"policy":settlement["policy"]},
                "valuation":{"schema_version":1,"source_ref":"controlled-valuation-source","currency":currency,"mark":fill["price"]["value"]},
                "collateral":{"schema_version":1,"kind":"NONE","instruction":null,"close_allocation":null}});
            for (field, family) in [
                ("fees", "ORDER_FEE_ACCRUAL"),
                ("settlement", "SETTLEMENT"),
                ("valuation", "VALUATION"),
            ] {
                let item = &mut p[field];
                item["scope"] = proof_scope.clone();
                item["family"] = json!(family);
                item["version"] = json!(n);
                item["as_of_sequence"] = json!(n);
                item["source_digest"] = json!(digest(item));
            }
            ("FILL", p)
        }
        _ => return Err(err("OBSERVED_OPERATION")),
    };
    let mut row = input(&scope, n, op, body);
    row["input_id"] = json!(fact.identity());
    row["time"] = raw["ts_event"].clone();
    // 多个 fact 可共享一条 DISCOVERY。引用同时绑定原 Journal 行和该行中的确切事实。
    row["source_ref"] = json!(digest(&json!([
        scope.record(),
        observed.source(),
        fact.identity()
    ])));
    Ok(row)
}

struct Reader<'a> {
    cash: &'a Cash,
    journal: &'a Logs,
    scope: &'a Scope,
}
impl Reader<'_> {
    fn admission(&self, c: &BrokerCommand) -> Result<onlyalpha_execution::Record> {
        if c.scope() != self.scope || c.operation() != Operation::Submit || c.order() != ORDER {
            return Err(err("CASH_ORDER_CONTEXT"));
        }
        let rows = self
            .cash
            .owners
            .ready_records(&self.cash.store)
            .map_err(storage)?;
        let mut matched = rows.into_iter().filter(|r| {
            let i = r.prepared().input();
            i["op"] == "ADMIT" && i["payload"]["order"] == c.order()
        });
        let r = matched
            .next()
            .ok_or_else(|| err("CASH_ADMISSION_MISSING"))?;
        let i = r.prepared().input();
        let snap = self.cash.snapshot()?;
        let mut expected = i["payload"]["request"].clone();
        expected["account_id"] = snap["account_id"].clone();
        if matched.next().is_some()
            || !r.ready()
            || [
                "engine",
                "account",
                "runtime",
                "gateway",
                "generation",
                "runtime_kind",
            ]
            .iter()
            .any(|k| i[*k] != self.scope.record()[*k])
            || c.record()["request"] != expected
            || snap["client_order_id"]["value"] != c.client()
            || snap["order_id"]["value"] != c.order()
        {
            return Err(err("CASH_ADMISSION_RELATION"));
        }
        Ok(r)
    }
    fn linked_intent(&self, c: &BrokerCommand) -> Result<ReadyIntent> {
        let row = self.admission(c)?;
        let p = row.prepared();
        ReadyIntent::new(
            c.clone(),
            p.id().to_string(),
            p.record()["payload_hash"]
                .as_str()
                .ok_or_else(|| err("CASH_READY_HASH"))?
                .into(),
        )
    }
    fn observation(&self, f: &Fact) -> Result<ObservedFact> {
        if f.scope() != *self.scope {
            return Err(err("CASH_FACT_SCOPE"));
        }
        let broker = Broker::recover(self.scope.clone(), self.journal, 16)?;
        let o = broker.observed(f.identity())?;
        if o.fact().record() != f.record() || o.fact().fingerprint() != f.fingerprint() {
            return Err(err("CASH_ORIGINAL_FACT_CONFLICT"));
        }
        let command = BrokerCommand::decode(&o.intent().record()["command"])?;
        if self.linked_intent(&command)?.record() != o.intent().record() {
            return Err(err("CASH_ORIGINAL_INTENT_CONFLICT"));
        }
        Ok(o)
    }
}
impl RuntimeReader for Reader<'_> {
    fn ready_intent(&self, c: &BrokerCommand) -> Result<ReadyIntent> {
        let intent = self.linked_intent(c)?;
        if self.cash.snapshot()?["status"] != "SUBMITTED"
            || self.cash.submission()? != "DISPATCHING"
        {
            return Err(err("CASH_NOT_DISPATCHABLE"));
        }
        Ok(intent)
    }
    fn application_receipt(&self, f: &Fact) -> Result<Option<ApplicationReceipt>> {
        let observed = self.observation(f)?;
        let c = BrokerCommand::decode(&observed.intent().record()["command"])?;
        let admitted = self.admission(&c)?;
        let rows = self
            .cash
            .owners
            .ready_records(&self.cash.store)
            .map_err(storage)?;
        for row in rows {
            let p = row.prepared();
            let i = p.input();
            if i["input_id"] != f.identity() {
                continue;
            }
            if !row.ready()
                || *i != source_input(&observed, admitted.prepared().input(), p.sequence())?
            {
                return Err(err("CASH_APPLIED_INPUT_CONFLICT"));
            }
            return ApplicationReceipt::new(
                f,
                p.id().into(),
                p.record()["payload_hash"]
                    .as_str()
                    .ok_or_else(|| err("CASH_APPLICATION_HASH"))?
                    .into(),
                ApplicationStatus::Applied,
            )
            .map(Some);
        }
        Ok(None)
    }
    fn order_view(&self, c: &BrokerCommand) -> Result<Option<OrderView>> {
        self.admission(c)?;
        let s = self.cash.snapshot()?;
        if s["venue_order_id"].is_null() {
            return Ok(None);
        }
        let filled = s["filled_quantity"]["value"]
            .as_str()
            .ok_or_else(|| err("CASH_QUANTITY"))?
            .parse::<bigdecimal::BigDecimal>()
            .map_err(storage)?
            .normalized()
            .to_plain_string();
        OrderView::decode(&json!({"scope":self.scope.record(),"order":s["order_id"]["value"],"client":s["client_order_id"]["value"],"venue":s["venue_order_id"]["value"],"request":c.record()["request"],"filled":filled,"status":s["status"]})).map(Some)
    }
}

fn gateway(
    f: &Fixture,
    logs: &Logs,
    state: &Rc<VenueState>,
    cp: Option<&Checkpoint>,
) -> SpotBroker<Logs> {
    let io = LostAck {
        base: Fake(f.state.clone()),
        venue: state.clone(),
    };
    SpotBroker::restore(
        f.config.clone(),
        Arc::new(Fixed),
        logs.clone(),
        Box::new(logs.clone()),
        cp,
        16,
        Box::new(io),
    )
    .unwrap()
}
fn connect(g: &mut SpotBroker<Logs>) {
    g.connect().unwrap();
    g.authenticate().unwrap();
    g.subscribe().unwrap();
}

fn scenario(symbol: &str, wrong_reference: bool) {
    let root = Root::new();
    let f = Fixture::new();
    let scope = &f.config.scope;
    let cfg = configuration(scope, symbol);
    let dir = root.0.join("execution");
    let logs = Logs(root.0.clone());
    let venue = Rc::new(VenueState {
        order: RefCell::new(Value::Null),
        posts: Cell::new(0),
        requests: RefCell::new(Vec::new()),
        filled: symbol == "BTCUSDT",
    });
    let mut cash = Cash::open(&dir, &cfg, true);
    let admit = admission(scope, symbol);
    cash.apply(&admit);
    let command = cash.command(scope, &admit);
    let mut g = gateway(&f, &logs, &venue, None);
    connect(&mut g);
    let reader = Reader {
        cash: &cash,
        journal: &logs,
        scope,
    };
    g.synchronize(&reader).unwrap();
    assert_eq!(
        g.dispatch(&reader, &command).unwrap(),
        CommandState::Unknown
    );
    assert_eq!(venue.posts.get(), 1);
    let cp = g.checkpoint().unwrap();
    cash.apply(&input(
        scope,
        2,
        "SUBMISSION",
        json!({"schema_version":1,"order":ORDER,"outcome":"UNKNOWN"}),
    ));
    drop((g, cash));
    let mut cash = Cash::open(&dir, &cfg, false);
    let mut g = gateway(&f, &logs, &venue, Some(&cp));
    let reader = Reader {
        cash: &cash,
        journal: &logs,
        scope,
    };
    assert_eq!(cash.command(scope, &admit), command);
    assert_eq!(cash.submission().unwrap(), "UNKNOWN");
    assert!(reader.ready_intent(&command).is_err());
    assert_eq!(
        g.dispatch(&reader, &command).unwrap(),
        CommandState::Unknown
    );
    assert_eq!(venue.posts.get(), 1);
    connect(&mut g);
    g.reconcile(command.id()).unwrap();
    assert_eq!(g.pending().len(), 1);
    let fact = g.pending()[0].clone();
    assert_eq!(
        fact.record()["kind"],
        if venue.filled { "TRADE" } else { "ACCEPTED" }
    );
    assert_eq!(reader.application_receipt(&fact).unwrap(), None);
    assert!(g.resolve(&reader, command.id()).is_err());
    let observation = reader.observation(&fact).unwrap();
    let mut changed = fact.record();
    changed["session"] = json!("foreign-occurrence");
    let changed = Fact::decode(&changed).unwrap();
    assert_eq!(fact.identity(), changed.identity());
    assert!(reader.observation(&changed).is_err());
    let mut application = source_input(&observation, &admit, 3).unwrap();
    if wrong_reference {
        application["source_ref"] = json!("other-journal-row");
    }
    let prepared = cash.apply(&application);
    let after = cash.snapshot().unwrap();
    // 同一 Prepared 重交只复查同一事务。
    coordinate(&mut cash.store, &mut cash.owners, &prepared).unwrap();
    assert_eq!(cash.store.head().unwrap(), 3);
    assert_eq!(cash.snapshot().unwrap(), after);
    let cp = g.checkpoint().unwrap();
    drop((g, cash));
    let cash = Cash::open(&dir, &cfg, false);
    let mut g = gateway(&f, &logs, &venue, Some(&cp));
    connect(&mut g);
    let reader = Reader {
        cash: &cash,
        journal: &logs,
        scope,
    };
    let mut other_scope = scope.record();
    other_scope["account"] = json!("other-cash-account");
    let other_scope = Scope::decode(&other_scope).unwrap();
    let foreign = Reader {
        scope: &other_scope,
        ..reader
    };
    assert_eq!(
        foreign.application_receipt(&fact).unwrap_err(),
        err("CASH_FACT_SCOPE")
    );
    let sequence = observation.source()["sequence"].as_u64().unwrap();
    let journal_dir = logs.dir("journal");
    let original = journal_dir.join(sequence.to_string());
    let held = journal_dir.join("held-original");
    fs::rename(&original, &held).unwrap();
    let unavailable = reader.application_receipt(&fact);
    fs::rename(&held, &original).unwrap();
    assert_eq!(unavailable.unwrap_err(), err("OFFLINE_STORE_UNAVAILABLE"));
    if wrong_reference {
        assert_eq!(
            reader.application_receipt(&fact).unwrap_err(),
            err("CASH_APPLIED_INPUT_CONFLICT")
        );
        assert!(g.resolve(&reader, command.id()).is_err());
        assert!(!g.ready());
    } else {
        let receipt = reader.application_receipt(&fact).unwrap().unwrap();
        assert_eq!(
            receipt,
            ApplicationReceipt::new(
                &fact,
                prepared.id().into(),
                prepared.record()["payload_hash"].as_str().unwrap().into(),
                ApplicationStatus::Applied
            )
            .unwrap()
        );
        assert_eq!(after["client_order_id"]["value"], command.client());
        assert_eq!(
            after["venue_order_id"]["value"],
            format!("BINANCE:{symbol}:9001")
        );
        assert_eq!(
            after["status"],
            if venue.filled { "FILLED" } else { "ACCEPTED" }
        );
        let quantity = after["filled_quantity"]["value"]
            .as_str()
            .unwrap()
            .parse::<bigdecimal::BigDecimal>()
            .unwrap();
        assert_eq!(
            quantity,
            if venue.filled { "0.01" } else { "0" }
                .parse::<bigdecimal::BigDecimal>()
                .unwrap()
        );
        assert_eq!(cash.submission().unwrap(), "RESOLVED");
        g.resolve(&reader, command.id()).unwrap();
        assert_eq!(g.command_state(command.id()), Some(CommandState::Resolved));
        g.synchronize(&reader).unwrap();
        assert!(g.ready());
        assert!(g.pending().is_empty());
    }
    assert_eq!(venue.posts.get(), 1);
    let requests = venue.requests.borrow();
    assert!(
        requests
            .iter()
            .any(|r| r["origClientOrderId"] == wire_client(command.client()))
    );
    assert!(requests.iter().all(|r| r["symbol"] == symbol
        && (r["origClientOrderId"] == wire_client(command.client()) || r["orderId"] == "9001")));
}

#[test]
fn original_unknown_spot_orders_recover_against_cold_cash_execution_and_exact_journal_facts() {
    scenario("BTCUSDT", false);
    scenario("ETHUSDT", false);
    scenario("BTCUSDT", true);
}
