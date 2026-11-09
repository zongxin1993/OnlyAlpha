use super::*;
use bigdecimal::{BigDecimal, Zero};
pub(crate) struct TradePages {
    symbol: String,
    venue: u64,
    buyer: bool,
    expected: BigDecimal,
    total: BigDecimal,
    limit: usize,
    next: u64,
    done: bool,
    pub(crate) rows: Vec<Value>,
}
impl TradePages {
    pub(crate) fn new(c: &BrokerCommand, venue: u64, filled: &str, limit: usize) -> Result<Self> {
        if !(1..=1000).contains(&limit) {
            return Err(err("BINANCE_PAGE_LIMIT"));
        }
        Ok(Self {
            symbol: symbol(c)?,
            venue,
            buyer: c.record()["request"]["side"] == "BUY",
            expected: wire_decimal(&json!(filled))?,
            total: BigDecimal::zero(),
            limit,
            next: 0,
            done: false,
            rows: Vec::new(),
        })
    }
    pub(crate) fn cursor(&self) -> u64 {
        self.next
    }
    pub(crate) fn push(&mut self, value: &Value) -> Result<bool> {
        let rows = value
            .as_array()
            .filter(|p| p.len() <= self.limit && !self.done)
            .ok_or_else(|| err("BINANCE_TRADE_PAGE"))?;
        for row in rows {
            let id = row["id"]
                .as_u64()
                .filter(|id| *id >= self.next)
                .ok_or_else(|| err("BINANCE_TRADE_CURSOR"))?;
            if row["symbol"] != self.symbol
                || row["orderId"].as_u64() != Some(self.venue)
                || row["isBuyer"].as_bool() != Some(self.buyer)
            {
                return Err(err("BINANCE_TRADE_SCOPE"));
            }
            let qty = wire_decimal(&row["qty"])?;
            if qty.is_zero() {
                return Err(err("BINANCE_TRADE_QUANTITY"));
            }
            self.total += qty;
            self.next = id
                .checked_add(1)
                .ok_or_else(|| err("BINANCE_CURSOR_OVERFLOW"))?;
            self.rows.push(row.clone());
        }
        self.done = rows.len() < self.limit;
        if self.total > self.expected || (self.done && self.total != self.expected) {
            return Err(err("BINANCE_INCOMPLETE_TRADES"));
        }
        Ok(self.done)
    }
}

