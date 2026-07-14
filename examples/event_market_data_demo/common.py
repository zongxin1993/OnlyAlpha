"""Shared deterministic fixtures for Event/MarketData demos."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from onlyalpha.cluster.base import OnlyCluster, OnlyClusterConfig
from onlyalpha.core.clock import OnlyClockView, OnlyVirtualClock
from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyPriceType,
    OnlySessionType,
)
from onlyalpha.domain.identifiers import (
    OnlyCalendarId,
    OnlyEngineId,
    OnlyInstrumentId,
    OnlyRuntimeId,
    OnlySymbol,
    OnlyVenueId,
)
from onlyalpha.domain.market import OnlyBar, OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.time import OnlyTimeZone
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.indicator.pipeline import OnlyIndicatorPipeline
from onlyalpha.market_data.aggregation.manager import OnlyBarAggregationManager
from onlyalpha.market_data.cache import OnlyMarketDataCache
from onlyalpha.market_data.dispatcher import OnlyStrategyBarDispatcher
from onlyalpha.market_data.pipeline import OnlyMarketDataPipeline


class OnlyDemoBarCluster(OnlyCluster):
    def __init__(self, cluster_id: str) -> None:
        super().__init__(OnlyClusterConfig(cluster_id))
        self.calls: list[str] = []

    def on_bar(self, bar: OnlyBar, context) -> None:
        updated = ",".join(
            f"{item.specification.step}m"
            for item in sorted(context.snapshot.updated_bar_types, key=lambda value: value.specification.step)
        )
        line = f"{bar.bar_end:%H:%M} {self.config.cluster_id} primary={bar.bar_type.specification.step}m updated={{{updated}}}"
        self.calls.append(line)
        print(line)


def only_demo_types() -> tuple[OnlyBarType, OnlyBarType]:
    instrument_id = OnlyInstrumentId(OnlySymbol("600000"), OnlyVenueId("XSHG"))
    base = OnlyBarType(
        instrument_id,
        OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
        OnlyAggregationSource.EXTERNAL,
    )
    derived = OnlyBarType(
        instrument_id,
        OnlyBarSpecification(3, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
        OnlyAggregationSource.INTERNAL,
    )
    return base, derived


def only_demo_bar(bar_type: OnlyBarType, minute: int) -> OnlyBar:
    start = datetime(2026, 1, 5, 1, 30, tzinfo=UTC) + timedelta(minutes=minute)
    price = Decimal("10.00") + Decimal(minute) / Decimal(100)
    return OnlyBar(
        bar_type=bar_type,
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


def only_demo_system() -> tuple[OnlyMarketDataPipeline, OnlyStrategyBarDispatcher, OnlyBarAggregationManager]:
    clock = OnlyVirtualClock(datetime(2026, 1, 5, 7, 0, tzinfo=UTC))
    calendar = OnlyTradingCalendar(
        OnlyCalendarId("XSHG"),
        OnlyVenueId("XSHG"),
        OnlyTimeZone("Asia/Shanghai"),
        (
            OnlyTradingSession("morning", time(9, 30), time(11, 30), OnlySessionType.CONTINUOUS),
            OnlyTradingSession("afternoon", time(13), time(15), OnlySessionType.CONTINUOUS),
        ),
    )
    manager = OnlyBarAggregationManager(calendar, clock)
    pipeline = OnlyMarketDataPipeline(
        OnlyEngineId("engine"),
        OnlyRuntimeId("runtime"),
        clock,
        OnlyMarketDataCache(),
        manager,
        OnlyIndicatorPipeline(),
    )
    return pipeline, OnlyStrategyBarDispatcher(pipeline, OnlyClockView(clock)), manager
