"""Pure Binance payload to provider-neutral canonical fact normalization."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from onlyalpha.domain.enums import OnlyAdjustmentType, OnlyOrderSide, OnlySessionType
from onlyalpha.domain.identifiers import OnlyTradeId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.market import (
    OnlyBar,
    OnlyBarType,
    OnlyMarketReferenceKind,
    OnlyMarketReferenceTick,
    OnlyTradeTick,
)
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha_plugin_binance.errors import OnlyBinanceError

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def only_binance_milliseconds(value: object) -> datetime:
    milliseconds = int(str(value))
    if milliseconds < 0:
        raise OnlyBinanceError("BINANCE_TIMESTAMP_INVALID")
    return _EPOCH + timedelta(milliseconds=milliseconds)


def only_normalize_rest_kline(raw: Sequence[object], instrument: OnlyInstrument, bar_type: OnlyBarType) -> OnlyBar:
    if len(raw) < 11:
        raise OnlyBinanceError("BINANCE_KLINE_SHAPE_INVALID")
    return _bar(
        instrument,
        bar_type,
        start=raw[0],
        open_value=raw[1],
        high=raw[2],
        low=raw[3],
        close=raw[4],
        volume=raw[5],
        quote_volume=raw[7],
        trade_count=raw[8],
    )


def only_normalize_ws_kline(
    raw: Mapping[str, object], instrument: OnlyInstrument, bar_type: OnlyBarType
) -> OnlyBar | None:
    if raw.get("x") is not True:
        return None
    return _bar(
        instrument,
        bar_type,
        start=raw["t"],
        open_value=raw["o"],
        high=raw["h"],
        low=raw["l"],
        close=raw["c"],
        volume=raw["v"],
        quote_volume=raw["q"],
        trade_count=raw["n"],
    )


def _bar(
    instrument: OnlyInstrument,
    bar_type: OnlyBarType,
    *,
    start: object,
    open_value: object,
    high: object,
    low: object,
    close: object,
    volume: object,
    quote_volume: object,
    trade_count: object,
) -> OnlyBar:
    bar_start = only_binance_milliseconds(start)
    bar_end = bar_start + timedelta(minutes=1)
    return OnlyBar(
        bar_type=bar_type,
        open=OnlyPrice(Decimal(str(open_value)), instrument.price_precision),
        high=OnlyPrice(Decimal(str(high)), instrument.price_precision),
        low=OnlyPrice(Decimal(str(low)), instrument.price_precision),
        close=OnlyPrice(Decimal(str(close)), instrument.price_precision),
        volume=OnlyQuantity(Decimal(str(volume)), instrument.quantity_precision),
        quote_volume=OnlyQuantity(
            Decimal(str(quote_volume)), instrument.price_precision + instrument.quantity_precision
        ),
        turnover=None,
        trade_count=int(str(trade_count)),
        open_interest=None,
        bar_start=bar_start,
        bar_end=bar_end,
        ts_event=bar_end,
        ts_init=bar_end,
        is_closed=True,
        revision=0,
        adjustment_type=OnlyAdjustmentType.RAW,
        trading_day=bar_start.date(),
        session_type=OnlySessionType.CONTINUOUS,
    )


def only_normalize_rest_trade(raw: Mapping[str, object], instrument: OnlyInstrument) -> OnlyTradeTick:
    return _trade(
        instrument,
        trade_id=raw["id"],
        price=raw["price"],
        quantity=raw["qty"],
        event_time=raw["time"],
        buyer_maker=raw["isBuyerMaker"],
    )


def only_normalize_ws_trade(raw: Mapping[str, object], instrument: OnlyInstrument) -> OnlyTradeTick:
    return _trade(
        instrument,
        trade_id=raw["t"],
        price=raw["p"],
        quantity=raw["q"],
        event_time=raw["T"],
        buyer_maker=raw["m"],
    )


def _trade(
    instrument: OnlyInstrument,
    *,
    trade_id: object,
    price: object,
    quantity: object,
    event_time: object,
    buyer_maker: object,
) -> OnlyTradeTick:
    if not isinstance(buyer_maker, bool):
        raise OnlyBinanceError("BINANCE_TRADE_MAKER_FLAG_INVALID")
    ts_event = only_binance_milliseconds(event_time)
    venue_trade_id = int(str(trade_id))
    return OnlyTradeTick(
        instrument_id=instrument.instrument_id,
        ts_event=ts_event,
        ts_init=ts_event,
        sequence=venue_trade_id,
        source="BINANCE_SPOT",
        price=OnlyPrice(Decimal(str(price)), instrument.price_precision),
        quantity=OnlyQuantity(Decimal(str(quantity)), instrument.quantity_precision),
        aggressor_side=OnlyOrderSide.SELL if buyer_maker else OnlyOrderSide.BUY,
        trade_id=OnlyTradeId(str(venue_trade_id)),
    )


def only_normalize_reference_price(raw: Mapping[str, object], instrument: OnlyInstrument) -> OnlyMarketReferenceTick:
    """Normalize only Binance's declared reference-price REST/stream fact."""
    if raw.get("e") == "referencePrice":
        if "s" not in raw or "r" not in raw or "t" not in raw:
            raise OnlyBinanceError("BINANCE_REFERENCE_PRICE_EVENT_INVALID")
        symbol_raw = raw["s"]
        event_raw = raw["t"]
        price_raw = raw["r"]
    elif "e" not in raw and {"symbol", "referencePrice", "timestamp"} <= raw.keys():
        symbol_raw = raw["symbol"]
        event_raw = raw["timestamp"]
        price_raw = raw["referencePrice"]
    else:
        raise OnlyBinanceError("BINANCE_REFERENCE_PRICE_PAYLOAD_INVALID")
    if str(symbol_raw).upper() != str(instrument.raw_symbol).upper():
        raise OnlyBinanceError("BINANCE_REFERENCE_PRICE_SYMBOL_MISMATCH")
    ts_event = only_binance_milliseconds(event_raw)
    return OnlyMarketReferenceTick(
        instrument_id=instrument.instrument_id,
        ts_event=ts_event,
        ts_init=ts_event,
        sequence=int(str(event_raw)),
        source="BINANCE_SPOT",
        reference_kind=OnlyMarketReferenceKind.VENUE_REFERENCE_PRICE,
        price=None if price_raw is None else OnlyPrice(Decimal(str(price_raw)), instrument.price_precision),
    )
