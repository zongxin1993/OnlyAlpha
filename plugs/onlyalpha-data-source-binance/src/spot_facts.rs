//! Spot 原始成交与场所参考价格的纯转换；调用者仍须先持久化原始响应。
use crate::spot_rest::{Error, Result};
use onlyalpha_domain::{
    enums::OnlyOrderSide,
    instrument::OnlyInstrument,
    market::{
        OnlyMarketReferenceKind, OnlyMarketReferenceTick, OnlyMarketReferenceTickInput,
        OnlyTradeTick, OnlyTradeTickInput,
    },
    time::{OnlyTimestamp, OnlyUtcDateTime},
    value::{OnlyPrice, OnlyQuantity},
};
use serde_json::Value;

pub(crate) fn milliseconds(value: &Value) -> Result<OnlyUtcDateTime> {
    let n = value.as_i64().filter(|n| *n >= 0).ok_or(Error::Shape)?;
    OnlyTimestamp::from_unix_millis(n.into())
        .to_datetime_exact()
        .map_err(|_| Error::Range)
}
fn check(instrument: &OnlyInstrument) -> Result<()> {
    let f = instrument.specification();
    if f.venue().value() != "BINANCE"
        || f.instrument_type().as_str() != "CRYPTO_SPOT"
        || f.market_type().as_str() != "CASH"
    {
        return Err(Error::Shape);
    }
    Ok(())
}
fn trade(raw: &Value, instrument: &OnlyInstrument, websocket: bool) -> Result<OnlyTradeTick> {
    check(instrument)?;
    if websocket
        && (raw["e"] != "trade"
            || raw["s"].as_str() != Some(instrument.specification().raw_symbol().value()))
    {
        return Err(Error::Shape);
    }
    let fields = if websocket {
        ["t", "p", "q", "T", "m"]
    } else {
        ["id", "price", "qty", "time", "isBuyerMaker"]
    };
    let sequence = raw[fields[0]]
        .as_i64()
        .filter(|n| *n >= 0)
        .ok_or(Error::Shape)?;
    let maker = raw[fields[4]].as_bool().ok_or(Error::Shape)?;
    let ts_event = milliseconds(&raw[fields[3]])?;
    let f = instrument.specification();
    OnlyTradeTick::new(OnlyTradeTickInput {
        instrument_id: f.instrument_id().clone(),
        ts_event,
        ts_init: ts_event,
        sequence: sequence.into(),
        source: "BINANCE_SPOT".into(),
        price: OnlyPrice::new(
            crate::spot_normalize::raw_decimal(&raw[fields[1]], true)?,
            *f.price_precision(),
        )
        .map_err(|_| Error::Shape)?,
        quantity: OnlyQuantity::new(
            crate::spot_normalize::raw_decimal(&raw[fields[2]], true)?,
            *f.quantity_precision(),
        )
        .map_err(|_| Error::Shape)?,
        aggressor_side: Some(if maker {
            OnlyOrderSide::Sell
        } else {
            OnlyOrderSide::Buy
        }),
        trade_id: sequence.to_string().parse().map_err(|_| Error::Shape)?,
    })
    .map_err(|_| Error::Shape)
}
/// `/api/v3/historicalTrades` 的原始成交，不接受 aggTrade 替代成交身份。
pub fn rest_trade(raw: &Value, instrument: &OnlyInstrument) -> Result<OnlyTradeTick> {
    trade(raw, instrument, false)
}
/// `@trade`，校验事件种类和精确标的后保留 provider trade ID。
pub fn websocket_trade(raw: &Value, instrument: &OnlyInstrument) -> Result<OnlyTradeTick> {
    trade(raw, instrument, true)
}
/// 仅接受 referencePrice 声明；null 表示场所当前没有参考值，不是零价。
pub fn reference_price(
    raw: &Value,
    instrument: &OnlyInstrument,
) -> Result<OnlyMarketReferenceTick> {
    check(instrument)?;
    let fields = if raw["e"] == "referencePrice" {
        ["s", "r", "t"]
    } else if raw.get("e").is_none() && raw.get("referencePrice").is_some() {
        ["symbol", "referencePrice", "timestamp"]
    } else {
        return Err(Error::Shape);
    };
    if raw[fields[0]].as_str() != Some(instrument.specification().raw_symbol().value()) {
        return Err(Error::Shape);
    }
    let ts_event = milliseconds(&raw[fields[2]])?;
    let value = raw.get(fields[1]).ok_or(Error::Shape)?;
    let price = if value.is_null() {
        None
    } else {
        Some(
            OnlyPrice::new(
                crate::spot_normalize::raw_decimal(value, true)?,
                *instrument.specification().price_precision(),
            )
            .map_err(|_| Error::Shape)?,
        )
    };
    OnlyMarketReferenceTick::new(OnlyMarketReferenceTickInput {
        instrument_id: instrument.specification().instrument_id().clone(),
        ts_event,
        ts_init: ts_event,
        sequence: raw[fields[2]].as_i64().ok_or(Error::Shape)?.into(),
        source: "BINANCE_SPOT".into(),
        reference_kind: OnlyMarketReferenceKind::VenueReferencePrice,
        price,
    })
    .map_err(|_| Error::Shape)
}
