use bigdecimal::{BigDecimal, RoundingMode, Zero, num_bigint::BigInt};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{fmt, str::FromStr};
#[derive(Clone, Debug, PartialEq, Eq)]
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
pub fn digest(v: &Value) -> String {
    Sha256::digest(v.to_string().as_bytes())
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
pub(crate) fn fields(v: &Value, keys: &[&str]) -> Result<(), Error> {
    let o = v.as_object().ok_or_else(|| err("FEE_RECORD"))?;
    if o.len() != keys.len() || keys.iter().any(|k| !o.contains_key(*k)) {
        return Err(err("FEE_FIELDS"));
    }
    Ok(())
}
pub(crate) fn text(v: &Value) -> Result<&str, Error> {
    v.as_str()
        .filter(|s| !s.trim().is_empty() && s.len() <= 256)
        .ok_or_else(|| err("FEE_TEXT"))
}
pub(crate) fn one(v: &Value, allowed: &[&str]) -> Result<(), Error> {
    if !allowed.contains(&text(v)?) {
        return Err(err("FEE_ENUM"));
    }
    Ok(())
}
pub(crate) fn num(v: &Value) -> Result<BigDecimal, Error> {
    let s = text(v)?;
    let n = BigDecimal::from_str(s).map_err(|_| err("FEE_DECIMAL"))?;
    let (c, e) = n.as_bigint_and_exponent();
    if c.to_string().len() > 128 || !(-64..=18).contains(&e) {
        return Err(err("FEE_DECIMAL_BOUND"));
    }
    if n < BigDecimal::zero() {
        return Err(err("FEE_NEGATIVE"));
    }
    Ok(n)
}
pub(crate) fn amount(n: &BigDecimal, precision: u8) -> Result<Value, Error> {
    let n = n.with_scale_round(i64::from(precision), RoundingMode::HalfEven);
    let (c, e) = n.as_bigint_and_exponent();
    if c.to_string().len() > 512 || e.unsigned_abs() > 512 {
        return Err(err("FEE_RESULT_BOUND"));
    }
    Ok(json!(n.to_plain_string()))
}
pub(crate) fn exact_amount(n: &BigDecimal, precision: u8) -> Result<Value, Error> {
    let v = amount(n, precision)?;
    let parsed = BigDecimal::from_str(text(&v)?).map_err(|_| err("FEE_DECIMAL"))?;
    if parsed != *n {
        return Err(err("FEE_MONEY_PRECISION"));
    }
    Ok(v)
}
pub(crate) fn unsigned(v: &Value) -> Result<u64, Error> {
    v.as_u64().ok_or_else(|| err("FEE_UNSIGNED"))
}
pub(crate) fn currency(v: &Value) -> Result<u8, Error> {
    use onlyalpha_domain::base::OnlyDomainModel;
    let c =
        onlyalpha_domain::value::OnlyCurrency::from_record(v).map_err(|e| Error(e.to_string()))?;
    if c.to_record() != *v {
        return Err(err("FEE_CURRENCY"));
    }
    Ok(c.precision())
}
pub(crate) fn array(v: &Value) -> Result<&Vec<Value>, Error> {
    v.as_array()
        .filter(|a| a.len() <= 4096)
        .ok_or_else(|| err("FEE_ARRAY_BOUND"))
}
pub(crate) fn bound(v: &Value, depth: u8) -> Result<(), Error> {
    if depth > 48 {
        return Err(err("FEE_DEPTH"));
    }
    match v {
        Value::Array(a) => {
            if a.len() > 4096 {
                return Err(err("FEE_ARRAY_BOUND"));
            }
            for x in a {
                bound(x, depth + 1)?;
            }
        }
        Value::Object(o) => {
            if o.len() > 4096 {
                return Err(err("FEE_OBJECT_BOUND"));
            }
            for (k, x) in o {
                if k.len() > 512 {
                    return Err(err("FEE_KEY_BOUND"));
                }
                bound(x, depth + 1)?;
            }
        }
        Value::String(s) if s.len() > 4096 => return Err(err("FEE_STRING_BOUND")),
        _ => {}
    }
    Ok(())
}
pub(crate) fn round(n: &BigDecimal, q: &BigDecimal, mode: &str) -> Result<BigDecimal, Error> {
    let (a, sa) = n.as_bigint_and_exponent();
    let (b, sb) = q.as_bigint_and_exponent();
    if b <= BigInt::from(0) {
        return Err(err("FEE_QUANTUM"));
    }
    let shift = sb - sa;
    if shift.unsigned_abs() > 1024 {
        return Err(err("FEE_RESULT_BOUND"));
    }
    let (a, b) = if shift >= 0 {
        (a * BigInt::from(10).pow(shift as u32), b)
    } else {
        (a, b * BigInt::from(10).pow((-shift) as u32))
    };
    let mut units = &a / &b;
    let rem = &a % &b;
    let twice = &rem * 2;
    let increment = match mode {
        "CEILING" => rem != BigInt::from(0),
        "FLOOR" => false,
        "HALF_UP" => twice >= b,
        "HALF_EVEN" => twice > b || (twice == b && &units % 2 != BigInt::from(0)),
        _ => return Err(err("FEE_ROUNDING")),
    };
    if increment {
        units += 1;
    }
    Ok(BigDecimal::from(units) * q)
}
pub(crate) fn scope(v: &Value) -> Result<(), Error> {
    fields(
        v,
        &[
            "engine",
            "runtime",
            "account",
            "broker",
            "gateway",
            "generation",
            "runtime_kind",
            "cluster",
            "revision",
            "order",
            "instrument",
            "market",
            "venue",
            "instrument_class",
            "currency",
            "side",
            "offset",
        ],
    )?;
    for (k, x) in v.as_object().expect("object") {
        if k != "currency" {
            text(x)?;
        }
    }
    currency(&v["currency"])?;
    for k in ["generation", "revision"] {
        let s = text(&v[k])?;
        if s.len() != 64
            || !s
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            return Err(err("FEE_FINGERPRINT"));
        }
    }
    one(&v["runtime_kind"], &["BACKTEST", "SIM", "LIVE"])?;
    one(&v["side"], &["BUY", "SELL"])?;
    one(
        &v["offset"],
        &["OPEN", "CLOSE", "CLOSE_TODAY", "CLOSE_YESTERDAY"],
    )?;
    Ok(())
}

pub(crate) fn instant(v: &Value) -> Result<BigInt, Error> {
    if !v.is_number() {
        return Err(err("FEE_TIMESTAMP"));
    }
    let s = v.to_string();
    if s.len() > 256 {
        return Err(err("FEE_TIMESTAMP_BOUND"));
    }
    BigInt::from_str(&s).map_err(|_| err("FEE_TIMESTAMP"))
}
pub(crate) fn instant_record(n: BigInt) -> Result<Value, Error> {
    if n.to_string().len() > 256 {
        return Err(err("FEE_TIMESTAMP_BOUND"));
    }
    serde_json::from_str(&n.to_string()).map_err(|_| err("FEE_TIMESTAMP"))
}
