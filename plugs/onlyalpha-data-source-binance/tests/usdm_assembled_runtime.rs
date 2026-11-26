//! 原始 USD-M 行情、规则、Virtual 场所与有限内存交易内核的库级组合。
//! 经济工作只在内存中保留；恢复是对同一冻结输入的确定性重算，
//! 不存在可以重新读取的持久前缀或旧格式 reader。
use onlyalpha_broker::{BrokerCommand, Fact, Scope};
use onlyalpha_broker_virtual::{MemoryVirtualActor, VirtualBroker};
use onlyalpha_data_source_binance::{
    reference_capture::ReferenceCapture, spot_normalize, usdm_facts,
};
use onlyalpha_domain::{
    base::OnlyDomainModel, identifiers::OnlyInstrumentId, instrument::OnlyInstrument,
    market::OnlyBar, time::OnlyUtcDateTime, trading::OnlyReferencePriceKind, value::OnlyMoney,
};
use onlyalpha_execution::{Error, MarketSourceCut, funding_boundary};
use onlyalpha_market_crypto::market_policy::{MarketBinding, Product};
use onlyalpha_runtime::{RunBinding, RunConfiguration, Session, TradingInput};
use serde_json::{Value, json};
use std::collections::BTreeMap;

const INSTRUMENT: &str = "BTCUSDT-PERP.BINANCE";
const ORDER: &str = "runtime-ORDER-000001";
const BOUNDARY: i64 = 1_788_249_600_000;
const MINUTE: i64 = 60_000;
const VERSION: &str = "recorded-perpetual-bars-v1";
const ACCT: &str = "backtest-account";
const SOURCE_BYTES: [&[u8]; 4] = [
    include_bytes!("fixtures/usdm-exchange.json"),
    include_bytes!("fixtures/usdm-funding.json"),
    include_bytes!("fixtures/usdm-brackets.json"),
    include_bytes!("fixtures/usdm-account.json"),
];

