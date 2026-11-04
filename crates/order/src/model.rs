use bigdecimal::BigDecimal;
use num_bigint::BigInt;
use onlyalpha_domain::{
    errors::OnlyDomainError, execution::OnlyOrderSnapshot, numeric::OnlyDecimal,
    time::OnlyTimestamp, value::OnlyPrice,
};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::{fmt, str::FromStr};

pub(crate) const MAX_COMMAND_BYTES: usize = 32768;
pub(crate) const MAX_ORDERS: usize = 64;
pub(crate) const MAX_JOURNAL_BYTES: usize = 4 * 1024 * 1024;
pub(crate) const MAX_JOURNAL: usize = 4096;
pub(crate) const MAX_CHECKPOINT: usize = 16 * 1024 * 1024;
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Error(pub String);
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for Error {}
impl From<OnlyDomainError> for Error {
    fn from(e: OnlyDomainError) -> Self {
        Self(e.to_string())
    }
}
impl From<serde_json::Error> for Error {
    fn from(e: serde_json::Error) -> Self {
        Self(e.to_string())
    }
}
pub(crate) fn err(message: &str) -> Error {
    Error(message.into())
}
pub fn digest(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
pub(crate) fn hash(value: &Value) -> String {
    digest(value.to_string().as_bytes())
}
pub(crate) fn row<'a>(value: &'a Value, fields: &[&str]) -> Result<&'a Map<String, Value>, Error> {
    let r = value
        .as_object()
        .ok_or_else(|| err("ORDER_RECORD_REQUIRED"))?;
    if r.get("schema_version").and_then(Value::as_u64) != Some(1)
        || r.len() != fields.len() + 1
        || fields.iter().any(|f| !r.contains_key(*f))
    {
        return Err(err("ORDER_SCHEMA_OR_FIELDS_INVALID"));
    }
    Ok(r)
}
pub(crate) fn text<'a>(r: &'a Map<String, Value>, field: &str) -> Result<&'a str, Error> {
    r.get(field)
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty() && s.len() <= 256)
        .ok_or_else(|| err("ORDER_TEXT_REQUIRED"))
}
pub(crate) fn fingerprint(value: &str) -> Result<(), Error> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(err("ORDER_FINGERPRINT_INVALID"));
    }
    Ok(())
}
pub(crate) fn integer(value: &Value) -> Result<BigInt, Error> {
    if !value.is_number() {
        return Err(err("ORDER_INTEGER_REQUIRED"));
    }
    let token = value.to_string();
    if token.len() > 64 {
        return Err(err("ORDER_INTEGER_BOUND"));
    }
    token.parse().map_err(|_| err("ORDER_INTEGER_REQUIRED"))
}
pub(crate) fn time(r: &Map<String, Value>, field: &str) -> Result<OnlyTimestamp, Error> {
    Ok(OnlyTimestamp::from_unix_nanos(integer(&r[field])?))
}
pub(crate) fn decimal_bound(v: &OnlyDecimal) -> Result<(), Error> {
    let d = BigDecimal::from_str(&v.to_string()).map_err(|_| err("ORDER_DECIMAL_INVALID"))?;
    let (c, s) = d.as_bigint_and_exponent();
    if c.to_string().len() > 1024 || !(-256..=256).contains(&s) {
        return Err(err("ORDER_ARITHMETIC_BOUND"));
    }
    Ok(())
}
/// The current closed fee tuple sums nested Money amounts inside Domain constructors.
/// Bound those leaves before any arithmetic-bearing Domain reader executes.
pub(crate) fn fee_amount_bounds(value: &Value) -> Result<(), Error> {
    let mut pending = vec![value];
    while let Some(value) = pending.pop() {
        match value {
            Value::Object(record) => {
                if record.contains_key("currency")
                    && let Some(amount) = record.get("amount")
                {
                    let token = amount
                        .as_str()
                        .ok_or_else(|| err("ORDER_FEE_AMOUNT_INVALID"))?;
                    decimal_bound(&token.parse()?)?;
                }
                pending.extend(record.values());
            }
            Value::Array(values) => pending.extend(values),
            _ => {}
        }
    }
    Ok(())
}

/// Round the exact rational once. Dividing to a fixed intermediate precision can double-round a tie.
pub(crate) fn average(
    total: &OnlyDecimal,
    quantity: &OnlyDecimal,
    precision: u8,
) -> Result<OnlyPrice, Error> {
    decimal_bound(total)?;
    decimal_bound(quantity)?;
    let (n, ns) = BigDecimal::from_str(&total.to_string())
        .map_err(|_| err("ORDER_DECIMAL_INVALID"))?
        .as_bigint_and_exponent();
    let (d, ds) = BigDecimal::from_str(&quantity.to_string())
        .map_err(|_| err("ORDER_DECIMAL_INVALID"))?
        .as_bigint_and_exponent();
    if n <= BigInt::from(0) || d <= BigInt::from(0) {
        return Err(err("ORDER_AVERAGE_INPUT_INVALID"));
    }
    let scale = i64::from(precision) + ds - ns;
    let (mut n, mut d) = (n, d);
    if scale >= 0 {
        n *= BigInt::from(10).pow(scale as u32);
    } else {
        d *= BigInt::from(10).pow((-scale) as u32);
    }
    let (mut q, r) = (&n / &d, &n % &d);
    let twice = &r * 2;
    if twice > d || (twice == d && &q % 2 != BigInt::from(0)) {
        q += 1;
    }
    Ok(OnlyPrice::new(
        BigDecimal::new(q, i64::from(precision))
            .to_string()
            .parse()?,
        precision,
    )?)
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ApplyResult {
    Applied,
    Duplicate,
    Stale,
    Conflict,
    Invalid,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Outcome {
    pub result: ApplyResult,
    pub snapshot: Option<OnlyOrderSnapshot>,
    pub fact: Option<Value>,
}
impl Outcome {
    pub(crate) fn unchanged(result: ApplyResult, snapshot: Option<OnlyOrderSnapshot>) -> Self {
        Self {
            result,
            snapshot,
            fact: None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn weighted_average_rounds_the_exact_ratio_only_once() {
        let p = average(
            &"10.0050000000000000000000000000000001".parse().unwrap(),
            &"1".parse().unwrap(),
            2,
        )
        .unwrap();
        assert_eq!(p.value().to_string(), "10.01");
        let p = average(
            &"10.0049999999999999999999999999999999".parse().unwrap(),
            &"1".parse().unwrap(),
            2,
        )
        .unwrap();
        assert_eq!(p.value().to_string(), "10.00");
    }
}
