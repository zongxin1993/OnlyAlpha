//! 仅在专用 Spot Testnet 账户和新 run id 获准时手动运行。
use super::*;
use crate::{
    Access, Binding, BrokerCommand, Provenance, ack_venue, cancel_client, ns, order_view,
    submit_params, subscription_event, subscription_id, trade_fact, venue_id, wire_client,
    wire_decimal,
};
use bigdecimal::{BigDecimal, RoundingMode, Zero};
use onlyalpha_broker::Scope;
use onlyalpha_domain::{enums::OnlyCurrencyType, value::OnlyCurrency};
use onlyalpha_integration_contract::source::SourceError;
use serde_json::json;
use std::{env, fs, sync::OnceLock};

const REST: &str = "https://testnet.binance.vision";
const WS: &str = "wss://ws-api.testnet.binance.vision/ws-api/v3";

#[derive(Default)]
struct ServerClock(OnceLock<(i64, Instant)>);
impl Clock for ServerClock {
    fn now_ns(&self) -> std::result::Result<i64, SourceError> {
        let (server, anchor) = self.0.get().ok_or(SourceError::Unavailable)?;
        let elapsed =
            i64::try_from(anchor.elapsed().as_nanos()).map_err(|_| SourceError::Invalid)?;
        server.checked_add(elapsed).ok_or(SourceError::Invalid)
    }
}

fn public(io: &Native, path: &str, params: &[(&str, &str)]) -> Result<Value> {
    let budget = Budget::new(15_000, 1);
    let remaining = budget.take()?;
    let mut url = reqwest::Url::parse(REST).expect("fixed testnet");
    url.set_path(path);
    if !params.is_empty() {
        url.query_pairs_mut().extend_pairs(params.iter().copied());
    }
    io.sync(&budget, async {
        let mut r = io
            .client
            .get(url)
            .timeout(remaining)
            .send()
            .await
            .map_err(|_| err("TESTNET_PUBLIC_UNAVAILABLE"))?;
        if r.status() != reqwest::StatusCode::OK
            || r.content_length().is_some_and(|n| n > io.limit as u64)
        {
            return Err(err("TESTNET_PUBLIC_RESPONSE"));
        }
        let mut bytes = Vec::new();
        while let Some(chunk) = r
            .chunk()
            .await
            .map_err(|_| err("TESTNET_PUBLIC_INCOMPLETE"))?
        {
            if bytes.len().saturating_add(chunk.len()) > io.limit {
                return Err(err("TESTNET_PUBLIC_SIZE"));
            }
            bytes.extend_from_slice(&chunk);
        }
        wire_json(&bytes)
    })
}

fn private(
    io: &Native,
    method: &str,
    path: &str,
    params: &BTreeMap<String, String>,
) -> Result<Value> {
    let response = io.request(method, path, params, &Budget::new(15_000, 1))?;
    if response.status != 200 {
        return Err(err("TESTNET_PRIVATE_RESPONSE"));
    }
    wire_json(&response.bytes)
}

fn filter<'a>(info: &'a Value, kinds: &[&str]) -> Result<&'a Value> {
    let rows = info["filters"]
        .as_array()
        .ok_or_else(|| err("TESTNET_FILTERS"))?;
    kinds
        .iter()
        .find_map(|kind| rows.iter().find(|r| r["filterType"] == *kind))
        .ok_or_else(|| err("TESTNET_FILTER_MISSING"))
}

fn align(value: BigDecimal, step: &BigDecimal, rounding: RoundingMode) -> Result<BigDecimal> {
    if *step <= BigDecimal::zero() {
        return Err(err("TESTNET_NONPOSITIVE_STEP"));
    }
    Ok((value / step).with_scale_round(0, rounding) * step)
}

fn amount(value: &BigDecimal, step: &BigDecimal) -> Result<Value> {
    let scale = step.as_bigint_and_exponent().1.max(0);
    if scale > 18 {
        return Err(err("TESTNET_PRECISION"));
    }
    Ok(
        json!({"schema_version":1,"value":value.with_scale(scale).to_plain_string(),"precision":scale}),
    )
}

