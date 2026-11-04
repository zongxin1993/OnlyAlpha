use bigdecimal::{BigDecimal, Zero};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    calendar::OnlyTradingCalendar,
    identifiers::OnlyIdentifier,
    time::{OnlyTimestamp, OnlyTradingDay},
    value::OnlyCurrency,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{fmt, str::FromStr};
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Error(pub String);
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for Error {}
pub(crate) fn err(s: &str) -> Error {
    Error(s.into())
}
pub(crate) fn external<T, E: fmt::Display>(v: Result<T, E>) -> Result<T, Error> {
    v.map_err(|e| Error(e.to_string()))
}
pub fn digest(v: &Value) -> String {
    Sha256::digest(v.to_string().as_bytes())
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
pub(crate) fn fields(v: &Value, keys: &[&str]) -> Result<(), Error> {
    let o = v.as_object().ok_or_else(|| err("SETTLEMENT_RECORD"))?;
    if o.len() != keys.len() || keys.iter().any(|k| !o.contains_key(*k)) {
        return Err(err("SETTLEMENT_FIELDS"));
    }
    Ok(())
}
pub(crate) fn text(v: &Value) -> Result<&str, Error> {
    v.as_str()
        .filter(|s| !s.trim().is_empty() && s.len() <= 256)
        .ok_or_else(|| err("SETTLEMENT_TEXT"))
}
pub(crate) fn id(v: &Value) -> Result<&str, Error> {
    let s = text(v)?;
    if external(OnlyIdentifier::new(s))?.value() != s {
        return Err(err("SETTLEMENT_NONCANONICAL_ID"));
    }
    Ok(s)
}
pub(crate) fn uint(v: &Value) -> Result<u64, Error> {
    v.as_u64().ok_or_else(|| err("SETTLEMENT_UNSIGNED"))
}
pub(crate) fn fingerprint(v: &Value) -> Result<(), Error> {
    let s = text(v)?;
    if s.len() != 64
        || !s
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(err("SETTLEMENT_FINGERPRINT"));
    }
    Ok(())
}
pub(crate) fn number(v: &Value) -> Result<BigDecimal, Error> {
    let s = text(v)?;
    let n = external(BigDecimal::from_str(s))?;
    let (c, e) = n.as_bigint_and_exponent();
    if c.to_string().len() > 128 || !(-64..=18).contains(&e) || n < BigDecimal::zero() {
        return Err(err("SETTLEMENT_DECIMAL"));
    }
    Ok(n)
}
pub(crate) fn money(v: &Value, p: u8) -> Result<Value, Error> {
    let n = number(v)?;
    let rounded = n.with_scale(i64::from(p));
    if n != rounded {
        return Err(err("SETTLEMENT_MONEY_PRECISION"));
    }
    Ok(json!(rounded.to_plain_string()))
}
pub(crate) fn currency(v: &Value) -> Result<u8, Error> {
    let c = external(OnlyCurrency::from_record(v))?;
    if c.to_record() != *v {
        return Err(err("SETTLEMENT_CURRENCY"));
    }
    Ok(c.precision())
}
pub(crate) fn day(v: &Value) -> Result<OnlyTradingDay, Error> {
    let d = external(OnlyTradingDay::from_record(
        &json!({"schema_version":1,"value":text(v)?}),
    ))?;
    if d.to_record()["value"] != *v {
        return Err(err("SETTLEMENT_DAY"));
    }
    Ok(d)
}
pub(crate) fn time(v: &Value) -> Result<OnlyTimestamp, Error> {
    if v.to_string().len() > 256 {
        return Err(err("SETTLEMENT_TIME_BOUND"));
    }
    external(OnlyTimestamp::from_record(
        &json!({"schema_version":1,"unix_nanos":v}),
    ))
}
pub(crate) const OWNER: [&str; 6] = [
    "engine",
    "runtime",
    "account",
    "gateway",
    "generation",
    "runtime_kind",
];
pub(crate) const AXES: [&str; 6] = [
    "asset_booked",
    "asset_trade_available",
    "cash_booked",
    "cash_trade_available",
    "cash_withdrawable",
    "legal_settled",
];
pub(crate) fn scope(v: &Value) -> Result<(), Error> {
    fields(
        v,
        &[
            "schema_version",
            "engine",
            "runtime",
            "account",
            "gateway",
            "generation",
            "runtime_kind",
            "cluster",
            "revision",
            "instrument",
            "request",
        ],
    )?;
    if v["schema_version"] != 1 {
        return Err(err("SETTLEMENT_SCHEMA"));
    }
    for k in OWNER
        .into_iter()
        .chain(["cluster", "revision", "instrument", "request"])
    {
        id(&v[k])?;
    }
    fingerprint(&v["generation"])?;
    if !matches!(text(&v["runtime_kind"])?, "BACKTEST" | "SIM" | "LIVE") {
        return Err(err("SETTLEMENT_RUNTIME_KIND"));
    }
    Ok(())
}
#[derive(Clone, Debug)]
pub struct Instruction {
    pub(crate) value: Value,
}
impl Instruction {
    pub fn record(&self) -> Value {
        self.value.clone()
    }
    pub fn id(&self) -> &str {
        self.value["id"].as_str().expect("compiled")
    }
}
#[derive(Clone, Debug)]
pub struct Maturity {
    pub(crate) value: Value,
}
impl Maturity {
    pub fn record(&self) -> Value {
        self.value.clone()
    }
}
/// Pure compiled-policy input. Producer authentication belongs to the owning Runtime adapter.
pub fn compile(mut v: Value) -> Result<Instruction, Error> {
    bounded(&v, 8192)?;
    fields(
        &v,
        &[
            "schema_version",
            "scope",
            "order",
            "trade",
            "currency",
            "side",
            "quantity",
            "gross_notional",
            "charges",
            "rebates",
            "trading_day",
            "time",
            "calendar",
            "policy",
            "position",
            "position_cycle",
            "allocation",
            "allocation_cycle",
            "provenance",
        ],
    )?;
    if v["schema_version"] != 1 {
        return Err(err("SETTLEMENT_SCHEMA"));
    }
    scope(&v["scope"])?;
    for k in ["order", "trade", "position", "allocation"] {
        id(&v[k])?;
    }
    for k in ["position_cycle", "allocation_cycle"] {
        if uint(&v[k])? == 0 {
            return Err(err("SETTLEMENT_CYCLE"));
        }
    }
    if !matches!(text(&v["side"])?, "BUY" | "SELL") {
        return Err(err("SETTLEMENT_SIDE"));
    }
    fields(
        &v["provenance"],
        &["reference", "fingerprint", "instruction"],
    )?;
    id(&v["provenance"]["instruction"])?;
    id(&v["provenance"]["reference"])?;
    fingerprint(&v["provenance"]["fingerprint"])?;
    let p = currency(&v["currency"])?;
    for k in ["gross_notional", "charges", "rebates"] {
        v[k] = money(&v[k], p)?;
    }
    let q = number(&v["quantity"])?;
    if q.is_zero() {
        return Err(err("SETTLEMENT_QUANTITY"));
    }
    v["quantity"] = json!(q.normalized().to_plain_string());
    v["time"] = time(&v["time"])?.to_record()["unix_nanos"].clone();
    let trade_day = day(&v["trading_day"])?;
    let calendar = external(OnlyTradingCalendar::from_record(&v["calendar"]))?;
    v["calendar"] = calendar.to_record();
    let instrument: onlyalpha_domain::identifiers::OnlyInstrumentId =
        external(text(&v["scope"]["instrument"])?.parse())?;
    if calendar.venue_id() != instrument.venue() {
        return Err(err("SETTLEMENT_CALENDAR_VENUE"));
    }

    if !calendar.is_effective_on(trade_day) || !calendar.is_trading_day(trade_day) {
        return Err(err("SETTLEMENT_CALENDAR_COVERAGE"));
    }
    let schedule = resolve_schedule(&v["calendar"], &v["policy"], text(&v["trading_day"])?)?;
    let net = if v["side"] == "SELL" {
        number(&v["gross_notional"])? - number(&v["charges"])? + number(&v["rebates"])?
    } else {
        -number(&v["gross_notional"])? - number(&v["charges"])? + number(&v["rebates"])?
    };
    let body = json!({"schema_version":1,"input":v,"schedule":schedule,"cash_flow":net.with_scale(i64::from(p)).to_plain_string()});
    let mut value = body.clone();
    value["id"] = json!(format!("SINS-{}", digest(&body)));
    bounded(&value, 10240)?;
    Ok(Instruction { value })
}

