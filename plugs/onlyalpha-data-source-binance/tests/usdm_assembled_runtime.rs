//! 原始 USD-M 行情、规则、Virtual 场所、Broker Journal 与持久交易内核的库级组合。
#[path = "support/perpetual_venue.rs"]
mod venue;
use onlyalpha_broker::{Fact, Scope};
use onlyalpha_data_source_binance::{
    reference_capture::ReferenceCapture, spot_normalize, usdm_facts,
};
use onlyalpha_domain::{
    base::OnlyDomainModel, identifiers::OnlyInstrumentId, instrument::OnlyInstrument,
    market::OnlyBar, time::OnlyUtcDateTime, trading::OnlyReferencePriceKind,
};
use onlyalpha_market_crypto::market_policy::{MarketBinding, Product};
use onlyalpha_runtime::Runtime;
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    fs,
    path::{Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
};
use venue::{ORDER, Venue, order_row};

const INSTRUMENT: &str = "BTCUSDT-PERP.BINANCE";
const BOUNDARY: i64 = 1_788_249_600_000;
const MINUTE: i64 = 60_000;
const VERSION: &str = "recorded-perpetual-bars-v1";
const ACCT: &str = "backtest-account";
static DIRECTORY: AtomicU64 = AtomicU64::new(0);
const SOURCE_BYTES: [&[u8]; 4] = [
    include_bytes!("fixtures/usdm-exchange.json"),
    include_bytes!("fixtures/usdm-funding.json"),
    include_bytes!("fixtures/usdm-brackets.json"),
    include_bytes!("fixtures/usdm-account.json"),
];

