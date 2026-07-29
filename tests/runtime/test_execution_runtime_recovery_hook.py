from collections.abc import Callable
from pathlib import Path

from onlyalpha.cluster.base import OnlyClusterConfig, OnlyClusterState
from onlyalpha.cluster.demo import OnlyDemoCluster
from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime
from onlyalpha.runtime.runtime import OnlyRuntimeState


def test_memory_runtime_initializes_without_persistent_recovery_work(
    make_runtime: Callable[[str], OnlyBacktestRuntime],
) -> None:
    runtime = make_runtime("runtime")
    cluster = OnlyDemoCluster(OnlyClusterConfig("demo"))
    runtime.add_cluster("engine", cluster)

    runtime.initialize()

    assert runtime.state is OnlyRuntimeState.READY
    assert cluster.state is OnlyClusterState.INITIALIZED
    assert runtime.runtime_recovery_diagnostics == ()
    assert runtime.execution_recovery_diagnostics == ()


def test_public_start_reaches_running_after_recovery_and_outbox_barriers(
    make_runtime: Callable[[str], OnlyBacktestRuntime],
) -> None:
    runtime = make_runtime("runtime")
    cluster = OnlyDemoCluster(OnlyClusterConfig("demo"))
    runtime.add_cluster("engine", cluster)

    runtime.initialize()
    runtime.start()

    assert runtime.state is OnlyRuntimeState.RUNNING
    assert cluster.state is OnlyClusterState.RUNNING


def test_recovery_and_outbox_failure_order_is_enforced_before_cluster_start() -> None:
    source = Path("src/onlyalpha/runtime/runtime.py").read_text(encoding="utf-8")
    initialize = source[source.index("    def initialize(self)") : source.index("    def _recover_runtime(self)")]
    start = source[source.index("    def start(self)") : source.index("    def pause(self)")]
    assert initialize.index("OnlyRuntimeState.RECOVERING") < initialize.index("self._recover_runtime()")
    assert initialize.index("self._recover_runtime()") < initialize.index("OnlyRuntimeState.READY")
    assert "except OnlyRuntimeRecoveryError" in initialize
    assert start.index("self._drain_execution_outbox()") < start.index("cluster_manager.start_all()")
    assert "except OnlyRuntimeOutboxDeliveryError" in start