/// Resolve only from the supplied immutable Calendar and compiled policy.
pub fn resolve_schedule(
    calendar: &Value,
    policy: &Value,
    trading_day: &str,
) -> Result<Value, Error> {
    bounded(calendar, 8192)?;
    bounded(policy, 8192)?;
    let calendar = external(OnlyTradingCalendar::from_record(calendar))?;
    let trade_day = day(&json!(trading_day))?;
    if !calendar.is_effective_on(trade_day) || !calendar.is_trading_day(trade_day) {
        return Err(err("SETTLEMENT_CALENDAR_COVERAGE"));
    }
    fields(
        policy,
        &[
            "id",
            "version",
            "asset_booked",
            "asset_trade_available",
            "cash_booked",
            "cash_trade_available",
            "cash_withdrawable",
            "legal_settled",
        ],
    )?;
    id(&policy["id"])?;
    id(&policy["version"])?;
    let mut schedule = json!({});
    for k in AXES {
        let lag = uint(&policy[k])?;
        if lag > 4096 {
            return Err(err("SETTLEMENT_LAG_BOUND"));
        }
        let mut d = trade_day;
        let mut remaining = lag;
        let mut scanned = 0;
        while remaining > 0 {
            scanned += 1;
            if scanned > 36600 {
                return Err(err("SETTLEMENT_CALENDAR_SEARCH_BOUND"));
            }
            d = external(OnlyTradingDay::new(external(d.value().tomorrow())?))?;
            if !calendar.is_effective_on(d) {
                return Err(err("SETTLEMENT_CALENDAR_COVERAGE"));
            }
            if calendar.is_trading_day(d) {
                remaining -= 1;
            }
        }
        schedule[k] = d.to_record()["value"].clone();
    }
    Ok(schedule)
}
pub(crate) fn bounded(v: &Value, bytes: usize) -> Result<(), Error> {
    let mut pending = vec![(v, 0u8)];
    let mut nodes = 0usize;
    while let Some((v, depth)) = pending.pop() {
        nodes += 1;
        if depth > 48 || nodes > 2000000 {
            return Err(err("SETTLEMENT_STRUCTURE_BOUND"));
        }
        match v {
            Value::Array(a) => {
                if a.len() > 4096 {
                    return Err(err("SETTLEMENT_ARRAY_BOUND"));
                }
                pending.extend(a.iter().map(|v| (v, depth + 1)));
            }
            Value::Object(o) => {
                if o.len() > 4096 {
                    return Err(err("SETTLEMENT_OBJECT_BOUND"));
                }
                pending.extend(o.values().map(|v| (v, depth + 1)));
            }
            _ => {}
        }
    }
    if v.to_string().len() > bytes {
        return Err(err("SETTLEMENT_SIZE_BOUND"));
    }
    Ok(())
}

pub(crate) fn units(q: &Value, precision: u8) -> Result<u64, Error> {
    if precision > 18 {
        return Err(err("SETTLEMENT_QUANTITY_PRECISION"));
    }
    let n = number(q)? * BigDecimal::new(1.into(), -i64::from(precision));
    let whole = n.with_scale(0);
    if n != whole {
        return Err(err("SETTLEMENT_QUANTITY_PRECISION"));
    }
    external(whole.to_plain_string().parse::<u64>())
}
