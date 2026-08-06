from onlyalpha.cluster.base import OnlyCluster, OnlyClusterConfig
from onlyalpha.core.clock import OnlyClockView
from tests.runtime_support.common import only_demo_runtime


def test_cluster_receives_clock_view_without_advancement_capability() -> None:
    runtime = only_demo_runtime("runtime", ("cluster",))
    cluster = OnlyCluster(OnlyClusterConfig("cluster"))
    runtime.add_cluster("engine", cluster)
    assert cluster.context is not None
    assert isinstance(cluster.context.clock, OnlyClockView)
    assert not hasattr(cluster.context.clock, "advance_to")
    assert not hasattr(cluster.context.clock, "close")