fn initial_currency() -> Value {
    json!({"schema_version":1,"code":"USDT","precision":8,"currency_type":"CRYPTO"})
}
fn cash_of(currency: &Value, amount: &str) -> OnlyMoney {
    OnlyMoney::from_record(&json!({"schema_version":1,"amount":amount,"currency":currency}))
        .unwrap()
}
fn venue_config() -> Value {
    json!({"maximum_fill_quantity":"0.001"})
}
fn broker_fee() -> (Value, Value) {
    let contract = json!({"id":"VIRTUAL_SIMULATION_ZERO","version":"1","broker":"virtual","account":ACCT,"families":["zero"]});
    let schedule = json!({"namespace":"BROKER","family":"zero","version":"1","from":0,"to":null,
        "scope":{"broker":"virtual","account":ACCT,"currency":"USDT"},
        "rules":[{"id":"zero","type":"BROKER_COMMISSION","authority":"BROKER","direction":"CHARGE","scope":"FILL",
        "resolution":"ORDER_FIXED","terms":[{"kind":"FIXED","amount":"0"}],"minimum":null,"maximum":null,
        "quantum":"0.00000001","rounding":"HALF_EVEN","pipeline":"ROUND_THEN_BOUNDS","side":null,"offset":null,"liquidity":null}]});
    (contract, schedule)
}
fn usdm_terms() -> Value {
    usdm_terms_for_account(false)
}
fn usdm_terms_for_account(hedging: bool) -> Value {
    // 单独确定已知的观测点和历史覆盖域，所有交易均晚于该观测点。
    let at: OnlyUtcDateTime = "2026-08-31T00:00:00Z".parse().unwrap();
    let start = "2026-08-01T00:00:00Z".parse().unwrap();
    let mut source = SOURCE_BYTES;
    if hedging {
        source[3] = br#"{"positionMode":"HEDGING","symbols":[{"symbol":"BTCUSDT","marginMode":"ISOLATED","leverage":"10"}]}"#;
    }
    let capture = ReferenceCapture::usdm(
        source,
        at,
        start,
        Some("2026-09-02T00:00:00Z".parse().unwrap()),
    )
    .unwrap();
    let refs = capture.authorities();
    let authoring = json!({"public_reference_resource_id":"public","expected_public_reference_fingerprint":refs[0].fingerprint(),
        "account_reference_resource_id":"account","expected_account_reference_fingerprint":refs[1].fingerprint(),
        "requested_position_mode":if hedging {"HEDGING"} else {"NETTING"},"requested_margin_mode":if hedging {"ISOLATED"} else {"CROSS"},"requested_leverage":"10","maker_fee_rate":"0.0002","taker_fee_rate":"0.0005"});
    let resources = BTreeMap::from([
        ("public".into(), refs[0].clone()),
        ("account".into(), refs[1].clone()),
    ]);
    let binding = MarketBinding::resolve(Product::Usdm, &authoring, &resources).unwrap();
    // 资源在前一日观测；本 Run 的编译日明确锚定首个 UTC 交易日。
    let policy = binding
        .compile(INSTRUMENT, "2026-09-01T00:00:00Z".parse().unwrap())
        .unwrap();
    policy
        .validate_limit(&"60000".parse().unwrap(), &"0.002".parse().unwrap())
        .unwrap();
    let (broker, schedule) = broker_fee();
    let catalog = binding.fee_catalog(&broker, &[schedule]).unwrap();
    let p = policy.record();
    json!({"schema_version":1,"instrument":INSTRUMENT,"account":ACCT,"cluster":"cluster","data_version":VERSION,
        "source":"BINANCE_USDM","market_binding":binding.fingerprint(),"market_product":"BINANCE_USDM","policy_fingerprint":p["policy_fingerprint"],
        "compiled_policy_json":policy.compiled_policy_json().unwrap(),"limit_rules_fingerprint":policy.static_limit_rules().unwrap().content_fingerprint(),"limit_rules":policy.static_limit_rules().unwrap().to_record(),"position_mode":p["position_mode"],"margin_mode":p["margin_mode"],"contract_type":"LINEAR",
        "multiplier":p["contract_multiplier"],"currency":initial_currency(),"margin_segments":p["margin_segments"],
        "funding_schedule":p["funding_schedule"],"fee_catalog":catalog.record()})
}
fn config(cash: &str, terms: Value) -> Value {
    let mut cfg = json!({"schema_version":3,"account_checkpoint_version":5,"engine":"engine","runtime":"runtime","account":ACCT,"gateway":"virtual",
        "generation":"a".repeat(64),"runtime_kind":"BACKTEST","currency":initial_currency(),"initial_cash":cash,
        "capitals":{"cluster":cash},"profiles":{"cluster":{"schema_version":1,"revision":"b".repeat(64),"instruments":[terms["instrument"]],"rules":[]}},
        "instruments":[{"schema_version":1,"id":terms["instrument"],"price_precision":2,"quantity_precision":3,"multiplier":terms["multiplier"]}],
        "perpetual":terms});
    let scope = Scope::decode(&scope(&cfg)).unwrap();
    let origin = VirtualBroker::new(
        scope,
        &"f".repeat(64),
        cash_of(&cfg["currency"], cash),
        &venue_config(),
    )
    .unwrap();
    cfg["perpetual"]["execution_source_binding"] =
        json!(onlyalpha_broker::digest(origin.source_binding()));
    bind_sources(&mut cfg, false);
    cfg
}
fn bind_sources(cfg: &mut Value, late: bool) {
    let id = INSTRUMENT.parse().unwrap();
    let mut rows = Vec::new();
    for (ms, time, sequence, price) in [
        (BOUNDARY - 2 * MINUTE, "2026-09-01T07:58:00Z", 3, "60000.00"),
        (BOUNDARY - MINUTE, "2026-09-01T07:59:00Z", 4, "60000.00"),
        (
            BOUNDARY - MINUTE + 1000,
            "2026-09-01T07:59:01Z",
            5,
            "60100.00",
        ),
        (BOUNDARY + MINUTE, "2026-09-01T08:01:00Z", 6, "60000.00"),
    ] {
        let raw = serde_json::to_vec(&json!({"T":ms,"p":price})).unwrap();
        rows.push(
            usdm_facts::source_cut_row(
                &raw,
                Some(OnlyReferencePriceKind::Mark),
                &usdm_facts::Context {
                    instrument_id: &id,
                    data_version: VERSION,
                    source_sequence: sequence,
                    received_at: time.parse().unwrap(),
                },
            )
            .unwrap(),
        );
    }
    let raw=serde_json::to_vec(&json!({"symbol":"BTCUSDT","fundingTime":BOUNDARY,"markPrice":"60000.00","fundingRate":"0.0001"})).unwrap();
    rows.push(
        usdm_facts::source_cut_row(
            &raw,
            None,
            &usdm_facts::Context {
                instrument_id: &id,
                data_version: VERSION,
                source_sequence: 5,
                received_at: if late {
                    "2026-09-01T08:00:01Z"
                } else {
                    "2026-09-01T08:00:00Z"
                }
                .parse()
                .unwrap(),
            },
        )
        .unwrap(),
    );
    let data = serde_json::to_vec(&rows).unwrap();
    cfg["perpetual"]["source_cut_sha256"] =
        json!(onlyalpha_market_crypto::reference::raw_sha256(&data));
    cfg["perpetual"]["source_rows"] = json!(rows);
}
fn scope(cfg: &Value) -> Value {
    let mut s = json!({});
    for k in [
        "engine",
        "runtime",
        "gateway",
        "account",
        "generation",
        "runtime_kind",
    ] {
        s[k] = cfg[k].clone();
    }
    s
}
fn msg(cfg: &Value, seq: u64, ms: i64, op: &str, payload: Value) -> Value {
    let mut result = scope(cfg);
    let fields = json!({"schema_version":1,"cluster":"cluster","revision":cfg["profiles"]["cluster"]["revision"],"input_id":format!("input-{seq}"),
        "runtime_sequence":seq,"source_ref":format!("occurrence-{seq}"),"time":ms*1_000_000,"trading_day":"2026-09-01","day_index":1,
        "op":op,"payload":payload});
    result
        .as_object_mut()
        .unwrap()
        .extend(fields.as_object().unwrap().clone());
    result
}
fn request(instrument: &str, q: &str) -> Value {
    let instrument: OnlyInstrumentId = instrument.parse().unwrap();
    json!({"schema_version":1,"request_id":{"schema_version":1,"value":"long-open"},"account_id":{"schema_version":1,"value":ACCT},
        "instrument_id":instrument.to_record(),"side":"BUY","order_type":"LIMIT","quantity":{"schema_version":1,"precision":3,"value":q},
        "time_in_force":"GTC","offset":"OPEN","price":{"schema_version":1,"precision":2,"value":"60000.00"},
        "stop_price":null,"expire_time":null,"tags":[],"metadata":{},
        "execution_intent":{"schema_version":2,"side":"BUY","position_mode":"NETTING","position_effect":"OPEN","position_side":"LONG","close_scope":"ANY","exposure_constraint":"NONE"}})
}
fn instrument() -> OnlyInstrument {
    let mut row = spot_normalize::instrument(&json!({"symbol":"BTCUSDT","baseAsset":"BTC","quoteAsset":"USDT","status":"TRADING",
        "filters":[{"filterType":"PRICE_FILTER","tickSize":"0.10"},{"filterType":"LOT_SIZE","stepSize":"0.001","minQty":"0.001"}]})).unwrap().to_record();
    row["model_type"] = json!("OnlyCryptoPerpetual");
    row["instrument_id"]["symbol"]["value"] = json!("BTCUSDT-PERP");
    row["instrument_type"] = json!("CRYPTO_PERPETUAL");
    row["market_type"] = json!("DERIVATIVE");
    row["margin_currency"] = row["quote_currency"].clone();
    row["contract_type"] = json!("LINEAR");
    OnlyInstrument::from_record(&row).unwrap()
}
fn bar(minute: i64) -> OnlyBar {
    let start = BOUNDARY + minute * MINUTE;
    usdm_facts::contract_bar(
        &json!([
            start,
            "60000.00",
            "60000.00",
            "60000.00",
            "60000.00",
            "1.000",
            start + MINUTE - 1,
            "60000.00",
            1,
            "0",
            "0",
            "0"
        ]),
        &instrument(),
    )
    .unwrap()
}
fn mark(minute: i64) -> Value {
    let received = match minute {
        -2 => "2026-09-01T07:58:00Z",
        -1 => "2026-09-01T07:59:00Z",
        1 => "2026-09-01T08:01:00Z",
        _ => panic!("unlisted input"),
    };
    let id = INSTRUMENT.parse().unwrap();
    usdm_facts::reference_price(
        &json!({"T":BOUNDARY+minute*MINUTE,"p":"60000.00"}),
        OnlyReferencePriceKind::Mark,
        &usdm_facts::Context {
            instrument_id: &id,
            data_version: VERSION,
            source_sequence: minute + 5,
            received_at: received.parse().unwrap(),
        },
    )
    .unwrap()
    .to_record()
}
fn boundary() -> (Value, Value) {
    let id = INSTRUMENT.parse().unwrap();
    let raw = json!({"symbol":"BTCUSDT","fundingTime":BOUNDARY,"markPrice":"60000.00","fundingRate":"0.0001"});
    let (m, f) = usdm_facts::funding_boundary(
        &raw,
        &usdm_facts::Context {
            instrument_id: &id,
            data_version: VERSION,
            source_sequence: 5,
            received_at: "2026-09-01T08:00:00Z".parse().unwrap(),
        },
    )
    .unwrap();
    assert!(m.stable_order() < f.stable_order());
    (m.to_record(), f.to_record())
}