struct Root(PathBuf);
impl Root {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "oa-perpetual-assembled-{}-{}",
            std::process::id(),
            DIRECTORY.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
}
impl Drop for Root {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}
fn initial_currency() -> Value {
    json!({"schema_version":1,"code":"USDT","precision":8,"currency_type":"CRYPTO"})
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
    cfg["perpetual"]["execution_source_binding"] = json!(Venue::binding(
        Scope::decode(&scope(&cfg)).unwrap(),
        &cfg["currency"],
        cash
    ));
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
struct Run {
    cfg: Value,
    artifact: String,
    runtime: Runtime,
    seq: u64,
}
impl Run {
    fn create(dir: &Path, cfg: Value) -> Self {
        let artifact = "e".repeat(64);
        fs::write(
            dir.join("market-source-cut.json"),
            serde_json::to_vec(&cfg["perpetual"]["source_rows"]).unwrap(),
        )
        .unwrap();
        if !dir.join("broker.sqlite3").exists() {
            Venue::create(
                dir,
                Scope::decode(&scope(&cfg)).unwrap(),
                &cfg["currency"],
                cfg["initial_cash"].as_str().unwrap(),
            );
        }
        let runtime = Runtime::create(dir, cfg.clone(), &artifact).unwrap();
        Self {
            cfg,
            artifact,
            runtime,
            seq: 0,
        }
    }
    fn input(&self, ms: i64, op: &str, payload: Value) -> Value {
        msg(&self.cfg, self.seq + 1, ms, op, payload)
    }
    fn apply(&mut self, ms: i64, op: &str, payload: Value) -> Value {
        let input = self.input(ms, op, payload);
        self.runtime.apply(&input).unwrap();
        self.seq += 1;
        input
    }
    fn admit(&mut self, ms: i64, req: &Value) {
        self.apply(ms,"ADMIT",json!({"schema_version":3,"order":ORDER,"request":req,"policy_fingerprint":self.cfg["perpetual"]["policy_fingerprint"]}));
    }
    fn mark(&mut self, ms: i64, v: &Value) {
        self.apply(ms, "MARK", json!({"schema_version":1,"fact":v}));
    }
    fn reopen(self, dir: &Path) -> Self {
        let Self {
            runtime,
            cfg,
            artifact,
            seq,
        } = self;
        drop(runtime);
        let runtime = Runtime::open(dir, cfg.clone(), &artifact).unwrap();
        Self {
            runtime,
            cfg,
            artifact,
            seq,
        }
    }
    fn consume(&mut self, venue: &mut Venue, ms: i64) -> Vec<Fact> {
        let facts = venue.pending();
        for fact in &facts {
            let f = fact.record();
            let op = match f["kind"].as_str().unwrap() {
                "ACCEPTED" => "ACCEPT",
                "TRADE" => "FILL",
                "REJECTED" => "TERMINAL",
                other => panic!("unexpected {other}"),
            };
            let proof = json!({"id":fact.identity(),"fingerprint":fact.fingerprint(),"record":f});
            self.apply(
                ms,
                op,
                json!({"schema_version":2,"order":ORDER,"broker":proof}),
            );
            venue.acknowledge(&self.runtime, fact);
        }
        facts
    }
}
fn amount(actual: &Value, expected: &str) {
    use bigdecimal::BigDecimal;
    assert_eq!(
        actual.as_str().unwrap().parse::<BigDecimal>().unwrap(),
        expected.parse::<BigDecimal>().unwrap()
    );
}
fn broker_submit(run: &mut Run, venue: &mut Venue, qty: &str) {
    let ms = BOUNDARY - 2 * MINUTE;
    venue.simulation.on_bar(1, &bar(-3)).unwrap();
    run.mark(ms, &mark(-2));
    let r = request(INSTRUMENT, qty);
    run.admit(ms, &r);
    venue.dispatch(&run.runtime, &r);
    run.apply(
        ms,
        "SUBMISSION",
        json!({"schema_version":1,"order":ORDER,"outcome":"DISPATCHED"}),
    );
}
fn start(dir: &Path, cash: &str, qty: &str) -> (Run, Venue) {
    let cfg = config(cash, usdm_terms());
    let mut venue = Venue::create(
        dir,
        Scope::decode(&scope(&cfg)).unwrap(),
        &cfg["currency"],
        cash,
    );
    let mut run = Run::create(dir, cfg);
    broker_submit(&mut run, &mut venue, qty);
    (run, venue)
}
fn records(run: &Run) -> Vec<Value> {
    run.runtime
        .records()
        .unwrap()
        .iter()
        .map(|r| r.record())
        .collect()
}
fn accepted(run: &mut Run, venue: &mut Venue) {
    let facts = run.consume(venue, BOUNDARY - 2 * MINUTE);
    assert_eq!(facts.len(), 1);
    assert_eq!(facts[0].record()["kind"], "ACCEPTED");
}
fn fills(run: &mut Run, venue: &mut Venue, qty: &str) -> (Value, Value) {
    let (boundary_mark, funding) = boundary();
    for (sequence, minute, m) in [(2, -1, mark(-1)), (3, 0, boundary_mark.clone())] {
        let ms = BOUNDARY + minute * MINUTE;
        run.mark(ms, &m);
        venue.simulation.on_bar(sequence, &bar(minute - 1)).unwrap();
        let received = run.consume(venue, ms);
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
    venue.simulation.advance(BOUNDARY * 1_000_000 + 1).unwrap();
    (boundary_mark, funding)
}
fn funding_payload(m: &Value, f: &Value) -> Value {
    json!({"schema_version":1,"mark_fact_id":m["fact_id"],"fact":f})
}
fn verify_amounts(run: &Run, qty: &str) {
    let s = run.runtime.state().unwrap();
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
    let order = order_row(&run.runtime);
    assert_eq!(order["snapshot"]["status"], "FILLED");
    amount(&order["snapshot"]["filled_quantity"]["value"], qty);
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
fn execute(dir: &Path, qty: &str, restore: bool) -> Value {
    let (mut run, mut venue) = start(dir, "100000.00000000", qty);
    accepted(&mut run, &mut venue);
    let (m, f) = fills(&mut run, &mut venue, qty);
    if restore {
        let cut = run.runtime.save_checkpoint().unwrap();
        assert!(cut.is_object());
        assert!(
            run.runtime.state().unwrap()["execution"]["perpetual"]["funding"]
                .as_object()
                .unwrap()
                .is_empty()
        );
        run = run.reopen(dir);
        venue = venue.restore(dir);
    }
    let payload = funding_payload(&m, &f);
    let original = run.apply(BOUNDARY + 1, "FUNDING", payload.clone());
    let once = run.runtime.state().unwrap();
    run.runtime.apply(&original).unwrap();
    assert_eq!(once, run.runtime.state().unwrap());
    run.apply(BOUNDARY + 1, "FUNDING", payload);
    let duplicate = run.runtime.state().unwrap();
    assert_eq!(duplicate["account"], once["account"]);
    assert_eq!(duplicate["ledger"], once["ledger"]);
    assert_eq!(
        duplicate["execution"]["perpetual"]["last_disposition"],
        "DUPLICATE"
    );
    run.mark(BOUNDARY + MINUTE, &mark(1));
    for (sequence, minute) in [(4, 0), (5, 1)] {
        venue.simulation.on_bar(sequence, &bar(minute)).unwrap();
        assert!(venue.pending().is_empty());
    }
    verify_amounts(&run, qty);
    let all = records(&run);
    let trade_count = all
        .iter()
        .filter(|v| v["prepared"]["input"]["op"] == "FILL")
        .count();
    assert_eq!(trade_count, if qty == "0.002" { 2 } else { 1 });
    json!({"state":run.runtime.state().unwrap(),"owners":run.runtime.fork_ready().unwrap().0.checkpoint().unwrap(),
        "transactions":all,"journal":venue.journal_rows(),"venue":venue.simulation.checkpoint()})
}
#[test]
fn original_two_partial_fills_funding_and_all_owners_recover_from_the_pre_funding_checkpoint() {
    for quantity in ["0.002", "0.001"] {
        let a = Root::new();
        let b = Root::new();
        assert_eq!(
            execute(&a.0, quantity, false),
            execute(&b.0, quantity, true)
        );
    }
}
#[test]
fn venue_notional_capacity_rejection_releases_the_original_kernel_risk_and_margin() {
    let root = Root::new();
    let (mut run, mut venue) = start(&root.0, "20.00000000", "0.002");
    let initial = run.runtime.state().unwrap();
    amount(&initial["account"]["snapshot"]["cash"], "20");
    amount(&initial["account"]["snapshot"]["reserved_margin"], "12");
    let returned = run.consume(&mut venue, BOUNDARY - 2 * MINUTE);
    assert_eq!(returned.len(), 1);
    assert_eq!(returned[0].record()["kind"], "REJECTED");
    assert!(
        returned[0].record()["payload"]["reason"]
            .as_str()
            .unwrap()
            .contains("INSUFFICIENT_VENUE_CAPACITY")
    );
    let after = run.runtime.state().unwrap();
    let a = &after["account"]["snapshot"];
    for k in ["reserved_margin", "occupied_margin", "reserved", "fees"] {
        amount(&a[k], "0");
    }
    amount(&a["cash"], "20");
    assert_eq!(order_row(&run.runtime)["snapshot"]["status"], "REJECTED");
    assert!(after["position"]["accounts"].as_array().unwrap().is_empty());
    assert_eq!(after["risk"]["active_count"], 0);
    let reopened = run.reopen(&root.0);
    assert_eq!(reopened.runtime.state().unwrap(), after);
    let mut venue = venue.restore(&root.0);
    assert!(venue.pending().is_empty());
}
#[test]
fn conflicting_unavailable_and_foreign_funding_leave_the_reopened_ready_prefix_intact() {
    let dir = Root::new();
    let (mut run, mut venue) = start(&dir.0, "100000.00000000", "0.002");
    accepted(&mut run, &mut venue);
    let (m, f) = fills(&mut run, &mut venue, "0.002");
    run.runtime.save_checkpoint().unwrap();
    run = run.reopen(&dir.0);
    let prior = run.runtime.state().unwrap();
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
        assert!(run.runtime.apply(&input).is_err(), "{key}");
        assert_eq!(
            run.runtime.state().unwrap_err().0,
            "RUNTIME_RECOVERY_REQUIRED"
        );
        run = run.reopen(&dir.0);
        assert_eq!(run.runtime.state().unwrap(), prior);
        assert_eq!(records(&run), prior_records);
    }
    let original = run.apply(BOUNDARY + 1, "FUNDING", funding_payload(&m, &f));
    run = run.reopen(&dir.0);
    let after = run.runtime.state().unwrap();
    let after_records = records(&run);
    let mut other = original.clone();
    other["payload"]["fact"]["rate"] = json!("0.0002");
    assert!(run.runtime.apply(&other).is_err());
    assert_eq!(
        run.runtime.state().unwrap_err().0,
        "RUNTIME_RECOVERY_REQUIRED"
    );
    run = run.reopen(&dir.0);
    assert_eq!(records(&run), after_records);
    let mut other = f.clone();
    other["rate"] = json!("0.0002");
    let other = run.input(BOUNDARY + 1, "FUNDING", funding_payload(&m, &other));
    assert!(run.runtime.apply(&other).is_err());
    assert_eq!(
        run.runtime.state().unwrap_err().0,
        "RUNTIME_RECOVERY_REQUIRED"
    );
    run = run.reopen(&dir.0);
    assert_eq!(records(&run), after_records);
    assert_eq!(run.runtime.state().unwrap(), after);
    let cfg = run.cfg.clone();
    let artifact = run.artifact.clone();
    drop(run);
    assert!(Runtime::open(&dir.0, cfg.clone(), &"0".repeat(64)).is_err());
    let mut wrong = cfg.clone();
    wrong["perpetual"]["data_version"] = json!("wrong-version");
    assert!(Runtime::open(&dir.0, wrong, &artifact).is_err());
    assert_eq!(
        Runtime::open(&dir.0, cfg, &artifact)
            .unwrap()
            .state()
            .unwrap(),
        after
    );
}

#[test]
fn exhausted_maintenance_history_preserves_marks_funding_and_the_admitted_fill() {
    let dir = Root::new();
    let mut cfg = config("100000.00000000", usdm_terms());
    for value in [json!(0), json!(513), json!("1")] {
        let mut wrong = cfg.clone();
        wrong["margin_observation_capacity"] = value;
        assert!(Runtime::create(&Root::new().0, wrong, &"e".repeat(64)).is_err());
    }
    let mut cash = cfg.clone();
    cash.as_object_mut().unwrap().remove("perpetual");
    cash["schema_version"] = json!(2);
    cash["margin_observation_capacity"] = json!(1);
    assert!(Runtime::create(&Root::new().0, cash, &"e".repeat(64)).is_err());
    cfg["margin_observation_capacity"] = json!(1);
    let mut venue = Venue::create(
        &dir.0,
        Scope::decode(&scope(&cfg)).unwrap(),
        &cfg["currency"],
        "100000.00000000",
    );
    let mut run = Run::create(&dir.0, cfg);
    broker_submit(&mut run, &mut venue, "0.003");
    accepted(&mut run, &mut venue);
    run.mark(BOUNDARY - MINUTE, &mark(-1));
    venue.simulation.on_bar(2, &bar(-2)).unwrap();
    assert_eq!(run.consume(&mut venue, BOUNDARY - MINUTE).len(), 1);

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
    let priced = run.runtime.state().unwrap();
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
    let unavailable = run.runtime.state().unwrap();
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

    venue.simulation.on_bar(3, &bar(-1)).unwrap();
    assert_eq!(run.consume(&mut venue, BOUNDARY).len(), 1);
    let no_cut = run.input(BOUNDARY, "FUNDING", funding_payload(&m, &f));
    assert_eq!(
        run.runtime.apply(&no_cut).unwrap_err().0,
        "BROKER_ECONOMIC_PREFIX_UNPROVEN"
    );
    run = run.reopen(&dir.0);
    venue
        .simulation
        .advance((BOUNDARY * 1_000_000).checked_add(1).unwrap())
        .unwrap();
    venue.observe_economic_prefix();
    run.apply(BOUNDARY + 1, "FUNDING", funding_payload(&m, &f));
    let funded = run.runtime.state().unwrap();
    amount(
        &funded["ledger"]["ledgers"]["cluster"]["snapshot"]["funding"],
        "-.012",
    );
    amount(&funded["account"]["snapshot"]["equity"], "99999.928");
    let mut req = request(INSTRUMENT, "0.001");
    req["request_id"]["value"] = json!("blocked-new-risk");
    let attempt=run.input(BOUNDARY+1,"ADMIT",json!({"schema_version":3,"order":"runtime-ORDER-000002","request":req,"policy_fingerprint":run.cfg["perpetual"]["policy_fingerprint"]}));
    assert_eq!(
        run.runtime.apply(&attempt).unwrap_err().0,
        "MARGIN_OBSERVATION_HISTORY_LIMIT"
    );
    run = run.reopen(&dir.0);
    assert_eq!(run.runtime.state().unwrap(), funded);
    venue.simulation.on_bar(4, &bar(0)).unwrap();
    assert_eq!(run.consume(&mut venue, BOUNDARY + MINUTE).len(), 1);
    let final_state = run.runtime.state().unwrap();
    assert_eq!(order_row(&run.runtime)["snapshot"]["status"], "FILLED");
    assert_eq!(
        final_state["account"]["snapshot"]["maintenance_status"],
        "UNAVAILABLE"
    );
    amount(&final_state["account"]["snapshot"]["occupied_margin"], "18");
    amount(&final_state["account"]["snapshot"]["fees"], ".09");
    amount(&final_state["account"]["snapshot"]["equity"], "99999.898");
    run.runtime.save_checkpoint().unwrap();
    let all = records(&run);
    let restored = run.reopen(&dir.0);
    assert_eq!(restored.runtime.state().unwrap(), final_state);
    assert_eq!(records(&restored), all);
    let mut changed = restored.cfg.clone();
    let artifact = restored.artifact.clone();
    drop(restored);
    changed["margin_observation_capacity"] = json!(2);
    assert!(Runtime::open(&dir.0, changed, &artifact).is_err());
}

#[test]
fn actual_admission_checks_the_bound_market_policy_for_every_order_and_time() {
    let dir = Root::new();
    let mut run = Run::create(&dir.0, config("100000.00000000", usdm_terms()));
    run.mark(BOUNDARY - MINUTE, &mark(-1));
    let original = records(&run);
    let before = run.runtime.state().unwrap();
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
            run.runtime.apply(&input).is_err(),
            "rule accepted {price}/{q} at {at}"
        );
        run = run.reopen(&dir.0);
        assert_eq!(run.runtime.state().unwrap(), before);
        assert_eq!(records(&run), original);
    }
}

