use bigdecimal::{BigDecimal as D, Zero};
use num_bigint::BigInt;
use onlyalpha_domain::{
    base::OnlyDomainModel,
    identifiers::{OnlyIdentifier, OnlyInstrumentId},
    numeric::OnlyDecimal,
    time::OnlyTradingDay,
};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fmt,
    str::FromStr,
};
pub(crate) type Decimal = D;
pub(crate) const MAX_COMMANDS: usize = 4096;
pub(crate) const MAX_CHECKPOINT: usize = 32 * 1024 * 1024;
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Error(pub String);
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for Error {}
impl From<onlyalpha_domain::errors::OnlyDomainError> for Error {
    fn from(e: onlyalpha_domain::errors::OnlyDomainError) -> Self {
        Self(e.to_string())
    }
}
impl From<serde_json::Error> for Error {
    fn from(e: serde_json::Error) -> Self {
        Self(e.to_string())
    }
}
pub(crate) fn err(s: &str) -> Error {
    Error(s.into())
}
pub fn digest(b: &[u8]) -> String {
    Sha256::digest(b)
        .iter()
        .map(|x| format!("{x:02x}"))
        .collect()
}
pub(crate) fn hash(v: &Value) -> String {
    digest(v.to_string().as_bytes())
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Status {
    Applied,
    Duplicate,
    Conflict,
    Stale,
}
#[derive(Debug, Clone)]
pub struct Outcome {
    pub status: Status,
    pub fact: Option<Value>,
}
pub(crate) fn outcome(status: Status) -> Outcome {
    Outcome { status, fact: None }
}
pub(crate) fn row<'a>(v: &'a Value, fields: &[&str]) -> Result<&'a Map<String, Value>, Error> {
    let r = v.as_object().ok_or_else(|| err("LEDGER_RECORD_REQUIRED"))?;
    if r.get("schema_version").and_then(Value::as_u64) != Some(1)
        || r.len() != fields.len() + 1
        || fields.iter().any(|f| !r.contains_key(*f))
    {
        return Err(err("LEDGER_FIELDS_INVALID"));
    }
    Ok(r)
}
pub(crate) fn text(v: &Value) -> Result<&str, Error> {
    v.as_str()
        .filter(|s| !s.is_empty() && s.len() <= 256)
        .ok_or_else(|| err("LEDGER_TEXT_INVALID"))
}
pub(crate) fn id(v: &Value) -> Result<String, Error> {
    let s = text(v)?;
    if OnlyIdentifier::new(s)?.value() != s {
        return Err(err("LEDGER_ID_NONCANONICAL"));
    }
    Ok(s.into())
}
pub(crate) fn fingerprint(v: &Value) -> Result<(), Error> {
    let s = text(v)?;
    if s.len() != 64
        || !s
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(err("LEDGER_FINGERPRINT_INVALID"));
    }
    Ok(())
}
pub(crate) fn uint(v: &Value) -> Result<u64, Error> {
    v.as_u64().ok_or_else(|| err("LEDGER_UNSIGNED_REQUIRED"))
}
pub(crate) fn boolean(v: &Value) -> Result<bool, Error> {
    v.as_bool().ok_or_else(|| err("LEDGER_BOOL_REQUIRED"))
}
pub(crate) fn time(v: &Value) -> Result<BigInt, Error> {
    let s = v.to_string();
    if !v.is_number() || s.len() > 40 {
        return Err(err("LEDGER_TIME_INVALID"));
    }
    s.parse().map_err(|_| err("LEDGER_TIME_INVALID"))
}
pub(crate) fn money(v: &Value, p: u8) -> Result<D, Error> {
    let s = text(v)?;
    let n: OnlyDecimal = s.parse()?;
    let d = D::from_str(&n.to_string()).map_err(|_| err("LEDGER_DECIMAL_INVALID"))?;
    let (_, scale) = d.as_bigint_and_exponent();
    if scale > i64::from(p) || scale < -64 {
        return Err(err("LEDGER_MONEY_BOUND_OR_PRECISION"));
    }
    let canonical = d.with_scale(i64::from(p));
    if canonical
        .as_bigint_and_exponent()
        .0
        .to_string()
        .trim_start_matches('-')
        .len()
        > 128
    {
        return Err(err("LEDGER_MONEY_BOUND_OR_PRECISION"));
    }
    Ok(canonical)
}
pub(crate) fn nonnegative(v: &Value, p: u8) -> Result<D, Error> {
    let n = money(v, p)?;
    if n < D::zero() {
        return Err(err("LEDGER_NEGATIVE_AMOUNT"));
    }
    Ok(n)
}
pub(crate) fn formatted(d: &D, p: u8) -> String {
    d.with_scale(i64::from(p)).to_plain_string()
}
pub(crate) fn key(family: &str, id: &str) -> String {
    json!([family, id]).to_string()
}
#[derive(Clone)]
pub(crate) struct Reservation {
    pub order: String,
    pub original: D,
    pub consumed: D,
    pub remaining: D,
    pub released: D,
    pub sent: bool,
    pub acknowledged: bool,
    pub unknown: bool,
    pub cancel_pending: bool,
    pub terminal_outcome: Option<String>,
}
impl Reservation {
    pub fn record(&self, p: u8) -> Value {
        json!({"order":self.order,"original":formatted(&self.original,p),"consumed":formatted(&self.consumed,p),"remaining":formatted(&self.remaining,p),"released":formatted(&self.released,p),"sent":self.sent,"acknowledged":self.acknowledged,"unknown":self.unknown,"cancel_pending":self.cancel_pending,"terminal_outcome":self.terminal_outcome})
    }
}