/// 内存驱动的一步：接受输入，或测试直接对内存场所做的操作。
/// 场所与经济状态都只在内存中保留，重算必须完整重现这份顺序。
enum Step {
    Input(Value),
    Bar(u64, Box<OnlyBar>),
    Advance(i64),
    Dispatch(Value),
    Publish,
}
struct Run {
    cfg: Value,
    scope: Scope,
    session: Session,
    venue: MemoryVirtualActor,
    cut: MarketSourceCut,
    seq: u64,
    steps: Vec<Step>,
}
impl Run {
    fn create(cfg: Value) -> Self {
        let configuration = RunConfiguration::from_record(cfg.clone()).unwrap();
        let binding = RunBinding::new(
            &configuration,
            &"e".repeat(64),
            &"c".repeat(64),
            &"d".repeat(64),
        )
        .unwrap();
        let session = Session::new(&configuration, &binding).unwrap();
        let scope = Scope::decode(&scope(&cfg)).unwrap();
        let expected = cfg["perpetual"]["execution_source_binding"]
            .as_str()
            .unwrap()
            .to_owned();
        let mut venue = MemoryVirtualActor::new(
            scope.clone(),
            &"f".repeat(64),
            cash_of(&cfg["currency"], cfg["initial_cash"].as_str().unwrap()),
            &venue_config(),
            &expected,
        )
        .unwrap();
        venue.connect().unwrap();
        venue.authenticate().unwrap();
        let cut = MarketSourceCut::read(
            &serde_json::to_vec(&cfg["perpetual"]["source_rows"]).unwrap(),
            cfg["perpetual"]["source_cut_sha256"].as_str().unwrap(),
        )
        .unwrap();
        Self {
            cfg,
            scope,
            session,
            venue,
            cut,
            seq: 0,
            steps: Vec::new(),
        }
    }
    fn input(&self, ms: i64, op: &str, payload: Value) -> Value {
        msg(&self.cfg, self.seq + 1, ms, op, payload)
    }
    /// 一次输入的完整协议：原始序列化证据、原始场所与确认。
    /// 被拒绝的输入不改变已保留前缀，也不进入重算顺序。
    fn accept(&mut self, input: &Value) -> Result<u64, Error> {
        let original = matches!(
            input["op"].as_str(),
            Some("MARK" | "FUNDING" | "ACCEPT" | "FILL" | "TERMINAL")
        );
        let event = if original {
            let source = if input["op"] == "FUNDING" {
                Some(
                    self.venue
                        .funding_history(
                            funding_boundary(&input["payload"]["fact"])?,
                            input["time"].as_u64().unwrap(),
                        )
                        .map_err(broker)?,
                )
            } else {
                None
            };
            self.session.apply_original(
                &TradingInput::from_record(input.clone())?,
                &self.cut,
                self.venue.broker(),
                source.as_ref(),
            )?
        } else {
            self.session
                .apply(&TradingInput::from_record(input.clone())?)?
        };
        let sequence = event.sequence();
        self.session.acknowledge(sequence)?;
        if let Some(id) = input["payload"]["broker"]["id"].as_str() {
            self.venue.acknowledge(&self.session, id).map_err(broker)?;
        }
        Ok(sequence)
    }
    fn record(&mut self, input: Value) -> Value {
        self.accept(&input).unwrap();
        self.seq += 1;
        self.steps.push(Step::Input(input.clone()));
        input
    }
    fn apply(&mut self, ms: i64, op: &str, payload: Value) -> Value {
        let input = self.input(ms, op, payload);
        self.record(input)
    }
    fn admit(&mut self, ms: i64, req: &Value) {
        self.apply(ms,"ADMIT",json!({"schema_version":3,"order":ORDER,"request":req,"policy_fingerprint":self.cfg["perpetual"]["policy_fingerprint"]}));
    }
    fn mark(&mut self, ms: i64, v: &Value) {
        self.apply(ms, "MARK", json!({"schema_version":1,"fact":v}));
    }
    fn publish(&mut self) -> usize {
        let count = self.venue.publish().unwrap();
        self.steps.push(Step::Publish);
        count
    }
    fn bar(&mut self, sequence: u64, bar: &OnlyBar) {
        self.venue.on_bar(sequence, bar).unwrap();
        self.steps.push(Step::Bar(sequence, Box::new(bar.clone())));
    }
    fn advance(&mut self, at: i64) {
        self.venue.advance(at).unwrap();
        self.steps.push(Step::Advance(at));
    }
    fn dispatch_record(&mut self, record: Value) {
        let command = BrokerCommand::decode(&record).unwrap();
        self.venue.dispatch(&self.session, &command).unwrap();
        self.steps.push(Step::Dispatch(record));
    }
    fn dispatch(&mut self, request: &Value) {
        let snapshot = self.session.order("cluster", ORDER).unwrap();
        let record = json!({"schema_version":1,"scope":self.scope.record(),"operation":"SUBMIT",
            "command_id":"original-submit","order":ORDER,"client":snapshot["client_order_id"]["value"],"request":request});
        self.dispatch_record(record);
    }
    fn consume(&mut self, ms: i64) -> Vec<Fact> {
        self.publish();
        let facts = self.venue.pending().to_vec();
        for fact in &facts {
            let body = fact.record();
            let op = match body["kind"].as_str().unwrap() {
                "ACCEPTED" => "ACCEPT",
                "TRADE" => "FILL",
                "REJECTED" => "TERMINAL",
                other => panic!("unexpected {other}"),
            };
            let proof = json!({"id":fact.identity(),"fingerprint":fact.fingerprint(),"record":body});
            let input = self.input(
                ms,
                op,
                json!({"schema_version":2,"order":ORDER,"broker":proof}),
            );
            self.record(input);
        }
        facts
    }
    /// 按同一配置和同一操作顺序从头重算；这是内存工作唯一的恢复语义。
    fn recompute(&self) -> Self {
        let mut restored = Self::create(self.cfg.clone());
        for (index, step) in self.steps.iter().enumerate() {
            match step {
                Step::Input(input) => {
                    if let Err(e) = restored.accept(input) {
                        panic!("recompute step {index} failed: {e}");
                    }
                    restored.seq += 1;
                    restored.steps.push(Step::Input(input.clone()));
                }
                Step::Bar(sequence, bar) => restored.bar(*sequence, bar),
                Step::Advance(at) => restored.advance(*at),
                Step::Dispatch(record) => restored.dispatch_record(record.clone()),
                Step::Publish => {
                    restored.publish();
                }
            }
        }
        restored
    }
    fn state(&self) -> Value {
        self.session.state().unwrap()
    }
    fn order_value(&self) -> Value {
        self.session.order("cluster", ORDER).unwrap()
    }
}
fn broker(e: impl std::fmt::Display) -> Error {
    Error(e.to_string())
}
fn amount(actual: &Value, expected: &str) {
    use bigdecimal::BigDecimal;
    assert_eq!(
        actual.as_str().unwrap().parse::<BigDecimal>().unwrap(),
        expected.parse::<BigDecimal>().unwrap()
    );
}
fn broker_submit(run: &mut Run, qty: &str) {
    let ms = BOUNDARY - 2 * MINUTE;
    run.bar(1, &bar(-3));
    run.mark(ms, &mark(-2));
    let r = request(INSTRUMENT, qty);
    run.admit(ms, &r);
    run.dispatch(&r);
    // 场所只有走到受理时钟才产出结果，与原始实现派发后的同刻推进一致。
    run.advance(run.venue.now());
    run.apply(
        ms,
        "SUBMISSION",
        json!({"schema_version":1,"order":ORDER,"outcome":"DISPATCHED"}),
    );
}
fn start(cash: &str, qty: &str) -> Run {
    let mut run = Run::create(config(cash, usdm_terms()));
    broker_submit(&mut run, qty);
    run
}
fn records(run: &Run) -> Vec<Value> {
    run.session
        .retained_facts()
        .iter()
        .map(|r| r.record())
        .collect()
}
fn accepted(run: &mut Run) {
    let facts = run.consume(BOUNDARY - 2 * MINUTE);
    assert_eq!(facts.len(), 1);
    assert_eq!(facts[0].record()["kind"], "ACCEPTED");
}
fn fills(run: &mut Run, qty: &str) -> (Value, Value) {
    let (boundary_mark, funding) = boundary();
    for (sequence, minute, m) in [(2_u64, -1, mark(-1)), (3, 0, boundary_mark.clone())] {
        let ms = BOUNDARY + minute * MINUTE;
        run.mark(ms, &m);
        run.bar(sequence, &bar(minute - 1));
        let received = run.consume(ms);
        if sequence == 3 && qty == "0.001" {
            assert!(received.is_empty());
        } else {
            assert_eq!(received.len(), 1);
            let raw = received[0].record();
            assert_eq!(raw["kind"], "TRADE");
            assert_eq!(raw["payload"]["fill"]["liquidity_side"], "TAKER");
            amount(&raw["payload"]["fill"]["quantity"]["value"], "0.001");
        }
    }
    run.advance(BOUNDARY * 1_000_000 + 1);
    (boundary_mark, funding)
}
fn funding_payload(m: &Value, f: &Value) -> Value {
    json!({"schema_version":1,"mark_fact_id":m["fact_id"],"fact":f})
}
fn verify_amounts(run: &Run, qty: &str) {
    let s = run.state();
    let a = &s["account"]["snapshot"];
    let l = &s["ledger"]["ledgers"]["cluster"]["snapshot"];
    let (fee, initial, maintenance, debit, equity, net) = match qty {
        "0.002" => (
            "0.06000000",
            "12",
            "0.48",
            "-0.01200000",
            "99999.92800000",
            "-0.072",
        ),
        "0.001" => (
            "0.03000000",
            "6",
            "0.24",
            "-0.00600000",
            "99999.96400000",
            "-0.036",
        ),
        _ => unreachable!(),
    };
    amount(&a["fees"], fee);
    amount(&a["occupied_margin"], initial);
    amount(&a["maintenance_required"], maintenance);
    amount(&a["reserved_margin"], "0");
    amount(&a["cash"], equity);
    amount(&a["equity"], equity);
    amount(&l["equity"], equity);
    amount(&l["net_pnl"], net);
    amount(&l["fees"], fee);
    amount(&l["external_cash_flow"], "0");
    assert!(!l["simple_return"].is_null());
    let order = run.order_value();
    assert_eq!(order["status"], "FILLED");
    amount(&order["filled_quantity"]["value"], qty);
    amount(&s["position"]["accounts"][0]["snapshot"]["quantity"], qty);
    amount(
        &s["position"]["allocations"][0]["snapshot"]["quantity"],
        qty,
    );
    let economic = &s["execution"]["perpetual"];
    assert_eq!(economic["marks"].as_object().unwrap().len(), 4);
    assert_eq!(economic["funding"].as_object().unwrap().len(), 1);
    let (m, f) = boundary();
    assert_eq!(economic["marks"][m["fact_id"].as_str().unwrap()], m);
    let event = &economic["funding"][f["fact_id"].as_str().unwrap()];
    assert_eq!(event["fact"], f);
    assert_eq!(event["mark_fact_id"], m["fact_id"]);
    assert_eq!(event["cashflow"]["account"], ACCT);
    assert_eq!(event["cashflow"]["cluster"], "cluster");
    amount(&event["cashflow"]["amount"], debit);
    let entries = s["ledger"]["ledgers"]["cluster"]["entries"]
        .as_array()
        .unwrap();
    assert_eq!(entries.iter().filter(|e| e["kind"] == "FUNDING").count(), 1);
}
fn execute(qty: &str, restore: bool) -> Value {
    let mut run = start("100000.00000000", qty);
    accepted(&mut run);
    let (m, f) = fills(&mut run, qty);
    if restore {
        assert!(
            run.state()["execution"]["perpetual"]["funding"]
                .as_object()
                .unwrap()
                .is_empty()
        );
        run = run.recompute();
    }
    let payload = funding_payload(&m, &f);
    let original = run.apply(BOUNDARY + 1, "FUNDING", payload.clone());
    let once = run.state();
    run.accept(&original).unwrap();
    assert_eq!(once, run.state());
    run.apply(BOUNDARY + 1, "FUNDING", payload);
    let duplicate = run.state();
    assert_eq!(duplicate["account"], once["account"]);
    assert_eq!(duplicate["ledger"], once["ledger"]);
    assert_eq!(
        duplicate["execution"]["perpetual"]["last_disposition"],
        "DUPLICATE"
    );
    run.mark(BOUNDARY + MINUTE, &mark(1));
    for (sequence, minute) in [(4_u64, 0), (5, 1)] {
        run.bar(sequence, &bar(minute));
        run.publish();
        assert!(run.venue.pending().is_empty());
    }
    verify_amounts(&run, qty);
    let all = records(&run);
    let trade_count = all.iter().filter(|v| v["input"]["op"] == "FILL").count();
    assert_eq!(trade_count, if qty == "0.002" { 2 } else { 1 });
    json!({
        "state":run.state(),
        "transactions":all,
        "order":run.order_value(),
        "view":run.session.position_order_view().unwrap()
    })
}