#[test]
fn late_funding_applies_once_to_the_boundary_position_after_another_fill_and_mark() {
    let dir = Root::new();
    let mut cfg = config("100000.00000000", usdm_terms());
    bind_sources(&mut cfg, true);
    let mut venue = Venue::create(
        &dir.0,
        Scope::decode(&scope(&cfg)).unwrap(),
        &cfg["currency"],
        "100000.00000000",
    );
    let mut run = Run::create(&dir.0, cfg);
    broker_submit(&mut run, &mut venue, "0.003");
    accepted(&mut run, &mut venue);
    run.mark(BOUNDARY - MINUTE, &mark(-1));
    venue.simulation.on_bar(2, &bar(-2)).unwrap();
    assert_eq!(run.consume(&mut venue, BOUNDARY - MINUTE).len(), 1);
    venue.simulation.on_bar(3, &bar(-1)).unwrap();
    assert_eq!(run.consume(&mut venue, BOUNDARY).len(), 1);
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
    venue.simulation.on_bar(4, &bar(0)).unwrap();
    let after = run.consume(&mut venue, BOUNDARY + MINUTE);
    assert_eq!(after.len(), 1);
    assert!(after[0].record()["ts_event"].as_i64().unwrap() > BOUNDARY * 1_000_000);
    run.runtime.save_checkpoint().unwrap();
    run = run.reopen(&dir.0);
    let original = run.apply(BOUNDARY + MINUTE, "FUNDING", funding_payload(&m, &f));
    let state = run.runtime.state().unwrap();
    amount(
        &state["ledger"]["ledgers"]["cluster"]["snapshot"]["funding"],
        "-.012",
    );
    amount(&state["account"]["snapshot"]["equity"], "99999.898");
    let rows = records(&run);
    run = run.reopen(&dir.0);
    run.runtime.apply(&original).unwrap();
    assert_eq!(run.runtime.state().unwrap(), state);
    assert_eq!(records(&run), rows);
}

#[test]
fn ready_broker_observations_require_the_original_dispatch_and_readable_journal() {
    let mut accepted_without_proof = Vec::new();
    for case in [
        "missing-record",
        "unreadable",
        "unavailable",
        "different-content",
    ] {
        let dir = Root::new();
        let (mut run, mut venue) = start(&dir.0, "100000.00000000", "0.001");
        let path = dir.0.join("broker.sqlite3");
        let dispatched = fs::read(&path).unwrap();
        assert!(
            venue
                .journal_rows()
                .iter()
                .any(|r| r["event"]["kind"] == "DISPATCHED")
        );
        let pending = venue.pending();
        assert_eq!(pending.len(), 1);
        let observed = &pending[0];
        let intact = fs::read(&path).unwrap();
        let mut reported = observed.record();
        assert!(
            venue
                .journal_rows()
                .iter()
                .any(|r| r["event"]["kind"] == "INGRESS" && r["event"]["facts"][0] == reported)
        );
        let ready = records(&run);
        let before = run.runtime.state().unwrap();
        match case {
            "missing-record" => fs::write(&path, &dispatched).unwrap(),
            "unreadable" => fs::write(&path, b"broken journal body").unwrap(),
            "unavailable" => fs::rename(&path, dir.0.join("unavailable.sqlite3")).unwrap(),
            "different-content" => reported["session"] = json!("a-new-session"),
            _ => unreachable!(),
        }
        let fact = Fact::decode(&reported).unwrap();
        assert_eq!(fact.identity(), observed.identity());
        assert_eq!(fact.fingerprint(), observed.fingerprint());
        let input = run.input(
            BOUNDARY - 2 * MINUTE,
            "ACCEPT",
            json!({"schema_version":2,"order":ORDER,
            "broker":{"id":fact.identity(),"fingerprint":fact.fingerprint(),"record":reported}}),
        );
        let applied = run.runtime.apply(&input).is_ok();
        fs::write(&path, intact).unwrap();
        if applied {
            accepted_without_proof.push(case);
        } else {
            run = run.reopen(&dir.0);
            assert_eq!(records(&run), ready);
            assert_eq!(run.runtime.state().unwrap(), before);
        }
    }
    assert!(
        accepted_without_proof.is_empty(),
        "accepted without original evidence: {accepted_without_proof:?}"
    );
}

