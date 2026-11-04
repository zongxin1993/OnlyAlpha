//! Binance Spot payload normalization. No storage, clock or Product authority.
use crate::spot_rest::{Error, Result};
use bigdecimal::BigDecimal;
use onlyalpha_domain::{
    base::OnlyDomainModel,
    instrument::OnlyInstrument,
    market::OnlyBar,
    numeric::{OnlyDecimal, only_quantize},
    time::OnlyTimestamp,
    value::{OnlyPrice, OnlyQuantity},
};
use serde_json::{Value, json};
use std::str::FromStr;
fn text(v: &Value) -> Result<&str> {
    v.as_str()
        .filter(|s| !s.is_empty() && s.len() <= 128)
        .ok_or(Error::Shape)
}
fn number(v: &Value) -> Result<BigDecimal> {
    let value = BigDecimal::from_str(text(v)?).map_err(|_| Error::Shape)?;
    let (coefficient, scale) = value.as_bigint_and_exponent();
    if scale.unsigned_abs() > 128 || coefficient.to_string().len() > 128 {
        return Err(Error::TooLarge);
    }
    Ok(value)
}
fn positive(v: &Value) -> Result<BigDecimal> {
    let n = number(v)?;
    if n <= 0 { Err(Error::Shape) } else { Ok(n) }
}
fn precision(v: &BigDecimal) -> Result<u8> {
    u8::try_from(v.normalized().as_bigint_and_exponent().1.max(0))
        .ok()
        .filter(|p| *p <= 18)
        .ok_or(Error::Shape)
}
fn decimal(v: &BigDecimal) -> Result<OnlyDecimal> {
    v.to_string().parse().map_err(|_| Error::Shape)
}
fn raw_decimal(v: &Value, normalize: bool) -> Result<OnlyDecimal> {
    let n = number(v)?;
    if normalize {
        let spelling = if n == 0 && text(v)?.starts_with('-') {
            "-0".into()
        } else {
            n.normalized().to_string()
        };
        spelling.parse().map_err(|_| Error::Shape)
    } else {
        text(v)?.parse().map_err(|_| Error::Shape)
    }
}
fn fixed(v: &BigDecimal, p: u8) -> Result<OnlyDecimal> {
    let v = decimal(v)?;
    let q = format!("1E-{p}").parse().map_err(|_| Error::Shape)?;
    let out = only_quantize(&v, &q).map_err(|_| Error::Shape)?;
    if out != v {
        return Err(Error::Shape);
    }
    Ok(out)
}
fn filter<'a>(filters: &'a [Value], kind: &str) -> Result<&'a Value> {
    let mut found = filters.iter().filter(|v| v["filterType"] == kind);
    let first = found.next().ok_or(Error::Shape)?;
    if found.next().is_some() {
        return Err(Error::Shape);
    }
    Ok(first)
}
pub fn instrument(raw: &Value) -> Result<OnlyInstrument> {
    let symbol = text(&raw["symbol"])?;
    if !crate::spot_rest::symbol(symbol) {
        return Err(Error::Shape);
    }
    let filters = raw["filters"].as_array().ok_or(Error::Shape)?;
    let tick = positive(&filter(filters, "PRICE_FILTER")?["tickSize"])?;
    let lot = filter(filters, "LOT_SIZE")?;
    let step = positive(&lot["stepSize"])?;
    let minimum = positive(&lot["minQty"])?;
    let price_precision = precision(&tick)?;
    let quantity_precision = precision(&step)?;
    let tick = OnlyPrice::new(fixed(&tick, price_precision)?, price_precision)
        .map_err(|_| Error::Shape)?;
    let step = OnlyQuantity::new(fixed(&step, quantity_precision)?, quantity_precision)
        .map_err(|_| Error::Shape)?;
    let minimum = OnlyQuantity::new(fixed(&minimum, quantity_precision)?, quantity_precision)
        .map_err(|_| Error::Shape)?;
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
    OnlyInstrument::from_record(&record).map_err(|_| Error::Shape)
}
/// Canonical provider-base 1m only. Event/init are the closed interval end,
/// matching the existing normalization; receive/ingest times belong to evidence.
pub fn rest_bar(raw: &Value, instrument: &OnlyInstrument) -> Result<OnlyBar> {
    rest_bar_interval(raw, instrument, 1)
}

