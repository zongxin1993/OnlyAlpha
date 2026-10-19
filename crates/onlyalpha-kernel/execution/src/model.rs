use bigdecimal::{BigDecimal, Zero};
use onlyalpha_domain::{identifiers::OnlyIdentifier, numeric::OnlyDecimal};
use serde_json::{Map, Value, json};
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
pub(crate) fn boundary<T, E: fmt::Display>(r: Result<T, E>) -> Result<T, Error> {
    r.map_err(|e| Error(e.to_string()))
}
pub fn digest(b: &[u8]) -> String {
    Sha256::digest(b)
        .iter()
        .map(|v| format!("{v:02x}"))
        .collect()
}
pub(crate) fn hash(v: &Value) -> String {
    digest(v.to_string().as_bytes())
}
pub(crate) fn row<'a>(v: &'a Value, fields: &[&str]) -> Result<&'a Map<String, Value>, Error> {
    let r = v.as_object().ok_or_else(|| err("EXECUTION_RECORD"))?;
    if r.get("schema_version").and_then(Value::as_u64) != Some(1)
        || r.len() != fields.len() + 1
        || fields.iter().any(|f| !r.contains_key(*f))
    {
        return Err(err("EXECUTION_FIELDS"));
    }
    Ok(r)
}
pub(crate) fn text(v: &Value) -> Result<&str, Error> {
    v.as_str()
        .filter(|s| !s.is_empty() && s.len() <= 256)
        .ok_or_else(|| err("EXECUTION_TEXT"))
}
pub(crate) fn id(v: &Value) -> Result<&str, Error> {
    let s = text(v)?;
    if OnlyIdentifier::new(s)?.value() != s {
        return Err(err("EXECUTION_ID"));
    }
    Ok(s)
}
pub(crate) fn uint(v: &Value) -> Result<u64, Error> {
    v.as_u64().ok_or_else(|| err("EXECUTION_UNSIGNED"))
}
pub(crate) fn fp(v: &Value) -> Result<(), Error> {
    let s = text(v)?;
    if s.len() != 64
        || !s
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(err("EXECUTION_DIGEST"));
    }
    Ok(())
}
pub(crate) fn dec(v: &Value) -> Result<BigDecimal, Error> {
    let s = text(v)?;
    let raw = BigDecimal::from_str(s).map_err(|_| err("EXECUTION_DECIMAL"))?;
    let (c, e) = raw.as_bigint_and_exponent();
    if c.to_string().len() > 128 || !(-64..=18).contains(&e) {
        return Err(err("EXECUTION_DECIMAL_BOUND"));
    }
    let canonical: OnlyDecimal = s.parse()?;
    let n = BigDecimal::from_str(&canonical.to_string()).map_err(|_| err("EXECUTION_DECIMAL"))?;
    let (c, scale) = n.as_bigint_and_exponent();
    if c.to_string().len() > 128 || !(-64..=18).contains(&scale) {
        return Err(err("EXECUTION_DECIMAL_BOUND"));
    }
    Ok(n)
}
pub(crate) fn exact(v: &Value) -> Result<BigDecimal, Error> {
    let s = v
        .as_str()
        .filter(|s| s.len() <= 1100)
        .ok_or_else(|| err("EXECUTION_EXACT"))?;
    let raw = BigDecimal::from_str(s).map_err(|_| err("EXECUTION_EXACT"))?;
    let (c, e) = raw.as_bigint_and_exponent();
    if c.to_string().len() > 1024 || !(-512..=512).contains(&e) {
        return Err(err("EXECUTION_EXACT_BOUND"));
    }
    let n: OnlyDecimal = s.parse()?;
    let d = BigDecimal::from_str(&n.to_string()).map_err(|_| err("EXECUTION_EXACT"))?;
    let (c, scale) = d.as_bigint_and_exponent();
    if c.to_string().len() > 1024
        || !(-512..=512).contains(&scale)
        || d.normalized().to_plain_string().len() > 1024
    {
        return Err(err("EXECUTION_EXACT_BOUND"));
    }
    Ok(d)
}
pub(crate) fn exact_record(n: &BigDecimal, p: u8) -> String {
    let s = n.normalized().as_bigint_and_exponent().1.max(i64::from(p));
    n.with_scale(s).to_plain_string()
}
pub(crate) fn nonnegative(v: &Value) -> Result<BigDecimal, Error> {
    let n = dec(v)?;
    if n < BigDecimal::zero() {
        return Err(err("EXECUTION_NEGATIVE"));
    }
    Ok(n)
}
pub(crate) fn money(n: &BigDecimal, p: u8) -> Result<String, Error> {
    let v = n.with_scale(i64::from(p));
    if &v != n {
        return Err(err("EXECUTION_MONEY_PRECISION"));
    }
    let s = v.to_plain_string();
    if s.len() > 160 {
        return Err(err("EXECUTION_MONEY_BOUND"));
    }
    Ok(s)
}
pub(crate) const COMPONENTS: [&str; 6] = [
    "ORDER",
    "POSITION",
    "ACCOUNT",
    "LEDGER",
    "RISK",
    "EXECUTION",
];
/// Constructed only by the pure planner. Store transport must bind its exact encoded digest.
#[derive(Clone, Debug)]
pub struct Prepared {
    pub(crate) value: Value,
    pub(crate) planned: bool,
}
impl PartialEq for Prepared {
    fn eq(&self, other: &Self) -> bool {
        self.value == other.value
    }
}
impl Eq for Prepared {}

