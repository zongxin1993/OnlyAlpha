from datetime import UTC, date, datetime
from decimal import Decimal

from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyPriceType,
    OnlySessionType,
)
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlySymbol, OnlyVenueId
from onlyalpha.domain.market import OnlyBar, OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity


def test_one_minute_bar_is_half_open() -> None:
    start = datetime(2026, 7, 13, 1, 30, tzinfo=UTC)
    end = datetime(2026, 7, 13, 1, 31, tzinfo=UTC)
    price = OnlyPrice(Decimal("10.00"), 2)
    bar = OnlyBar(
        bar_type=OnlyBarType(
            OnlyInstrumentId(OnlySymbol("600000"), OnlyVenueId("XSHG")),
            OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
            OnlyAggregationSource.INTERNAL,
        ),
        open=price,
        high=price,
        low=price,
        close=price,
        volume=OnlyQuantity(Decimal("100"), 0),
        quote_volume=None,
        turnover=None,
        trade_count=1,
        open_interest=None,
        bar_start=start,
        bar_end=end,
        ts_event=end,
        ts_init=end,
        is_closed=True,
        revision=0,
        adjustment_type=OnlyAdjustmentType.RAW,
        trading_day=date(2026, 7, 13),
        session_type=OnlySessionType.CONTINUOUS,
    )
    assert bar.contains(start)
    assert bar.contains(datetime(2026, 7, 13, 1, 30, 59, 999999, tzinfo=UTC))
    assert not bar.contains(end)