fn order(
    io: &Native,
    scope: &Scope,
    run: &str,
    info: &Value,
    market: bool,
    available: &BigDecimal,
) -> Result<BrokerCommand> {
    let symbol = info["symbol"]
        .as_str()
        .ok_or_else(|| err("TESTNET_SYMBOL"))?;
    if info["status"] != "TRADING" || !matches!(symbol, "BTCUSDT" | "ETHUSDT") {
        return Err(err("TESTNET_TRADING_SYMBOL"));
    }
    let ticker = public(io, "/api/v3/ticker/price", &[("symbol", symbol)])?;
    if ticker["symbol"] != symbol {
        return Err(err("TESTNET_TICKER_SYMBOL"));
    }
    let spot = wire_decimal(&ticker["price"])?;
    let tick = wire_decimal(&filter(info, &["PRICE_FILTER"])?["tickSize"])?;
    let lot = filter(info, &["LOT_SIZE"])?;
    let lot = if market {
        let m = filter(info, &["MARKET_LOT_SIZE"])?;
        if wire_decimal(&m["stepSize"])?.is_zero() {
            lot
        } else {
            m
        }
    } else {
        lot
    };
    let step = wire_decimal(&lot["stepSize"])?;
    let minimum = wire_decimal(&filter(info, &["NOTIONAL", "MIN_NOTIONAL"])?["minNotional"])?;
    let hundred = BigDecimal::from(100);
    let reference = if market {
        spot
    } else {
        align(
            spot * BigDecimal::from(98) / &hundred,
            &tick,
            RoundingMode::Floor,
        )?
    };
    if reference <= BigDecimal::zero() || minimum <= BigDecimal::zero() {
        return Err(err("TESTNET_PRICE_OR_NOTIONAL"));
    }
    let target =
        (minimum * BigDecimal::from(110) / hundred / &reference).max(wire_decimal(&lot["minQty"])?);
    let qty = align(target, &step, RoundingMode::Ceiling)?;
    if &qty * &reference > *available {
        return Err(err("TESTNET_USDT_REQUIRED"));
    }
    let kind = if market { "MARKET" } else { "LIMIT" };
    let client = format!("oa-{run}-{symbol}-{kind}");
    let mut request = serde_json::from_str::<Value>(include_str!(
        "../../../../test-data/broker/domain-inputs.json"
    ))
    .unwrap()["request"]
        .clone();
    request["request_id"]["value"] = json!(format!("req-{client}"));
    request["account_id"]["value"] = scope.record()["account"].clone();
    request["instrument_id"]["venue"]["value"] = json!("BINANCE");
    request["instrument_id"]["symbol"]["value"] = json!(symbol);
    request["order_type"] = json!(kind);
    request["time_in_force"] = json!("GTC");
    request["quantity"] = amount(&qty, &step)?;
    request["price"] = if market {
        Value::Null
    } else {
        amount(&reference, &tick)?
    };
    BrokerCommand::decode(
        &json!({"schema_version":1,"operation":"SUBMIT","scope":scope.record(),"command_id":format!("submit-{client}"),"order":format!("order-{client}"),"client":client,"request":request}),
    )
}

fn query(io: &Native, c: &BrokerCommand, venue: Option<u64>) -> Result<Value> {
    let mut params = BTreeMap::from([("symbol".into(), crate::symbol(c)?)]);
    if let Some(n) = venue {
        params.insert("orderId".into(), n.to_string());
    } else {
        params.insert("origClientOrderId".into(), wire_client(c.client()));
    }
    private(io, "GET", "/api/v3/order", &params)
}

fn submit(io: &Native, c: &BrokerCommand) -> Result<u64> {
    let params = submit_params(c)?;
    let ack =
        private(io, "POST", "/api/v3/order", &params).and_then(|raw| ack_venue(c, c, None, &raw));
    if let Ok(venue) = ack {
        return Ok(venue);
    }

    // 未取得合法 ACK 仍可能已成交。只从原 client 查询，完整对应原委托后才清理仍开着的 LIMIT。
    let wire = wire_client(c.client());
    let unresolved = || err(&format!("TESTNET_SUBMIT_UNKNOWN original_client={wire}"));
    let observed = query(io, c, None).map_err(|_| unresolved())?;
    let venue = observed["orderId"].as_u64().ok_or_else(unresolved)?;
    let view = order_view(c, Some(venue), std::slice::from_ref(&wire), &observed)
        .map_err(|_| unresolved())?;
    let state = view.record();
    if params["type"] == "LIMIT"
        && matches!(
            state["status"].as_str(),
            Some("ACCEPTED" | "PARTIALLY_FILLED")
        )
    {
        cancel_known_limit(io, c, venue).map_err(|_| {
            err(&format!(
                "TESTNET_CANCEL_UNCONFIRMED original_client={wire} venue={venue}"
            ))
        })?;
    }
    Err(err(&format!(
        "TESTNET_SUBMIT_ACK_UNCONFIRMED original_client={wire} venue={venue}"
    )))
}

fn limit_contract(io: &Native, c: &BrokerCommand) -> Result<()> {
    let venue = submit(io, c)?;
    // 有明确场所 ACK 时，即使首次查询失败，也对该确切场所单执行一次撤单。
    let wire = wire_client(c.client());
    let first = query(io, c, None)
        .and_then(|r| order_view(c, Some(venue), std::slice::from_ref(&wire), &r));
    cancel_known_limit(io, c, venue)?;
    first?;
    Ok(())
}

