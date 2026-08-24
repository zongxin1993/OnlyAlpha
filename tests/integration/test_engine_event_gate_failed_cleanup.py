from pathlib import Path

import pytest
from onlyalpha_test_plugin.broker import OnlyExternalTestBrokerGateway

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.event.bus import OnlyEventCapacityError
from onlyalpha.runtime.events import OnlyRuntimeEventGatePhase
from onlyalpha.strategy.adapter import OnlyRevisionStrategyAdapter
from tests.integration.test_engine_recovery_same_bar_continuation import _same_bar_config, _services
from tests.runtime_runner import only_migrate_cluster_to_strategy


def test_plugin_start_failure_close_is_silent_and_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_start(self: OnlyExternalTestBrokerGateway) -> None:
        del self
        raise RuntimeError("TEST_PLUGIN_START_FAILURE")

    monkeypatch.setattr(OnlyExternalTestBrokerGateway, "start", fail_start)
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("failed-cleanup-plugin"), tmp_path))
    engine.add_cluster(
        only_migrate_cluster_to_strategy(
            OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster_external_plugins.yaml"), tmp_path
        )
    )
    engine.initialize()
    runtime = engine.runtime_sessions[0].runtime
    with pytest.raises(Exception, match="TEST_PLUGIN_START_FAILURE"):
        engine.start()
    runtime.close()
    runtime.close()
    assert runtime.event_gate_snapshot.phase is OnlyRuntimeEventGatePhase.CLOSED
    assert runtime.event_bus.pending_count() == 0
    assert runtime.event_bus.dispatch_results == ()


def test_router_open_failure_close_keeps_queue_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("failed-cleanup-router"), tmp_path))
    engine.add_cluster(
        only_migrate_cluster_to_strategy(OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json"), tmp_path)
    )
    engine.initialize()
    runtime = engine.runtime_sessions[0].runtime

    def fail_atomic(self: object, events: tuple[object, ...]) -> int:
        del self, events
        raise OnlyEventCapacityError("TEST_ROUTER_OPEN_FAILURE")

    monkeypatch.setattr("onlyalpha.event.bus.OnlyEventBus.publish_many_atomic", fail_atomic)
    with pytest.raises(Exception, match="TEST_ROUTER_OPEN_FAILURE"):
        engine.start()
    runtime.close()
    runtime.close()
    assert runtime.event_gate_snapshot.phase is OnlyRuntimeEventGatePhase.CLOSED
    assert runtime.event_bus.pending_count() == 0
    assert runtime.event_bus.dispatch_results == ()


def test_open_failure_cleanup_drains_accepted_events_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_start(self: OnlyRevisionStrategyAdapter) -> None:
        del self
        raise RuntimeError("TEST_CLUSTER_START_FAILURE")

    monkeypatch.setattr(OnlyRevisionStrategyAdapter, "on_start", fail_start)
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("failed-cleanup-open"), tmp_path), services=_services())
    engine.add_cluster(_same_bar_config(tmp_path))
    engine.initialize()
    runtime = engine.runtime_sessions[0].runtime
    accepted = runtime.event_gate_snapshot.staged_count
    with pytest.raises(Exception, match="TEST_CLUSTER_START_FAILURE"):
        engine.start()
    assert runtime.event_bus.pending_count() == 0
    first_dispatch_count = len(runtime.event_bus.dispatch_results)
    engine.stop()
    engine.close()
    assert runtime.event_gate_snapshot.phase is OnlyRuntimeEventGatePhase.CLOSED
    assert first_dispatch_count == accepted
    assert len(runtime.event_bus.dispatch_results) == first_dispatch_count
    assert all(item.event.event_type.value != "RUNTIME_STARTED" for item in runtime.event_bus.dispatch_results)
