use bigdecimal::{BigDecimal, Zero};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    execution::{OnlyCancelOrderRequest, OnlyOrderFill, OnlyOrderRequest},
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{collections::BTreeSet, fmt, str::FromStr};
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Error(String);
impl Error {
    pub fn new(code: &str) -> Self {
        Self(code.into())
    }
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(f)
    }
}
impl std::error::Error for Error {}
impl From<serde_json::Error> for Error {
    fn from(_: serde_json::Error) -> Self {
        Self::new("BROKER_JSON")
    }
}
pub(crate) fn err(code: &str) -> Error {
    Error::new(code)
}
fn sha(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
pub fn digest(v: &Value) -> String {
    sha(v.to_string().as_bytes())
}
pub(crate) fn text(v: &Value) -> Result<&str, Error> {
    v.as_str().ok_or_else(|| err("BROKER_STRING"))
}
pub(crate) fn id(v: &Value) -> Result<&str, Error> {
    let s = text(v)?;
    if s.is_empty() || s.len() > 512 || s.chars().any(|c| c.is_control() || c.is_whitespace()) {
        return Err(err("BROKER_ID"));
    }
    Ok(s)
}
pub(crate) fn fp(v: &Value) -> Result<&str, Error> {
    let s = text(v)?;
    if s.len() != 64
        || !s
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(err("BROKER_DIGEST"));
    }
    Ok(s)
}
pub(crate) fn row(v: &Value, fields: &[&str]) -> Result<(), Error> {
    let o = v.as_object().ok_or_else(|| err("BROKER_OBJECT"))?;
    if o.len() != fields.len() || fields.iter().any(|f| !o.contains_key(*f)) {
        return Err(err("BROKER_FIELDS"));
    }
    Ok(())
}
fn integer(v: &Value, nonnegative: bool) -> Result<bigdecimal::num_bigint::BigInt, Error> {
    let text = v
        .as_number()
        .ok_or_else(|| err("BROKER_INTEGER"))?
        .to_string();
    if text.len() > 4096
        || !text
            .bytes()
            .enumerate()
            .all(|(i, b)| b.is_ascii_digit() || (i == 0 && b == b'-'))
    {
        return Err(err("BROKER_INTEGER"));
    }
    let n = bigdecimal::num_bigint::BigInt::from_str(&text).map_err(|_| err("BROKER_INTEGER"))?;
    if nonnegative && n < bigdecimal::num_bigint::BigInt::from(0) {
        return Err(err("BROKER_NEGATIVE_SEQUENCE"));
    }
    Ok(n)
}
pub(crate) fn decimal(v: &Value) -> Result<BigDecimal, Error> {
    let s = text(v)?;
    if s.is_empty() || s.len() > 128 || s.contains(['e', 'E', '+']) {
        return Err(err("BROKER_DECIMAL"));
    }
    let n = BigDecimal::from_str(s).map_err(|_| err("BROKER_DECIMAL"))?;
    if n < BigDecimal::zero() {
        return Err(err("BROKER_DECIMAL"));
    }
    Ok(n)
}
pub(crate) fn bounded(v: &Value) -> Result<(), Error> {
    match v {
        Value::String(s) if s.len() > 4096 => return Err(err("BROKER_STRING_BOUND")),
        Value::Object(o) => {
            if let Some(n) = o.get("value").filter(|_| o.contains_key("precision")) {
                decimal(n)?;
            }
            for x in o.values() {
                bounded(x)?;
            }
        }
        Value::Array(a) => {
            if a.len() > 4096 {
                return Err(err("BROKER_ARRAY_BOUND"));
            }
            for x in a {
                bounded(x)?;
            }
        }
        _ => (),
    }
    Ok(())
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Scope(Value);
impl Scope {
    pub fn decode(v: &Value) -> Result<Self, Error> {
        row(
            v,
            &[
                "engine",
                "runtime",
                "gateway",
                "account",
                "generation",
                "runtime_kind",
            ],
        )?;
        for k in ["engine", "runtime", "gateway", "account"] {
            id(&v[k])?;
        }
        fp(&v["generation"])?;
        if !matches!(text(&v["runtime_kind"])?, "BACKTEST" | "SIM" | "LIVE") {
            return Err(err("BROKER_RUNTIME_KIND"));
        }
        Ok(Self(v.clone()))
    }
    pub fn record(&self) -> Value {
        self.0.clone()
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Operation {
    Submit,
    Cancel,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BrokerCommand {
    pub(crate) value: Value,
    pub(crate) scope: Scope,
    pub(crate) operation: Operation,
}
impl BrokerCommand {
    pub fn decode(v: &Value) -> Result<Self, Error> {
        row(
            v,
            &[
                "schema_version",
                "scope",
                "operation",
                "command_id",
                "order",
                "client",
                "request",
            ],
        )?;
        if v["schema_version"] != 1 {
            return Err(err("BROKER_VERSION"));
        }
        bounded(v)?;
        let scope = Scope::decode(&v["scope"])?;
        for k in ["command_id", "order", "client"] {
            id(&v[k])?;
        }
        let operation = match text(&v["operation"])? {
            "SUBMIT" => Operation::Submit,
            "CANCEL" => Operation::Cancel,
            _ => return Err(err("BROKER_OPERATION")),
        };
        match operation {
            Operation::Submit => {
                if v["request"]["execution_intent"].is_null() {
                    return Err(err("BROKER_EXPLICIT_INTENT_REQUIRED"));
                }
                let request = OnlyOrderRequest::from_record(&v["request"])
                    .map_err(|_| err("BROKER_REQUEST"))?;
                if request.to_record() != v["request"]
                    || v["request"]["account_id"]["value"] != v["scope"]["account"]
                {
                    return Err(err("BROKER_REQUEST_SCOPE"));
                }
            }
            Operation::Cancel => {
                let request = OnlyCancelOrderRequest::from_record(&v["request"])
                    .map_err(|_| err("BROKER_CANCEL"))?;
                if request.to_record() != v["request"]
                    || v["request"]["order_id"]["value"] != v["order"]
                {
                    return Err(err("BROKER_REQUEST_ORDER"));
                }
            }
        }
        Ok(Self {
            value: v.clone(),
            scope,
            operation,
        })
    }
    pub fn record(&self) -> Value {
        self.value.clone()
    }
    pub fn scope(&self) -> &Scope {
        &self.scope
    }
    pub fn operation(&self) -> Operation {
        self.operation
    }
    pub fn id(&self) -> &str {
        self.value["command_id"].as_str().expect("validated")
    }
    pub fn order(&self) -> &str {
        self.value["order"].as_str().expect("validated")
    }
    pub fn client(&self) -> &str {
        self.value["client"].as_str().expect("validated")
    }
}
/// An immutable semantic comparison view, excluding transport sessions, observation times and fees.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OrderView(Value);
impl OrderView {
    pub fn decode(v: &Value) -> Result<Self, Error> {
        row(
            v,
            &[
                "scope", "order", "client", "venue", "request", "filled", "status",
            ],
        )?;
        Scope::decode(&v["scope"])?;
        for k in ["order", "client", "venue"] {
            id(&v[k])?;
        }
        bounded(v)?;
        let r = OnlyOrderRequest::from_record(&v["request"])
            .map_err(|_| err("BROKER_ORDER_REQUEST"))?;
        if r.to_record() != v["request"]
            || v["request"]["account_id"]["value"] != v["scope"]["account"]
        {
            return Err(err("BROKER_ORDER_SCOPE"));
        }
        let filled = decimal(&v["filled"])?;
        let quantity = decimal(&v["request"]["quantity"]["value"])?;
        let status = text(&v["status"])?;
        if filled > quantity
            || !matches!(
                status,
                "ACCEPTED" | "PARTIALLY_FILLED" | "FILLED" | "CANCELLED" | "REJECTED" | "EXPIRED"
            )
            || (status == "FILLED" && filled != quantity)
            || (status == "ACCEPTED" && !filled.is_zero())
            || (status == "PARTIALLY_FILLED" && (filled.is_zero() || filled == quantity))
        {
            return Err(err("BROKER_ORDER_STATE"));
        }
        Ok(Self(v.clone()))
    }
    pub fn record(&self) -> Value {
        self.0.clone()
    }
    pub(crate) fn matches(&self, c: &BrokerCommand) -> bool {
        self.0["scope"] == c.value["scope"]
            && self.0["order"] == c.value["order"]
            && self.0["client"] == c.value["client"]
            && (c.operation == Operation::Cancel || self.0["request"] == c.value["request"])
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Fact {
    pub(crate) value: Value,
    pub(crate) identity: String,
    pub(crate) fingerprint: String,
}
impl Fact {
    pub fn decode(v: &Value) -> Result<Self, Error> {
        row(
            v,
            &[
                "scope",
                "session",
                "update_id",
                "source_sequence",
                "ts_event",
                "ts_init",
                "correlation",
                "causation",
                "quality",
                "kind",
                "payload",
            ],
        )?;
        bounded(v)?;
        let scope = Scope::decode(&v["scope"])?;
        for k in ["session", "update_id", "correlation", "causation"] {
            id(&v[k])?;
        }
        if !v["source_sequence"].is_null() {
            integer(&v["source_sequence"], true)?;
        }
        if integer(&v["ts_event"], false)? > integer(&v["ts_init"], false)? {
            return Err(err("BROKER_PROVENANCE"));
        }
        let q = v["quality"]
            .as_array()
            .ok_or_else(|| err("BROKER_QUALITY"))?;
        let flags = q.iter().map(id).collect::<Result<BTreeSet<_>, _>>()?;
        if flags.len() != q.len()
            || (v["source_sequence"].is_null() && !flags.contains("PROVIDER_SEQUENCE_UNAVAILABLE"))
        {
            return Err(err("BROKER_SOURCE_SEQUENCE"));
        }
        let kind = text(&v["kind"])?;
        let p = &v["payload"];
        let s = scope.record();
        let root = json!({"schema_version":2,"runtime_id":s["runtime"],"gateway_id":s["gateway"],"account_id":s["account"]});
        let mut payload = root.clone();
        let mut parts = vec![
            "2".to_string(),
            text(&s["runtime"])?.into(),
            text(&s["gateway"])?.into(),
            text(&s["account"])?.into(),
        ];
        let prefix = match kind {
            "ACCEPTED" => {
                row(p, &["order", "venue"])?;
                id(&p["order"])?;
                id(&p["venue"])?;
                parts.extend([
                    text(&p["order"])?.into(),
                    text(&p["venue"])?.into(),
                    "ACCEPTED".into(),
                ]);
                payload["order_id"] = p["order"].clone();
                payload["venue_order_id"] = p["venue"].clone();
                payload["semantic_type"] = json!("ACCEPTED");
                "EACK-"
            }
            "CANCELLED" | "REJECTED" | "EXPIRED" => {
                row(p, &["order", "venue", "reason"])?;
                id(&p["order"])?;
                if !p["venue"].is_null() {
                    id(&p["venue"])?;
                }
                text(&p["reason"])?;
                if kind != "REJECTED" && p["reason"] != "" {
                    return Err(err("BROKER_TERMINAL_REASON"));
                }
                parts.extend([
                    text(&p["order"])?.into(),
                    p["venue"].as_str().unwrap_or("").into(),
                    kind.into(),
                ]);
                payload["order_id"] = p["order"].clone();
                payload["venue_order_id"] = p["venue"].clone();
                payload["terminal_status"] = json!(kind);
                payload["terminal_reason"] = p["reason"].clone();
                "ETERM-"
            }
            "TRADE" => {
                row(p, &["order", "fill"])?;
                id(&p["order"])?;
                let f = &p["fill"];
                let fill = OnlyOrderFill::from_record(f).map_err(|_| err("BROKER_FILL"))?;
                if fill.to_record() != *f || f["order_id"]["value"] != p["order"] {
                    return Err(err("BROKER_FILL_SCOPE"));
                }
                let trade = text(&f["trade_id"]["value"])?;
                let venue_trade = f["venue_trade_id"]["value"].as_str();
                parts.extend([
                    text(&p["order"])?.into(),
                    if venue_trade.is_some() {
                        "VENUE_TRADE_ID"
                    } else {
                        "TRADE_ID"
                    }
                    .into(),
                    venue_trade.unwrap_or(trade).into(),
                ]);
                for (k, x) in [
                    ("order_id", p["order"].clone()),
                    ("trade_id", json!(trade)),
                    ("venue_order_id", f["venue_order_id"]["value"].clone()),
                    ("venue_trade_id", f["venue_trade_id"]["value"].clone()),
                    ("liquidity_side", f["liquidity_side"].clone()),
                    ("trade_event_time", f["ts_event"]["unix_nanos"].clone()),
                    ("price", f["price"]["value"].clone()),
                    ("price_precision", f["price"]["precision"].clone()),
                    ("quantity", f["quantity"]["value"].clone()),
                    ("quantity_precision", f["quantity"]["precision"].clone()),
                    ("reference_price", f["reference_price"]["value"].clone()),
                    (
                        "reference_price_precision",
                        f["reference_price"]["precision"].clone(),
                    ),
                ] {
                    payload[k] = x;
                }
                "EFILL-"
            }
            "CONNECTION" => {
                row(p, &["state"])?;
                if !matches!(
                    text(&p["state"])?,
                    "DISCONNECTED"
                        | "CONNECTING"
                        | "CONNECTED"
                        | "AUTHENTICATING"
                        | "READY"
                        | "RECONNECTING"
                        | "FAILED"
                ) {
                    return Err(err("BROKER_CONNECTION"));
                }
                return Self::observation(v);
            }
            "ACCOUNT" | "POSITION" => {
                let snapshot = Snapshot::decode(p)?;
                if snapshot.0["scope"] != v["scope"] || snapshot.0["kind"] != v["kind"] {
                    return Err(err("BROKER_SNAPSHOT_SCOPE"));
                }
                return Self::observation(v);
            }
            "BALANCES" => {
                let a = p
                    .as_array()
                    .filter(|a| !a.is_empty())
                    .ok_or_else(|| err("BROKER_BALANCES"))?;
                let mut previous = String::new();
                for item in a {
                    let snapshot = Snapshot::decode(item)?;
                    let code = text(&item["payload"]["currency"]["code"])?;
                    if snapshot.0["scope"] != v["scope"]
                        || snapshot.0["kind"] != "BALANCE"
                        || code <= previous.as_str()
                    {
                        return Err(err("BROKER_BALANCES_ORDER"));
                    }
                    previous = code.into();
                }
                return Self::observation(v);
            }
            _ => return Err(err("BROKER_FACT_KIND")),
        };
        let identity = format!("{prefix}{}", sha(parts.join("\u{1f}").as_bytes()));
        Ok(Self {
            value: v.clone(),
            identity,
            fingerprint: digest(&payload),
        })
    }
    fn observation(v: &Value) -> Result<Self, Error> {
        let identity = format!(
            "BOBS-{}",
            digest(&json!([v["scope"], v["session"], v["update_id"]]))
        );
        let fingerprint = digest(&json!([
            v["scope"],
            v["kind"],
            v["payload"],
            v["source_sequence"],
            v["ts_event"]
        ]));
        Ok(Self {
            value: v.clone(),
            identity,
            fingerprint,
        })
    }
    pub fn record(&self) -> Value {
        self.value.clone()
    }
    pub fn identity(&self) -> &str {
        &self.identity
    }
    pub fn fingerprint(&self) -> &str {
        &self.fingerprint
    }
    pub fn scope(&self) -> Scope {
        Scope::decode(&self.value["scope"]).expect("validated")
    }
    pub fn order(&self) -> Option<&str> {
        self.value["payload"]["order"].as_str()
    }
}

/// Validated normalized query observation. It never acts as an Account/Position manager.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Snapshot(Value);
impl Snapshot {
    pub fn decode(v: &Value) -> Result<Self, Error> {
        row(
            v,
            &[
                "scope",
                "kind",
                "source_sequence",
                "snapshot_time",
                "payload",
            ],
        )?;
        Scope::decode(&v["scope"])?;
        bounded(v)?;
        integer(&v["source_sequence"], true)?;
        integer(&v["snapshot_time"], false)?;
        let p = &v["payload"];
        match text(&v["kind"])? {
            "ACCOUNT" | "BALANCE" => {
                let fields = if v["kind"] == "ACCOUNT" {
                    vec![
                        "currency",
                        "ledger_cash",
                        "trade_available_cash",
                        "order_reserved_cash",
                        "equity",
                    ]
                } else {
                    vec![
                        "currency",
                        "ledger_cash",
                        "trade_available_cash",
                        "order_reserved_cash",
                    ]
                };
                row(p, &fields)?;
                use onlyalpha_domain::value::{OnlyCurrency, OnlyMoney};
                let currency = OnlyCurrency::from_record(&p["currency"])
                    .map_err(|_| err("BROKER_CURRENCY"))?;
                if currency.to_record() != p["currency"] {
                    return Err(err("BROKER_CURRENCY"));
                }
                for f in fields.iter().filter(|f| **f != "currency") {
                    let amount = text(&p[*f]["amount"])?;
                    if amount.len() > 128 || amount.contains(['e', 'E', '+']) {
                        return Err(err("BROKER_MONEY_BOUND"));
                    }
                    let money = OnlyMoney::from_record(&p[*f]).map_err(|_| err("BROKER_MONEY"))?;
                    if money.to_record() != p[*f] || p[*f]["currency"] != p["currency"] {
                        return Err(err("BROKER_MONEY_CURRENCY"));
                    }
                }
            }
            "POSITION" => {
                row(
                    p,
                    &[
                        "instrument",
                        "side",
                        "quantity",
                        "available",
                        "frozen",
                        "average_price",
                    ],
                )?;
                use onlyalpha_domain::{
                    identifiers::OnlyInstrumentId,
                    value::{OnlyPrice, OnlyQuantity},
                };
                let instrument = OnlyInstrumentId::from_record(&p["instrument"])
                    .map_err(|_| err("BROKER_INSTRUMENT"))?;
                if instrument.to_record() != p["instrument"]
                    || !matches!(text(&p["side"])?, "LONG" | "SHORT")
                {
                    return Err(err("BROKER_POSITION_SCOPE"));
                }
                for f in ["quantity", "available", "frozen"] {
                    let q = OnlyQuantity::from_record(&p[f]).map_err(|_| err("BROKER_QUANTITY"))?;
                    if q.to_record() != p[f] || p[f]["precision"] != p["quantity"]["precision"] {
                        return Err(err("BROKER_QUANTITY_PRECISION"));
                    }
                }
                if decimal(&p["available"]["value"])? + decimal(&p["frozen"]["value"])?
                    > decimal(&p["quantity"]["value"])?
                {
                    return Err(err("BROKER_POSITION_QUANTITY"));
                }
                if !p["average_price"].is_null() {
                    let price = OnlyPrice::from_record(&p["average_price"])
                        .map_err(|_| err("BROKER_PRICE"))?;
                    if price.to_record() != p["average_price"] {
                        return Err(err("BROKER_PRICE"));
                    }
                }
            }
            _ => return Err(err("BROKER_SNAPSHOT_KIND")),
        }
        Ok(Self(v.clone()))
    }
    pub fn record(&self) -> Value {
        self.0.clone()
    }
}
