from datetime import UTC, datetime, time
from decimal import Decimal

from onlyalpha.cluster.base import OnlyCluster, OnlyClusterConfig
from onlyalpha.core.clock import OnlyClockView
from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import OnlyRuntimeMode, OnlySessionType
from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyClusterId, OnlyVenueId
from onlyalpha.domain.time import OnlyTimeZone
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime
from onlyalpha.runtime.runtime import OnlyRuntimeAssemblyConfig


def test_cluster_receives_clock_view_without_advancement_capability() -> None:
    currency = OnlyCurrency("CNY", 2)
    capital = OnlyMoney(Decimal("1000000.00"), currency)
    runtime = OnlyBacktestRuntime(
        OnlyRuntimeAssemblyConfig(
            "engine",
            "runtime",
            OnlyRuntimeMode.BACKTEST,
            strategy_base_currency=currency,
            strategy_capitals={OnlyClusterId("cluster"): capital},
            account_initial_cash=capital,
        ),
        OnlyTradingCalendar(
            OnlyCalendarId("TEST"),
            OnlyVenueId("TEST"),
            OnlyTimeZone("UTC"),
            (OnlyTradingSession("all", time(0), time(0), OnlySessionType.CONTINUOUS),),
            weekend_days=(),
        ),
        datetime(2026, 1, 1, tzinfo=UTC),
    )
    cluster = OnlyCluster(OnlyClusterConfig("cluster"))
    runtime.add_cluster("engine", cluster)
    assert cluster.context is not None
    assert isinstance(cluster.context.clock, OnlyClockView)
    assert not hasattr(cluster.context.clock, "advance_to")
    assert not hasattr(cluster.context.clock, "close")
