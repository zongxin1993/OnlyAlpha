use bigdecimal::{BigDecimal, Zero};
use onlyalpha_domain::{
    base::OnlyDomainModel, identifiers::OnlyIdentifier, time::OnlyTimestamp, value::OnlyCurrency,
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
    let o = v.as_object().ok_or_else(|| err("MARGIN_RECORD"))?;
    if o.len() != keys.len() || keys.iter().any(|k| !o.contains_key(*k)) {
        return Err(err("MARGIN_FIELDS"));
    }
    Ok(())
}
pub(crate) fn text(v: &Value) -> Result<&str, Error> {
    v.as_str()
        .filter(|s| !s.trim().is_empty() && s.len() <= 256)
        .ok_or_else(|| err("MARGIN_TEXT"))
}
pub(crate) fn id(v: &Value) -> Result<&str, Error> {
    let s = text(v)?;
    if external(OnlyIdentifier::new(s))?.value() != s {
        return Err(err("MARGIN_NONCANONICAL_ID"));
    }
    Ok(s)
}
pub(crate) fn uint(v: &Value) -> Result<u64, Error> {
    v.as_u64().ok_or_else(|| err("MARGIN_UNSIGNED"))
}
pub(crate) fn fingerprint(v: &Value) -> Result<(), Error> {
    let s = text(v)?;
    if s.len() != 64
        || !s
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(err("MARGIN_FINGERPRINT"));
    }
    Ok(())
}
pub(crate) fn number(v: &Value) -> Result<BigDecimal, Error> {
    let s = text(v)?;
    let n = external(BigDecimal::from_str(s))?;
    let (c, e) = n.as_bigint_and_exponent();
    if c.to_string().len() > 128 || !(-64..=18).contains(&e) || n < BigDecimal::zero() {
        return Err(err("MARGIN_DECIMAL"));
    }
    Ok(n)
}
pub(crate) fn money(v: &Value, p: u8) -> Result<Value, Error> {
    let n = number(v)?;
    let rounded = n.with_scale(i64::from(p));
    if n != rounded {
        return Err(err("MARGIN_MONEY_PRECISION"));
    }
    number(&json!(rounded.to_plain_string()))?;
    Ok(json!(rounded.to_plain_string()))
}
pub(crate) fn currency(v: &Value) -> Result<u8, Error> {
    let c = external(OnlyCurrency::from_record(v))?;
    if c.to_record() != *v {
        return Err(err("MARGIN_CURRENCY"));
    }
    Ok(c.precision())
}
pub(crate) fn time(v: &Value) -> Result<OnlyTimestamp, Error> {
    if v.to_string().len() > 256 {
        return Err(err("MARGIN_TIME_BOUND"));
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
        return Err(err("MARGIN_SCHEMA"));
    }
    for k in OWNER
        .into_iter()
        .chain(["cluster", "revision", "instrument", "request"])
    {
        id(&v[k])?;
    }
    fingerprint(&v["generation"])?;
    if !matches!(text(&v["runtime_kind"])?, "BACKTEST" | "SIM" | "LIVE") {
        return Err(err("MARGIN_RUNTIME_KIND"));
    }
    Ok(())
}

pub(crate) fn bounded(v: &Value, bytes: usize) -> Result<(), Error> {
    let mut pending = vec![(v, 0u8)];
    let mut nodes = 0usize;
    while let Some((v, depth)) = pending.pop() {
        nodes += 1;
        if depth > 48 || nodes > 2000000 {
            return Err(err("MARGIN_STRUCTURE_BOUND"));
        }
        match v {
            Value::Array(a) => {
                if a.len() > 4096 {
                    return Err(err("MARGIN_ARRAY_BOUND"));
                }
                pending.extend(a.iter().map(|v| (v, depth + 1)));
            }
            Value::Object(o) => {
                if o.len() > 4096 {
                    return Err(err("MARGIN_OBJECT_BOUND"));
                }
                pending.extend(o.values().map(|v| (v, depth + 1)));
            }
            _ => {}
        }
    }
    if v.to_string().len() > bytes {
        return Err(err("MARGIN_SIZE_BOUND"));
    }
    Ok(())
}

pub(crate) fn units(q: &Value, precision: u8) -> Result<u64, Error> {
    if precision > 18 {
        return Err(err("MARGIN_QUANTITY_PRECISION"));
    }
    let n = number(q)? * BigDecimal::new(1.into(), -i64::from(precision));
    let whole = n.with_scale(0);
    if n != whole {
        return Err(err("MARGIN_QUANTITY_PRECISION"));
    }
    external(whole.to_plain_string().parse::<u64>())
}
