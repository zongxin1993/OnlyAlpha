from collections.abc import Callable

import pytest

from onlyalpha.cluster.base import OnlyCluster, OnlyClusterConfig, OnlyClusterState
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.market_data.subscriptions import OnlyBarSubscription
from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime
from onlyalpha.runtime.context import OnlyRuntimeContextError, OnlyTimerContext
from onlyalpha.runtime.runtime import OnlyRuntimeState
from onlyalpha.strategy.base import OnlyStrategy
from onlyalpha.strategy.config import OnlyStrategyConfig
from onlyalpha.strategy.context import OnlyStrategyBarContext, OnlyStrategyTimerContext
from onlyalpha.strategy.identifiers import OnlyStrategyId


class OnlyOrderedStrategy(OnlyStrategy):
    def __init__(self, strategy_id: str, *, fail_on_second: bool = False) -> None:
        super().__init__(OnlyStrategyConfig(OnlyStrategyId(strategy_id)))
        self.order: list[str] = []
        self.fail_on_second = fail_on_second

    def on_initialize(self) -> None:
        self.context.timers.schedule_at("same-time", self.context.clock.timestamp_ns() + 3 * 60 * 1_000_000_000)

    def on_timer(self, context: OnlyStrategyTimerContext) -> None:
        assert isinstance(context.timer, OnlyTimerContext)
        self.order.append(f"timer:{context.timer.event.deadline_ns}")

    def on_bar(self, context: OnlyStrategyBarContext) -> None:
        self.order.append(f"bar:{context.snapshot.ts_event.unix_nanos}")  # type: ignore[union-attr]
        if self.fail_on_second and len([item for item in self.order if item.startswith("bar:")]) == 2:
            raise RuntimeError("expected cluster failure")


class OnlyOrderedCluster(OnlyCluster):
    def __init__(self, config: OnlyClusterConfig, subscription: OnlyBarSubscription, *, fail: bool = False) -> None:
        strategy = OnlyOrderedStrategy(f"{config.cluster_id}-strategy", fail_on_second=fail)
        super().__init__(OnlyClusterConfig(config.cluster_id, subscription, config.values), strategy)
        self.ordered_strategy = strategy

    @property
    def order(self) -> list[str]:
        return self.ordered_strategy.order


def test_same_timestamp_timer_fires_before_bar(
    make_runtime: Callable[[str], OnlyBacktestRuntime],
    make_runtime_bar: Callable[[int, str], OnlyBar],
    runtime_types: tuple[OnlyBarType, OnlyBarType],
) -> None:
    runtime = make_runtime("runtime")
    cluster = OnlyOrderedCluster(OnlyClusterConfig("ordered"), OnlyBarSubscription(runtime_types))
    runtime.add_cluster("engine", cluster)
    runtime.start()
    for index in range(3):
        runtime.process_bar(make_runtime_bar(index, "10.00"))
    assert cluster.order[-2].startswith("timer:")
    assert cluster.order[-1].startswith("bar:")
    assert cluster.order[-2].split(":", 1)[1] == cluster.order[-1].split(":", 1)[1]


def test_cluster_stop_cancels_timer_and_releases_subscription(
    make_runtime: Callable[[str], OnlyBacktestRuntime],
    runtime_types: tuple[OnlyBarType, OnlyBarType],
) -> None:
    runtime = make_runtime("runtime")
    cluster = OnlyOrderedCluster(OnlyClusterConfig("ordered"), OnlyBarSubscription(runtime_types))
    runtime.add_cluster("engine", cluster)
    runtime.start()
    assert runtime.status().active_timer_count == 1
    assert runtime.status().subscription_count == 1
    runtime.stop_cluster("ordered")
    assert runtime.status().active_timer_count == 0
    assert runtime.status().subscription_count == 0
    assert cluster.context is not None
    with pytest.raises(OnlyRuntimeContextError):
        cluster.context.timers.schedule_after("late", 1)


def test_failed_cluster_stops_receiving_while_healthy_cluster_continues(
    make_runtime: Callable[[str], OnlyBacktestRuntime],
    make_runtime_bar: Callable[[int, str], OnlyBar],
    runtime_types: tuple[OnlyBarType, OnlyBarType],
) -> None:
    runtime = make_runtime("runtime")
    subscription = OnlyBarSubscription(runtime_types)
    failing = OnlyOrderedCluster(OnlyClusterConfig("a-failing"), subscription, fail=True)
    healthy = OnlyOrderedCluster(OnlyClusterConfig("b-healthy"), subscription)
    runtime.add_cluster("engine", failing)
    runtime.add_cluster("engine", healthy)
    runtime.start()
    for index in range(3):
        runtime.process_bar(make_runtime_bar(index, "10.00"))

    assert failing.state is OnlyClusterState.FAILED
    assert len([item for item in failing.order if item.startswith("bar:")]) == 2
    assert healthy.state is OnlyClusterState.RUNNING
    assert len([item for item in healthy.order if item.startswith("bar:")]) == 3
    assert runtime.state is OnlyRuntimeState.RUNNING
    failure = runtime.cluster_status()[0].last_failure
    assert failure is not None
    assert failure.runtime_id == runtime.config.runtime_id
    assert failure.bar_type is not None
