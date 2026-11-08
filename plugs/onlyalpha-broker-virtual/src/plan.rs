//! 计划只决定数量、顺序与到期偏移，触价由场所处理。
use bigdecimal::{BigDecimal, RoundingMode, Zero};
use onlyalpha_broker::{Error, digest};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    numeric::OnlyDecimal,
    value::{OnlyPrice, OnlyQuantity},
};
use serde_json::{Value, json};
use std::str::FromStr;

pub(crate) fn err(code: &str) -> Error {
    Error::new(code)
}

pub(crate) fn fields(value: &Value, allowed: &[&str]) -> Result<(), Error> {
    if value
        .as_object()
        .is_none_or(|row| row.keys().any(|k| !allowed.contains(&k.as_str())))
    {
        return Err(err("VIRTUAL_FIELDS"));
    }
    Ok(())
}

fn bounded_number(text: &str) -> Result<BigDecimal, Error> {
    if text.len() > 128 || text.is_empty() {
        return Err(err("VIRTUAL_DECIMAL"));
    }
    let mantissa = if let Some((digits, exp)) = text.split_once(['e', 'E']) {
        let exponent: i16 = exp.parse().map_err(|_| err("VIRTUAL_DECIMAL"))?;
        if !(-128..=127).contains(&exponent) {
            return Err(err("VIRTUAL_DECIMAL"));
        }
        digits
    } else {
        text
    };
    let unsigned = mantissa.strip_prefix(['-', '+']).unwrap_or(mantissa);
    if !unsigned.bytes().all(|b| b.is_ascii_digit() || b == b'.') {
        return Err(err("VIRTUAL_DECIMAL"));
    }
    let n = BigDecimal::from_str(text).map_err(|_| err("VIRTUAL_DECIMAL"))?;
    if n.to_plain_string().len() > 128 {
        return Err(err("VIRTUAL_DECIMAL"));
    }
    Ok(n)
}

/// Broker/Domain 的正式记录只接受字符串；typed 解码已校验完整记录。
pub(crate) fn number(v: &Value) -> Result<BigDecimal, Error> {
    let text = v.as_str().ok_or_else(|| err("VIRTUAL_DECIMAL"))?;
    let n = bounded_number(text)?;
    if text.starts_with('+')
        || text.contains(['e', 'E']) && {
            let canonical = OnlyDecimal::from_str(text).map_err(|_| err("VIRTUAL_DECIMAL"))?;
            canonical.fractional_precision() > 18 || canonical.to_string() != text
        }
    {
        return Err(err("VIRTUAL_DECIMAL"));
    }
    Ok(n)
}

/// 配置允许 JSON 数字与文本，保留原始十进制数字后再归一化。
pub(crate) fn setting_number(v: &Value) -> Result<BigDecimal, Error> {
    match v {
        Value::String(text) => bounded_number(text.trim()),
        Value::Number(n) => bounded_number(&n.to_string()),
        _ => Err(err("VIRTUAL_DECIMAL")),
    }
}

fn positive(n: BigDecimal) -> Result<BigDecimal, Error> {
    if n > BigDecimal::zero() {
        Ok(n)
    } else {
        Err(err("VIRTUAL_POSITIVE"))
    }
}

pub(crate) fn fixed(n: &BigDecimal, precision: i64) -> String {
    n.with_scale(precision).to_plain_string()
}

pub(crate) fn domain_value(n: &BigDecimal, p: i64) -> Result<OnlyDecimal, Error> {
    if !(0..=18).contains(&p) || n.with_scale(p) != *n {
        return Err(err("VIRTUAL_PRECISION"));
    }
    fixed(n, p).parse().map_err(|_| err("VIRTUAL_DECIMAL"))
}
pub(crate) fn price_record(n: &BigDecimal, p: i64) -> Result<Value, Error> {
    Ok(OnlyPrice::new(domain_value(n, p)?, p as u8)
        .map_err(|_| err("VIRTUAL_PRICE"))?
        .to_record())
}
pub(crate) fn quantity_record(n: &BigDecimal, p: i64) -> Result<Value, Error> {
    Ok(OnlyQuantity::new(domain_value(n, p)?, p as u8)
        .map_err(|_| err("VIRTUAL_QUANTITY"))?
        .to_record())
}