#[test]
fn original_two_partial_fills_funding_and_the_economic_work_recomputes() {
    for quantity in ["0.002", "0.001"] {
        assert_eq!(execute(quantity, false), execute(quantity, true));
    }
}

#[test]
fn venue_notional_capacity_rejection_releases_the_original_kernel_risk_and_margin() {
    let mut run = start("20.00000000", "0.002");
    let initial = run.state();
    amount(&initial["account"]["snapshot"]["cash"], "20");
    amount(&initial["account"]["snapshot"]["reserved_margin"], "12");
    let returned = run.consume(BOUNDARY - 2 * MINUTE);
    assert_eq!(returned.len(), 1);
    assert_eq!(returned[0].record()["kind"], "REJECTED");
    assert!(
        returned[0].record()["payload"]["reason"]
            .as_str()
            .unwrap()
            .contains("INSUFFICIENT_VENUE_CAPACITY")
    );
    let after = run.state();
    let a = &after["account"]["snapshot"];
    for k in ["reserved_margin", "occupied_margin", "reserved", "fees"] {
        amount(&a[k], "0");
    }
    amount(&a["cash"], "20");
    assert_eq!(run.order_value()["status"], "REJECTED");
    assert!(after["position"]["accounts"].as_array().unwrap().is_empty());
    assert_eq!(after["risk"]["active_count"], 0);
    let restored = run.recompute();
    assert_eq!(restored.state(), after);
    assert!(restored.venue.pending().is_empty());
}

