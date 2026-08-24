import pytest

from onlyalpha.cluster.base import OnlyCluster, OnlyClusterConfig
from onlyalpha.cluster.demo import OnlyDemoCluster
from onlyalpha.runtime.events import OnlyRuntimeEventGatePhase
from onlyalpha.runtime.runtime import OnlyRuntimeState
from tests.runtime_support.common import only_demo_runtime


class OnlyFailingCluster(OnlyCluster):
    def on_start(self) -> None:
        raise RuntimeError("expected isolated failure")


def test_engine_manages_multiple_runtimes_and_isolates_clusters() -> None:
    runtimes = [
        only_demo_runtime("runtime-0", ("failing", "healthy")),
        only_demo_runtime("runtime-1", ("second",)),
    ]
    healthy = OnlyDemoCluster(OnlyClusterConfig("healthy"))
    runtimes[0].add_cluster(
        "engine",
        OnlyFailingCluster(OnlyClusterConfig("failing")),
    )
    runtimes[0].add_cluster("engine", healthy)
    for runtime in runtimes:
        runtime.initialize()
    with pytest.raises(Exception, match="expected isolated failure"):
        runtimes[0].start()
    runtimes[1].start()
    assert runtimes[0].state is OnlyRuntimeState.FAILED
    assert runtimes[0].event_gate_snapshot.phase is OnlyRuntimeEventGatePhase.FAILED
    assert all(item.event.event_type.value != "RUNTIME_STARTED" for item in runtimes[0].event_bus.dispatch_results)
    assert runtimes[1].state is OnlyRuntimeState.RUNNING
    assert healthy.started
    for runtime in runtimes:
        runtime.close()
        runtime.close()
    assert all(runtime.state is OnlyRuntimeState.CLOSED for runtime in runtimes)