fn cancel_known_limit(io: &Native, c: &BrokerCommand, venue: u64) -> Result<()> {
    let wire = wire_client(c.client());
    let cancel = BrokerCommand::decode(
        &json!({"schema_version":1,"scope":c.scope().record(),"operation":"CANCEL","command_id":format!("cancel-{}",c.client()),"client":c.client(),"order":c.order(),"request":{"schema_version":1,"request_id":{"schema_version":1,"value":format!("cx-{}",c.client())},"order_id":{"schema_version":1,"value":c.order()},"reason":"testnet protocol certification","metadata":{}}}),
    )?;
    let cancel_wire = cancel_client(&cancel);
    let params = BTreeMap::from([
        ("symbol".into(), crate::symbol(c)?),
        ("orderId".into(), venue.to_string()),
        ("origClientOrderId".into(), wire.clone()),
        ("newClientOrderId".into(), cancel_wire.clone()),
    ]);
    let response = private(io, "DELETE", "/api/v3/order", &params);
    let confirmed = query(io, c, Some(venue));
    ack_venue(&cancel, c, Some(venue), &response?)?;
    let terminal = order_view(c, Some(venue), &[wire, cancel_wire], &confirmed?)?;
    if terminal.record()["status"] != "CANCELLED" {
        return Err(err("TESTNET_CANCEL_NOT_TERMINAL"));
    }
    Ok(())
}

fn market_contract(io: &Native, c: &BrokerCommand, subscription: u64) -> Result<()> {
    let venue = submit(io, c)?;
    let raw = query(io, c, None)?;
    let view = order_view(c, Some(venue), &[wire_client(c.client())], &raw)?;
    if view.record()["status"] != "FILLED" {
        return Err(err("TESTNET_MARKET_NOT_FILLED"));
    }
    let symbol = crate::symbol(c)?;
    let mut pages = crate::TradePages::new(
        c,
        venue,
        raw["executedQty"]
            .as_str()
            .ok_or_else(|| err("TESTNET_EXECUTED_QTY"))?,
        1000,
    )?;
    let paging = Budget::new(15_000, 16);
    loop {
        let params = BTreeMap::from([
            ("symbol".into(), symbol.clone()),
            ("orderId".into(), venue.to_string()),
            ("limit".into(), "1000".into()),
            ("fromId".into(), pages.cursor().to_string()),
        ]);
        let response = io.request("GET", "/api/v3/myTrades", &params, &paging)?;
        if response.status != 200 {
            return Err(err("TESTNET_TRADES_UNAVAILABLE"));
        }
        if pages.push(&wire_json(&response.bytes)?)? {
            break;
        }
    }
    if pages.rows.is_empty() {
        return Err(err("TESTNET_INCOMPLETE_MARKET_TRADES"));
    }
    let budget = Budget::new(15_000, 128);
    loop {
        let frame = wire_json(&io.next(&budget)?)?;
        let event = subscription_event(subscription, &frame)?;
        if event["e"] != "executionReport"
            || event["x"] != "TRADE"
            || event["c"] != wire_client(c.client())
        {
            continue;
        }
        if event["s"] != symbol
            || event["i"].as_u64() != Some(venue)
            || event["S"] != "BUY"
            || event["o"] != "MARKET"
        {
            return Err(err("TESTNET_STREAM_ORDER_CONFLICT"));
        }
        let row = pages
            .rows
            .iter()
            .find(|r| r["id"] == event["t"])
            .ok_or_else(|| err("TESTNET_STREAM_TRADE_MISSING"))?;
        if row["time"] != event["T"]
            || row["isMaker"] != event["m"]
            || wire_decimal(&row["qty"])? != wire_decimal(&event["l"])?
            || wire_decimal(&row["price"])? != wire_decimal(&event["L"])?
        {
            return Err(err("TESTNET_STREAM_TRADE_CONFLICT"));
        }
        let fact = trade_fact(
            c,
            row,
            &Provenance {
                session: "testnet",
                received: io.clock.now_ns().map_err(|_| err("TESTNET_CLOCK"))?,
                source: "binance-query",
            },
        )?;
        let fill = &fact.record()["payload"]["fill"];
        if fill["order_id"]["value"] != c.order()
            || fill["venue_order_id"]["value"] != venue_id(&symbol, venue)?
        {
            return Err(err("TESTNET_MARKET_FILL_IDENTITY"));
        }
        return Ok(());
    }
}