pub(crate) fn decimal(v: &Value) -> Result<D, Error> {
    let d = money(v, 18)?;
    Ok(d.normalized())
}
pub(crate) fn positive(v: &Value) -> Result<D, Error> {
    let d = decimal(v)?;
    if d <= D::zero() {
        return Err(err("LEDGER_POSITIVE_REQUIRED"));
    }
    Ok(d)
}
pub(crate) fn instrument(v: &Value) -> Result<String, Error> {
    let s = text(v)?;
    if OnlyInstrumentId::from_str(s)?.to_string() != s {
        return Err(err("LEDGER_INSTRUMENT_INVALID"));
    }
    Ok(s.into())
}
pub(crate) fn day(v: &Value) -> Result<(), Error> {
    OnlyTradingDay::from_record(&json!({"schema_version":1,"value":v}))?;
    Ok(())
}
#[derive(Clone)]
pub(crate) struct Allocation {
    pub quantity: D,
    pub cost: D,
    pub realized: D,
    pub version: u64,
    pub evidence: String,
}
impl Allocation {
    pub fn empty() -> Self {
        Self {
            quantity: D::zero(),
            cost: D::zero(),
            realized: D::zero(),
            version: 0,
            evidence: String::new(),
        }
    }
    pub fn record(&self, p: u8) -> Value {
        json!({"schema_version":1,"quantity":self.quantity.normalized().to_plain_string(),"cost":formatted(&self.cost,p),"realized":formatted(&self.realized,p),"version":self.version})
    }
}
#[derive(Clone)]
pub(crate) struct Line {
    pub allocation: Allocation,
    pub mark: D,
    pub multiplier: D,
    pub market: D,
    pub unrealized: D,
}
impl Line {
    pub fn record(&self, p: u8) -> Value {
        json!({"allocation":self.allocation.record(p),"allocation_evidence":self.allocation.evidence,"mark":self.mark.normalized().to_plain_string(),"multiplier":self.multiplier.normalized().to_plain_string(),"market_value":formatted(&self.market,p),"unrealized":formatted(&self.unrealized,p)})
    }
}
#[derive(Clone)]
pub(crate) struct Ledger {
    pub initial: D,
    pub cash: D,
    pub external: D,
    pub external_occurred: bool,
    pub day_flow_occurred: bool,
    pub realized: D,
    pub fees: D,
    pub lifecycle: String,
    pub flags: BTreeSet<String>,
    pub reservations: BTreeMap<String, Reservation>,
    pub lines: BTreeMap<String, Line>,
    pub economic_version: u64,
    pub valuation_version: u64,
    pub trade_sequence: Option<u64>,
    pub high_water: D,
    pub max_drawdown: D,
    pub day_start: D,
    pub day_external: D,
    pub entries: Vec<Value>,
    pub fee_entries: Vec<Value>,
}
impl Ledger {
    pub fn new(initial: D, p: u8) -> Self {
        Self {
            cash: initial.clone(),
            high_water: initial.clone(),
            day_start: initial.clone(),
            entries: vec![
                json!({"kind":"INITIAL_ALLOCATION","amount":formatted(&initial,p),"sequence":0,"affects_cash":true}),
            ],
            initial,
            external: D::zero(),
            external_occurred: false,
            day_flow_occurred: false,
            realized: D::zero(),
            fees: D::zero(),
            lifecycle: "CREATED".into(),
            flags: BTreeSet::new(),
            reservations: BTreeMap::new(),
            lines: BTreeMap::new(),
            economic_version: 0,
            valuation_version: 0,
            trade_sequence: None,
            max_drawdown: D::zero(),
            day_external: D::zero(),
            fee_entries: vec![],
        }
    }
    pub fn reserved(&self) -> D {
        self.reservations
            .values()
            .map(|r| r.remaining.clone())
            .sum()
    }
    pub fn available(&self) -> D {
        &self.cash - self.reserved()
    }
    pub fn cost(&self) -> D {
        self.lines.values().map(|l| l.allocation.cost.clone()).sum()
    }
    pub fn market(&self) -> D {
        self.lines.values().map(|l| l.market.clone()).sum()
    }
    pub fn unrealized(&self) -> D {
        self.lines.values().map(|l| l.unrealized.clone()).sum()
    }
    pub fn equity(&self) -> D {
        &self.cash + self.market()
    }
    pub fn pnl_equity(&self) -> D {
        &self.initial + &self.external + &self.realized + self.unrealized() - &self.fees
    }
    pub fn status(&self) -> &str {
        if self.lifecycle == "CLOSED" {
            "CLOSED"
        } else if !self.flags.is_empty() {
            "RECONCILING"
        } else {
            &self.lifecycle
        }
    }
    pub fn ready(&self) -> bool {
        self.status() == "ACTIVE"
    }
    pub fn ratio(n: D, d: &D) -> Option<String> {
        if d <= &D::zero() {
            None
        } else {
            Some(
                (n / d)
                    .with_scale_round(8, bigdecimal::RoundingMode::HalfEven)
                    .to_plain_string(),
            )
        }
    }
    pub fn drawdown(&self) -> D {
        if self.high_water > D::zero() {
            (&self.equity() / &self.high_water - D::from(1))
                .with_scale_round(8, bigdecimal::RoundingMode::HalfEven)
        } else {
            D::zero()
        }
    }
    pub fn refresh(&mut self) {
        if self.equity() != self.pnl_equity() {
            self.flags.insert("EQUITY_VIEW_MISMATCH".into());
        } else {
            self.flags.remove("EQUITY_VIEW_MISMATCH");
        }
        self.high_water = self.high_water.clone().max(self.equity());
        self.max_drawdown = self.max_drawdown.clone().min(self.drawdown());
    }
    pub fn validate(&self) -> Result<(), Error> {
        if self.cash < D::zero() || self.available() < D::zero() {
            return Err(err("LEDGER_CASH_CONSERVATION"));
        }
        if self.reservations.len() > 512 || self.lines.len() > 256 {
            return Err(err("LEDGER_RESOURCE_BOUND"));
        }
        for d in [
            &self.cash,
            &self.external,
            &self.realized,
            &self.fees,
            &self.high_water,
            &self.cost(),
            &self.market(),
            &self.unrealized(),
        ] {
            let (c, s) = d.as_bigint_and_exponent();
            if c.to_string().len() > 1024 || !(-512..=512).contains(&s) {
                return Err(err("LEDGER_ARITHMETIC_BOUND"));
            }
        }
        for r in self.reservations.values() {
            if r.original != &r.remaining + &r.consumed + &r.released
                || [&r.original, &r.remaining, &r.consumed, &r.released]
                    .iter()
                    .any(|v| *v < &D::zero())
            {
                return Err(err("LEDGER_RESERVATION_CONSERVATION"));
            }
        }
        Ok(())
    }
    pub fn snapshot(&self, p: u8) -> Value {
        let daily = self.equity() - &self.day_start - (&self.external - &self.day_external);
        json!({"status":self.status(),"lifecycle":self.lifecycle,"flags":self.flags,"initial_capital":formatted(&self.initial,p),"cash":formatted(&self.cash,p),"external_cash_flow":formatted(&self.external,p),"reserved":formatted(&self.reserved(),p),"available":formatted(&self.available(),p),"position_cost":formatted(&self.cost(),p),"market_value":formatted(&self.market(),p),"realized_pnl":formatted(&self.realized,p),"unrealized_pnl":formatted(&self.unrealized(),p),"fees":formatted(&self.fees,p),"equity":formatted(&self.equity(),p),"pnl_equity":formatted(&self.pnl_equity(),p),"net_pnl":formatted(&(&self.realized+self.unrealized()-&self.fees),p),"simple_return":if self.external_occurred{None}else{Self::ratio(self.equity()-&self.initial,&self.initial)},"high_water_mark":formatted(&self.high_water,p),"drawdown":formatted(&self.drawdown(),8),"maximum_drawdown":formatted(&self.max_drawdown,8),"day_start_equity":formatted(&self.day_start,p),"daily_pnl":formatted(&daily,p),"daily_return":if self.day_flow_occurred{None}else{Self::ratio(daily,&self.day_start)},"economic_version":self.economic_version,"valuation_version":self.valuation_version,"trade_sequence":self.trade_sequence})
    }
    pub fn record(&self, p: u8) -> Value {
        json!({"snapshot":self.snapshot(p),"reservations":self.reservations.iter().map(|(k,v)|(k.clone(),v.record(p))).collect::<BTreeMap<_,_>>(),"lines":self.lines.iter().map(|(k,v)|(k.clone(),v.record(p))).collect::<BTreeMap<_,_>>(),"external_occurred":self.external_occurred,"day_flow_occurred":self.day_flow_occurred,"day_external":formatted(&self.day_external,p),"entries":self.entries,"fee_entries":self.fee_entries})
    }
}
pub(crate) fn normalize_allocation(v: &Value, p: u8) -> Result<Value, Error> {
    let mut r = row(v, &["quantity", "cost", "realized", "version"])?.clone();
    let q = decimal(&r["quantity"])?;
    let c = nonnegative(&r["cost"], p)?;
    if q < D::zero() || (q == D::zero() && c != D::zero()) {
        return Err(err("LEDGER_ALLOCATION_QUANTITY_COST"));
    }
    r.insert("quantity".into(), json!(q.to_plain_string()));
    r.insert("cost".into(), json!(formatted(&c, p)));
    r.insert(
        "realized".into(),
        json!(formatted(&money(&r["realized"], p)?, p)),
    );
    uint(&r["version"])?;
    Ok(Value::Object(r))
}
pub(crate) fn normalize_line(v: &Value) -> Result<Value, Error> {
    let mut r = row(
        v,
        &[
            "instrument",
            "allocation_version",
            "allocation_evidence",
            "mark",
            "multiplier",
        ],
    )?
    .clone();
    instrument(&r["instrument"])?;
    uint(&r["allocation_version"])?;
    fingerprint(&r["allocation_evidence"])?;
    for k in ["mark", "multiplier"] {
        r.insert(k.into(), json!(positive(&r[k])?.to_plain_string()));
    }
    Ok(Value::Object(r))
}
pub(crate) fn normalize(op: &str, v: &Value, p: u8) -> Result<Value, Error> {
    let (fields, amounts, ids): (&[&str], &[&str], &[&str]) = match op {
        "ACTIVATE" | "CLOSE" => (&[], &[], &[]),
        "RESERVE" => (
            &["reservation", "order", "amount"],
            &["amount"],
            &["reservation", "order"],
        ),
        "STAGE" => (&["reservation", "stage"], &[], &["reservation"]),
        "RELEASE" => (&["reservation", "outcome"], &[], &["reservation"]),
        "CASH_FLOW" => (
            &["cashflow", "source_fact", "amount"],
            &["amount"],
            &["cashflow", "source_fact"],
        ),
        "FEE" => (
            &[
                "fee_instruction",
                "source_fact",
                "order",
                "trade",
                "charges",
                "rebates",
            ],
            &["charges", "rebates"],
            &["fee_instruction", "source_fact", "order", "trade"],
        ),
        "TRADE" => (
            &[
                "trade",
                "execution",
                "venue_trade",
                "order",
                "fee_instruction",
                "source_sequence",
                "side",
                "instrument",
                "notional",
                "charges",
                "rebates",
                "reservation",
                "terminal_fill",
                "before",
                "after",
                "allocation_evidence",
                "mark",
                "multiplier",
            ],
            &["notional", "charges", "rebates"],
            &[
                "trade",
                "execution",
                "venue_trade",
                "order",
                "fee_instruction",
            ],
        ),
        "VALUATION" => (
            &["valuation", "economic_version", "version", "lines"],
            &[],
            &["valuation"],
        ),
        _ => return Err(err("LEDGER_OP_UNSUPPORTED")),
    };
    let mut r = row(v, fields)?.clone();
    for k in ids {
        id(&r[*k])?;
    }
    for k in amounts {
        r.insert((*k).into(), json!(formatted(&money(&r[*k], p)?, p)));
    }
    match op {
        "TRADE" => {
            uint(&r["source_sequence"])?;
            if !matches!(text(&r["side"])?, "BUY" | "SELL") {
                return Err(err("LEDGER_SIDE"));
            }
            for k in ["notional", "charges", "rebates"] {
                nonnegative(&r[k], p)?;
            }
            instrument(&r["instrument"])?;
            fingerprint(&r["allocation_evidence"])?;
            boolean(&r["terminal_fill"])?;
            if !r["reservation"].is_null() {
                id(&r["reservation"])?;
            }
            for k in ["before", "after"] {
                r.insert(k.into(), normalize_allocation(&r[k], p)?);
            }
            for k in ["mark", "multiplier"] {
                r.insert(k.into(), json!(positive(&r[k])?.to_plain_string()));
            }
        }
        "FEE" => {
            nonnegative(&r["charges"], p)?;
            nonnegative(&r["rebates"], p)?;
        }
        "RESERVE" => {
            nonnegative(&r["amount"], p)?;
        }
        "VALUATION" => {
            uint(&r["economic_version"])?;
            uint(&r["version"])?;
            let rows = r["lines"]
                .as_array()
                .filter(|a| a.len() <= 256)
                .ok_or_else(|| err("LEDGER_LINES_BOUND"))?;
            let mut lines = rows
                .iter()
                .map(normalize_line)
                .collect::<Result<Vec<_>, _>>()?;
            lines.sort_by(|a, b| a["instrument"].as_str().cmp(&b["instrument"].as_str()));
            r.insert("lines".into(), json!(lines));
        }
        _ => {}
    }
    Ok(Value::Object(r))
}
