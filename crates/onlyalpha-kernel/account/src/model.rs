use bigdecimal::{BigDecimal as D, Zero};
use num_bigint::BigInt;
use onlyalpha_domain::{
    base::OnlyDomainModel,
    identifiers::{OnlyIdentifier, OnlyInstrumentId},
    numeric::OnlyDecimal,
    value::OnlyCurrency,
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
pub(crate) const MAX_CHECKPOINT: usize = 16 * 1024 * 1024;
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
    let r = v
        .as_object()
        .ok_or_else(|| err("ACCOUNT_RECORD_REQUIRED"))?;
    if r.get("schema_version").and_then(Value::as_u64) != Some(1)
        || r.len() != fields.len() + 1
        || fields.iter().any(|f| !r.contains_key(*f))
    {
        return Err(err("ACCOUNT_FIELDS_INVALID"));
    }
    Ok(r)
}
pub(crate) fn text(v: &Value) -> Result<&str, Error> {
    v.as_str()
        .filter(|s| !s.is_empty() && s.len() <= 256)
        .ok_or_else(|| err("ACCOUNT_TEXT_INVALID"))
}
pub(crate) fn id(v: &Value) -> Result<String, Error> {
    let s = text(v)?;
    if OnlyIdentifier::new(s)?.value() != s {
        return Err(err("ACCOUNT_ID_NONCANONICAL"));
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
        return Err(err("ACCOUNT_FINGERPRINT_INVALID"));
    }
    Ok(())
}
pub(crate) fn uint(v: &Value) -> Result<u64, Error> {
    v.as_u64().ok_or_else(|| err("ACCOUNT_UNSIGNED_REQUIRED"))
}
pub(crate) fn boolean(v: &Value) -> Result<bool, Error> {
    v.as_bool().ok_or_else(|| err("ACCOUNT_BOOL_REQUIRED"))
}
pub(crate) fn time(v: &Value) -> Result<BigInt, Error> {
    let s = v.to_string();
    if !v.is_number() || s.len() > 40 {
        return Err(err("ACCOUNT_TIME_INVALID"));
    }
    s.parse().map_err(|_| err("ACCOUNT_TIME_INVALID"))
}
pub(crate) fn money(v: &Value, p: u8) -> Result<D, Error> {
    let s = text(v)?;
    let n: OnlyDecimal = s.parse()?;
    let d = D::from_str(&n.to_string()).map_err(|_| err("ACCOUNT_DECIMAL_INVALID"))?;
    let (_, scale) = d.as_bigint_and_exponent();
    if scale > i64::from(p) || scale < -64 {
        return Err(err("ACCOUNT_MONEY_BOUND_OR_PRECISION"));
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
        return Err(err("ACCOUNT_MONEY_BOUND_OR_PRECISION"));
    }
    Ok(canonical)
}
pub(crate) fn nonnegative(v: &Value, p: u8) -> Result<D, Error> {
    let n = money(v, p)?;
    if n < D::zero() {
        return Err(err("ACCOUNT_NEGATIVE_AMOUNT"));
    }
    Ok(n)
}
pub(crate) fn analytical(v: &Value) -> Result<D, Error> {
    let s = v
        .as_str()
        .filter(|s| s.len() <= 1100)
        .ok_or_else(|| err("ACCOUNT_ANALYTICAL_INPUT"))?;
    let raw = D::from_str(s).map_err(|_| err("ACCOUNT_ANALYTICAL_INPUT"))?;
    let (c, scale) = raw.as_bigint_and_exponent();
    if c.to_string().len() > 1024 || !(-512..=512).contains(&scale) {
        return Err(err("ACCOUNT_ANALYTICAL_BOUND"));
    }
    let n: OnlyDecimal = s.parse()?;
    let d = D::from_str(&n.to_string()).map_err(|_| err("ACCOUNT_ANALYTICAL_INPUT"))?;
    let (c, scale) = d.as_bigint_and_exponent();
    if c.to_string().len() > 1024 || !(-512..=512).contains(&scale) {
        return Err(err("ACCOUNT_ANALYTICAL_BOUND"));
    }
    if d.normalized().to_plain_string().len() > 1024 {
        return Err(err("ACCOUNT_ANALYTICAL_BOUND"));
    }
    Ok(d)
}
pub(crate) fn analytical_record(d: &D, p: u8) -> String {
    let scale = d.normalized().as_bigint_and_exponent().1.max(i64::from(p));
    d.with_scale(scale).to_plain_string()
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
#[derive(Clone)]
pub(crate) struct State {
    pub cash: D,
    pub realized: D,
    pub realized_rounding_adjustment: D,
    pub unrealized: D,
    pub fees: D,
    pub market_value: D,
    pub reservations: BTreeMap<String, Reservation>,
    pub receivables: BTreeMap<String, D>,
    pub receipts: BTreeMap<String, String>,
    pub semantic: BTreeMap<String, String>,
    pub journal: Vec<Value>,
    pub sequence: u64,
    pub economic_version: u64,
    pub valuation_version: u64,
    pub trade_sequence: Option<u64>,
    pub broker_sequence: Option<u64>,
    pub broker: Option<Value>,
    pub differences: Vec<String>,
    pub flags: BTreeSet<String>,
    pub now: Option<BigInt>,
    pub position_evidence: Option<String>,
}
impl State {
    pub fn new(cash: D) -> Self {
        Self {
            cash,
            realized: D::zero(),
            realized_rounding_adjustment: D::zero(),
            unrealized: D::zero(),
            fees: D::zero(),
            market_value: D::zero(),
            reservations: BTreeMap::new(),
            receivables: BTreeMap::new(),
            receipts: BTreeMap::new(),
            semantic: BTreeMap::new(),
            journal: vec![],
            sequence: 0,
            economic_version: 0,
            valuation_version: 0,
            trade_sequence: None,
            broker_sequence: None,
            broker: None,
            differences: vec![],
            flags: BTreeSet::new(),
            now: None,
            position_evidence: None,
        }
    }
    pub fn reserved(&self) -> D {
        self.reservations
            .values()
            .map(|r| r.remaining.clone())
            .sum()
    }
    pub fn unsettled(&self) -> D {
        self.receivables.values().cloned().sum()
    }
    pub fn available(&self) -> D {
        &self.cash - self.reserved()
    }
    pub fn withdrawable(&self) -> D {
        self.available() - self.unsettled()
    }
    pub fn validate(&self) -> Result<(), Error> {
        if self.cash < D::zero() || self.market_value < D::zero() || self.withdrawable() < D::zero()
        {
            return Err(err("ACCOUNT_CASH_CONSERVATION"));
        }
        for d in [
            &self.cash,
            &self.market_value,
            &self.realized,
            &self.realized_rounding_adjustment,
            &self.unrealized,
            &self.fees,
        ] {
            let (c, s) = d.as_bigint_and_exponent();
            if c.to_string().len() > 1024 || !(-512..=512).contains(&s) {
                return Err(err("ACCOUNT_ARITHMETIC_BOUND"));
            }
        }
        for r in self.reservations.values() {
            if r.original != &r.remaining + &r.consumed + &r.released
                || [&r.original, &r.remaining, &r.consumed, &r.released]
                    .iter()
                    .any(|v| *v < &D::zero())
            {
                return Err(err("ACCOUNT_RESERVATION_CONSERVATION"));
            }
        }
        Ok(())
    }
    pub fn validate_admission(&self) -> Result<(), Error> {
        if self.reservations.len() > 512
            || self.receivables.len() > 1024
            || self.semantic.len() > 8192
        {
            return Err(err("ACCOUNT_RESOURCE_BOUND"));
        }
        let mut families = BTreeMap::<String, usize>::new();
        for identity in self.semantic.keys() {
            let parts: Vec<String> = serde_json::from_str(identity)?;
            let count = families.entry(parts[0].clone()).or_default();
            *count += 1;
            if *count > 1024 {
                return Err(err("ACCOUNT_SEMANTIC_FAMILY_BOUND"));
            }
        }
        Ok(())
    }
    pub fn snapshot(&self, p: u8) -> Value {
        json!({"cash":formatted(&self.cash,p),"reserved":formatted(&self.reserved(),p),"unsettled":formatted(&self.unsettled(),p),"trade_available":formatted(&self.available(),p),"withdrawable":formatted(&self.withdrawable(),p),"market_value":formatted(&self.market_value,p),"equity":formatted(&(&self.cash+&self.market_value),p),"realized_pnl":analytical_record(&self.realized,p),"realized_rounding_adjustment":analytical_record(&self.realized_rounding_adjustment,p),"unrealized_pnl":analytical_record(&self.unrealized,p),"fees":formatted(&self.fees,p),"sequence":self.sequence,"economic_version":self.economic_version,"valuation_version":self.valuation_version,"trade_sequence":self.trade_sequence,"position_evidence":self.position_evidence,"status":if self.flags.is_empty(){"ACTIVE"}else{"RECONCILING"},"flags":self.flags,"time":self.now.as_ref().map(|t|serde_json::from_str::<Value>(&t.to_string()).expect("validated integer"))})
    }
}
pub(crate) fn validate_config(v: &Value) -> Result<u8, Error> {
    let r = row(
        v,
        &[
            "engine",
            "runtime",
            "account",
            "gateway",
            "generation",
            "account_type",
            "currency",
            "initial_cash",
        ],
    )?;
    for f in ["engine", "runtime", "account", "gateway", "generation"] {
        id(&r[f])?;
    }
    if text(&r["account_type"])? != "CASH" {
        return Err(err("ACCOUNT_UNSUPPORTED_TYPE"));
    }
    let c = OnlyCurrency::from_record(&r["currency"])?;
    if c.to_record() != r["currency"] {
        return Err(err("ACCOUNT_CURRENCY_NONCANONICAL"));
    }
    nonnegative(&r["initial_cash"], c.precision())?;
    Ok(c.precision())
}
pub(crate) fn normalize_payload(op: &str, v: &Value, p: u8) -> Result<Value, Error> {
    let (fields, amounts, ids): (&[&str], &[&str], &[&str]) = match op {
        "CASH_CHANGE" => (
            &["change", "kind", "amount", "source_fact"],
            &["amount"],
            &["change", "source_fact"],
        ),
        "RESERVE" => (
            &["reservation", "order", "amount"],
            &["amount"],
            &["reservation", "order"],
        ),
        "STAGE" => (&["reservation", "stage"], &[], &["reservation"]),
        "RELEASE" => (&["reservation", "outcome"], &[], &["reservation"]),
        "TRADE" => (
            &[
                "trade",
                "execution",
                "venue_trade",
                "order",
                "sequence",
                "side",
                "notional",
                "fee_instruction",
                "charges",
                "rebates",
                "realized_pnl_delta",
                "position_evidence",
                "market_value_delta",
                "unrealized_pnl",
                "realized_rounding_adjustment",
                "reservation",
                "terminal_fill",
                "cash_withdrawable",
            ],
            &[
                "notional",
                "charges",
                "rebates",
                "realized_pnl_delta",
                "market_value_delta",
                "unrealized_pnl",
                "realized_rounding_adjustment",
            ],
            &[
                "trade",
                "execution",
                "venue_trade",
                "order",
                "fee_instruction",
            ],
        ),
        "ECONOMIC" => (
            &["cashflow", "kind", "amount", "source_fact", "instrument"],
            &["amount"],
            &["cashflow", "source_fact"],
        ),
        "SETTLE" => (
            &["instruction", "source_trade", "amount"],
            &["amount"],
            &["instruction", "source_trade"],
        ),
        "VALUATION" => (
            &[
                "valuation",
                "version",
                "economic_version",
                "position_evidence",
                "market_value",
                "unrealized_pnl",
                "realized_rounding_adjustment",
            ],
            &["market_value", "unrealized_pnl"],
            &["valuation"],
        ),
        "BROKER" => (
            &[
                "snapshot",
                "sequence",
                "basis_sequence",
                "quality",
                "cash",
                "reserved",
                "trade_available",
                "withdrawable",
                "equity",
            ],
            &[
                "cash",
                "reserved",
                "trade_available",
                "withdrawable",
                "equity",
            ],
            &["snapshot"],
        ),
        _ => return Err(err("ACCOUNT_OP_UNSUPPORTED")),
    };
    let mut r = row(v, fields)?.clone();
    for f in ids {
        id(&r[*f])?;
    }
    for f in amounts {
        let n = if matches!(
            *f,
            "realized_pnl_delta" | "unrealized_pnl" | "realized_rounding_adjustment"
        ) {
            analytical(&r[*f])?
        } else {
            money(&r[*f], p)?
        };
        r.insert(
            (*f).into(),
            json!(if matches!(
                *f,
                "realized_pnl_delta" | "unrealized_pnl" | "realized_rounding_adjustment"
            ) {
                analytical_record(&n, p)
            } else {
                formatted(&n, p)
            }),
        );
    }
    if matches!(op, "TRADE" | "VALUATION") {
        let value = analytical(&r["realized_rounding_adjustment"])?;
        r.insert(
            "realized_rounding_adjustment".into(),
            json!(analytical_record(&value, p)),
        );
    }
    match op {
        "TRADE" => {
            uint(&r["sequence"])?;
            for f in ["notional", "charges", "rebates"] {
                nonnegative(&r[f], p)?;
            }
            if !matches!(text(&r["side"])?, "BUY" | "SELL") {
                return Err(err("ACCOUNT_TRADE_SIDE"));
            }
            fingerprint(&r["position_evidence"])?;
            boolean(&r["terminal_fill"])?;
            boolean(&r["cash_withdrawable"])?;
            if !r["reservation"].is_null() {
                id(&r["reservation"])?;
            }
        }
        "ECONOMIC" => {
            let s = text(&r["instrument"])?;
            if OnlyInstrumentId::from_str(s)?.to_string() != s {
                return Err(err("ACCOUNT_INSTRUMENT_INVALID"));
            }
        }
        "VALUATION" => {
            uint(&r["version"])?;
            uint(&r["economic_version"])?;
            fingerprint(&r["position_evidence"])?;
        }
        "BROKER" => {
            uint(&r["sequence"])?;
            uint(&r["basis_sequence"])?;
            if !matches!(text(&r["quality"])?, "VERIFIED" | "UNAVAILABLE" | "UNKNOWN") {
                return Err(err("ACCOUNT_BROKER_QUALITY"));
            }
        }
        _ => {}
    }
    Ok(Value::Object(r))
}

pub(crate) fn checkpoint_row<'a>(
    v: &'a Value,
    fields: &[&str],
) -> Result<&'a serde_json::Map<String, Value>, Error> {
    let r = v
        .as_object()
        .ok_or_else(|| err("COMPONENT_CHECKPOINT_RECORD"))?;
    if r.get("schema_version").and_then(Value::as_u64) != Some(2)
        || r.len() != fields.len() + 1
        || fields.iter().any(|f| !r.contains_key(*f))
    {
        return Err(err("COMPONENT_CHECKPOINT_SCHEMA"));
    }
    Ok(r)
}

#[cfg(test)]
mod analytical_boundary_tests {
    #[test]
    fn extreme_exponent_is_rejected_before_domain_arithmetic() {
        let result = std::panic::catch_unwind(|| {
            super::analytical(&serde_json::json!("1E+9223372036854775807"))
        });
        assert!(result.is_ok());
        assert!(result.unwrap().is_err());
    }
}