#[test]
fn conflicting_unavailable_and_foreign_funding_leave_the_recomputed_prefix_intact() {
    let mut run = start("100000.00000000", "0.002");
    accepted(&mut run);
    let (m, f) = fills(&mut run, "0.002");
    run = run.recompute();
    let prior = run.state();
    let prior_records = records(&run);
    for key in [
        "mark_fact_id",
        "account",
        "data_version",
        "provider_evidence_id",
        "source_record_hash",
        "source_sequence",
        "instrument_id",
        "funding_time",
    ] {
        let mut input = run.input(BOUNDARY + 1, "FUNDING", funding_payload(&m, &f));
        let fact = &mut input["payload"]["fact"];
        match key {
            "account" => input["account"] = json!("other-account"),
            "mark_fact_id" => input["payload"][key] = json!("missing-mark"),
            "source_record_hash" => fact[key] = json!("0".repeat(64)),
            "source_sequence" => fact[key] = json!(100),
            "instrument_id" => fact[key]["symbol"]["value"] = json!("ETHUSDT-PERP"),
            "funding_time" => fact[key] = json!("2026-09-01T07:59:00Z"),
            _ => fact[key] = json!("foreign"),
        }
        assert!(run.accept(&input).is_err(), "{key}");
        assert_eq!(
            run.session.state().unwrap_err().0,
            "MEMORY_SESSION_FAILED"
        );
        run = run.recompute();
        assert_eq!(run.state(), prior);
        assert_eq!(records(&run), prior_records);
    }
    let original = run.apply(BOUNDARY + 1, "FUNDING", funding_payload(&m, &f));
    run = run.recompute();
    let after = run.state();
    let after_records = records(&run);
    let mut other = original.clone();
    other["payload"]["fact"]["rate"] = json!("0.0002");
    assert!(run.accept(&other).is_err());
    assert_eq!(
        run.session.state().unwrap_err().0,
        "MEMORY_SESSION_FAILED"
    );
    run = run.recompute();
    assert_eq!(records(&run), after_records);
    let mut other = f.clone();
    other["rate"] = json!("0.0002");
    let other = run.input(BOUNDARY + 1, "FUNDING", funding_payload(&m, &other));
    assert!(run.accept(&other).is_err());
    assert_eq!(
        run.session.state().unwrap_err().0,
        "MEMORY_SESSION_FAILED"
    );
    run = run.recompute();
    assert_eq!(records(&run), after_records);
    assert_eq!(run.state(), after);
}

