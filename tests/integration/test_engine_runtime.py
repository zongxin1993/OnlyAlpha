from datetime import UTC, datetime, time
from decimal import Decimal

from onlyalpha.cluster.base import OnlyCluster, OnlyClusterConfig
from onlyalpha.cluster.demo import OnlyDemoCluster
from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import OnlyRuntimeMode, OnlySessionType
from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyClusterId, OnlyVenueId
from onlyalpha.domain.time import OnlyTimeZone
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime
from onlyalpha.runtime.runtime import OnlyRuntimeAssemblyConfig, OnlyRuntimeState
from onlyalpha.strategy.base import OnlyStrategy
from onlyalpha.strategy.config import OnlyStrategyConfig
from onlyalpha.strategy.context import OnlyStrategyBarContext
from onlyalpha.strategy.identifiers import OnlyStrategyId


class OnlyFailingStrategy(OnlyStrategy):
    def on_initialize(self) -> None:
        pass

    def on_bar(self, context: OnlyStrategyBarContext) -> None:
        del context

    def on_start(self) -> None:
        raise RuntimeError("expected isolated failure")


def test_engine_manages_multiple_runtimes_and_isolates_clusters() -> None:
    currency = OnlyCurrency("CNY", 2)
    calendar = OnlyTradingCalendar(
        OnlyCalendarId("TEST"),
        OnlyVenueId("TEST"),
        OnlyTimeZone("UTC"),
        (OnlyTradingSession("all", time(0), time(0), OnlySessionType.CONTINUOUS),),
        weekend_days=(),
    )
    runtimes = [
        OnlyBacktestRuntime(
            OnlyRuntimeAssemblyConfig(
                "engine",
                f"runtime-{index}",
                OnlyRuntimeMode.BACKTEST,
                strategy_base_currency=currency,
                strategy_capitals=(
                    {
                        OnlyClusterId("failing"): OnlyMoney(Decimal("500000.00"), currency),
                        OnlyClusterId("healthy"): OnlyMoney(Decimal("500000.00"), currency),
                    }
                    if index == 0
                    else {}
                ),
                account_initial_cash=OnlyMoney(Decimal("1000000.00"), currency),
            ),
            calendar,
            datetime(2026, 1, index + 1, tzinfo=UTC),
        )
        for index in range(2)
    ]
    healthy = OnlyDemoCluster(OnlyClusterConfig("healthy"))
    runtimes[0].add_cluster(
        "engine",
        OnlyCluster(
            OnlyClusterConfig("failing"),
            OnlyFailingStrategy(OnlyStrategyConfig(OnlyStrategyId("failing-strategy"))),
        ),
    )
    runtimes[0].add_cluster("engine", healthy)
    for runtime in runtimes:
        runtime.initialize()
        runtime.start()
    assert all(runtime.state is OnlyRuntimeState.RUNNING for runtime in runtimes)
    assert healthy.started
    for runtime in runtimes:
        runtime.close()
        runtime.close()
    assert all(runtime.state is OnlyRuntimeState.CLOSED for runtime in runtimes)
