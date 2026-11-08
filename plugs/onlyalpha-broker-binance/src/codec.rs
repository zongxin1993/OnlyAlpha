use super::*;
use bigdecimal::BigDecimal;
use onlyalpha_broker::Operation;
use onlyalpha_domain::trading::{OnlyExecutionIntent, OnlyExposureConstraint, OnlyPositionMode};
use sha2::{Digest, Sha256};
use std::str::FromStr;
pub(crate) fn wire_client(id: &str) -> String {
    if (1..=36).contains(&id.len())
        && id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"._:/-".contains(&b))
    {
        return id.into();
    }
    let hash = hex(&Sha256::digest(id.as_bytes()));
    format!("oa_{}", &hash[..32])
}
pub(crate) fn cancel_client(c: &BrokerCommand) -> String {
    let hash = onlyalpha_broker::digest(&c.record());
    format!("oc_{}", &hash[..32])
}
pub(crate) fn symbol(c: &BrokerCommand) -> Result<String> {
    let record = c.record();
    let instrument = &record["request"]["instrument_id"];
    if instrument["venue"]["value"] != "BINANCE" {
        return Err(err("BINANCE_INSTRUMENT_VENUE"));
    }
    let symbol = instrument["symbol"]["value"]
        .as_str()
        .ok_or_else(|| err("BINANCE_SYMBOL"))?;
    venue_id(symbol, 0)?;
    Ok(symbol.to_owned())
}
pub(crate) fn venue_id(symbol: &str, number: u64) -> Result<String> {
    if symbol.is_empty() || symbol.len() > 64 || !symbol.chars().all(char::is_alphanumeric) {
        return Err(err("BINANCE_SYMBOL"));
    }
    Ok(format!("BINANCE:{symbol}:{number}"))
}
pub(crate) fn wire_decimal(v: &Value) -> Result<BigDecimal> {
    let s = v
        .as_str()
        .filter(|s| {
            !s.is_empty() && s.len() <= 128 && s.bytes().all(|b| b.is_ascii_digit() || b == b'.')
        })
        .ok_or_else(|| err("BINANCE_DECIMAL"))?;
    let n = BigDecimal::from_str(s).map_err(|_| err("BINANCE_DECIMAL"))?;
    if n.as_bigint_and_exponent().1 > 18 {
        return Err(err("BINANCE_DECIMAL_SCALE"));
    }
    Ok(n)
}
pub(crate) fn ack_venue(
    command: &BrokerCommand,
    original: &BrokerCommand,
    bound: Option<u64>,
    raw: &Value,
) -> Result<u64> {
    let venue = raw["orderId"]
        .as_u64()
        .ok_or_else(|| err("BINANCE_ACK_ID"))?;
    if command.scope() != original.scope()
        || command.order() != original.order()
        || command.client() != original.client()
        || raw["symbol"] != symbol(original)?
        || bound.is_some_and(|n| n != venue)
    {
        return Err(err("BINANCE_ACK_IDENTITY"));
    }
    let client = wire_client(original.client());
    match command.operation() {
        Operation::Submit if command == original && raw["clientOrderId"] == client => Ok(venue),
        Operation::Cancel
            if bound == Some(venue)
                && raw["status"] == "CANCELED"
                && raw["origClientOrderId"] == client
                && raw["clientOrderId"] == cancel_client(command) =>
        {
            Ok(venue)
        }
        _ => Err(err("BINANCE_ACK_IDENTITY")),
    }
}
/// 仅翻译既有 USD-M 仓位模式的 wire 参数，调用者提供账户的实际模式。
pub fn usdm_order_parameters(
    intent: &OnlyExecutionIntent,
    mode: OnlyPositionMode,
) -> Result<BTreeMap<&'static str, &'static str>> {
    let mut p = BTreeMap::from([("side", intent.side().as_str())]);
    if mode == OnlyPositionMode::Hedging {
        p.insert("positionSide", intent.position_side().as_str());
    } else {
        p.insert("positionSide", "BOTH");
        if intent.exposure_constraint() == OnlyExposureConstraint::ReduceOnly {
            p.insert("reduceOnly", "true");
        } else if intent.reduces_exposure() {
            return Err(err("BINANCE_USDM_CLOSE_REQUIRES_REDUCE_ONLY"));
        }
    }
    Ok(p)
}
pub(crate) fn submit_params(c: &BrokerCommand) -> Result<BTreeMap<String, String>> {
    let v = c.record();
    let r = &v["request"];
    let intent = &r["execution_intent"];
    if c.operation() != Operation::Submit
        || intent["position_mode"] != "NETTING"
        || intent["position_side"] != "LONG"
        || intent["close_scope"] != "ANY"
        || !matches!(
            (r["side"].as_str(), intent["position_effect"].as_str()),
            (Some("BUY"), Some("OPEN")) | (Some("SELL"), Some("CLOSE"))
        )
        || !r["stop_price"].is_null()
        || !r["expire_time"].is_null()
    {
        return Err(err("BINANCE_SPOT_INTENT"));
    }
    let plain = |v: &Value| -> Result<String> {
        let n = v["value"]
            .as_str()
            .and_then(|s| s.parse::<BigDecimal>().ok())
            .ok_or_else(|| err("BINANCE_QUANTITY"))?;
        if n <= 0 {
            return Err(err("BINANCE_NONPOSITIVE"));
        }
        Ok(n.to_plain_string())
    };
    let mut p = BTreeMap::from([
        ("symbol".into(), symbol(c)?),
        ("side".into(), r["side"].as_str().unwrap_or("").into()),
        ("quantity".into(), plain(&r["quantity"])?),
        ("newClientOrderId".into(), wire_client(c.client())),
        ("newOrderRespType".into(), "ACK".into()),
    ]);
    match (r["order_type"].as_str(), r["time_in_force"].as_str()) {
        (Some("LIMIT"), Some(tif @ ("GTC" | "IOC" | "FOK"))) => {
            p.insert("type".into(), "LIMIT".into());
            p.insert("price".into(), plain(&r["price"])?);
            p.insert("timeInForce".into(), tif.into());
        }
        (Some("MARKET"), Some("GTC")) if r["price"].is_null() => {
            p.insert("type".into(), "MARKET".into());
        }
        _ => return Err(err("BINANCE_SPOT_ORDER_TYPE")),
    }
    Ok(p)
}