impl Prepared {
    pub(crate) fn new(mut v: Value) -> Result<Self, Error> {
        v["payload_hash"] = json!(hash(&v));
        let result = Self {
            value: v,
            planned: true,
        };
        result.validate()?;
        Ok(result)
    }
    pub fn record(&self) -> Value {
        self.value.clone()
    }
    pub fn encode(&self) -> Result<Vec<u8>, Error> {
        Ok(serde_json::to_vec(&self.value)?)
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, Error> {
        let v: Value = serde_json::from_slice(bytes)?;
        if serde_json::to_vec(&v)? != bytes {
            return Err(err("EXECUTION_NONCANONICAL"));
        }
        let p = Self {
            value: v,
            planned: false,
        };
        p.validate()?;
        Ok(p)
    }
    pub fn id(&self) -> &str {
        self.value["transaction_id"].as_str().expect("validated")
    }
    pub fn sequence(&self) -> u64 {
        self.value["sequence"].as_u64().expect("validated")
    }
    pub fn input(&self) -> &Value {
        &self.value["input"]
    }
    pub fn projection_count(&self) -> usize {
        COMPONENTS.len()
    }
    pub fn events(&self) -> &Value {
        &self.value["events"]
    }
    pub(crate) fn validate(&self) -> Result<(), Error> {
        let v = &self.value;
        row(
            v,
            &[
                "transaction_id",
                "config_hash",
                "sequence",
                "predecessor",
                "input",
                "projections",
                "events",
                "payload_hash",
            ],
        )?;
        for f in ["config_hash", "payload_hash"] {
            fp(&v[f])?;
        }
        if uint(&v["sequence"])? == 0
            || uint(&v["predecessor"])?.checked_add(1) != Some(uint(&v["sequence"])?)
        {
            return Err(err("EXECUTION_SEQUENCE"));
        }
        if text(&v["transaction_id"])? != format!("ETX-{}", hash(&v["input"])) {
            return Err(err("EXECUTION_IDENTITY"));
        }
        let mut content = v.clone();
        let expected = content
            .as_object_mut()
            .expect("row")
            .remove("payload_hash")
            .expect("row");
        if expected != hash(&content) {
            return Err(err("EXECUTION_PAYLOAD_HASH"));
        }
        let ps = v["projections"]
            .as_array()
            .filter(|p| p.len() == COMPONENTS.len())
            .ok_or_else(|| err("EXECUTION_PROJECTIONS"))?;
        for (i, p) in ps.iter().enumerate() {
            row(p, &["component", "before_hash", "result_hash", "result"])?;
            if p["component"] != COMPONENTS[i] || p["result_hash"] != hash(&p["result"]) {
                return Err(err("EXECUTION_PROJECTION_HASH_OR_ORDER"));
            }
            fp(&p["before_hash"])?;
        }
        let events = v["events"]
            .as_array()
            .filter(|a| a.len() == 1)
            .ok_or_else(|| err("EXECUTION_EVENTS"))?;
        if events[0]
            != json!({"schema_version":1,"event_id":format!("{}-EVENT-1",self.id()),"transaction_id":self.id(),"sequence":v["sequence"],"input":v["input"]})
        {
            return Err(err("EXECUTION_EVENT_IDENTITY"));
        }
        Ok(())
    }
}

pub(crate) fn settled_money(
    proof: &Value,
    key: &str,
    raw: &BigDecimal,
    currency: &Value,
    p: u8,
) -> Result<String, Error> {
    let v = &proof[key];
    row(v, &["amount", "currency"])?;
    if v["currency"] != *currency || proof["rounding"] != "HALF_EVEN" {
        return Err(err("EXECUTION_SETTLEMENT_ROUNDING"));
    }
    let amount = money(&nonnegative(&v["amount"])?, p)?;
    if v["amount"] != amount
        || nonnegative(&v["amount"])?
            != raw.with_scale_round(i64::from(p), bigdecimal::RoundingMode::HalfEven)
    {
        return Err(err("EXECUTION_SETTLEMENT_NOTIONAL"));
    }
    Ok(amount)
}
// Bound all external decimal leaves before calling typed Domain readers.
pub(crate) fn bound_decimal_leaves(v: &Value) -> Result<(), Error> {
    match v {
        Value::Object(m) => {
            for (k, v) in m {
                if (k == "amount" || (k == "value" && m.contains_key("precision")))
                    && v.as_str().is_some_and(|s| {
                        s.bytes()
                            .next()
                            .is_some_and(|b| b.is_ascii_digit() || b == b'-' || b == b'+')
                    })
                {
                    dec(v)?;
                } else {
                    bound_decimal_leaves(v)?;
                }
            }
        }
        Value::Array(a) => {
            for v in a {
                bound_decimal_leaves(v)?;
            }
        }
        _ => {}
    }
    Ok(())
}
