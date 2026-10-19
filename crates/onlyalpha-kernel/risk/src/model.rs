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
pub(crate) const MAX_CHECKPOINT: usize = 32 * 1024 * 1024;
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Error(pub String);
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for Error {}
impl From<serde_json::Error> for Error {
    fn from(e: serde_json::Error) -> Self {
        Self(e.to_string())
    }
}
impl From<onlyalpha_domain::errors::OnlyDomainError> for Error {
    fn from(e: onlyalpha_domain::errors::OnlyDomainError) -> Self {
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
}
#[derive(Debug, Clone)]
pub struct Outcome {
    pub status: Status,
    pub decision: Option<Value>,
}
pub(crate) fn row<'a>(v: &'a Value, fields: &[&str]) -> Result<&'a Map<String, Value>, Error> {
    let m = v.as_object().ok_or_else(|| err("RISK_RECORD_REQUIRED"))?;
    if m.get("schema_version").and_then(Value::as_u64) != Some(1)
        || m.len() != fields.len() + 1
        || fields.iter().any(|f| !m.contains_key(*f))
    {
        return Err(err("RISK_FIELDS_INVALID"));
    }
    Ok(m)
}
pub(crate) fn text(v: &Value) -> Result<&str, Error> {
    v.as_str()
        .filter(|s| !s.is_empty() && s.len() <= 256)
        .ok_or_else(|| err("RISK_TEXT_INVALID"))
}
pub(crate) fn id(v: &Value) -> Result<String, Error> {
    let s = text(v)?;
    if OnlyIdentifier::new(s)?.value() != s {
        return Err(err("RISK_ID_NONCANONICAL"));
    }
    Ok(s.into())
}
pub(crate) fn fp(v: &Value) -> Result<(), Error> {
    let s = text(v)?;
    if s.len() != 64
        || !s
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(err("RISK_DIGEST_INVALID"));
    }
    Ok(())
}
pub(crate) fn uint(v: &Value) -> Result<u64, Error> {
    v.as_u64().ok_or_else(|| err("RISK_UNSIGNED_REQUIRED"))
}
pub(crate) fn boolean(v: &Value) -> Result<bool, Error> {
    v.as_bool().ok_or_else(|| err("RISK_BOOL_REQUIRED"))
}
pub(crate) fn time(v: &Value) -> Result<BigInt, Error> {
    let s = v.to_string();
    if !v.is_number() || s.len() > 40 {
        return Err(err("RISK_TIME_INVALID"));
    }
    s.parse().map_err(|_| err("RISK_TIME_INVALID"))
}
pub(crate) fn dec(v: &Value, p: u8) -> Result<D, Error> {
    let raw = text(v)?;
    let parsed: OnlyDecimal = raw.parse()?;
    let n = D::from_str(&parsed.to_string()).map_err(|_| err("RISK_DECIMAL_INVALID"))?;
    let (coefficient, scale) = n.as_bigint_and_exponent();
    // Plain normalized identity expands a negative scale into integer zeros.
    // Bound that same representation before admitting values to its own reader.
    let plain_digits =
        coefficient.to_string().len() as u64 + if scale < 0 { scale.unsigned_abs() } else { 0 };
    if scale > i64::from(p) || scale < -64 || plain_digits > 128 {
        return Err(err("RISK_DECIMAL_BOUND"));
    }
    if n < D::zero() {
        return Err(err("RISK_NEGATIVE_VALUE"));
    }
    Ok(n)
}
pub(crate) fn norm(n: &D) -> String {
    n.normalized().to_plain_string()
}
pub(crate) fn money(n: &D, p: u8) -> String {
    n.with_scale(i64::from(p)).to_plain_string()
}
pub(crate) fn instrument(v: &Value) -> Result<String, Error> {
    let s = text(v)?;
    if OnlyInstrumentId::from_str(s)?.to_string() != s {
        return Err(err("RISK_INSTRUMENT_NONCANONICAL"));
    }
    Ok(s.into())
}
pub(crate) fn key(family: &str, id: &str) -> String {
    json!([family, id]).to_string()
}
pub(crate) fn scope(s: &str) -> Result<u8, Error> {
    match s {
        "SYSTEM" => Ok(0),
        "RUNTIME" => Ok(1),
        "ACCOUNT" => Ok(2),
        "INSTRUMENT" => Ok(3),
        "CLUSTER" => Ok(4),
        _ => Err(err("RISK_SCOPE_INVALID")),
    }
}
#[derive(Clone)]
pub(crate) struct Rule {
    pub id: String,
    pub scope: String,
    pub order: u64,
    pub observing: bool,
    pub kind: String,
    pub limit: D,
}
#[derive(Clone)]
pub(crate) struct Profile {
    pub revision: String,
    pub instruments: BTreeSet<String>,
    pub rules: Vec<Rule>,
}
pub(crate) fn config(v: &Value) -> Result<(u8, BTreeMap<String, Profile>), Error> {
    let r = row(
        v,
        &[
            "engine",
            "runtime",
            "account",
            "generation",
            "runtime_kind",
            "currency",
            "clusters",
            "admission_limits",
        ],
    )?;
    for k in ["engine", "runtime", "account", "generation"] {
        id(&r[k])?;
    }
    if !matches!(text(&r["runtime_kind"])?, "BACKTEST" | "SIM" | "LIVE") {
        return Err(err("RISK_RUNTIME_KIND"));
    }
    let currency = OnlyCurrency::from_record(&r["currency"])?;
    if currency.to_record() != r["currency"] {
        return Err(err("RISK_CURRENCY_NONCANONICAL"));
    }
    let limits = row(
        &r["admission_limits"],
        &[
            "commands",
            "journal_bytes",
            "checkpoint_bytes",
            "reservations",
        ],
    )?;
    for (field, maximum) in [
        ("commands", MAX_COMMANDS as u64),
        ("reservations", 1024),
        ("journal_bytes", 8 * 1024 * 1024),
        ("checkpoint_bytes", MAX_CHECKPOINT as u64),
    ] {
        let value = uint(&limits[field])?;
        if value == 0 || value > maximum {
            return Err(err("RISK_ADMISSION_LIMIT_INVALID"));
        }
    }
    let p = currency.precision();
    let cs = r["clusters"]
        .as_object()
        .filter(|m| !m.is_empty() && m.len() <= 64)
        .ok_or_else(|| err("RISK_CLUSTER_BOUND"))?;
    let mut profiles = BTreeMap::new();
    for (c, v) in cs {
        id(&json!(c))?;
        let x = row(v, &["revision", "instruments", "rules"])?;
        let revision = id(&x["revision"])?;
        let instruments = x["instruments"]
            .as_array()
            .filter(|a| !a.is_empty() && a.len() <= 256)
            .ok_or_else(|| err("RISK_INSTRUMENT_BOUND"))?;
        let mut allowed = BTreeSet::new();
        for i in instruments {
            if !allowed.insert(instrument(i)?) {
                return Err(err("RISK_DUPLICATE_INSTRUMENT"));
            }
        }
        let rules = x["rules"]
            .as_array()
            .filter(|a| a.len() <= 64)
            .ok_or_else(|| err("RISK_RULE_BOUND"))?;
        let mut ids = BTreeSet::new();
        let mut rs = vec![];
        for rv in rules {
            let rr = row(rv, &["id", "scope", "order", "mode", "kind", "limit"])?;
            let rid = id(&rr["id"])?;
            let sc = text(&rr["scope"])?;
            scope(sc)?;
            if sc == "SYSTEM" || rid.starts_with("system.") || !ids.insert(rid.clone()) {
                return Err(err("RISK_MANDATORY_OR_DUPLICATE_RULE"));
            }
            let mode = text(&rr["mode"])?;
            if !matches!(mode, "ENFORCING" | "OBSERVING") {
                return Err(err("RISK_RULE_MODE"));
            }
            let kind = text(&rr["kind"])?;
            if !matches!(
                kind,
                "MAX_ACTIVE_ORDERS"
                    | "MAX_ORDER_QUANTITY"
                    | "MAX_ORDER_NOTIONAL"
                    | "MAX_RESERVED_NOTIONAL"
            ) {
                return Err(err("RISK_RULE_KIND"));
            }
            let precision = if kind == "MAX_ACTIVE_ORDERS" {
                0
            } else if kind == "MAX_ORDER_QUANTITY" {
                18
            } else {
                p
            };
            rs.push(Rule {
                id: rid,
                scope: sc.into(),
                order: uint(&rr["order"])?,
                observing: mode == "OBSERVING",
                kind: kind.into(),
                limit: dec(&rr["limit"], precision)?,
            });
        }
        rs.sort_by_key(|r| (scope(&r.scope).unwrap_or(5), r.order, r.id.clone()));
        profiles.insert(
            c.clone(),
            Profile {
                revision,
                instruments: allowed,
                rules: rs,
            },
        );
    }
    Ok((p, profiles))
}
#[derive(Clone)]
pub(crate) struct Hold {
    pub cluster: String,
    pub request: String,
    pub instrument: String,
    pub side: String,
    pub position_side: String,
    pub position_mode: String,
    pub increasing: bool,
    pub quantity: D,
    pub notional: D,
    pub fee: D,
    pub cash_requirement: D,
    pub consumed_quantity: D,
    pub consumed_notional: D,
    pub released_quantity: D,
    pub released_notional: D,
    pub state: String,
    pub sent: bool,
    pub unknown: bool,
    pub acknowledged: bool,
    pub cancel_pending: bool,
    pub terminal: Option<String>,
}
impl Hold {
    pub fn remaining_quantity(&self) -> D {
        &self.quantity - &self.consumed_quantity - &self.released_quantity
    }
    pub fn remaining_notional(&self) -> D {
        &self.notional - &self.consumed_notional - &self.released_notional
    }
    pub fn cash(&self) -> D {
        if self.increasing && self.state == "ACTIVE" {
            &self.cash_requirement + &self.fee
        } else {
            D::zero()
        }
    }
    pub fn record(&self, p: u8) -> Value {
        json!({"cluster":self.cluster,"request":self.request,"instrument":self.instrument,"side":self.side,"position_side":self.position_side,"position_mode":self.position_mode,"increasing":self.increasing,"original_quantity":norm(&self.quantity),"original_notional":money(&self.notional,p),"fee_envelope":money(&self.fee,p),"cash_requirement":money(&self.cash_requirement,p),"consumed_quantity":norm(&self.consumed_quantity),"consumed_notional":money(&self.consumed_notional,p),"released_quantity":norm(&self.released_quantity),"released_notional":money(&self.released_notional,p),"remaining_quantity":norm(&self.remaining_quantity()),"remaining_notional":money(&self.remaining_notional(),p),"cash_hold":money(&self.cash(),p),"state":self.state,"sent":self.sent,"unknown":self.unknown,"acknowledged":self.acknowledged,"cancel_pending":self.cancel_pending,"terminal":self.terminal})
    }
}
