//! Spot exchangeInfo 与 executionRules 的交易词汇和不可变语义记录。
use crate::reference_capture::{keyed, rows, text};
use onlyalpha_domain::{
    enums::{OnlyOrderType, OnlyTimeInForce},
    numeric::OnlyDecimal,
    time::OnlyUtcDateTime,
};
use onlyalpha_market_crypto::reference::{Reference, Result, decimal_text};
use serde_json::{Value, json};
use std::collections::BTreeMap;

/// Binance Spot 的限价单额外执行条件。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ExecutionInstruction {
    PostOnly,
}

/// 把交易所订单类型解析为 Domain 类型及显式成交指令。
pub fn order_type(native: &str) -> Result<(OnlyOrderType, Option<ExecutionInstruction>)> {
    use OnlyOrderType::*;
    Ok(match native {
        "LIMIT" => (Limit, None),
        "MARKET" => (Market, None),
        "STOP_LOSS" => (StopMarket, None),
        "STOP_LOSS_LIMIT" => (StopLimit, None),
        "TAKE_PROFIT" => (MarketIfTouched, None),
        "TAKE_PROFIT_LIMIT" => (LimitIfTouched, None),
        "LIMIT_MAKER" => (Limit, Some(ExecutionInstruction::PostOnly)),
        _ => return Err("BINANCE_SPOT_ORDER_TYPE_UNKNOWN"),
    })
}

const TIME_IN_FORCE: [OnlyTimeInForce; 3] = [
    OnlyTimeInForce::Gtc,
    OnlyTimeInForce::Ioc,
    OnlyTimeInForce::Fok,
];

/// Binance Spot 提供的有效期集合。
pub fn time_in_force(native: &str) -> Result<OnlyTimeInForce> {
    TIME_IN_FORCE
        .into_iter()
        .find(|tif| tif.as_str() == native)
        .ok_or("BINANCE_SPOT_TIME_IN_FORCE_UNKNOWN")
}

