from collections.abc import Callable

import pytest

from onlyalpha.cluster.base import OnlyClusterConfig, OnlyClusterState
from onlyalpha.cluster.demo import OnlyDemoCluster
from onlyalpha.core.errors import OnlyLifecycleError
from onlyalpha.domain.market import OnlyBarType
from onlyalpha.market_data.subscriptions import OnlyBarSubscription
from onlyalpha.runtime.context import OnlyRuntimeContextError
from onlyalpha.runtime.runtime import OnlyBacktestRuntime, OnlyRuntimeState


def test_runtime_and_cluster_lifecycle_is_manager_owned(
    make_runtime: Callable[[str], OnlyBacktestRuntime],
) -> None:
    runtime = make_runtime("runtime")
    cluster = OnlyDemoCluster(OnlyClusterConfig("demo"))
    runtime.add_cluster("engine", cluster)
    assert cluster.state is OnlyClusterState.LOADED

    runtime.initialize()
    assert runtime.state is OnlyRuntimeState.READY
    assert cluster.state is OnlyClusterState.INITIALIZED
    runtime.start()
    assert cluster.state is OnlyClusterState.RUNNING
    runtime.stop()
    runtime.stop()
    assert runtime.state is OnlyRuntimeState.STOPPED
    assert cluster.state is OnlyClusterState.STOPPED
    runtime.close()
    runtime.close()
    assert runtime.state is OnlyRuntimeState.CLOSED
    assert cluster.state is OnlyClusterState.UNLOADED


def test_illegal_runtime_transition_is_rejected(make_runtime: Callable[[str], OnlyBacktestRuntime]) -> None:
    runtime = make_runtime("runtime")
    with pytest.raises(OnlyLifecycleError):
        runtime.pause()


def test_context_does_not_expose_mutable_runtime_resources(
    make_runtime: Callable[[str], OnlyBacktestRuntime],
) -> None:
    runtime = make_runtime("runtime")
    cluster = OnlyDemoCluster(OnlyClusterConfig("demo"))
    runtime.add_cluster("engine", cluster)
    context = cluster.context
    assert context is not None
    assert not hasattr(context.clock, "advance_to")
    assert not hasattr(context.clock, "close")
    assert not hasattr(context.clock, "schedule_at")
    for forbidden in ("cache", "event_bus", "aggregator", "gateway", "services"):
        assert not hasattr(context, forbidden)


def test_subscription_is_initialization_only_and_released_on_stop(
    make_runtime: Callable[[str], OnlyBacktestRuntime],
    runtime_types: tuple[OnlyBarType, OnlyBarType],
) -> None:
    runtime = make_runtime("runtime")
    subscription = OnlyBarSubscription(runtime_types)
    cluster = OnlyDemoCluster(OnlyClusterConfig("demo"), subscription)
    runtime.add_cluster("engine", cluster)
    runtime.initialize()
    runtime.start()
    assert runtime.status().subscription_count == 1
    assert cluster.context is not None
    with pytest.raises(OnlyRuntimeContextError):
        cluster.context.subscriptions.subscribe_bars(subscription)
    runtime.stop()
    assert runtime.status().subscription_count == 0
    assert runtime.status().active_timer_count == 0
