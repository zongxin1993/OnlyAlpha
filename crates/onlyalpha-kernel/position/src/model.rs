use bigdecimal::{BigDecimal as D, RoundingMode, Signed, Zero};
use num_bigint::BigInt;
use onlyalpha_domain::{
    base::OnlyDomainModel,
    identifiers::{OnlyIdentifier, OnlyInstrumentId},
    numeric::OnlyDecimal,
    value::{OnlyCurrency, OnlyMultiplier, OnlyPrice, OnlyQuantity},
};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, fmt, str::FromStr};
pub(crate) type Decimal = D;
pub(crate) const MAX_JOURNAL: usize = 4096;
pub(crate) const MAX_JOURNAL_BYTES: usize = 4 * 1024 * 1024;
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
pub fn digest(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
pub(crate) fn hash(v: &Value) -> String {
    digest(v.to_string().as_bytes())
}
pub(crate) fn row<'a>(v: &'a Value, fields: &[&str]) -> Result<&'a Map<String, Value>, Error> {
    let r = v
        .as_object()
        .ok_or_else(|| err("POSITION_RECORD_REQUIRED"))?;
    if r.get("schema_version").and_then(Value::as_u64) != Some(1)
        || r.len() != fields.len() + 1
        || fields.iter().any(|f| !r.contains_key(*f))
    {
        return Err(err("POSITION_FIELDS_INVALID"));
    }
    Ok(r)
}
pub(crate) fn text(v: &Value) -> Result<&str, Error> {
    v.as_str()
        .filter(|s| !s.is_empty() && s.len() <= 256)
        .ok_or_else(|| err("POSITION_TEXT_REQUIRED"))
}
pub(crate) fn id(v: &Value) -> Result<String, Error> {
    let s = text(v)?;
    if OnlyIdentifier::new(s)?.value() != s {
        return Err(err("POSITION_NONCANONICAL_ID"));
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
        return Err(err("POSITION_FINGERPRINT_INVALID"));
    }
    Ok(())
}
pub(crate) fn uint(v: &Value) -> Result<u64, Error> {
    v.as_u64()
        .ok_or_else(|| err("POSITION_UNSIGNED_INTEGER_REQUIRED"))
}
pub(crate) fn boolean(v: &Value) -> Result<bool, Error> {
    v.as_bool().ok_or_else(|| err("POSITION_BOOL_REQUIRED"))
}
pub(crate) fn time(v: &Value) -> Result<BigInt, Error> {
    let s = v.to_string();
    if !v.is_number() || s.len() > 40 {
        return Err(err("POSITION_TIME_INVALID"));
    }
    s.parse().map_err(|_| err("POSITION_TIME_INVALID"))
}
pub(crate) fn bounded(d: &D, input: bool) -> Result<(), Error> {
    let (n, s) = d.as_bigint_and_exponent();
    let (digits, scale) = if input { (128, 64) } else { (1024, 512) };
    if n.to_string().len() > digits || !(-scale..=scale).contains(&s) {
        return Err(err("POSITION_ARITHMETIC_BOUND"));
    }
    Ok(())
}
pub(crate) fn decimal(v: &Value) -> Result<D, Error> {
    let s = text(v)?;
    let canonical: OnlyDecimal = s.parse()?;
    let d = D::from_str(&canonical.to_string()).map_err(|_| err("POSITION_DECIMAL_INVALID"))?;
    bounded(&d, true)?;
    Ok(d)
}
pub(crate) fn positive(v: &Value) -> Result<D, Error> {
    let d = decimal(v)?;
    if d <= D::zero() {
        return Err(err("POSITION_POSITIVE_REQUIRED"));
    }
    Ok(d)
}
pub(crate) fn nonnegative(v: &Value) -> Result<D, Error> {
    let d = decimal(v)?;
    if d < D::zero() {
        return Err(err("POSITION_NONNEGATIVE_REQUIRED"));
    }
    Ok(d)
}
pub(crate) fn number(d: &D) -> String {
    d.normalized().to_string()
}
pub(crate) fn rounded(d: &D, p: u8) -> String {
    d.with_scale_round(i64::from(p), RoundingMode::HalfEven)
        .to_plain_string()
}
/// Exact rational with a single half-even rounding at the target scale.
pub(crate) fn ratio(n: &D, d: &D, scale: i64) -> Result<D, Error> {
    bounded(n, false)?;
    bounded(d, false)?;
    if n.is_negative() || d <= &D::zero() {
        return Err(err("POSITION_RATIO_INVALID"));
    }
    let (mut a, sa) = n.as_bigint_and_exponent();
    let (mut b, sb) = d.as_bigint_and_exponent();
    let shift = scale + sb - sa;
    if !(-2048..=2048).contains(&shift) {
        return Err(err("POSITION_RATIO_BOUND"));
    }
    if shift >= 0 {
        a *= BigInt::from(10).pow(shift as u32);
    } else {
        b *= BigInt::from(10).pow((-shift) as u32);
    }
    let (mut q, r) = (&a / &b, &a % &b);
    if &r * 2 > b || (&r * 2 == b && &q % 2 != BigInt::from(0)) {
        q += 1;
    }
    Ok(D::new(q, scale))
}
pub(crate) fn release_cost(cost: &D, qty: &D, fill: &D, qp: u8) -> Result<D, Error> {
    if fill == qty {
        return Ok(cost.clone());
    }
    let numerator = cost * fill;
    let (c, cs) = numerator.as_bigint_and_exponent();
    let (q, qs) = qty.as_bigint_and_exponent();
    let mut exp = c.to_string().len() as i64 - cs - q.to_string().len() as i64 + qs;
    let power = D::new(BigInt::from(1), -exp);
    if numerator < qty * &power {
        exp -= 1;
    }
    let digits = cost.as_bigint_and_exponent().0.to_string().len() as i64;
    let precision = 36.max(digits + 12).max(2 * i64::from(qp) + 18);
    ratio(&numerator, qty, precision - 1 - exp)
}
#[derive(Clone, Debug)]
pub(crate) struct Instrument {
    pub pp: u8,
    pub qp: u8,
    pub multiplier: D,
}
impl Instrument {
    pub fn price(&self, v: &Value) -> Result<D, Error> {
        let d = positive(v)?;
        OnlyPrice::new(d.to_string().parse()?, self.pp)?;
        Ok(d)
    }
    pub fn quantity(&self, v: &Value) -> Result<D, Error> {
        let d = positive(v)?;
        OnlyQuantity::new(d.to_string().parse()?, self.qp)?;
        Ok(d)
    }
}
pub(crate) fn instrument(v: &Value) -> Result<(String, Instrument), Error> {
    let r = row(
        v,
        &["id", "price_precision", "quantity_precision", "multiplier"],
    )?;
    let name = id(&r["id"])?;
    let parsed: OnlyInstrumentId = name.parse()?;
    if parsed.to_string() != name {
        return Err(err("POSITION_INSTRUMENT_NONCANONICAL"));
    }
    let pp = u8::try_from(uint(&r["price_precision"])?).map_err(|_| err("POSITION_PRECISION"))?;
    let qp =
        u8::try_from(uint(&r["quantity_precision"])?).map_err(|_| err("POSITION_PRECISION"))?;
    if pp > 18 || qp > 18 {
        return Err(err("POSITION_PRECISION"));
    }
    let multiplier = positive(&r["multiplier"])?;
    OnlyMultiplier::new(multiplier.to_string().parse()?, 18)?;
    Ok((name, Instrument { pp, qp, multiplier }))
}
pub(crate) fn currency(v: &Value) -> Result<OnlyCurrency, Error> {
    let c = OnlyCurrency::from_record(v)?;
    if c.to_record() != *v {
        return Err(err("POSITION_CURRENCY_NONCANONICAL"));
    }
    Ok(c)
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Status {
    Applied,
    Duplicate,
    Conflict,
    Stale,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Outcome {
    pub status: Status,
    pub fact: Option<Value>,
}
#[derive(Clone, Debug)]
pub(crate) struct Book {
    pub id: String,
    pub qty: D,
    pub settled: D,
    pub cost: D,
    pub realized: D,
    pub fees: D,
    pub cycle: u64,
    pub version: u64,
    pub opened: BigInt,
    pub updated: BigInt,
    pub closed: Option<BigInt>,
}
impl Book {
    pub fn new(key: &Value, cycle: u64, at: &BigInt) -> Self {
        Self {
            id: format!("POS-{}", hash(&json!([key, cycle]))),
            qty: D::zero(),
            settled: D::zero(),
            cost: D::zero(),
            realized: D::zero(),
            fees: D::zero(),
            cycle,
            version: 0,
            opened: at.clone(),
            updated: at.clone(),
            closed: None,
        }
    }
    pub fn record(&self, spec: &Instrument, available: D, blocked: bool) -> Result<Value, Error> {
        let average = if self.qty.is_zero() {
            Value::Null
        } else {
            json!(ratio(&self.cost, &self.qty, i64::from(spec.pp))?.to_plain_string())
        };
        Ok(
            json!({"id":self.id,"quantity":number(&self.qty),"settled":number(&self.settled),"unsettled":number(&(&self.qty-&self.settled)),"cost":number(&self.cost),"average":average,"realized_pnl":number(&self.realized),"fees":number(&self.fees),"cycle":self.cycle,"version":self.version,"opened":self.opened.to_string(),"updated":self.updated.to_string(),"closed":self.closed.as_ref().map(ToString::to_string),"status":if self.qty.is_zero(){"CLOSED"}else if blocked{"RECONCILING"}else{"OPEN"},"available":number(&available)}),
        )
    }
}
#[derive(Clone, Debug)]
pub(crate) struct Reservation {
    pub instrument: String,
    pub cluster: String,
    pub order: String,
    pub quantity: D,
    pub remaining: D,
    pub consumed: D,
    pub released: D,
    pub stage: String,
    pub acknowledged: bool,
    pub state: String,
    pub version: u64,
}
impl Reservation {
    pub fn local(&self) -> bool {
        !self.acknowledged
    }
    pub fn record(&self) -> Value {
        json!({"instrument":self.instrument,"cluster":self.cluster,"order":self.order,"quantity":number(&self.quantity),"remaining":number(&self.remaining),"consumed":number(&self.consumed),"released":number(&self.released),"stage":self.stage,"acknowledged":self.acknowledged,"state":self.state,"version":self.version})
    }
}
#[derive(Clone, Debug, Default)]
pub(crate) struct State {
    pub accounts: BTreeMap<String, Book>,
    pub allocations: BTreeMap<(String, String), Book>,
    pub history: Vec<Value>,
    pub reservations: BTreeMap<String, Reservation>,
    pub restrictions: BTreeMap<String, Value>,
    pub brokers: BTreeMap<String, Value>,
    pub stale: BTreeMap<String, Value>,
    pub watermarks: BTreeMap<String, (u64, BigInt, String)>,
    pub receipts: BTreeMap<String, String>,
    pub commands: BTreeMap<String, String>,
    pub journal: Vec<Value>,
    pub sequence: u64,
    pub now: BigInt,
}