pub(crate) fn policy(partial: &Value, maxima: &[&Value]) -> Result<Value, Error> {
    fields(
        partial,
        &["mode", "dispatch_mode", "steps", "maximum_fill_quantity"],
    )?;
    let mut maximum = None;
    for item in maxima.iter().filter(|v| !v.is_null()) {
        let n = positive(setting_number(item)?)?;
        if maximum.as_ref().is_some_and(|m| m != &n) {
            return Err(err("VIRTUAL_FILL_POLICY_CONFLICT"));
        }
        maximum = Some(n);
    }
    let mode = keyword(
        partial,
        "mode",
        if maximum.is_some() {
            "MAX_PER_BAR"
        } else {
            "WHOLE"
        },
    )?;
    let dispatch = keyword(partial, "dispatch_mode", "ONE_PER_BAR")?;
    let empty = json!([]);
    let specs = partial
        .get("steps")
        .unwrap_or(&empty)
        .as_array()
        .ok_or_else(|| err("VIRTUAL_STEPS"))?;
    if !matches!(mode.as_str(), "WHOLE" | "MAX_PER_BAR" | "SCHEDULE")
        || !matches!(dispatch.as_str(), "ONE_PER_BAR" | "ALL_DUE")
        || (mode == "MAX_PER_BAR") != maximum.is_some()
        || (mode == "SCHEDULE") == specs.is_empty()
    {
        return Err(err("VIRTUAL_FILL_POLICY_CONFLICT"));
    }
    let mut prev = 0;
    let mut ratio_sum = BigDecimal::zero();
    let mut normalized = Vec::new();
    for spec in specs {
        fields(spec, &["bar_offset", "ratio", "quantity"])?;
        let offset = spec["bar_offset"]
            .as_u64()
            .filter(|n| *n > 0)
            .ok_or_else(|| err("VIRTUAL_STEP_OFFSET"))?;
        if offset < prev
            || (offset == prev && dispatch == "ONE_PER_BAR")
            || spec["ratio"].is_null() == spec["quantity"].is_null()
        {
            return Err(err("VIRTUAL_FILL_STEP"));
        }
        prev = offset;
        let key = if spec["ratio"].is_null() {
            "quantity"
        } else {
            "ratio"
        };
        if specs[0][key].is_null() {
            return Err(err("VIRTUAL_FILL_STEP_MIXED"));
        }
        let n = positive(setting_number(&spec[key])?)?;
        if key == "ratio" {
            ratio_sum += &n;
        }
        normalized.push(json!({"bar_offset":offset,(key):n.normalized().to_plain_string()}));
    }
    if !ratio_sum.is_zero() && ratio_sum != 1 {
        return Err(err("VIRTUAL_FILL_RATIO_SUM"));
    }
    Ok(
        json!({"mode":mode,"dispatch_mode":if mode == "MAX_PER_BAR" {"ONE_PER_BAR"} else {&dispatch},
              "maximum":maximum.map(|v| v.normalized().to_plain_string()),"steps":normalized}),
    )
}

pub(crate) fn keyword(v: &Value, key: &str, default: &str) -> Result<String, Error> {
    match v.get(key) {
        None => Ok(default.into()),
        Some(v) => v
            .as_str()
            .map(str::to_ascii_uppercase)
            .ok_or_else(|| err("VIRTUAL_KEYWORD")),
    }
}

fn steps(policy: &Value, quantity: &Value) -> Result<Vec<(u64, String)>, Error> {
    let total = positive(number(&quantity["value"])?)?;
    let p = quantity["precision"]
        .as_i64()
        .filter(|p| (0..=18).contains(p))
        .ok_or_else(|| err("VIRTUAL_PRECISION"))?;
    let mut remaining = total.clone();
    let mut result = Vec::new();
    let mut take = |offset, n: BigDecimal| -> Result<(), Error> {
        if n <= BigDecimal::zero() || n > remaining || n.with_scale(p) != n {
            return Err(err("VIRTUAL_STEP_QUANTITY"));
        }
        result.push((offset, fixed(&n, p)));
        remaining -= n;
        Ok(())
    };
    match policy["mode"].as_str() {
        Some("WHOLE") => take(1, total.clone())?,
        Some("MAX_PER_BAR") => {
            let cap = positive(number(&policy["maximum"])?)?;
            if total > &cap * BigDecimal::from(65536) {
                return Err(err("VIRTUAL_FILL_PLAN_CAPACITY"));
            }
            let mut left = total.clone();
            let mut offset = 1;
            while left > BigDecimal::zero() {
                let part = left.clone().min(cap.clone());
                take(offset, part.clone())?;
                left -= part;
                offset += 1;
            }
        }
        Some("SCHEDULE") => {
            let specs = policy["steps"]
                .as_array()
                .ok_or_else(|| err("VIRTUAL_STEPS"))?;
            let mut left = total.clone();
            for (i, spec) in specs.iter().enumerate() {
                let part = if !spec["quantity"].is_null() {
                    positive(number(&spec["quantity"])?)?
                } else if i + 1 == specs.len() {
                    left.clone()
                } else {
                    (&total * positive(number(&spec["ratio"])?)?)
                        .with_scale_round(p, RoundingMode::Down)
                };
                take(
                    spec["bar_offset"]
                        .as_u64()
                        .ok_or_else(|| err("VIRTUAL_STEP_OFFSET"))?,
                    part.clone(),
                )?;
                left -= part;
            }
        }
        _ => return Err(err("VIRTUAL_FILL_POLICY")),
    }
    if !remaining.is_zero() {
        return Err(err("VIRTUAL_FILL_QUANTITY_MISMATCH"));
    }
    Ok(result)
}

#[derive(Clone)]
pub(crate) struct Plan {
    pub id: String,
    pub accepted_bar: u64,
    pub steps: Vec<(u64, String)>,
    pub cursor: usize,
    pub version: usize,
}
impl Plan {
    pub fn new(
        policy: &Value,
        command: &onlyalpha_broker::BrokerCommand,
        venue: &str,
        accepted_bar: u64,
    ) -> Result<Self, Error> {
        let c = command.record();
        let q = &c["request"]["quantity"];
        let steps = steps(policy, q)?;
        let normalized: Vec<_> = steps
            .iter()
            .enumerate()
            .map(|(i, (offset, q))| json!({"step_index":i+1,"bar_offset":offset,"quantity":q}))
            .collect();
        let p = q["precision"]
            .as_i64()
            .ok_or_else(|| err("VIRTUAL_PRECISION"))?;
        let identity = json!({"schema_version":1,"gateway_id":c["scope"]["gateway"],"account_id":c["scope"]["account"],
            "order_id":command.order(),"venue_order_id":venue,"mode":policy["mode"],"dispatch_mode":policy["dispatch_mode"],
            "original_quantity":fixed(&number(&q["value"])?,p),"quantity_precision":p,"normalized_steps":normalized});
        Ok(Self {
            id: format!("VPLAN-{}", digest(&identity)),
            accepted_bar,
            steps,
            cursor: 0,
            version: 1,
        })
    }
}

#[cfg(test)]
#[path = "tests/plan.rs"]
mod tests;
