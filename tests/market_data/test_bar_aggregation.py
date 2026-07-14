from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import pytest

from onlyalpha.core.clock import OnlyVirtualClock
from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import OnlySessionType
from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyVenueId
from onlyalpha.domain.time import OnlyTimeZone
from onlyalpha.market_data.aggregation.manager import OnlyBarAggregationManager
from onlyalpha.market_data.aggregation.time_bar import OnlyBarAggregationError
from onlyalpha.market_data.subscriptions import OnlyBarSubscription, OnlyMissingBarPolicy


def test_1m_to_3m_is_calendar_aligned(shanghai_calendar, bar_1m, bar_3m, make_bar) -> None:
    clock = OnlyVirtualClock(datetime(2026, 1, 5, 7, 0, tzinfo=UTC))
    manager = OnlyBarAggregationManager(shanghai_calendar, clock)
    manager.register_subscription(OnlyBarSubscription((bar_1m, bar_3m)))
    assert manager.process(make_bar(0)) == ()
    assert manager.process(make_bar(1)) == ()
    derived = manager.process(make_bar(2))
    assert len(derived) == 1
    bar = derived[0]
    assert bar.bar_start == datetime(2026, 1, 5, 1, 30, tzinfo=UTC)
    assert bar.bar_end == datetime(2026, 1, 5, 1, 33, tzinfo=UTC)
    assert bar.open.value == Decimal("10.00")
    assert bar.close.value == Decimal("10.07")
    assert bar.volume.value == Decimal("300")
    assert bar.trade_count == 3


def test_multiple_derived_bars_have_stable_duration_order(
    shanghai_calendar, bar_1m, bar_3m, bar_5m, bar_15m, make_bar
) -> None:
    manager = OnlyBarAggregationManager(
        shanghai_calendar,
        OnlyVirtualClock(datetime(2026, 1, 5, 7, 0, tzinfo=UTC)),
    )
    manager.register_subscription(OnlyBarSubscription((bar_15m, bar_5m, bar_3m, bar_1m)))
    results = []
    for minute in range(15):
        results = list(manager.process(make_bar(minute)))
    assert [item.bar_type for item in results] == [bar_3m, bar_5m, bar_15m]


def test_multi_cluster_registration_reuses_same_aggregator(shanghai_calendar, bar_1m, bar_3m) -> None:
    manager = OnlyBarAggregationManager(
        shanghai_calendar,
        OnlyVirtualClock(datetime(2026, 1, 5, 7, 0, tzinfo=UTC)),
    )
    subscription = OnlyBarSubscription((bar_1m, bar_3m))
    manager.register_subscription(subscription)
    manager.register_subscription(subscription)
    assert manager.aggregator_count == 1
    assert manager.creation_count == 1


def test_missing_source_bar_rejects_window(shanghai_calendar, bar_1m, bar_3m, make_bar) -> None:
    manager = OnlyBarAggregationManager(
        shanghai_calendar,
        OnlyVirtualClock(datetime(2026, 1, 5, 7, 0, tzinfo=UTC)),
        missing_policy=OnlyMissingBarPolicy.REJECT,
    )
    manager.register_subscription(OnlyBarSubscription((bar_1m, bar_3m)))
    manager.process(make_bar(0))
    with pytest.raises(OnlyBarAggregationError, match="gap"):
        manager.process(make_bar(2))


def test_afternoon_bars_anchor_at_afternoon_session_not_morning(shanghai_calendar, bar_1m, bar_3m) -> None:
    from dataclasses import replace
    from datetime import date, timedelta

    manager = OnlyBarAggregationManager(
        shanghai_calendar,
        OnlyVirtualClock(datetime(2026, 1, 5, 7, 0, tzinfo=UTC)),
    )
    manager.register_subscription(OnlyBarSubscription((bar_1m, bar_3m)))
    start = datetime(2026, 1, 5, 5, 0, tzinfo=UTC)
    bars = []
    for minute in range(3):
        bar = replace(
            _base_bar(bar_1m, start + timedelta(minutes=minute)),
            trading_day=date(2026, 1, 5),
        )
        bars.extend(manager.process(bar))
    assert len(bars) == 1
    assert bars[0].bar_start == start
    assert bars[0].bar_end == start + timedelta(minutes=3)


def _base_bar(bar_type, start):
    from datetime import date, timedelta

    from onlyalpha.domain.enums import OnlyAdjustmentType, OnlySessionType
    from onlyalpha.domain.market import OnlyBar
    from onlyalpha.domain.value import OnlyPrice, OnlyQuantity

    return OnlyBar(
        bar_type=bar_type,
        open=OnlyPrice(Decimal("10.00"), 2),
        high=OnlyPrice(Decimal("10.10"), 2),
        low=OnlyPrice(Decimal("9.90"), 2),
        close=OnlyPrice(Decimal("10.00"), 2),
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


def test_incomplete_session_tail_is_dropped_without_partial_bar(bar_1m, bar_3m) -> None:
    short_calendar = OnlyTradingCalendar(
        OnlyCalendarId("SHORT"),
        OnlyVenueId("XSHG"),
        OnlyTimeZone("Asia/Shanghai"),
        (OnlyTradingSession("short", time(9, 30), time(9, 34), OnlySessionType.CONTINUOUS),),
    )
    manager = OnlyBarAggregationManager(
        short_calendar,
        OnlyVirtualClock(datetime(2026, 1, 5, 7, 0, tzinfo=UTC)),
    )
    manager.register_subscription(OnlyBarSubscription((bar_1m, bar_3m)))
    results = []
    start = datetime(2026, 1, 5, 1, 30, tzinfo=UTC)
    for minute in range(4):
        results.append(manager.process(_base_bar(bar_1m, start + timedelta(minutes=minute))))
    assert [len(item) for item in results] == [0, 0, 1, 0]
