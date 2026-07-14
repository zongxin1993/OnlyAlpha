from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest

from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyPriceType,
    OnlyRuntimeMode,
    OnlySessionType,
)
from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyInstrumentId, OnlySymbol, OnlyVenueId
from onlyalpha.domain.market import OnlyBar, OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.time import OnlyTimeZone
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.runtime.runtime import OnlyBacktestRuntime, OnlyRuntimeConfig


@pytest.fixture
def runtime_types() -> tuple[OnlyBarType, OnlyBarType]:
    instrument_id = OnlyInstrumentId(OnlySymbol("600000"), OnlyVenueId("XSHG"))
    return (
        OnlyBarType(
            instrument_id,
            OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
            OnlyAggregationSource.EXTERNAL,
        ),
        OnlyBarType(
            instrument_id,
            OnlyBarSpecification(3, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
            OnlyAggregationSource.INTERNAL,
        ),
    )


@pytest.fixture
def runtime_calendar() -> OnlyTradingCalendar:
    return OnlyTradingCalendar(
        OnlyCalendarId("XSHG"),
        OnlyVenueId("XSHG"),
        OnlyTimeZone("Asia/Shanghai"),
        (
            OnlyTradingSession("morning", time(9, 30), time(11, 30), OnlySessionType.CONTINUOUS),
            OnlyTradingSession("afternoon", time(13), time(15), OnlySessionType.CONTINUOUS),
        ),
    )


@pytest.fixture
def make_runtime(runtime_calendar: OnlyTradingCalendar) -> Callable[[str], OnlyBacktestRuntime]:
    def build(runtime_id: str) -> OnlyBacktestRuntime:
        return OnlyBacktestRuntime(
            OnlyRuntimeConfig("engine", runtime_id, OnlyRuntimeMode.BACKTEST),
            runtime_calendar,
            datetime(2026, 1, 5, 1, 30, tzinfo=UTC),
        )

    return build


@pytest.fixture
def make_runtime_bar(runtime_types: tuple[OnlyBarType, OnlyBarType]) -> Callable[[int, str], OnlyBar]:
    bar_1m, _ = runtime_types

    def build(minute: int, close: str = "10.00") -> OnlyBar:
        start = datetime(2026, 1, 5, 1, 30, tzinfo=UTC) + timedelta(minutes=minute)
        price = Decimal(close) + Decimal(minute) / Decimal(100)
        return OnlyBar(
            bar_type=bar_1m,
            open=OnlyPrice(price, 2),
            high=OnlyPrice(price + Decimal("0.10"), 2),
            low=OnlyPrice(price - Decimal("0.10"), 2),
            close=OnlyPrice(price + Decimal("0.05"), 2),
            volume=OnlyQuantity(Decimal("100"), 0),
            quote_volume=None,
            turnover=None,
            trade_count=1,
            open_interest=None,
            bar_start=start,
            bar_end=start + timedelta(minutes=1),
            ts_event=start + timedelta(minutes=1),
            ts_init=start + timedelta(minutes=1),
            is_closed=True,
            revision=0,
            adjustment_type=OnlyAdjustmentType.RAW,
            trading_day=date(2026, 1, 5),
            session_type=OnlySessionType.CONTINUOUS,
        )

    return build
