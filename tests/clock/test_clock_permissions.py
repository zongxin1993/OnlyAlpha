from datetime import UTC, datetime

from onlyalpha.cache.memory import OnlyMemoryCache
from onlyalpha.cluster.base import OnlyCluster, OnlyClusterConfig
from onlyalpha.core.clock import OnlyBacktestClock, OnlyClockView
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.runtime.runtime import OnlyBacktestRuntime


def test_cluster_receives_clock_view_without_advancement_capability() -> None:
    runtime = OnlyBacktestRuntime(
        "runtime",
        OnlyBacktestClock(datetime(2026, 1, 1, tzinfo=UTC)),
        OnlyEventBus(),
        OnlyMemoryCache(),
    )
    cluster = OnlyCluster(OnlyClusterConfig("cluster"))
    runtime.add_cluster("engine", cluster)
    assert cluster.context is not None
    assert isinstance(cluster.context.clock, OnlyClockView)
    assert not hasattr(cluster.context.clock, "advance_to")
    assert not hasattr(cluster.context.clock, "close")