#[test]
fn market_compiler_preimage_binds_the_complete_static_rules() {
    let cfg = config("100000.00000000", usdm_terms());
    let valid_dir = Root::new();
    let valid = Run::create(&valid_dir.0, cfg.clone());
    valid.runtime.state().unwrap();
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
        let rejected_dir = Root::new();
        let error = Runtime::create(&rejected_dir.0, changed, &"e".repeat(64))
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
    let rejected_dir = Root::new();
    assert!(Runtime::create(&rejected_dir.0, changed, &"e".repeat(64)).is_err());
}

#[test]
fn compiled_account_modes_cannot_be_relabelled_as_the_runtime_open_profile() {
    let control = Root::new();
    let matched = Run::create(&control.0, config("100000.00000000", usdm_terms()));
    matched.runtime.state().unwrap();
    let mut terms = usdm_terms_for_account(true);
    let body: Value =
        serde_json::from_str(terms["compiled_policy_json"].as_str().unwrap()).unwrap();
    assert_eq!(body["position_mode"], "HEDGING");
    assert_eq!(body["margin_mode"], "ISOLATED");
    terms["position_mode"] = json!("NETTING");
    terms["margin_mode"] = json!("CROSS");
    let rejected = Root::new();
    assert!(
        Runtime::create(
            &rejected.0,
            config("100000.00000000", terms),
            &"e".repeat(64)
        )
        .is_err(),
        "real HEDGING/ISOLATED compiled policy was accepted as NETTING/CROSS"
    );
}

#[test]
fn compiled_margin_curve_cannot_be_replaced_by_a_cheaper_runtime_curve() {
    let mut cfg = config("100000.00000000", usdm_terms());
    let control = Root::new();
    Run::create(&control.0, cfg.clone())
        .runtime
        .state()
        .unwrap();
    let original_body = cfg["perpetual"]["compiled_policy_json"].clone();
    for segment in cfg["perpetual"]["margin_segments"].as_array_mut().unwrap() {
        // 原资源按同一十倍杠杆编译，两档初始直线都过原点。
        assert_eq!(segment["initial_slope"], "0.1");
        assert_eq!(segment["initial_intercept"], "0");
        segment["initial_slope"] = json!("0.05");
    }
    assert_eq!(cfg["perpetual"]["compiled_policy_json"], original_body);
    let rejected = Root::new();
    assert!(
        Runtime::create(&rejected.0, cfg, &"e".repeat(64)).is_err(),
        "lower runtime margin curve replaced the original compiler economics"
    );
}

#[test]
fn funding_waits_until_the_virtual_boundary_is_closed_before_counting_same_time_fills() {
    let dir = Root::new();
    let (mut run, mut venue) = start(&dir.0, "100000.00000000", "0.002");
    accepted(&mut run, &mut venue);
    run.mark(BOUNDARY - MINUTE, &mark(-1));
    venue.simulation.on_bar(2, &bar(-2)).unwrap();
    assert_eq!(run.consume(&mut venue, BOUNDARY - MINUTE).len(), 1);
    let ns = BOUNDARY * 1_000_000;
    venue.simulation.advance(ns).unwrap();
    venue.observe_economic_prefix();
    let (m, f) = boundary();
    run.mark(BOUNDARY, &m);
    run.runtime.save_checkpoint().unwrap();
    let before = run.runtime.state().unwrap();
    let pending = run.input(BOUNDARY, "FUNDING", funding_payload(&m, &f));
    assert!(
        run.runtime.apply(&pending).is_err(),
        "unclosed inclusive boundary funded only the first fill"
    );
    run = run.reopen(&dir.0);
    assert_eq!(run.runtime.state().unwrap(), before);
    venue.simulation.on_bar(3, &bar(-1)).unwrap();
    let same_time = run.consume(&mut venue, BOUNDARY);
    assert_eq!(same_time.len(), 1);
    assert_eq!(same_time[0].record()["ts_event"], ns);
    venue
        .simulation
        .advance(ns.checked_add(1).unwrap())
        .unwrap();
    venue.observe_economic_prefix();
    let original = run.apply(BOUNDARY + 1, "FUNDING", funding_payload(&m, &f));
    let funded = run.runtime.state().unwrap();
    amount(
        &funded["ledger"]["ledgers"]["cluster"]["snapshot"]["funding"],
        "-.012",
    );
    amount(&funded["account"]["snapshot"]["equity"], "99999.928");
    run.runtime.save_checkpoint().unwrap();
    let history = records(&run);
    run = run.reopen(&dir.0);
    run.runtime.apply(&original).unwrap();
    assert_eq!(run.runtime.state().unwrap(), funded);
    assert_eq!(records(&run), history);
}

#[test]
fn funding_checkpoint_reopens_after_a_later_fill_and_keeps_original_duplicate() {
    let dir = Root::new();
    let (mut run, mut venue) = start(&dir.0, "100000.00000000", "0.003");
    accepted(&mut run, &mut venue);
    run.mark(BOUNDARY - MINUTE, &mark(-1));
    for (sequence, minute, visible) in [(2, -2, BOUNDARY - MINUTE), (3, -1, BOUNDARY)] {
        venue.simulation.on_bar(sequence, &bar(minute)).unwrap();
        assert_eq!(run.consume(&mut venue, visible).len(), 1);
    }
    let (m, f) = boundary();
    run.mark(BOUNDARY, &m);
    venue
        .simulation
        .advance((BOUNDARY * 1_000_000).checked_add(1).unwrap())
        .unwrap();
    venue.observe_economic_prefix();
    let original = run.apply(BOUNDARY + 1, "FUNDING", funding_payload(&m, &f));
    amount(
        &run.runtime.state().unwrap()["ledger"]["ledgers"]["cluster"]["snapshot"]["funding"],
        "-.012",
    );
    run.runtime.save_checkpoint().unwrap();
    venue.simulation.on_bar(4, &bar(0)).unwrap();
    assert_eq!(run.consume(&mut venue, BOUNDARY + MINUTE).len(), 1);
    assert_eq!(order_row(&run.runtime)["snapshot"]["status"], "FILLED");
    let final_state = run.runtime.state().unwrap();
    amount(&final_state["account"]["snapshot"]["cash"], "99999.898");
    run.runtime.save_checkpoint().unwrap();
    let history = records(&run);
    run = run.reopen(&dir.0);
    run.runtime.apply(&original).unwrap();
    assert_eq!(run.runtime.state().unwrap(), final_state);
    assert_eq!(records(&run), history);
}

