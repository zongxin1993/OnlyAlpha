from collections.abc import Callable

import pytest

from onlyalpha.cluster.base import OnlyCluster, OnlyClusterConfig, OnlyClusterState
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.market_data.subscriptions import OnlyBarSubscription
from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime
from onlyalpha.runtime.context import OnlyRuntimeContextError, OnlyTimerContext
from onlyalpha.runtime.runtime import OnlyRuntimeState


class OnlyOrderedCluster(OnlyCluster):
    def __init__(self, config: OnlyClusterConfig, subscription: OnlyBarSubscription, *, fail: bool = False) -> None:
        super().__init__(OnlyClusterConfig(config.cluster_id, subscription, config.values))
        self.order: list[str] = []
        self._fail_on_second = fail

    def on_initialize(self) -> None:
        super().on_initialize()
        assert self.context is not None
        self.context.timers.schedule_at("same-time", self.context.clock.timestamp_ns() + 3 * 60 * 1_000_000_000)

    def on_timer(self, context: OnlyTimerContext) -> None:
        self.order.append(f"timer:{context.event.deadline_ns}")

    def on_bar(self, bar: OnlyBar, context) -> None:
        del bar
        self.order.append(f"bar:{context.snapshot.ts_event.unix_nanos}")
        if self._fail_on_second and len([item for item in self.order if item.startswith("bar:")]) == 2:
            raise RuntimeError("expected cluster failure")


def test_same_timestamp_timer_fires_before_bar(
    make_runtime: Callable[[str], OnlyBacktestRuntime],
    make_runtime_bar: Callable[[int, str], OnlyBar],
    runtime_types: tuple[OnlyBarType, OnlyBarType],
) -> None:
    runtime = make_runtime("runtime", {"ordered": "1000000.00"})
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
    runtime = make_runtime("runtime", {"ordered": "1000000.00"})
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
    runtime = make_runtime("runtime", {"a-failing": "500000.00", "b-healthy": "500000.00"})
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