fn sorted(v: &Value) -> Result<Vec<String>> {
    let mut out = rows(v)?
        .iter()
        .map(|s| text(s).map(str::to_owned))
        .collect::<Result<Vec<_>>>()?;
    out.sort();
    Ok(out)
}
fn boolean(v: &Value) -> Result<bool> {
    v.as_bool().ok_or("BINANCE_SPOT_BOOLEAN")
}
fn optional(v: &Value) -> Result<Value> {
    let s = decimal_text(v)?;
    Ok(
        if s.parse::<OnlyDecimal>()
            .map_err(|_| "BINANCE_SPOT_DECIMAL")?
            .is_zero()
        {
            Value::Null
        } else {
            json!(s)
        },
    )
}
fn rule(r: &Value, key: &str, category: &str) -> Result<Value> {
    let mut pairs = Vec::new();
    for (k, v) in r.as_object().ok_or("BINANCE_SPOT_RULE_OBJECT")? {
        if k == key {
            continue;
        }
        let value = if v.is_string() {
            let s = text(v)?;
            json!(match s.parse::<OnlyDecimal>() {
                Ok(_) => decimal_text(v)?,
                Err(_) => s.to_owned(),
            })
        } else if v.is_boolean() || v.is_i64() || v.is_u64() {
            v.clone()
        } else {
            return Err("BINANCE_SPOT_RULE_VALUE");
        };
        pairs.push(json!([k, value]));
    }
    Ok(json!({"rule_type":text(&r[key])?,"category":category,"values":pairs}))
}
fn notional(filters: &BTreeMap<&str, &Value>) -> Result<(Value, Value, bool, bool, u64)> {
    let legacy = |v: &Value| -> Result<(String, bool, u64)> {
        Ok((
            decimal_text(&v["minNotional"])?,
            boolean(&v["applyToMarket"])?,
            v["avgPriceMins"].as_u64().ok_or("BINANCE_SPOT_WINDOW")?,
        ))
    };
    if let Some(n) = filters.get("NOTIONAL") {
        let min = decimal_text(&n["minNotional"])?;
        let applies = boolean(&n["applyMinToMarket"])?;
        let minutes = n["avgPriceMins"].as_u64().ok_or("BINANCE_SPOT_WINDOW")?;
        if let Some(old) = filters.get("MIN_NOTIONAL") {
            let (m, a, w) = legacy(old)?;
            if m.parse::<OnlyDecimal>().ok() != min.parse::<OnlyDecimal>().ok()
                || a != applies
                || w != minutes
            {
                return Err("BINANCE_NOTIONAL_FILTER_CONFLICT");
            }
        }
        return Ok((
            json!(min),
            optional(&n["maxNotional"])?,
            applies,
            boolean(&n["applyMaxToMarket"])?,
            minutes,
        ));
    }
    let (min, applies, window) = legacy(
        filters
            .get("MIN_NOTIONAL")
            .ok_or("BINANCE_SPOT_MIN_NOTIONAL")?,
    )?;
    Ok((json!(min), Value::Null, applies, false, window))
}
fn symbol(raw: &Value, execution: Option<&&Value>) -> Result<Value> {
    let name = text(&raw["symbol"])?;
    let status = text(&raw["status"])?;
    let filters = keyed(&raw["filters"], "filterType")?;
    let price = filters.get("PRICE_FILTER").ok_or("BINANCE_SPOT_PRICE")?;
    let lot = filters.get("LOT_SIZE").ok_or("BINANCE_SPOT_LOT")?;
    let (min_notional, max_notional, min_market, max_market, window) = notional(&filters)?;
    let order_types = sorted(&raw["orderTypes"])?;
    let mut compatible = matches!(status, "TRADING" | "HALT" | "BREAK")
        && order_types.iter().all(|v| order_type(v).is_ok());
    let time_in_force = TIME_IN_FORCE.map(OnlyTimeInForce::as_str);
    let mut rules = Vec::new();
    for (k, r) in filters.iter() {
        let category = match *k {
            "PRICE_FILTER" | "LOT_SIZE" | "MIN_NOTIONAL" | "NOTIONAL" => "STATIC",
            "MARKET_LOT_SIZE" => "ORDER_TYPE_SPECIFIC",
            "PERCENT_PRICE" | "PERCENT_PRICE_BY_SIDE" | "TRAILING_DELTA" => "DYNAMIC",
            "ICEBERG_PARTS"
            | "MAX_NUM_ORDERS"
            | "MAX_NUM_ALGO_ORDERS"
            | "MAX_NUM_ICEBERG_ORDERS"
            | "MAX_POSITION"
            | "MAX_NUM_ORDER_LISTS"
            | "MAX_NUM_ORDER_AMENDS" => "CAPACITY",
            "T_PLUS_SELL" => "SETTLEMENT",
            _ => {
                compatible = false;
                "UNKNOWN_CRITICAL"
            }
        };
        rules.push(rule(r, "filterType", category)?);
    }
    let exec = match execution {
        Some(v) => rows(&v["rules"])?.as_slice(),
        None => &[],
    };
    if exec.is_empty() {
        compatible = false;
    }
    for r in exec {
        let cat = if r["ruleType"] == "PRICE_RANGE" {
            "DYNAMIC"
        } else {
            compatible = false;
            "UNKNOWN_CRITICAL"
        };
        rules.push(rule(r, "ruleType", cat)?);
    }
    rules.sort_by(|a, b| {
        a["rule_type"]
            .as_str()
            .cmp(&b["rule_type"].as_str())
            .then_with(|| a["values"].to_string().cmp(&b["values"].to_string()))
    });
    let mut permission = rows(&raw["permissionSets"])?
        .iter()
        .map(sorted)
        .collect::<Result<Vec<_>>>()?;
    permission.sort();
    let stp = sorted(&raw["allowedSelfTradePreventionModes"])?;
    let default_stp = text(&raw["defaultSelfTradePreventionMode"])?;
    if !stp.iter().any(|s| s == default_stp) {
        return Err("BINANCE_SPOT_STP");
    }
    compatible &= stp.iter().all(|s| {
        matches!(
            s.as_str(),
            "NONE" | "EXPIRE_MAKER" | "EXPIRE_TAKER" | "EXPIRE_BOTH" | "DECREMENT" | "TRANSFER"
        )
    });
    let mut caps = Vec::new();
    for key in [
        "allowTrailingStop",
        "amendAllowed",
        "cancelReplaceAllowed",
        "pegInstructionsAllowed",
        "quoteOrderQtyMarketAllowed",
    ] {
        caps.push(json!([
            key,
            raw.get(key).map(boolean).transpose()?.unwrap_or(false)
        ]));
    }
    let mut groups = Vec::new();
    for (key, group) in [
        ("ocoAllowed", "OCO"),
        ("otoAllowed", "OTO"),
        ("opoAllowed", "OPO"),
    ] {
        if raw.get(key).map(boolean).transpose()?.unwrap_or(false) {
            groups.push(group);
        }
    }
    let m = filters.get("MARKET_LOT_SIZE");
    Ok(
        json!({"instrument_id":format!("{name}.BINANCE"),"raw_symbol":name,"base_currency":text(&raw["baseAsset"])?,"quote_currency":text(&raw["quoteAsset"])?,"provider_status":status,"spot_trading_allowed":boolean(&raw["isSpotTradingAllowed"])?,"price_tick":decimal_text(&price["tickSize"])?,"minimum_price":optional(&price["minPrice"])?,"maximum_price":optional(&price["maxPrice"])?,"quantity_step":decimal_text(&lot["stepSize"])?,"minimum_quantity":decimal_text(&lot["minQty"])?,"maximum_quantity":optional(&lot["maxQty"])?,"market_quantity_step":m.map(|r|decimal_text(&r["stepSize"])).transpose()?,"market_minimum_quantity":m.map(|r|decimal_text(&r["minQty"])).transpose()?,"market_maximum_quantity":m.map(|r|optional(&r["maxQty"])).transpose()?,"minimum_notional":min_notional,"maximum_notional":max_notional,"minimum_notional_applies_to_market":min_market,"maximum_notional_applies_to_market":max_market,"notional_reference_window_minutes":window,"venue_order_types":order_types,"time_in_force":time_in_force,"order_group_capabilities":groups,"default_stp_mode":default_stp,"allowed_stp_modes":stp,"permission_sets":permission,"capabilities":caps,"rules":rules,"compatibility_status":if compatible{"COMPATIBLE"}else{"INCOMPATIBLE"}}),
    )
}
pub(crate) fn normalize(
    exchange: &Value,
    execution: &Value,
    at: OnlyUtcDateTime,
) -> Result<Reference> {
    text(&exchange["timezone"])?;
    let by_symbol = keyed(&execution["symbolRules"], "symbol")?;
    let symbols = keyed(&exchange["symbols"], "symbol")?;
    if by_symbol.keys().any(|s| !symbols.contains_key(s)) {
        return Err("BINANCE_SPOT_EXECUTION_SCOPE");
    }
    let refs = symbols
        .into_iter()
        .map(|(s, r)| symbol(r, by_symbol.get(s)))
        .collect::<Result<_>>()?;
    let mut rules = Vec::new();
    for (k, r) in keyed(&exchange["exchangeFilters"], "filterType")? {
        let category = if matches!(
            k,
            "EXCHANGE_MAX_NUM_ORDERS"
                | "EXCHANGE_MAX_ALGO_ORDERS"
                | "EXCHANGE_MAX_NUM_ICEBERG_ORDERS"
                | "EXCHANGE_MAX_NUM_ORDER_LISTS"
        ) {
            "CAPACITY"
        } else {
            "UNKNOWN_CRITICAL"
        };
        rules.push(rule(r, "filterType", category)?);
    }
    Reference::spot(at, json!(rules), refs)
}