use crate::Config;
use onlyalpha_broker::{Fact, OrderView, Snapshot};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    time::OnlyTimestamp,
    value::{OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity},
};
pub(crate) fn ns(ms: &Value) -> Result<i64> {
    ms.as_i64()
        .filter(|n| *n >= 0)
        .and_then(|n| n.checked_mul(1_000_000))
        .ok_or_else(|| err("BINANCE_EVENT_TIME"))
}
fn id(n: &str) -> Value {
    json!({"schema_version":1,"value":n})
}
fn decimal_value(n: &BigDecimal) -> Result<onlyalpha_domain::numeric::OnlyDecimal> {
    n.normalized()
        .to_plain_string()
        .parse()
        .map_err(|_| err("BINANCE_DECIMAL"))
}
/// REST 和执行回报中的订单数量、原始委托价及限价有效期。成交价由 trade_fact 独立处理。
pub(crate) fn check_order_terms(
    wire: &BTreeMap<String, String>,
    quantity: &Value,
    price: &Value,
    tif: &Value,
) -> Result<()> {
    let requested = wire["quantity"]
        .parse::<BigDecimal>()
        .map_err(|_| err("BINANCE_QUANTITY"))?;
    if wire_decimal(quantity)? != requested {
        return Err(err("BINANCE_ORDER_IDENTITY"));
    }
    let reported_price = wire_decimal(price)?;
    let matches = if let Some(limit) = wire.get("price") {
        let requested_price = limit
            .parse::<BigDecimal>()
            .map_err(|_| err("BINANCE_PRICE"))?;
        reported_price == requested_price
            && tif.as_str() == wire.get("timeInForce").map(String::as_str)
    } else {
        reported_price.is_zero()
    };
    if !matches {
        return Err(err("BINANCE_ORDER_IDENTITY"));
    }
    Ok(())
}
pub(crate) fn order_view(
    original: &BrokerCommand,
    venue: Option<u64>,
    clients: &[String],
    raw: &Value,
) -> Result<OrderView> {
    let cmd = original.record();
    let r = &cmd["request"];
    let wire = submit_params(original)?;
    let num = raw["orderId"]
        .as_u64()
        .ok_or_else(|| err("BINANCE_ORDER_ID"))?;
    if venue.is_some_and(|v| v != num)
        || !clients.iter().any(|c| raw["clientOrderId"] == *c)
        || raw["symbol"] != wire["symbol"]
        || raw["side"] != r["side"]
        || raw["type"] != r["order_type"]
    {
        return Err(err("BINANCE_ORDER_IDENTITY"));
    }
    check_order_terms(&wire, &raw["origQty"], &raw["price"], &raw["timeInForce"])?;
    ns(&raw["updateTime"])?;
    let status = match raw["status"].as_str() {
        Some("NEW") => "ACCEPTED",
        Some("PARTIALLY_FILLED") => "PARTIALLY_FILLED",
        Some("FILLED") => "FILLED",
        Some("CANCELED") => "CANCELLED",
        Some("REJECTED") => "REJECTED",
        Some("EXPIRED" | "EXPIRED_IN_MATCH") => "EXPIRED",
        _ => return Err(err("BINANCE_ORDER_STATE")),
    };
    OrderView::decode(
        &json!({"scope":original.scope().record(),"order":original.order(),"client":original.client(),"venue":venue_id(&wire["symbol"],num)?,"request":r,"filled":wire_decimal(&raw["executedQty"])?.normalized().to_plain_string(),"status":status}),
    )
}
pub(crate) struct Provenance<'a> {
    pub session: &'a str,
    pub received: i64,
    pub source: &'a str,
}
impl Provenance<'_> {
    pub(crate) fn fact(
        &self,
        scope: &onlyalpha_broker::Scope,
        correlation: &str,
        kind: &str,
        event_ns: i64,
        payload: Value,
    ) -> Result<Fact> {
        let mut flags = vec!["PROVIDER_SEQUENCE_UNAVAILABLE"];
        if event_ns > self.received {
            flags.push("PROVIDER_CLOCK_AHEAD");
        }
        let update = onlyalpha_broker::digest(&json!([kind, correlation, event_ns, payload]));
        Fact::decode(
            &json!({"scope":scope.record(),"session":self.session,"update_id":update,"source_sequence":null,"ts_event":event_ns,"ts_init":self.received.max(event_ns),"correlation":correlation,"causation":self.source,"quality":flags,"kind":kind,"payload":payload}),
        )
    }
}
pub(crate) fn order_fact(
    c: &BrokerCommand,
    num: u64,
    status: &str,
    event: i64,
    prov: &Provenance<'_>,
    reason: &str,
) -> Result<Fact> {
    let mut p = json!({"order":c.order(),"venue":venue_id(&symbol(c)?,num)?});
    if status != "ACCEPTED" {
        p["reason"] = json!(reason);
    }
    prov.fact(c.scope(), c.client(), status, event, p)
}
pub(crate) fn trade_fact(c: &BrokerCommand, row: &Value, prov: &Provenance<'_>) -> Result<Fact> {
    let s = symbol(c)?;
    let num = row["orderId"]
        .as_u64()
        .ok_or_else(|| err("BINANCE_ORDER_ID"))?;
    let trade = row["id"].as_u64().ok_or_else(|| err("BINANCE_TRADE_ID"))?;
    if row["symbol"] != s
        || row["isBuyer"].as_bool() != Some(c.record()["request"]["side"] == "BUY")
    {
        return Err(err("BINANCE_TRADE_SCOPE"));
    }
    let t = ns(&row["time"])?;
    let maker = row["isMaker"]
        .as_bool()
        .ok_or_else(|| err("BINANCE_TRADE_MAKER"))?;
    let qty = decimal_value(&wire_decimal(&row["qty"])?)?;
    let price = decimal_value(&wire_decimal(&row["price"])?)?;
    let qty = OnlyQuantity::new(qty.clone(), qty.fractional_precision().max(0) as u8)
        .map_err(|_| err("BINANCE_QUANTITY"))?;
    let price = OnlyPrice::new(price.clone(), price.fractional_precision().max(0) as u8)
        .map_err(|_| err("BINANCE_PRICE"))?;
    let trade_key = venue_id(&s, trade)?;
    let fill = json!({"schema_version":1,"trade_id":id(&trade_key),"order_id":id(c.order()),"price":price.to_record(),"quantity":qty.to_record(),
        "ts_event":OnlyTimestamp::from_unix_nanos(t.into()).to_record(),"ts_init":OnlyTimestamp::from_unix_nanos(prov.received.max(t).into()).to_record(),
        "venue_trade_id":id(&trade_key),"venue_order_id":id(&venue_id(&s,num)?),"liquidity_side":if maker{"MAKER"}else{"TAKER"},"external_sequence":trade,"external_event_id":format!("binance-trade:{s}:{trade}"),"metadata":{},"reference_price":null});
    prov.fact(
        c.scope(),
        c.client(),
        "TRADE",
        t,
        json!({"order":c.order(),"fill":fill}),
    )
}
pub(crate) fn balances(
    c: &Config,
    rows: &Value,
    observed: i64,
    stream: bool,
) -> Result<Vec<Snapshot>> {
    let mut balances = BTreeMap::new();
    for row in rows.as_array().ok_or_else(|| err("BINANCE_BALANCES"))? {
        let (asset, free, locked) = if stream {
            ("a", "f", "l")
        } else {
            ("asset", "free", "locked")
        };
        let code = row[asset].as_str().ok_or_else(|| err("BINANCE_CURRENCY"))?;
        let currency = c
            .currencies
            .get(code)
            .ok_or_else(|| err("BINANCE_UNRESOLVED_CURRENCY"))?;
        let money = |v: &Value| -> Result<OnlyMoney> {
            OnlyMoney::new(decimal_value(&wire_decimal(v)?)?, currency.clone())
                .map_err(|_| err("BINANCE_MONEY"))
        };
        let free = money(&row[free])?;
        let reserved = money(&row[locked])?;
        let total = free
            .checked_add(&reserved)
            .map_err(|_| err("BINANCE_MONEY"))?;
        let snapshot = Snapshot::decode(
            &json!({"scope":c.scope.record(),"kind":"BALANCE","source_sequence":0,"snapshot_time":observed,"payload":{"currency":currency.to_record(),"ledger_cash":total.to_record(),"trade_available_cash":free.to_record(),"order_reserved_cash":reserved.to_record()}}),
        )?;
        if balances.insert(code, snapshot).is_some() {
            return Err(err("BINANCE_DUPLICATE_BALANCE"));
        }
    }
    Ok(balances.into_values().collect())
}
pub(crate) fn fee_evidence(
    c: &BrokerCommand,
    row: &Value,
    currencies: &BTreeMap<String, OnlyCurrency>,
) -> Result<Value> {
    let code = row["commissionAsset"]
        .as_str()
        .ok_or_else(|| err("BINANCE_FEE_CURRENCY"))?;
    let cur = currencies
        .get(code)
        .ok_or_else(|| err("BINANCE_FEE_CURRENCY"))?;
    let amount = OnlyMoney::new(
        decimal_value(&wire_decimal(&row["commission"])?)?,
        cur.clone(),
    )
    .map_err(|_| err("BINANCE_MONEY"))?;
    let id = venue_id(
        &symbol(c)?,
        row["id"].as_u64().ok_or_else(|| err("BINANCE_TRADE_ID"))?,
    )?;
    let s = c.scope().record();
    let reference = format!("binance-trade:{id}:commission");
    let scope = json!({"kind":"TRADE","id":id,"broker":s["gateway"],"account":s["account"],"currency":cur.code()});
    let evidence_id =
        onlyalpha_broker::digest(&json!([s, scope, reference, 1, amount.to_record()]));
    Ok(
        json!({"id":evidence_id,"reference":reference,"revision":1,"supersedes":null,"scope":scope,"mode":"COMMISSION_ONLY","complete":true,"components":[],"total":amount.to_record()["amount"]}),
    )
}