#[test]
fn funding_requires_the_original_time_quantity_price_and_order_at_both_economic_owners() {
    let dir = Root::new();
    let mut cfg = config("100000.00000000", usdm_terms());
    bind_sources(&mut cfg, true);
    let mut venue = Venue::create(
        &dir.0,
        Scope::decode(&scope(&cfg)).unwrap(),
        &cfg["currency"],
        "100000.00000000",
    );
    let mut run = Run::create(&dir.0, cfg);
    broker_submit(&mut run, &mut venue, "0.003");
    accepted(&mut run, &mut venue);
    run.mark(BOUNDARY - MINUTE, &mark(-1));
    venue.simulation.on_bar(2, &bar(-2)).unwrap();
    assert_eq!(run.consume(&mut venue, BOUNDARY - MINUTE).len(), 1);
    venue.simulation.on_bar(3, &bar(-1)).unwrap();
    assert_eq!(run.consume(&mut venue, BOUNDARY).len(), 1);
    let instrument = INSTRUMENT.parse().unwrap();
    let raw = json!({"symbol":"BTCUSDT","fundingTime":BOUNDARY,"markPrice":"60000.00","fundingRate":"0.0001"});
    let (m, f) = usdm_facts::funding_boundary(
        &raw,
        &usdm_facts::Context {
            instrument_id: &instrument,
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
    venue.simulation.on_bar(4, &bar(0)).unwrap();
    let later = run.consume(&mut venue, BOUNDARY + MINUTE);
    assert_eq!(later.len(), 1);
    let boundary_ns = u64::try_from(BOUNDARY)
        .unwrap()
        .checked_mul(1_000_000)
        .unwrap();
    assert!(later[0].record()["ts_event"].as_u64().unwrap() > boundary_ns);
    assert_eq!(order_row(&run.runtime)["snapshot"]["status"], "FILLED");
    run.runtime.save_checkpoint().unwrap();
    run = run.reopen(&dir.0);
    let before = run.runtime.fork_ready().unwrap().0.checkpoint().unwrap();
    let position_cp = &before["components"][1];
    assert_eq!(position_cp["schema_version"], 2);
    assert!(position_cp["config"].is_object());
    let journal = position_cp["journal"].as_array().unwrap();
    let mut original = onlyalpha_position::Manager::new(position_cp["config"].clone()).unwrap();
    for command in journal {
        original.apply(command).unwrap();
    }
    assert_eq!(
        *position_cp,
        serde_json::from_slice::<Value>(&original.checkpoint().unwrap().0).unwrap()
    );
    let cut_bytes = fs::read(dir.0.join("market-source-cut.json")).unwrap();
    let cut = onlyalpha_domain::market_source::OnlyMarketSourceCut::read(
        &cut_bytes,
        run.cfg["perpetual"]["source_cut_sha256"].as_str().unwrap(),
    )
    .unwrap();
    let reference = json!({"schema_version":1,"mark":m["fact_id"],"funding":f["fact_id"]});
    let correct = original.funding(&cut, &reference).unwrap();
    let account_cp = &before["components"][2];
    let ledger_cp = &before["components"][3];
    let mut account =
        onlyalpha_account::Manager::new_checkpoint5(account_cp["config"].clone()).unwrap();
    let mut ledger = onlyalpha_strategy_ledger::Manager::new(ledger_cp["config"].clone()).unwrap();
    let account_bytes = serde_json::to_vec(account_cp).unwrap();
    let ledger_bytes = serde_json::to_vec(ledger_cp).unwrap();
    account
        .restore_with_funding(
            &account_bytes,
            &onlyalpha_account::digest(&account_bytes),
            &original,
            &cut,
        )
        .unwrap();
    ledger
        .restore_with_funding(
            &ledger_bytes,
            &onlyalpha_strategy_ledger::digest(&ledger_bytes),
            &original,
            &cut,
        )
        .unwrap();
    assert_eq!(account.checkpoint().unwrap().0, account_bytes);
    assert_eq!(ledger.checkpoint().unwrap().0, ledger_bytes);
    // 信封来自真正 Runtime 成功入账后的原 owner journal，不自行生成资金命令。
    run.apply(BOUNDARY + MINUTE, "FUNDING", funding_payload(&m, &f));
    let after = run.runtime.fork_ready().unwrap().0.checkpoint().unwrap();
    let account_input = after["components"][2]["journal"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["op"] == "ECONOMIC" && c["payload"]["kind"] == "FUNDING")
        .unwrap();
    let ledger_input = after["components"][3]["journal"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["op"] == "FUNDING")
        .unwrap();
    let mut correct_account = account.clone();
    let mut correct_ledger = ledger.clone();
    assert_eq!(
        correct_account
            .apply_funding(account_input, &correct)
            .unwrap()
            .status,
        onlyalpha_account::Status::Applied
    );
    assert_eq!(
        correct_ledger
            .apply_funding(ledger_input, &correct)
            .unwrap()
            .status,
        onlyalpha_strategy_ledger::Status::Applied
    );
    amount(&correct_account.snapshot()["cash"], "99999.898");

    let original_fill = run
        .runtime
        .records()
        .unwrap()
        .into_iter()
        .rfind(|r| r.prepared().input()["op"] == "FILL")
        .unwrap()
        .prepared()
        .input()
        .clone();
    let account_before = account.checkpoint().unwrap();
    let ledger_before = ledger.checkpoint().unwrap();
    // 一组保持旧投影可见的 cause/订单结果，另一组从改后的完整 Broker 原文重建上游身份。
    for rebuild_source in [false, true] {
        for (key, value) in [
            ("economic_time", json!(boundary_ns)),
            ("quantity", json!("0.002")),
            ("price", json!("59999.00")),
            ("order", json!("different-original-order")),
        ] {
            let mut alternate =
                onlyalpha_position::Manager::new(position_cp["config"].clone()).unwrap();
            let mut n = 0;
            for c in journal {
                let mut change = c.clone();
                if c["op"] == "TRADE" {
                    n += 1;
                    if n == 3 {
                        change["payload"][key] = value.clone();
                        let previous = alternate.checkpoint().unwrap();
                        assert_eq!(
                            alternate.apply(&change).unwrap_err().0,
                            "POSITION_TRADE_EVIDENCE_CONFLICT"
                        );
                        assert_eq!(alternate.checkpoint().unwrap(), previous);
                        if rebuild_source {
                            let mut origin = original_fill.clone();
                            assert_eq!(c["cause"], onlyalpha_broker::digest(&origin));
                            let raw = &mut origin["payload"]["broker"]["record"];
                            match key {
                                "economic_time" => {
                                    for field in ["ts_event", "ts_init"] {
                                        raw[field] = value.clone();
                                        raw["payload"]["fill"][field]["unix_nanos"] = value.clone();
                                    }
                                }
                                "order" => {
                                    raw["payload"]["order"] = value.clone();
                                    raw["payload"]["fill"]["order_id"]["value"] = value.clone();
                                    raw["correlation"] = value.clone();
                                    raw["causation"] = value.clone();
                                }
                                _ => raw["payload"]["fill"][key]["value"] = value.clone(),
                            }
                            let fact = Fact::decode(raw).unwrap();
                            change["payload"]["broker_record_digest"] =
                                json!(onlyalpha_broker::digest(&fact.record()));
                            origin["payload"]["broker"] = json!({"id":fact.identity(),"fingerprint":fact.fingerprint(),"record":fact.record()});
                            if key == "order" {
                                origin["payload"]["order"] = value.clone();
                            }
                            let cause = onlyalpha_broker::digest(&origin);
                            change["cause"] = json!(cause);
                            change["payload"]["execution"] = json!(format!("ETX-{cause}"));
                        }
                        change["payload"]["trade_evidence"] =
                            json!(alternate.trade_input_digest(&change).unwrap());
                    }
                }
                alternate.apply(&change).unwrap();
            }
            assert_eq!(n, 3);
            let foreign = alternate.funding(&cut, &reference).unwrap();
            if key == "economic_time" {
                amount(&correct.record()["amount"], "-.012");
                amount(&foreign.record()["amount"], "-.018");
            }
            assert_eq!(foreign.record()["cashflow"], correct.record()["cashflow"]);
            assert_ne!(foreign.account_lineage(), correct.account_lineage());
            assert_ne!(foreign.ledger_lineage(), correct.ledger_lineage());
            assert_eq!(
                account
                    .apply_funding(account_input, &foreign)
                    .unwrap_err()
                    .0,
                "ACCOUNT_FUNDING_SOURCE_RELATION"
            );
            assert_eq!(
                ledger.apply_funding(ledger_input, &foreign).unwrap_err().0,
                "LEDGER_FUNDING_SOURCE_RELATION"
            );
            assert_eq!(account.checkpoint().unwrap(), account_before);
            assert_eq!(ledger.checkpoint().unwrap(), ledger_before);
            assert!(
                account
                    .restore_with_funding(
                        &account_bytes,
                        &onlyalpha_account::digest(&account_bytes),
                        &alternate,
                        &cut
                    )
                    .is_err()
            );
            assert!(
                ledger
                    .restore_with_funding(
                        &ledger_bytes,
                        &onlyalpha_strategy_ledger::digest(&ledger_bytes),
                        &alternate,
                        &cut
                    )
                    .is_err()
            );
        }
    }
}

#[test]
fn funding_closes_all_orders_and_the_original_ready_prefix_survives_new_source_facts() {
    use onlyalpha_broker::{Broker, BrokerCommand, Connection, Journal};
    use onlyalpha_broker_virtual::BoundVirtualActor;
    use onlyalpha_domain::value::OnlyMoney;
    let dir = Root::new();
    let (mut run, mut venue) = start(&dir.0, "100000.00000000", "0.001");
    accepted(&mut run, &mut venue);
    run.mark(BOUNDARY - MINUTE, &mark(-1));
    venue.simulation.on_bar(2, &bar(-2)).unwrap();
    assert_eq!(run.consume(&mut venue, BOUNDARY - MINUTE).len(), 1);
    assert_eq!(order_row(&run.runtime)["snapshot"]["status"], "FILLED");
    let bc = BOUNDARY * 1_000_000;
    venue.simulation.advance(bc).unwrap();
    let binding = run.cfg["perpetual"]["execution_source_binding"]
        .as_str()
        .unwrap()
        .to_owned();
    let sc = Scope::decode(&scope(&run.cfg)).unwrap();
    let cash = OnlyMoney::from_record(
        &json!({"schema_version":1,"amount":"100000.00000000","currency":run.cfg["currency"]}),
    )
    .unwrap();
    let mut stale = BoundVirtualActor::open(
        &dir.0,
        sc.clone(),
        &"f".repeat(64),
        cash,
        &json!({"maximum_fill_quantity":"0.001"}),
        &binding,
    )
    .unwrap();
    let (m, f) = boundary();
    run.mark(BOUNDARY, &m);
    let original = run.input(BOUNDARY, "FUNDING", funding_payload(&m, &f));
    let before = run.runtime.state().unwrap();
    assert_eq!(
        run.runtime.apply(&original).unwrap_err().0,
        "BROKER_ECONOMIC_PREFIX_UNPROVEN"
    );
    run = run.reopen(&dir.0);
    assert_eq!(run.runtime.state().unwrap(), before);
    venue.simulation.advance(bc + 1).unwrap();
    assert_eq!(
        run.runtime.apply(&original).unwrap_err().0,
        "BROKER_ECONOMIC_PREFIX_UNPROVEN"
    );
    run = run.reopen(&dir.0);
    let original = run.apply(BOUNDARY + 1, "FUNDING", funding_payload(&m, &f));
    let funded = run.runtime.state().unwrap();
    amount(
        &funded["ledger"]["ledgers"]["cluster"]["snapshot"]["funding"],
        "-.006",
    );
    assert_eq!(
        stale.on_bar(3, &bar(-1)).unwrap_err().to_string(),
        "VIRTUAL_SOURCE_PREDECESSOR"
    );
    assert_eq!(
        venue
            .simulation
            .on_bar(3, &bar(-1))
            .unwrap_err()
            .to_string(),
        "VIRTUAL_CLOCK_REGRESSION"
    );
    run.runtime.save_checkpoint().unwrap();
    run = run.reopen(&dir.0);
    let mut req = request(INSTRUMENT, "0.001");
    req["request_id"]["value"] = json!("second-open");
    let next = "runtime-ORDER-000002";
    let admission = json!({"schema_version":3,"order":next,"request":req,"policy_fingerprint":run.cfg["perpetual"]["policy_fingerprint"]});
    let history = records(&run);
    for at in [BOUNDARY, BOUNDARY - 1] {
        let input = run.input(at, "ADMIT", admission.clone());
        assert_eq!(
            run.runtime.apply(&input).unwrap_err().0,
            "EXECUTION_ADMISSION_AT_SETTLED_BOUNDARY"
        );
        run = run.reopen(&dir.0);
        assert_eq!(run.runtime.state().unwrap(), funded);
        assert_eq!(records(&run), history);
    }
    run.apply(BOUNDARY + 1, "ADMIT", admission);
    let cp = run.runtime.fork_ready().unwrap().0.checkpoint().unwrap();
    let client = &cp["components"][0]["state"]["orders"]
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["snapshot"]["order_id"]["value"] == next)
        .unwrap()["snapshot"]["client_order_id"]["value"];
    let cmd=BrokerCommand::decode(&json!({"schema_version":1,"scope":sc.record(),"operation":"SUBMIT","command_id":"second-submit","order":next,"client":client,"request":req})).unwrap();
    let mut j = onlyalpha_runtime::BoundBrokerJournal::open(&dir.0, &binding).unwrap();
    let mut broker = Broker::recover(sc, &j, 32).unwrap();
    broker.set_connection(Connection::Ready);
    broker.set_health(true, true, true);
    let prior = j.records().unwrap();
    assert_eq!(
        j.dispatch(&mut broker, &run.runtime, &mut venue.simulation, &cmd)
            .unwrap_err()
            .to_string(),
        "BROKER_SOURCE_CLOCK_BEFORE_ADMISSION"
    );
    assert_eq!(j.records().unwrap(), prior);
    venue.simulation.advance(bc + 1_000_000).unwrap();
    j.dispatch(&mut broker, &run.runtime, &mut venue.simulation, &cmd)
        .unwrap();
    run.apply(
        BOUNDARY + 1,
        "SUBMISSION",
        json!({"schema_version":1,"order":next,"outcome":"DISPATCHED"}),
    );
    let before_source = run.runtime.state().unwrap();
    let rows = records(&run);
    run = run.reopen(&dir.0);
    assert_eq!(run.runtime.state().unwrap(), before_source);
    venue.simulation.advance(bc + 1_000_000).unwrap();
    venue.simulation.on_bar(3, &bar(0)).unwrap();
    venue.simulation.publish(&mut broker, &mut j).unwrap();
    let actual = broker.pending().to_vec();
    assert!(actual.iter().any(
        |f| f.record()["kind"] == "TRADE" && f.record()["ts_event"] == bc + MINUTE * 1_000_000
    ));
    run = run.reopen(&dir.0);
    assert_eq!(run.runtime.state().unwrap(), before_source);
    assert_eq!(records(&run), rows);
    for fact in actual {
        let r = fact.record();
        let op = if r["kind"] == "ACCEPTED" {
            "ACCEPT"
        } else {
            "FILL"
        };
        run.apply(BOUNDARY+MINUTE,op,json!({"schema_version":2,"order":next,"broker":{"id":fact.identity(),"fingerprint":fact.fingerprint(),"record":r}}));
        j.acknowledge_original(&mut broker, &run.runtime, fact.identity())
            .unwrap();
    }
    let final_state = run.runtime.state().unwrap();
    amount(
        &final_state["ledger"]["ledgers"]["cluster"]["snapshot"]["funding"],
        "-.006",
    );
    run = run.reopen(&dir.0);
    run.runtime.apply(&original).unwrap();
    assert_eq!(run.runtime.state().unwrap(), final_state);
}

#[test]
fn delayed_original_trade_from_unknown_dispatch_must_reach_ready_before_funding() {
    let dir = Root::new();
    let cfg = config("100000.00000000", usdm_terms());
    let mut venue = Venue::create(
        &dir.0,
        Scope::decode(&scope(&cfg)).unwrap(),
        &cfg["currency"],
        "100000.00000000",
    );
    let mut run = Run::create(&dir.0, cfg);
    let initial = BOUNDARY - 2 * MINUTE;
    venue.simulation.on_bar(1, &bar(-3)).unwrap();
    run.mark(initial, &mark(-2));
    let req = request(INSTRUMENT, "0.001");
    run.admit(initial, &req);
    venue.dispatch_losing_receipt(&run.runtime, &req);
    run.apply(
        initial,
        "SUBMISSION",
        json!({"schema_version":1,"order":ORDER,"outcome":"UNKNOWN"}),
    );
    venue.simulation.advance(initial * 1_000_000).unwrap();
    accepted(&mut run, &mut venue);
    venue.simulation.on_bar(2, &bar(-2)).unwrap();
    let (m, f) = boundary();
    run.mark(BOUNDARY, &m);
    venue.simulation.advance(BOUNDARY * 1_000_000 + 1).unwrap();
    let before = run.runtime.state().unwrap();
    let funding = run.input(BOUNDARY + 1, "FUNDING", funding_payload(&m, &f));
    assert_eq!(
        run.runtime.apply(&funding).unwrap_err().0,
        "EXECUTION_FUNDING_UNAPPLIED_TRADE"
    );
    run = run.reopen(&dir.0);
    assert_eq!(run.runtime.state().unwrap(), before);
    venue = venue.restore(&dir.0);
    let trade = run.consume(&mut venue, BOUNDARY + 1);
    assert_eq!(trade.len(), 1);
    assert_eq!(
        trade[0].record()["ts_event"],
        (BOUNDARY - MINUTE) * 1_000_000
    );
    let funded = run.apply(BOUNDARY + 1, "FUNDING", funding_payload(&m, &f));
    let expected = run.runtime.state().unwrap();
    amount(
        &expected["ledger"]["ledgers"]["cluster"]["snapshot"]["funding"],
        "-.006",
    );
    run = run.reopen(&dir.0);
    run.runtime.apply(&funded).unwrap();
    assert_eq!(run.runtime.state().unwrap(), expected);
}

fn admitted_for_original_query(dir: &Path) -> (Run, Venue, Value, i64) {
    let cfg = config("100000.00000000", usdm_terms());
    let mut venue = Venue::create(
        dir,
        Scope::decode(&scope(&cfg)).unwrap(),
        &cfg["currency"],
        "100000.00000000",
    );
    let mut run = Run::create(dir, cfg);
    let at = BOUNDARY - 2 * MINUTE;
    venue.simulation.on_bar(1, &bar(-3)).unwrap();
    run.mark(at, &mark(-2));
    let req = request(INSTRUMENT, "0.001");
    run.admit(at, &req);
    (run, venue, req, at)
}

#[test]
fn two_original_queries_and_real_ack_resolve_unknown_across_reopen() {
    use onlyalpha_broker::{CommandState, Journal, source::QueryPhase};
    let dir = Root::new();
    let (mut run, mut venue, req, at) = admitted_for_original_query(&dir.0);
    venue.dispatch_losing_receipt(&run.runtime, &req);
    run.apply(
        at,
        "SUBMISSION",
        json!({"schema_version":1,"order":ORDER,"outcome":"UNKNOWN"}),
    );
    let weak = venue
        .simulation
        .observe_command(QueryPhase::Discovery, "submit")
        .unwrap();
    venue.simulation.advance(at * 1_000_000).unwrap();
    assert!(
        venue
            .journal
            .reconcile_original(&mut venue.protocol, "submit", &weak)
            .is_err()
    );
    venue.simulation.on_bar(2, &bar(-2)).unwrap();
    let first = venue
        .simulation
        .observe_command(QueryPhase::Discovery, "submit")
        .unwrap();
    assert!(
        venue
            .journal
            .reconcile_original(&mut venue.protocol, "other", &first)
            .is_err()
    );
    assert!(
        venue
            .journal
            .resolve_original(&mut venue.protocol, &run.runtime, "submit", &first)
            .is_err()
    );
    assert_eq!(
        venue.protocol.command_state("submit"),
        Some(CommandState::Unknown)
    );
    venue
        .journal
        .reconcile_original(&mut venue.protocol, "submit", &first)
        .unwrap();
    let after_discovery = venue.journal.records().unwrap();
    venue = venue.restore(&dir.0);
    venue
        .journal
        .reconcile_original(&mut venue.protocol, "submit", &first)
        .unwrap();
    assert_eq!(venue.journal.records().unwrap(), after_discovery);
    let discovered = venue.protocol.pending().to_vec();
    assert_eq!(discovered.len(), 2);
    let early = venue
        .simulation
        .observe_command(QueryPhase::Resolve, "submit")
        .unwrap();
    assert!(
        venue
            .journal
            .resolve_original(&mut venue.protocol, &run.runtime, "submit", &early)
            .is_err()
    );
    assert!(
        venue
            .journal
            .acknowledge_original(&mut venue.protocol, &run.runtime, discovered[0].identity())
            .is_err()
    );
    // 发现可先于正常流的投递。重开后依据最初的查询原件推进 PUBLISHED 游标。
    assert_eq!(
        venue
            .simulation
            .publish(&mut venue.protocol, &mut venue.journal)
            .unwrap(),
        2
    );
    assert_eq!(
        venue
            .simulation
            .publish(&mut venue.protocol, &mut venue.journal)
            .unwrap(),
        0
    );
    assert!(
        !venue
            .journal_rows()
            .iter()
            .any(|r| r["event"]["kind"] == "INGRESS")
    );
    for (index, fact) in discovered.iter().enumerate() {
        let body = fact.record();
        let op = if body["kind"] == "ACCEPTED" {
            "ACCEPT"
        } else {
            "FILL"
        };
        run.apply(BOUNDARY-MINUTE,op,json!({"schema_version":2,"order":ORDER,"broker":{"id":fact.identity(),"fingerprint":fact.fingerprint(),"record":body}}));
        assert!(
            venue
                .protocol
                .acknowledge(&mut venue.journal, &run.runtime, fact.identity())
                .is_err()
        );
        venue.acknowledge(&run.runtime, fact);
        if index == 0 {
            let partial = venue
                .simulation
                .observe_command(QueryPhase::Resolve, "submit")
                .unwrap();
            assert!(
                venue
                    .journal
                    .resolve_original(&mut venue.protocol, &run.runtime, "submit", &partial)
                    .is_err()
            );
        }
    }
    assert_eq!(
        venue.protocol.command_state("submit"),
        Some(CommandState::Reconciling)
    );
    assert!(
        venue
            .journal
            .resolve_original(&mut venue.protocol, &run.runtime, "submit", &early)
            .is_err()
    );
    run = run.reopen(&dir.0);
    venue = venue.restore(&dir.0);
    let second = venue
        .simulation
        .observe_command(QueryPhase::Resolve, "submit")
        .unwrap();
    venue
        .journal
        .resolve_original(&mut venue.protocol, &run.runtime, "submit", &second)
        .unwrap();
    let final_rows = venue.journal.records().unwrap();
    assert_eq!(
        final_rows.last().unwrap().record()["event"]["receipts"]
            .as_array()
            .unwrap()
            .len(),
        2
    );
    venue = venue.restore(&dir.0);
    venue
        .journal
        .resolve_original(&mut venue.protocol, &run.runtime, "submit", &second)
        .unwrap();
    assert_eq!(
        venue.protocol.command_state("submit"),
        Some(CommandState::Resolved)
    );
    assert_eq!(venue.journal.records().unwrap(), final_rows);
    assert!(venue.protocol.ready());
}

#[test]
fn bound_journal_must_reject_absence_from_a_disconnected_shadow_venue() {
    use onlyalpha_broker::{
        CommandState, ConnectionPort, DispatchResult, TradingPort, source::QueryPhase,
    };
    use onlyalpha_broker_virtual::VirtualBroker;
    use onlyalpha_domain::value::OnlyMoney;
    for original_rejected in [false, true] {
        let dir = Root::new();
        let (mut run, mut venue, req, at) = admitted_for_original_query(&dir.0);
        if original_rejected {
            venue.simulation.disconnect().unwrap();
        }
        venue.dispatch_losing_receipt(&run.runtime, &req);
        run.apply(
            at,
            "SUBMISSION",
            json!({"schema_version":1,"order":ORDER,"outcome":"UNKNOWN"}),
        );
        venue.simulation.advance(at * 1_000_000).unwrap();
        let cmd = venue.command(&run.runtime, &req);
        let cash = OnlyMoney::from_record(
            &json!({"schema_version":1,"amount":"100000.00000000","currency":run.cfg["currency"]}),
        )
        .unwrap();
        let mut shadow = VirtualBroker::new(
            cmd.scope().clone(),
            &"f".repeat(64),
            cash,
            &json!({"maximum_fill_quantity":"0.001"}),
        )
        .unwrap();
        assert_eq!(shadow.dispatch(&cmd).unwrap(), DispatchResult::Rejected);
        assert!(
            shadow
                .reconcile(&mut venue.protocol, &mut venue.journal, "submit")
                .is_err()
        );
        assert_eq!(
            venue.protocol.command_state("submit"),
            Some(CommandState::Unknown)
        );
        let first = venue
            .simulation
            .observe_command(QueryPhase::Discovery, "submit")
            .unwrap();
        venue
            .journal
            .reconcile_original(&mut venue.protocol, "submit", &first)
            .unwrap();
        if original_rejected {
            let second = venue
                .simulation
                .observe_command(QueryPhase::Resolve, "submit")
                .unwrap();
            venue
                .journal
                .resolve_original(&mut venue.protocol, &run.runtime, "submit", &second)
                .unwrap();
            venue = venue.restore(&dir.0);
            assert_eq!(
                venue.protocol.command_state("submit"),
                Some(CommandState::Resolved)
            );
            let head = venue.simulation.checkpoint();
            assert_eq!(
                venue.simulation.dispatch(&cmd).unwrap(),
                DispatchResult::Rejected
            );
            assert_eq!(venue.simulation.checkpoint(), head);
        } else {
            assert!(
                venue
                    .protocol
                    .pending()
                    .iter()
                    .any(|f| f.record()["kind"] == "ACCEPTED")
            );
        }
    }
}

#[test]
fn bound_result_must_match_actual_received_and_rejected() {
    use onlyalpha_broker::{
        BrokerCommand, Capabilities, CommandState, ConnectionPort, DispatchResult, ReadyIntent,
        TradingPort,
    };
    use onlyalpha_broker_virtual::BoundVirtualActor;
    struct ChangedReply<'a>(&'a mut BoundVirtualActor);
    impl TradingPort for ChangedReply<'_> {
        fn capabilities(&self) -> Capabilities {
            self.0.capabilities()
        }
        fn check_dispatch(&self, i: &ReadyIntent) -> Result<(), onlyalpha_broker::Error> {
            self.0.check_dispatch(i)
        }
        fn dispatch(
            &mut self,
            c: &BrokerCommand,
        ) -> Result<DispatchResult, onlyalpha_broker::Error> {
            Ok(match self.0.dispatch(c)? {
                DispatchResult::Received => DispatchResult::Rejected,
                DispatchResult::Rejected => DispatchResult::Received,
                DispatchResult::Unknown => panic!("deterministic venue"),
            })
        }
    }
    for disconnected in [false, true] {
        let dir = Root::new();
        let (run, mut venue, req, _) = admitted_for_original_query(&dir.0);
        if disconnected {
            venue.simulation.disconnect().unwrap();
        }
        let command = venue.command(&run.runtime, &req);
        let e = venue
            .journal
            .dispatch(
                &mut venue.protocol,
                &run.runtime,
                &mut ChangedReply(&mut venue.simulation),
                &command,
            )
            .unwrap_err();
        assert_eq!(e.to_string(), "BROKER_SOURCE_COMMAND_RESULT");
        venue = venue.restore(&dir.0);
        assert_eq!(
            venue.protocol.command_state("submit"),
            Some(CommandState::Unknown)
        );
        assert!(
            !venue
                .journal_rows()
                .iter()
                .any(|r| r["event"]["kind"] == "RESULT")
        );
        let head = venue.simulation.checkpoint();
        assert_eq!(
            venue
                .journal
                .dispatch(
                    &mut venue.protocol,
                    &run.runtime,
                    &mut venue.simulation,
                    &command
                )
                .unwrap(),
            CommandState::Unknown
        );
        assert_eq!(venue.simulation.checkpoint(), head);
    }
}

