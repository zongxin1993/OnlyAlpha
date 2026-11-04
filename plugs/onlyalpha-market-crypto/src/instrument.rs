use bigdecimal::BigDecimal;
use onlyalpha_domain::{
    base::OnlyDomainModel, instrument::OnlyInstrument, numeric::{OnlyDecimal, only_quantize},
    value::{OnlyPrice, OnlyQuantity},
};
use serde_json::{Value, json};
use std::str::FromStr;

#[derive(Clone, Copy, Debug)]
pub enum InstrumentError {
    Shape,
    TooLarge,
}
impl std::fmt::Display for InstrumentError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(match self { Self::Shape => "BINANCE_PUBLIC_RESPONSE_SHAPE_INVALID", Self::TooLarge => "BINANCE_PUBLIC_RESPONSE_TOO_LARGE" })
    }
}
type Result<T> = std::result::Result<T, InstrumentError>;

fn symbol_is_valid(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 64
        && value
            .chars()
            .all(|c| c.is_alphanumeric() && !c.is_lowercase())
}

fn text(v: &Value) -> Result<&str> {
    v.as_str()
        .filter(|s| !s.is_empty() && s.len() <= 128)
        .ok_or(InstrumentError::Shape)
}
fn number(v: &Value) -> Result<BigDecimal> {
    let value = BigDecimal::from_str(text(v)?).map_err(|_| InstrumentError::Shape)?;
    let (coefficient, scale) = value.as_bigint_and_exponent();
    if scale.unsigned_abs() > 128 || coefficient.to_string().len() > 128 {
        return Err(InstrumentError::TooLarge);
    }
    Ok(value)
}
fn positive(v: &Value) -> Result<BigDecimal> {
    let n = number(v)?;
    if n <= 0 { Err(InstrumentError::Shape) } else { Ok(n) }
}
fn precision(v: &BigDecimal) -> Result<u8> {
    u8::try_from(v.normalized().as_bigint_and_exponent().1.max(0))
        .ok()
        .filter(|p| *p <= 18)
        .ok_or(InstrumentError::Shape)
}
fn decimal(v: &BigDecimal) -> Result<OnlyDecimal> {
    v.to_string().parse().map_err(|_| InstrumentError::Shape)
}
fn fixed(v: &BigDecimal, p: u8) -> Result<OnlyDecimal> {
    let v = decimal(v)?;
    let q = format!("1E-{p}").parse().map_err(|_| InstrumentError::Shape)?;
    let out = only_quantize(&v, &q).map_err(|_| InstrumentError::Shape)?;
    if out != v {
        return Err(InstrumentError::Shape);
    }
    Ok(out)
}
fn filter<'a>(filters: &'a [Value], kind: &str) -> Result<&'a Value> {
    let mut found = filters.iter().filter(|v| v["filterType"] == kind);
    let first = found.next().ok_or(InstrumentError::Shape)?;
    if found.next().is_some() {
        return Err(InstrumentError::Shape);
    }
    Ok(first)
}
pub fn instrument(raw: &Value) -> Result<OnlyInstrument> {
    let symbol = text(&raw["symbol"])?;
    if !symbol_is_valid(symbol) {
        return Err(InstrumentError::Shape);
    }
    let filters = raw["filters"].as_array().ok_or(InstrumentError::Shape)?;
    let tick = positive(&filter(filters, "PRICE_FILTER")?["tickSize"])?;
    let lot = filter(filters, "LOT_SIZE")?;
    let step = positive(&lot["stepSize"])?;
    let minimum = positive(&lot["minQty"])?;
    let price_precision = precision(&tick)?;
    let quantity_precision = precision(&step)?;
    let tick = OnlyPrice::new(fixed(&tick, price_precision)?, price_precision)
        .map_err(|_| InstrumentError::Shape)?;
    let step = OnlyQuantity::new(fixed(&step, quantity_precision)?, quantity_precision)
        .map_err(|_| InstrumentError::Shape)?;
    let minimum = OnlyQuantity::new(fixed(&minimum, quantity_precision)?, quantity_precision)
        .map_err(|_| InstrumentError::Shape)?;
    let quote = json!({"schema_version":1,"code":text(&raw["quoteAsset"])?,"precision":price_precision,"currency_type":"CRYPTO"});
    let record = json!({"schema_version":2,"model_type":"OnlyInstrument",
        "instrument_id":{"schema_version":1,"symbol":{"schema_version":1,"value":symbol},"venue":{"schema_version":1,"value":"BINANCE"}},
        "raw_symbol":{"schema_version":1,"value":symbol},"asset_class":"CRYPTOCURRENCY","instrument_type":"CRYPTO_SPOT","market_type":"CASH",
        "quote_currency":quote,"settlement_currency":quote,"price_precision":price_precision,"quantity_precision":quantity_precision,
        "tick_size":tick.to_record(),"step_size":step.to_record(),"contract_multiplier":{"schema_version":1,"value":"1","precision":0},
        "base_currency":{"schema_version":1,"code":text(&raw["baseAsset"])?,"precision":quantity_precision,"currency_type":"CRYPTO"},
        "margin_currency":null,"minimum_quantity":minimum.to_record(),"maximum_quantity":null,"minimum_notional":null,"maximum_notional":null,
        "minimum_price":null,"maximum_price":null,"lot_size":null,"instrument_version":1,"activation_time":null,"effective_from":null,"effective_to":null,
        "timezone":"UTC","trading_calendar_id":null,"session_profile_id":null,"status":match raw["status"].as_str(){Some("TRADING")=>"ACTIVE",Some("HALT"|"BREAK")=>"HALTED",_=>"SUSPENDED"}});
    OnlyInstrument::from_record(&record).map_err(|_| InstrumentError::Shape)
}
