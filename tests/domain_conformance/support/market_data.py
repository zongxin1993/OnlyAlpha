"""Market data fixtures with explicit event and initialization timestamps."""

from datetime import UTC, date, datetime
from decimal import Decimal

from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyOrderSide,
    OnlyPriceType,
    OnlySessionType,
)
from onlyalpha.domain.identifiers import OnlyTradeId
from onlyalpha.domain.market import OnlyBar, OnlyBarSpecification, OnlyBarType, OnlyQuoteTick, OnlyTradeTick
from onlyalpha.domain.value import OnlyMoney, OnlyPrice, OnlyQuantity
from tests.domain_conformance.support.instruments import build_instruments

NOW = datetime(2026, 1, 5, 1, 31, tzinfo=UTC)


def build_trade_tick() -> OnlyTradeTick:
    instrument = build_instruments()["a_share"]
    return OnlyTradeTick(
        instrument.instrument_id,
        NOW,
        NOW,
        1,
        "fixture",
        OnlyPrice(Decimal("10.00"), 2),
        OnlyQuantity(Decimal("100"), 0),
        OnlyOrderSide.BUY,
        OnlyTradeId("trade-tick-1"),
    )


def build_quote_tick() -> OnlyQuoteTick:
    instrument = build_instruments()["a_share"]
    return OnlyQuoteTick(
        instrument.instrument_id,
        NOW,
        NOW,
        2,
        "fixture",
        OnlyPrice(Decimal("9.99"), 2),
        OnlyQuantity(Decimal("100"), 0),
        OnlyPrice(Decimal("10.01"), 2),
        OnlyQuantity(Decimal("200"), 0),
    )


def build_bar() -> OnlyBar:
    instrument = build_instruments()["a_share"]
    start = datetime(2026, 1, 5, 1, 30, tzinfo=UTC)
    return OnlyBar(
        bar_type=OnlyBarType(
            instrument.instrument_id,
            OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
            OnlyAggregationSource.EXTERNAL,
        ),
        open=OnlyPrice(Decimal("10.00"), 2),
        high=OnlyPrice(Decimal("10.10"), 2),
        low=OnlyPrice(Decimal("9.90"), 2),
        close=OnlyPrice(Decimal("10.05"), 2),
        volume=OnlyQuantity(Decimal("100"), 0),
        quote_volume=OnlyQuantity(Decimal("1000"), 0),
        turnover=OnlyMoney(Decimal("1000.00"), instrument.quote_currency),
        trade_count=10,
        open_interest=None,
        bar_start=start,
        bar_end=NOW,
        ts_event=NOW,
        ts_init=NOW,
        is_closed=True,
        revision=0,
        adjustment_type=OnlyAdjustmentType.RAW,
        trading_day=date(2026, 1, 5),
        session_type=OnlySessionType.REGULAR,
    )