#[test]
#[ignore = "真实 Spot Testnet 专用账户协议认证，必须显式授权并使用新的 run id"]
fn authorized_spot_testnet_limit_cancel_market_trade_and_subscription() {
    assert!(env::var("ONLYALPHA_BINANCE_TESTNET_AUTHORIZED").as_deref() == Ok("1"));
    for (name, expected) in [
        ("ONLYALPHA_BINANCE_TESTNET_REST_BASE_URL", REST),
        ("ONLYALPHA_BINANCE_TESTNET_WS_BASE_URL", WS),
    ] {
        if let Some(value) = env::var_os(name) {
            assert!(
                value.to_str() == Some(expected),
                "专项 endpoint 必须使用固定 Spot Testnet"
            );
        }
    }
    let run = env::var("ONLYALPHA_BINANCE_TESTNET_RUN_ID").expect("需提供本次唯一 run id");
    assert!((1..=8).contains(&run.len()) && run.bytes().all(|b| b.is_ascii_alphanumeric()));
    let uid = env::var("ONLYALPHA_BINANCE_TESTNET_UID")
        .expect("需提供专用 Testnet UID")
        .parse::<u64>()
        .unwrap();
    let trust = Trust::explicit_roots(vec![
        fs::read(env::var_os("ONLYALPHA_BINANCE_TESTNET_CA_PEM").expect("需提供测试信任根"))
            .unwrap(),
    ])
    .unwrap();
    let keys = Credentials::new(
        env::var("ONLYALPHA_BINANCE_TESTNET_API_KEY").expect("缺专用 Testnet API key"),
        env::var("ONLYALPHA_BINANCE_TESTNET_API_SECRET").expect("缺专用 Testnet secret"),
    )
    .unwrap();
    let scope=Scope::decode(&json!({"account":"spot-testnet","engine":"protocol","runtime":format!("testnet-{run}"),"gateway":"binance-testnet","runtime_kind":"SIM","generation":"c".repeat(64)})).unwrap();
    let config = Config {
        binding: Binding {
            access: Access::Trading,
            environment: Environment::SpotTestnet,
            artifact_sha256: "d".repeat(64),
            scope: scope.clone(),
            uid,
            key_slot: "dedicated-testnet-key".into(),
            secret_slot: "dedicated-testnet-secret".into(),
        },
        currencies: BTreeMap::from([(
            "USDT".into(),
            OnlyCurrency::new("USDT", 8, OnlyCurrencyType::Crypto).unwrap(),
        )]),
        recv_window_ms: 5000,
        max_bytes: 1024 * 1024,
        max_requests: 128,
        timeout_ms: 15_000,
    };
    config.validate().unwrap();
    let clock = Arc::new(ServerClock::default());
    let io = Native::new(&config, keys, &trust, clock.clone()).unwrap();
    assert_eq!(io.rest, REST);
    assert_eq!(io.ws, WS);
    let time = public(&io, "/api/v3/time", &[]).unwrap();
    clock
        .0
        .set((ns(&time["serverTime"]).unwrap(), Instant::now()))
        .unwrap();
    let account = private(&io, "GET", "/api/v3/account", &BTreeMap::new()).unwrap();
    assert!(
        account["uid"].as_u64() == Some(uid)
            && account["canTrade"] == true
            && account["accountType"] == "SPOT"
    );
    let balances = account["balances"].as_array().expect("需要真实账户余额");
    let usdt = balances
        .iter()
        .find(|r| r["asset"] == "USDT")
        .expect("需要 USDT");
    let available = wire_decimal(&usdt["free"]).unwrap();
    let info = public(
        &io,
        "/api/v3/exchangeInfo",
        &[("symbols", r#"["BTCUSDT","ETHUSDT"]"#)],
    )
    .unwrap();
    let symbols = info["symbols"].as_array().unwrap();
    assert_eq!(symbols.len(), 2);
    let symbol = |name: &str| {
        symbols
            .iter()
            .find(|r| r["symbol"] == name)
            .expect("缺少所需交易对")
    };
    let id = format!("cert-{run}");
    let ack = wire_json(&io.subscribe(&id, &Budget::new(15_000, 1)).unwrap()).unwrap();
    let subscription = subscription_id(&id, &ack).unwrap();
    for name in ["BTCUSDT", "ETHUSDT"] {
        let c = order(&io, &scope, &run, symbol(name), false, &available).unwrap();
        limit_contract(&io, &c).expect("限价单或撤单未证实，请按原 client 和场所订单查询");
    }
    let c = order(&io, &scope, &run, symbol("BTCUSDT"), true, &available).unwrap();
    market_contract(&io, &c, subscription).expect("市价单或成交未证实，请查询原订单");
    io.close();
}
