use crate::{CalculationError, Result};
use bigdecimal::{BigDecimal, Zero, num_bigint::BigInt};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::str::FromStr;
pub(crate) const LIMIT: usize = 4096;
pub(crate) fn err(message: &str) -> CalculationError {
    CalculationError(message.into())
}
pub(crate) fn object<'a>(v: &'a Value, fields: &[&str]) -> Result<&'a Map<String, Value>> {
    let o = v.as_object().ok_or_else(|| err("OBJECT_REQUIRED"))?;
    if o.len() != fields.len() || fields.iter().any(|f| !o.contains_key(*f)) {
        return Err(err("EXACT_FIELDS_REQUIRED"));
    }
    Ok(o)
}
pub(crate) fn map(v: &Value) -> Result<&Map<String, Value>> {
    let m = v.as_object().ok_or_else(|| err("MAP_REQUIRED"))?;
    if m.len() > LIMIT {
        return Err(err("COLLECTION_BUDGET"));
    }
    Ok(m)
}
pub(crate) fn array(v: &Value) -> Result<&Vec<Value>> {
    let a = v.as_array().ok_or_else(|| err("ARRAY_REQUIRED"))?;
    if a.len() > LIMIT {
        return Err(err("COLLECTION_BUDGET"));
    }
    Ok(a)
}
pub(crate) fn text(v: &Value) -> Result<&str> {
    let s = v.as_str().ok_or_else(|| err("TEXT_REQUIRED"))?;
    if s.len() > LIMIT {
        return Err(err("TEXT_BUDGET"));
    }
    Ok(s)
}
pub(crate) fn name(v: &Value) -> Result<&str> {
    let s = text(v)?;
    if s.is_empty() || s.chars().any(|c| c.is_whitespace() || c.is_control()) {
        return Err(err("NAME_REQUIRED"));
    }
    Ok(s)
}
pub(crate) fn member<'a>(v: &'a Value, choices: &[&str]) -> Result<&'a str> {
    let s = text(v)?;
    if !choices.contains(&s) {
        return Err(err("ENUM_INVALID"));
    }
    Ok(s)
}
pub(crate) fn boolean(v: &Value) -> Result<bool> {
    v.as_bool().ok_or_else(|| err("BOOLEAN_REQUIRED"))
}
pub(crate) fn positive(v: &Value) -> Result<u64> {
    v.as_u64()
        .filter(|n| *n > 0 && *n <= LIMIT as u64)
        .ok_or_else(|| err("POSITIVE_INTEGER_BUDGET"))
}
pub(crate) fn digest(v: &Value) -> Result<&str> {
    let s = text(v)?;
    if s.len() != 64
        || !s
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(err("DIGEST_REQUIRED"));
    }
    Ok(s)
}
pub(crate) fn decimal(s: &str) -> Result<String> {
    if s.is_empty()
        || s.len() > LIMIT
        || !s
            .bytes()
            .all(|b| b.is_ascii_digit() || b"+-.eE".contains(&b))
    {
        return Err(err("DECIMAL_REQUIRED"));
    }
    let d = BigDecimal::from_str(s).map_err(|_| err("FINITE_DECIMAL_REQUIRED"))?;
    let (coefficient, scale) = d.as_bigint_and_exponent();
    if scale.unsigned_abs() > LIMIT as u64 || coefficient.to_string().len() > LIMIT {
        return Err(err("DECIMAL_BUDGET"));
    }
    let normalized = if d.is_zero() {
        "0".into()
    } else {
        d.normalized().to_plain_string()
    };
    if normalized.len() > LIMIT {
        return Err(err("DECIMAL_BUDGET"));
    }
    Ok(normalized)
}
pub(crate) fn scalar(v: &Value) -> Result<Value> {
    let m = object(v, &["type", "value"])?;
    let t = text(&m["type"])?;
    let value = &m["value"];
    let value = match t {
        "NULL" if value.is_null() => Value::Null,
        "BOOLEAN" => json!(boolean(value)?),
        "STRING" => json!(text(value)?),
        "DECIMAL" => json!(decimal(text(value)?)?),
        "INTEGER" => {
            let n = value
                .as_number()
                .ok_or_else(|| err("INTEGER_REQUIRED"))?
                .to_string();
            if n.len() > LIMIT {
                return Err(err("INTEGER_BUDGET"));
            }
            let integer = BigInt::from_str(&n).map_err(|_| err("INTEGER_REQUIRED"))?;
            serde_json::from_str(&integer.to_string()).map_err(|_| err("INTEGER_REQUIRED"))?
        }
        _ => return Err(err("SCALAR_TAG_INVALID")),
    };
    Ok(json!({"type":t,"value":value}))
}
pub(crate) fn scalars(v: &Value) -> Result<Value> {
    let mut out = Map::new();
    for (k, v) in map(v)? {
        name(&json!(k))?;
        out.insert(k.clone(), scalar(v)?);
    }
    Ok(Value::Object(out))
}
pub(crate) fn hash(v: &Value) -> String {
    use std::fmt::Write;
    let mut s = String::with_capacity(64);
    for b in Sha256::digest(v.to_string().as_bytes()) {
        write!(&mut s, "{b:02x}").expect("string write");
    }
    s
}