#[test]
fn exhausted_maintenance_history_preserves_marks_funding_and_the_admitted_fill() {
    let mut cfg = config("100000.00000000", usdm_terms());
    for value in [json!(0), json!(513), json!("1")] {
        let mut wrong = cfg.clone();
        wrong["margin_observation_capacity"] = value;
        assert!(RunConfiguration::from_record(wrong).is_err());
    }
    let mut cash = cfg.clone();
    cash.as_object_mut().unwrap().remove("perpetual");
    cash["schema_version"] = json!(2);
    cash["margin_observation_capacity"] = json!(1);
    assert!(RunConfiguration::from_record(cash).is_err());
    cfg["margin_observation_capacity"] = json!(1);
    let mut run = Run::create(cfg);
    broker_submit(&mut run, "0.003");
    accepted(&mut run);
    run.mark(BOUNDARY - MINUTE, &mark(-1));
    run.bar(2, &bar(-2));
    assert_eq!(run.consume(BOUNDARY - MINUTE).len(), 1);

    // 已有 0.001 仓，60100 时的可证维护额为 0.2404，使用最后一份观测容量。
    let repriced_at = BOUNDARY - MINUTE + 1000;
    let instrument = INSTRUMENT.parse().unwrap();
    let repriced = usdm_facts::reference_price(
        &json!({"T":repriced_at,"p":"60100.00"}),
        OnlyReferencePriceKind::Mark,
        &usdm_facts::Context {
            instrument_id: &instrument,
            data_version: VERSION,
            source_sequence: 5,
            received_at: "2026-09-01T07:59:01Z".parse().unwrap(),
        },
    )
    .unwrap()
    .to_record();
    run.mark(repriced_at, &repriced);
    let priced = run.state();
    assert_eq!(priced["execution"]["margin_authority"]["schema_version"], 2);
    assert_eq!(
        priced["execution"]["margin_authority"]["config"]["observation_capacity"],
        1
    );
    amount(
        &priced["account"]["snapshot"]["maintenance_required"],
        ".2404",
    );

    let (m, f) = boundary();
    run.mark(BOUNDARY, &m);
    let unavailable = run.state();
    assert_eq!(
        unavailable["execution"]["perpetual"]["marks"][m["fact_id"].as_str().unwrap()],
        m
    );
    let a = &unavailable["account"]["snapshot"];
    assert_eq!(a["maintenance_status"], "UNAVAILABLE");
    assert!(a["maintenance_required"].is_null() && a["maintenance_to_equity"].is_null());
    amount(&a["last_confirmed_maintenance"]["amount"], ".2404");
    assert_eq!(
        a["last_confirmed_maintenance"]["time"],
        repriced_at * 1_000_000
    );
    amount(&a["unrealized_pnl"], "0");

    run.bar(3, &bar(-1));
    assert_eq!(run.consume(BOUNDARY).len(), 1);
    let no_cut = run.input(BOUNDARY, "FUNDING", funding_payload(&m, &f));
    assert_eq!(
        run.accept(&no_cut).unwrap_err().0,
        "BROKER_ECONOMIC_PREFIX_UNPROVEN"
    );
    run = run.recompute();
    run.advance(BOUNDARY * 1_000_000 + 1);
    run.apply(BOUNDARY + 1, "FUNDING", funding_payload(&m, &f));
    let funded = run.state();
    amount(
        &funded["ledger"]["ledgers"]["cluster"]["snapshot"]["funding"],
        "-.012",
    );
    amount(&funded["account"]["snapshot"]["equity"], "99999.928");
    let mut req = request(INSTRUMENT, "0.001");
    req["request_id"]["value"] = json!("blocked-new-risk");
    let attempt=run.input(BOUNDARY+1,"ADMIT",json!({"schema_version":3,"order":"runtime-ORDER-000002","request":req,"policy_fingerprint":run.cfg["perpetual"]["policy_fingerprint"]}));
    assert_eq!(
        run.accept(&attempt).unwrap_err().0,
        "MARGIN_OBSERVATION_HISTORY_LIMIT"
    );
    run = run.recompute();
    assert_eq!(run.state(), funded);
    run.bar(4, &bar(0));
    assert_eq!(run.consume(BOUNDARY + MINUTE).len(), 1);
    let final_state = run.state();
    assert_eq!(run.order_value()["status"], "FILLED");
    assert_eq!(
        final_state["account"]["snapshot"]["maintenance_status"],
        "UNAVAILABLE"
    );
    amount(&final_state["account"]["snapshot"]["occupied_margin"], "18");
    amount(&final_state["account"]["snapshot"]["fees"], ".09");
    amount(&final_state["account"]["snapshot"]["equity"], "99999.898");
    let all = records(&run);
    let restored = run.recompute();
    assert_eq!(restored.state(), final_state);
    assert_eq!(records(&restored), all);
}

#[test]
fn actual_admission_checks_the_bound_market_policy_for_every_order_and_time() {
    let mut run = Run::create(config("100000.00000000", usdm_terms()));
    run.mark(BOUNDARY - MINUTE, &mark(-1));
    let original = records(&run);
    let before = run.state();
    for (at, price, q) in [
        (BOUNDARY, "60000.01", "0.002"),
        (BOUNDARY, "100.00", "0.001"),
        (BOUNDARY + 86_400_000, "60000.00", "0.002"),
    ] {
        let mut req = request(INSTRUMENT, q);
        req["price"]["value"] = json!(price);
        let mut input=run.input(at,"ADMIT",json!({"schema_version":3,"order":ORDER,"request":req,"policy_fingerprint":run.cfg["perpetual"]["policy_fingerprint"]}));
        if at > BOUNDARY {
            input["trading_day"] = json!("2026-09-02");
            input["day_index"] = json!(2);
        }
        assert!(
            run.accept(&input).is_err(),
            "rule accepted {price}/{q} at {at}"
        );
        run = run.recompute();
        assert_eq!(run.state(), before);
        assert_eq!(records(&run), original);
    }
}