/// Binance-native interval normalization; interval and grid are provider-owned.
pub fn rest_bar_interval(
    raw: &Value,
    instrument: &OnlyInstrument,
    minutes: u16,
) -> Result<OnlyBar> {
    let stride = crate::spot_rest::native_interval(minutes)?.1;
    let row = raw
        .as_array()
        .filter(|r| r.len() >= 11)
        .ok_or(Error::Shape)?;
    let start = row[0]
        .as_i64()
        .filter(|n| *n >= 0 && n % stride == 0)
        .ok_or(Error::Range)?;
    let end = start.checked_add(stride).ok_or(Error::Range)?;
    if row[6].as_i64() != Some(end - 1) {
        return Err(Error::Range);
    }
    let start = OnlyTimestamp::from_unix_millis(start.into())
        .to_datetime_exact()
        .map_err(|_| Error::Range)?;
    let end = OnlyTimestamp::from_unix_millis(end.into())
        .to_datetime_exact()
        .map_err(|_| Error::Range)?;
    let f = instrument.specification();
    if f.venue().value() != "BINANCE"
        || f.asset_class().as_str() != "CRYPTOCURRENCY"
        || f.instrument_type().as_str() != "CRYPTO_SPOT"
        || f.market_type().as_str() != "CASH"
    {
        return Err(Error::Shape);
    }

    let price = |v: &Value| {
        OnlyPrice::new(raw_decimal(v, true)?, *f.price_precision())
            .map(|p| p.to_record())
            .map_err(|_| Error::Shape)
    };
    let quantity = |v: &Value, p: u8| {
        OnlyQuantity::new(raw_decimal(v, true)?, p)
            .map(|q| q.to_record())
            .map_err(|_| Error::Shape)
    };
    let quote_precision = f
        .price_precision()
        .checked_add(*f.quantity_precision())
        .ok_or(Error::Shape)?;
    let count = row[8].as_i64().filter(|n| *n >= 0).ok_or(Error::Shape)?;
    let record = json!({"schema_version":1,
        "bar_type":{"schema_version":2,"instrument_id":f.instrument_id().to_record(),"semantic":{"schema_version":3,"formation":{"schema_version":1,"kind":"FIXED_DURATION","window_minutes":minutes,"stride_minutes":minutes,"alignment":"SESSION_START"},"price_type":"LAST","adjustment_policy":"RAW"}},
        "open":price(&row[1])?,"high":price(&row[2])?,"low":price(&row[3])?,"close":price(&row[4])?,
        "volume":quantity(&row[5],*f.quantity_precision())?,"quote_volume":quantity(&row[7],quote_precision)?,"turnover":null,"trade_count":count,"open_interest":null,
        "bar_start":start.to_string(),"bar_end":end.to_string(),"ts_event":end.to_string(),"ts_init":end.to_string(),"is_closed":true,"revision":0,
        "adjustment_type":"RAW","trading_day":start.date().to_string(),"session_type":"CONTINUOUS"});
    OnlyBar::from_record(&record).map_err(|_| Error::Shape)
}
pub struct Quote {
    pub instrument_id: String,
    pub last_price: String,
    pub change_pct: String,
    pub ts_event_ns: i64,
}
pub fn quote(raw: &Value) -> Result<Quote> {
    let symbol = text(&raw["symbol"])?;
    if !crate::spot_rest::symbol(symbol) {
        return Err(Error::Shape);
    }
    let _ = positive(&raw["lastPrice"])?;
    let _ = number(&raw["priceChangePercent"])?;
    let event = raw["closeTime"]
        .as_i64()
        .filter(|n| *n > 0)
        .and_then(|n| n.checked_mul(1000000))
        .ok_or(Error::Shape)?;
    Ok(Quote {
        instrument_id: format!("{symbol}.BINANCE"),
        last_price: raw_decimal(&raw["lastPrice"], false)?.to_string(),
        change_pct: raw_decimal(&raw["priceChangePercent"], false)?.to_string(),
        ts_event_ns: event,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use onlyalpha_domain::base::OnlyDomainModel;
    use serde_json::{Value, json};
    fn symbol() -> Value {
        json!({"symbol":"BTCUSDT","baseAsset":"BTC","quoteAsset":"USDT","status":"TRADING","filters":[
            {"filterType":"PRICE_FILTER","tickSize":"0.01000000"},
            {"filterType":"LOT_SIZE","stepSize":"0.00001000","minQty":"0.00001000"}
        ]})
    }
    #[test]
    fn unicode_spot_instruments_and_quotes_preserve_provider_spelling() {
        let mut raw = symbol();
        raw["symbol"] = json!("币安人生USDT");
        raw["baseAsset"] = json!("币安人生");
        let instrument = instrument(&raw).unwrap();
        assert_eq!(
            instrument.specification().instrument_id().to_string(),
            "币安人生USDT.BINANCE"
        );
        assert_eq!(
            instrument
                .specification()
                .base_currency()
                .as_ref()
                .unwrap()
                .code(),
            "币安人生"
        );
        assert_eq!(
            OnlyInstrument::from_record(&instrument.to_record()).unwrap(),
            instrument
        );
        let value = quote(&json!({"symbol":"币安人生USDT","lastPrice":"1.00","priceChangePercent":"0","closeTime":1})).unwrap();
        assert_eq!(value.instrument_id, "币安人生USDT.BINANCE");
    }
    fn row() -> Value {
        json!([
            0,
            "10.000",
            "11.0",
            "9.00000",
            "10.5000",
            "1.230000",
            59999,
            "12.915000",
            3,
            "0",
            "0",
            "0"
        ])
    }
    #[test]
    fn exchange_filters_and_rest_bar_use_the_original_canonical_domain() {
        let i = instrument(&symbol()).unwrap();
        let r = i.to_record();
        assert_eq!(r["model_type"], "OnlyInstrument");
        assert_eq!(r["price_precision"], 2);
        assert_eq!(r["quantity_precision"], 5);
        assert_eq!(
            r["tick_size"],
            json!({"schema_version":1,"value":"0.01","precision":2})
        );
        assert_eq!(
            r["step_size"],
            json!({"schema_version":1,"value":"0.00001","precision":5})
        );
        let b = rest_bar(&row(), &i).unwrap().to_record();
        assert_eq!(
            b["open"],
            json!({"schema_version":1,"value":"10","precision":2})
        );
        assert_eq!(
            b["close"],
            json!({"schema_version":1,"value":"10.5","precision":2})
        );
        assert_eq!(
            b["volume"],
            json!({"schema_version":1,"value":"1.23","precision":5})
        );
        assert_eq!(
            b["quote_volume"],
            json!({"schema_version":1,"value":"12.915","precision":7})
        );
        assert_eq!(b["bar_start"], "1970-01-01T00:00:00Z");
        assert_eq!(b["bar_end"], "1970-01-01T00:01:00Z");
        assert_eq!(b["ts_event"], b["bar_end"]);
        assert_eq!(b["ts_init"], b["bar_end"]);
        assert_eq!(b["session_type"], "CONTINUOUS");
        assert_eq!(b["revision"], 0);
        assert_eq!(b["is_closed"], true);
        assert_eq!(b["bar_type"]["semantic"]["formation"]["window_minutes"], 1);
    }
    #[test]
    fn invalid_market_payloads_never_become_canonical_bars() {
        let i = instrument(&symbol()).unwrap();
        for (index, value) in [
            (0, json!(-1)),
            (0, json!(1)),
            (1, json!("NaN")),
            (1, json!("1E+999999999")),
            (1, json!("10.001")),
            (2, json!("8")),
            (5, json!("-1")),
            (8, json!(-1)),
            (8, json!(true)),
        ] {
            let mut r = row();
            r[index] = value;
            assert!(rest_bar(&r, &i).is_err());
        }
        let mut s = symbol();
        s["filters"][0]["tickSize"] = json!("0");
        assert!(instrument(&s).is_err());
        let mut s = symbol();
        s["filters"][1]["stepSize"] = json!("1E-100000000");
        assert!(instrument(&s).is_err());
        let mut s = symbol();
        let duplicate = s["filters"][0].clone();
        s["filters"].as_array_mut().unwrap().push(duplicate);
        assert!(instrument(&s).is_err());
    }
    #[test]
    fn quotes_keep_provider_scale_and_explicit_event_time() {
        let q=quote(&json!({"symbol":"BTCUSDT","lastPrice":"83547.33000000","priceChangePercent":"-0.614","closeTime":1800000000123_i64})).unwrap();
        assert_eq!(q.instrument_id, "BTCUSDT.BINANCE");
        assert_eq!(q.last_price, "83547.33000000");
        assert_eq!(q.change_pct, "-0.614");
        assert_eq!(q.ts_event_ns, 1800000000123000000_i64);
        assert!(
            quote(
                &json!({"symbol":"BTCUSDT","lastPrice":"0","priceChangePercent":"1","closeTime":1})
            )
            .is_err()
        );
    }
    #[test]
    fn signed_zero_and_foreign_instruments_keep_distinct_meanings() {
        let i = instrument(&symbol()).unwrap();
        let mut r = row();
        for index in [1, 3, 4, 5, 7] {
            r[index] = json!("-0.000");
        }
        let b = rest_bar(&r, &i).unwrap().to_record();
        assert_eq!(b["open"]["value"], "-0");
        assert_eq!(b["volume"]["value"], "-0");
        let mut foreign = i.to_record();
        foreign["instrument_id"]["venue"]["value"] = json!("X");
        let foreign = OnlyInstrument::from_record(&foreign).unwrap();
        assert!(rest_bar(&row(), &foreign).is_err());
        let q=quote(&json!({"symbol":"BTCUSDT","lastPrice":"1.00","priceChangePercent":"-0.000","closeTime":1})).unwrap();
        assert_eq!(q.change_pct, "-0.000");
    }
}
