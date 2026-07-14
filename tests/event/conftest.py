from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

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


@pytest.fixture
def instrument_id() -> OnlyInstrumentId:
    return OnlyInstrumentId(OnlySymbol("600000"), OnlyVenueId("XSHG"))


@pytest.fixture
def closed_bar(instrument_id: OnlyInstrumentId) -> OnlyBar:
    start = datetime(2026, 1, 5, 1, 30, tzinfo=UTC)
    return OnlyBar(
        bar_type=OnlyBarType(
            instrument_id,
            OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
            OnlyAggregationSource.EXTERNAL,
        ),
        open=OnlyPrice(Decimal("10.00"), 2),
        high=OnlyPrice(Decimal("10.10"), 2),
        low=OnlyPrice(Decimal("9.90"), 2),
        close=OnlyPrice(Decimal("10.05"), 2),
        volume=OnlyQuantity(Decimal("100"), 0),
        quote_volume=None,
        turnover=None,
        trade_count=1,
        open_interest=None,
        bar_start=start,
        bar_end=datetime(2026, 1, 5, 1, 31, tzinfo=UTC),
        ts_event=datetime(2026, 1, 5, 1, 31, tzinfo=UTC),
        ts_init=datetime(2026, 1, 5, 1, 31, tzinfo=UTC),
        is_closed=True,
        revision=0,
        adjustment_type=OnlyAdjustmentType.RAW,
        trading_day=date(2026, 1, 5),
        session_type=OnlySessionType.CONTINUOUS,
    )
