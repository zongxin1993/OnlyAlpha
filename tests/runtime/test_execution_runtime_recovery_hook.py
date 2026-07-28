from collections.abc import Callable

import pytest

from onlyalpha.cluster.base import OnlyClusterConfig, OnlyClusterState
from onlyalpha.cluster.demo import OnlyDemoCluster
from onlyalpha.core.errors import OnlyLifecycleError
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.execution import (
    OnlyExecutionCommitCoordinationStatus,
    OnlyExecutionRecoveryResult,
    OnlyExecutionRecoveryStatus,
    OnlyOutboxPublishResult,
)
from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime
from onlyalpha.runtime.runtime import (
    OnlyRuntimeOutboxDeliveryError,
    OnlyRuntimeRecoveryError,
    OnlyRuntimeState,
)


class _OnlyRecoveryFailure:
    def recover(self, runtime_id: OnlyRuntimeId, *, limit: int | None = None) -> OnlyExecutionRecoveryResult:
        del limit
        return OnlyExecutionRecoveryResult(
            runtime_id,
            OnlyExecutionRecoveryStatus.FAILED,
            1,
            0,
            0,
            0,
            1,
            "transaction-1",
            None,
            None,
            OnlyExecutionCommitCoordinationStatus.PROJECTION_FAILED,
            "projection failed",
            "injected recovery failure",
        )


def test_initialize_records_no_work_before_entering_ready(
    make_runtime: Callable[[str], OnlyBacktestRuntime],
) -> None:
    runtime = make_runtime("runtime")
    cluster = OnlyDemoCluster(OnlyClusterConfig("demo"))
    runtime.add_cluster("engine", cluster)

    runtime.initialize()

    assert runtime.state is OnlyRuntimeState.READY
    assert cluster.state is OnlyClusterState.INITIALIZED
    assert tuple(item.status for item in runtime.execution_recovery_diagnostics) == (
        OnlyExecutionRecoveryStatus.NO_WORK,
    )


def test_recovery_failure_blocks_runtime_cluster_and_all_inbound_processing(
    make_runtime: Callable[[str], OnlyBacktestRuntime],
) -> None:
    runtime = make_runtime("runtime")
    cluster = OnlyDemoCluster(OnlyClusterConfig("demo"))
    runtime.add_cluster("engine", cluster)
    runtime._services.execution_recovery_service = _OnlyRecoveryFailure()  # type: ignore[assignment]

    with pytest.raises(OnlyRuntimeRecoveryError, match="transaction-1"):
        runtime.initialize()

    assert runtime.state is OnlyRuntimeState.FAILED
    assert cluster.state is OnlyClusterState.INITIALIZED
    assert runtime.execution_recovery_diagnostics[-1].status is OnlyExecutionRecoveryStatus.FAILED
    assert not any(item.event.event_type.value == "RUNTIME_STARTED" for item in runtime.event_bus.dispatch_results)
    with pytest.raises(OnlyLifecycleError):
        runtime.receive_market_data_update(object())  # type: ignore[arg-type]
    with pytest.raises(OnlyLifecycleError):
        runtime.receive_broker_update(object())  # type: ignore[arg-type]


def test_start_drains_recovered_outbox_before_starting_cluster(
    make_runtime: Callable[[str], OnlyBacktestRuntime],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = make_runtime("runtime")
    cluster = OnlyDemoCluster(OnlyClusterConfig("demo"))
    runtime.add_cluster("engine", cluster)
    runtime.initialize()
    calls: list[str] = []
    original_start = runtime._services.cluster_manager.start_all

    def publish_pending(runtime_id: OnlyRuntimeId, *, limit: int = 100) -> OnlyOutboxPublishResult:
        del runtime_id, limit
        calls.append("outbox")
        return OnlyOutboxPublishResult(0, 0, 0, 0, False, None)

    def start_all() -> None:
        calls.append("cluster")
        original_start()

    monkeypatch.setattr(runtime._services.execution_outbox_publisher, "publish_pending", publish_pending)
    monkeypatch.setattr(runtime._services.cluster_manager, "start_all", start_all)

    runtime.start()

    assert calls == ["outbox", "cluster"]
    assert runtime.state is OnlyRuntimeState.RUNNING


def test_recovered_outbox_failure_is_distinct_and_blocks_cluster_start(
    make_runtime: Callable[[str], OnlyBacktestRuntime],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = make_runtime("runtime")
    cluster = OnlyDemoCluster(OnlyClusterConfig("demo"))
    runtime.add_cluster("engine", cluster)
    runtime.initialize()

    def publish_pending(runtime_id: OnlyRuntimeId, *, limit: int = 100) -> OnlyOutboxPublishResult:
        del runtime_id, limit
        return OnlyOutboxPublishResult(1, 0, 1, 1, True, "EventBus rejected event")

    monkeypatch.setattr(runtime._services.execution_outbox_publisher, "publish_pending", publish_pending)

    with pytest.raises(OnlyRuntimeOutboxDeliveryError, match="EventBus rejected"):
        runtime.start()

    assert runtime.state is OnlyRuntimeState.FAILED
    assert cluster.state is OnlyClusterState.INITIALIZED