#[test]
fn missed_source_command_stays_unknown_and_cannot_enter_after_dispatch_window() {
    use onlyalpha_broker::{
        BrokerCommand, Capabilities, CommandState, DispatchResult, TradingPort, source::QueryPhase,
    };
    struct LoseBeforeDelivery(Capabilities);
    impl TradingPort for LoseBeforeDelivery {
        fn capabilities(&self) -> Capabilities {
            self.0.clone()
        }
        fn dispatch(
            &mut self,
            _: &BrokerCommand,
        ) -> Result<DispatchResult, onlyalpha_broker::Error> {
            Ok(DispatchResult::Unknown)
        }
    }
    let dir = Root::new();
    let (mut run, mut venue, req, at) = admitted_for_original_query(&dir.0);
    let command = venue.command(&run.runtime, &req);
    let mut lost = LoseBeforeDelivery(venue.simulation.capabilities());
    assert_eq!(
        venue
            .journal
            .dispatch(&mut venue.protocol, &run.runtime, &mut lost, &command)
            .unwrap(),
        CommandState::Unknown
    );
    run.apply(
        at,
        "SUBMISSION",
        json!({"schema_version":1,"order":ORDER,"outcome":"UNKNOWN"}),
    );
    let first = venue
        .simulation
        .observe_command(QueryPhase::Discovery, "submit")
        .unwrap();
    venue
        .journal
        .reconcile_original(&mut venue.protocol, "submit", &first)
        .unwrap();
    let second = venue
        .simulation
        .observe_command(QueryPhase::Resolve, "submit")
        .unwrap();
    assert!(
        venue
            .journal
            .resolve_original(&mut venue.protocol, &run.runtime, "submit", &second)
            .is_err()
    );
    let head = venue.simulation.checkpoint();
    assert!(venue.simulation.dispatch(&command).is_err());
    venue = venue.restore(&dir.0);
    assert_eq!(venue.simulation.checkpoint(), head);
    assert_eq!(
        venue.protocol.command_state("submit"),
        Some(CommandState::Reconciling)
    );
    assert!(venue.protocol.pending().is_empty());
}