#[test]
fn late_funding_applies_once_to_the_boundary_position_after_another_fill_and_mark() {
    let mut cfg = config("100000.00000000", usdm_terms());
    bind_sources(&mut cfg, true);
    let mut run = Run::create(cfg);
    broker_submit(&mut run, "0.003");
    accepted(&mut run);
    run.mark(BOUNDARY - MINUTE, &mark(-1));
    run.bar(2, &bar(-2));
    assert_eq!(run.consume(BOUNDARY - MINUTE).len(), 1);
    run.bar(3, &bar(-1));
    assert_eq!(run.consume(BOUNDARY).len(), 1);
    let inst = INSTRUMENT.parse().unwrap();
    let raw = json!({"symbol":"BTCUSDT","fundingTime":BOUNDARY,"markPrice":"60000.00","fundingRate":"0.0001"});
    let (m, f) = usdm_facts::funding_boundary(
        &raw,
        &usdm_facts::Context {
            instrument_id: &inst,
            data_version: VERSION,
            source_sequence: 5,
            received_at: "2026-09-01T08:00:01Z".parse().unwrap(),
        },
    )
    .unwrap();
    let m = m.to_record();
    let f = f.to_record();
    run.mark(BOUNDARY + 1000, &m);
    run.mark(BOUNDARY + MINUTE, &mark(1));
    run.bar(4, &bar(0));
    let after = run.consume(BOUNDARY + MINUTE);
    assert_eq!(after.len(), 1);
    assert!(after[0].record()["ts_event"].as_i64().unwrap() > BOUNDARY * 1_000_000);
    run = run.recompute();
    let original = run.apply(BOUNDARY + MINUTE, "FUNDING", funding_payload(&m, &f));
    let state = run.state();
    amount(
        &state["ledger"]["ledgers"]["cluster"]["snapshot"]["funding"],
        "-.012",
    );
    amount(&state["account"]["snapshot"]["equity"], "99999.898");
    let rows = records(&run);
    run = run.recompute();
    run.accept(&original).unwrap();
    assert_eq!(run.state(), state);
    assert_eq!(records(&run), rows);
}

#[test]
fn original_broker_facts_must_match_the_recorded_observation() {
    let mut run = start("100000.00000000", "0.001");
    run.publish();
    let pending = run.venue.pending().to_vec();
    assert_eq!(pending.len(), 1);
    let observed = &pending[0];
    let ready = records(&run);
    let before = run.state();
    // 观察身份与指纹都不含顶层 session，改动它仍必须被原文比对拒绝。
    let mut reported = observed.record();
    reported["session"] = json!("a-new-session");
    let fact = Fact::decode(&reported).unwrap();
    assert_eq!(fact.identity(), observed.identity());
    assert_eq!(fact.fingerprint(), observed.fingerprint());
    let input = run.input(
        BOUNDARY - 2 * MINUTE,
        "ACCEPT",
        json!({"schema_version":2,"order":ORDER,
            "broker":{"id":fact.identity(),"fingerprint":fact.fingerprint(),"record":reported}}),
    );
    assert_eq!(
        run.accept(&input).unwrap_err().0,
        "EXECUTION_BROKER_ORIGINAL_CONFLICT"
    );
    assert_eq!(
        run.session.state().unwrap_err().0,
        "MEMORY_SESSION_FAILED"
    );
    let mut restored = run.recompute();
    assert_eq!(records(&restored), ready);
    assert_eq!(restored.state(), before);
    // 场所原文完好时，同一见证可以入账。
    let facts = restored.consume(BOUNDARY - 2 * MINUTE);
    assert_eq!(facts.len(), 1);
    assert_eq!(facts[0].record()["kind"], "ACCEPTED");
    assert_eq!(restored.order_value()["status"], "ACCEPTED");
}

#[test]
fn market_compiler_preimage_binds_the_complete_static_rules() {
    let cfg = config("100000.00000000", usdm_terms());
    Run::create(cfg.clone()).state();
    for (key, value) in [
        ("price_tick", json!("0.01")),
        ("minimum_notional", json!("0.01")),
        ("binding", json!("f".repeat(64))),
        ("effective_to", json!("2026-09-04T00:00:00Z")),
    ] {
        let mut changed = cfg.clone();
        changed["perpetual"]["limit_rules"][key] = value;
        // 攻击者可以重算整份 raw 规则的摘要，仍不能改变原市场编译正文。
        let rules = onlyalpha_domain::market_rules::OnlyStaticLimitRules::from_record(
            &changed["perpetual"]["limit_rules"],
        )
        .unwrap();
        changed["perpetual"]["limit_rules_fingerprint"] = json!(rules.content_fingerprint());
        let error = RunConfiguration::from_record(changed)
            .err()
            .unwrap_or_else(|| panic!("same original policy accepted changed {key}"));
        assert_eq!(error.0, "EXECUTION_LIMIT_RULE_IDENTITY");
    }
    let mut changed = cfg.clone();
    let mut body: Value = serde_json::from_str(
        changed["perpetual"]["compiled_policy_json"]
            .as_str()
            .unwrap(),
    )
    .unwrap();
    body["price_tick"] = json!("0.01");
    changed["perpetual"]["compiled_policy_json"] = json!(body.to_string());
    assert!(RunConfiguration::from_record(changed).is_err());
}

#[test]
fn compiled_account_modes_cannot_be_relabelled_as_the_runtime_open_profile() {
    let matched = Run::create(config("100000.00000000", usdm_terms()));
    matched.state();
    let mut terms = usdm_terms_for_account(true);
    let body: Value =
        serde_json::from_str(terms["compiled_policy_json"].as_str().unwrap()).unwrap();
    assert_eq!(body["position_mode"], "HEDGING");
    assert_eq!(body["margin_mode"], "ISOLATED");
    terms["position_mode"] = json!("NETTING");
    terms["margin_mode"] = json!("CROSS");
    assert!(
        RunConfiguration::from_record(config("100000.00000000", terms)).is_err(),
        "real HEDGING/ISOLATED compiled policy was accepted as NETTING/CROSS"
    );
}

#[test]
fn compiled_margin_curve_cannot_be_replaced_by_a_cheaper_runtime_curve() {
    let mut cfg = config("100000.00000000", usdm_terms());
    Run::create(cfg.clone()).state();
    let original_body = cfg["perpetual"]["compiled_policy_json"].clone();
    for segment in cfg["perpetual"]["margin_segments"].as_array_mut().unwrap() {
        // 原资源按同一十倍杠杆编译，两档初始直线都过原点。
        assert_eq!(segment["initial_slope"], "0.1");
        assert_eq!(segment["initial_intercept"], "0");
        segment["initial_slope"] = json!("0.05");
    }
    assert_eq!(cfg["perpetual"]["compiled_policy_json"], original_body);
    assert!(
        RunConfiguration::from_record(cfg).is_err(),
        "lower runtime margin curve replaced the original compiler economics"
    );
}

#[test]
fn funding_waits_until_the_virtual_boundary_is_closed_before_counting_same_time_fills() {
    let mut run = start("100000.00000000", "0.002");
    accepted(&mut run);
    run.mark(BOUNDARY - MINUTE, &mark(-1));
    run.bar(2, &bar(-2));
    assert_eq!(run.consume(BOUNDARY - MINUTE).len(), 1);
    let ns = BOUNDARY * 1_000_000;
    run.advance(ns);
    let (m, f) = boundary();
    run.mark(BOUNDARY, &m);
    let before = run.state();
    let pending = run.input(BOUNDARY, "FUNDING", funding_payload(&m, &f));
    assert!(
        run.accept(&pending).is_err(),
        "unclosed inclusive boundary funded only the first fill"
    );
    run = run.recompute();
    assert_eq!(run.state(), before);
    run.bar(3, &bar(-1));
    let same_time = run.consume(BOUNDARY);
    assert_eq!(same_time.len(), 1);
    assert_eq!(same_time[0].record()["ts_event"], ns);
    run.advance(ns + 1);
    let original = run.apply(BOUNDARY + 1, "FUNDING", funding_payload(&m, &f));
    let funded = run.state();
    amount(
        &funded["ledger"]["ledgers"]["cluster"]["snapshot"]["funding"],
        "-.012",
    );
    amount(&funded["account"]["snapshot"]["equity"], "99999.928");
    let history = records(&run);
    run = run.recompute();
    run.accept(&original).unwrap();
    assert_eq!(run.state(), funded);
    assert_eq!(records(&run), history);
}

#[test]
fn funding_recomputes_after_a_later_fill_and_keeps_the_original_duplicate() {
    let mut run = start("100000.00000000", "0.003");
    accepted(&mut run);
    run.mark(BOUNDARY - MINUTE, &mark(-1));
    for (sequence, minute, visible) in [(2_u64, -2, BOUNDARY - MINUTE), (3, -1, BOUNDARY)] {
        run.bar(sequence, &bar(minute));
        assert_eq!(run.consume(visible).len(), 1);
    }
    let (m, f) = boundary();
    run.mark(BOUNDARY, &m);
    run.advance(BOUNDARY * 1_000_000 + 1);
    let original = run.apply(BOUNDARY + 1, "FUNDING", funding_payload(&m, &f));
    amount(
        &run.state()["ledger"]["ledgers"]["cluster"]["snapshot"]["funding"],
        "-.012",
    );
    run.bar(4, &bar(0));
    assert_eq!(run.consume(BOUNDARY + MINUTE).len(), 1);
    assert_eq!(run.order_value()["status"], "FILLED");
    let final_state = run.state();
    amount(&final_state["account"]["snapshot"]["cash"], "99999.898");
    let history = records(&run);
    run = run.recompute();
    run.accept(&original).unwrap();
    assert_eq!(run.state(), final_state);
    assert_eq!(records(&run), history);
}

#[test]
fn funding_settles_the_boundary_and_refuses_new_admission_at_it() {
    let mut run = start("100000.00000000", "0.001");
    accepted(&mut run);
    run.mark(BOUNDARY - MINUTE, &mark(-1));
    run.bar(2, &bar(-2));
    assert_eq!(run.consume(BOUNDARY - MINUTE).len(), 1);
    assert_eq!(run.order_value()["status"], "FILLED");
    let bc = BOUNDARY * 1_000_000;
    run.advance(bc);
    let (m, f) = boundary();
    run.mark(BOUNDARY, &m);
    let original = run.input(BOUNDARY, "FUNDING", funding_payload(&m, &f));
    let before = run.state();
    assert_eq!(
        run.accept(&original).unwrap_err().0,
        "BROKER_ECONOMIC_PREFIX_UNPROVEN"
    );
    run = run.recompute();
    assert_eq!(run.state(), before);
    run.advance(bc + 1);
    assert_eq!(
        run.accept(&original).unwrap_err().0,
        "BROKER_ECONOMIC_PREFIX_UNPROVEN"
    );
    run = run.recompute();
    let original = run.apply(BOUNDARY + 1, "FUNDING", funding_payload(&m, &f));
    let funded = run.state();
    amount(
        &funded["ledger"]["ledgers"]["cluster"]["snapshot"]["funding"],
        "-.006",
    );
    // 已结算边界之后的同一来源序列不得回退场所时钟。
    assert_eq!(
        run.venue.on_bar(3, &bar(-1)).unwrap_err().to_string(),
        "VIRTUAL_CLOCK_REGRESSION"
    );
    let mut req = request(INSTRUMENT, "0.001");
    req["request_id"]["value"] = json!("second-open");
    let admission = json!({"schema_version":3,"order":"runtime-ORDER-000002","request":req,"policy_fingerprint":run.cfg["perpetual"]["policy_fingerprint"]});
    let history = records(&run);
    for at in [BOUNDARY, BOUNDARY - 1] {
        let input = run.input(at, "ADMIT", admission.clone());
        assert_eq!(
            run.accept(&input).unwrap_err().0,
            "EXECUTION_ADMISSION_AT_SETTLED_BOUNDARY"
        );
        run = run.recompute();
        assert_eq!(run.state(), funded);
        assert_eq!(records(&run), history);
    }
    let next = run.input(BOUNDARY + 1, "ADMIT", admission);
    run.record(next);
    assert_eq!(
        run.session
            .order("cluster", "runtime-ORDER-000002")
            .unwrap()["status"],
        "SUBMITTED"
    );
    let settled = run.state();
    let all = records(&run);
    let mut restored = run.recompute();
    assert_eq!(restored.state(), settled);
    assert_eq!(records(&restored), all);
    // 同一原始输入重放是幂等的：不新增事实，也不改变已结算状态。
    restored.accept(&original).unwrap();
    assert_eq!(restored.state(), settled);
    assert_eq!(records(&restored), all);
}
