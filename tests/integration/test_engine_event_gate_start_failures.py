from pathlib import Path

import pytest
from onlyalpha_test_plugin.broker import OnlyExternalTestBrokerGateway

from onlyalpha.cluster.base import OnlyClusterState
from onlyalpha.cluster.manager import OnlyClusterManager
from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngineConfig
from onlyalpha.engine.engine import OnlyEngine
from onlyalpha.event.bus import OnlyEventCapacityError
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.runtime.events import OnlyRuntimeEventGatePhase, OnlyRuntimeEventRouter
from onlyalpha.runtime.persistence.store import OnlySqliteRuntimePersistenceStore
from onlyalpha.runtime.runtime import OnlyRuntimeState
from onlyalpha.strategy.adapter import OnlyRevisionStrategyAdapter
from tests.integration.recovery_finalization_support import only_create_tail_failure
from tests.integration.test_engine_recovery_same_bar_continuation import _same_bar_config, _services
from tests.runtime_runner import only_migrate_cluster_to_strategy


def _event_types(runtime: object) -> tuple[str, ...]:
    return tuple(item.event.event_type.value for item in runtime.event_bus.dispatch_results)  # type: ignore[attr-defined]


def test_plugin_start_failure_is_completely_silent_before_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_start(self: OnlyExternalTestBrokerGateway) -> None:
        del self
        raise RuntimeError("TEST_PLUGIN_START_FAILURE")

    monkeypatch.setattr(OnlyExternalTestBrokerGateway, "start", fail_start)
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("event-gate-plugin-start"), tmp_path))
    engine.add_cluster(
        only_migrate_cluster_to_strategy(
            OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster_external_plugins.yaml"), tmp_path
        )
    )
    engine.initialize()
    runtime = engine.runtime_sessions[0].runtime
    with pytest.raises(Exception, match="TEST_PLUGIN_START_FAILURE"):
        engine.start()
    assert engine.state.value == "FAILED"
    assert runtime.status().state is OnlyRuntimeState.CLOSED
    assert runtime.event_gate_snapshot.phase is OnlyRuntimeEventGatePhase.CLOSED
    assert runtime.event_bus.pending_count() == 0
    assert runtime.event_bus.dispatch_results == ()
    assert "RUNTIME_STARTED" not in _event_types(runtime)
    engine.stop()


def test_router_open_failure_is_atomic_and_blocks_later_start_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("event-gate-router-open"), tmp_path))
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
    assert engine.state.value == "FAILED"
    assert runtime.status().state is OnlyRuntimeState.CLOSED
    assert runtime.event_gate_snapshot.phase is OnlyRuntimeEventGatePhase.CLOSED
    assert runtime.event_bus.pending_count() == 0
    assert runtime.event_bus.dispatch_results == ()
    assert all(item.state is not OnlyClusterState.RUNNING for item in runtime.cluster_status())
    engine.stop()


@pytest.mark.parametrize("fail_on", (1, 2))
def test_outbox_failure_stops_at_first_error_and_preserves_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_on: int
) -> None:
    engine_id = OnlyEngineId(f"event-gate-outbox-{fail_on}")
    only_create_tail_failure(tmp_path, engine_id)
    engine = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path), services=_services())
    engine.add_cluster(_same_bar_config(tmp_path))
    engine.initialize()
    runtime = engine.runtime_sessions[0].runtime
    state_path = OnlyUserDataLayout(tmp_path).runtime_persistence_path(engine_id, runtime.runtime_id)
    before_reader = OnlySqliteRuntimePersistenceStore(state_path)
    published_prefix = sum(
        item.published
        for item in before_reader.outbox_records(runtime.config.runtime_id)  # type: ignore[arg-type]
    )
    before_reader.close()
    original = OnlyRuntimeEventRouter.publish_durable
    calls = 0

    def fail_nth(self: OnlyRuntimeEventRouter, event: object):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == fail_on:
            raise RuntimeError(f"TEST_OUTBOX_FAILURE_{fail_on}")
        return original(self, event)  # type: ignore[arg-type]

    monkeypatch.setattr(OnlyRuntimeEventRouter, "publish_durable", fail_nth)
    with pytest.raises(Exception, match=f"TEST_OUTBOX_FAILURE_{fail_on}"):
        engine.start()
    reader = OnlySqliteRuntimePersistenceStore(state_path)
    records = reader.outbox_records(runtime.config.runtime_id)  # type: ignore[arg-type]
    reader.close()
    failed_index = published_prefix + fail_on - 1
    assert sum(item.published for item in records) == published_prefix + fail_on - 1
    assert records[failed_index].last_error is not None
    assert all(not item.published for item in records[failed_index:])
    assert engine.state.value == "FAILED"
    assert runtime.event_gate_snapshot.phase is OnlyRuntimeEventGatePhase.CLOSED
    assert "RUNTIME_STARTED" not in _event_types(runtime)
    engine.stop()
    assert len(runtime.event_bus.dispatch_results) == fail_on - 1


def test_fresh_cluster_start_failure_occurs_after_bootstrap_acceptance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_start(self: OnlyRevisionStrategyAdapter) -> None:
        del self
        raise RuntimeError("TEST_CLUSTER_START_FAILURE")

    monkeypatch.setattr(OnlyRevisionStrategyAdapter, "on_start", fail_start)
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("event-gate-cluster-start"), tmp_path), services=_services())
    engine.add_cluster(_same_bar_config(tmp_path))
    engine.initialize()
    runtime = engine.runtime_sessions[0].runtime
    with pytest.raises(Exception, match="TEST_CLUSTER_START_FAILURE"):
        engine.start()
    assert engine.state.value == "FAILED"
    assert runtime.event_gate_snapshot.phase is OnlyRuntimeEventGatePhase.CLOSED
    assert runtime.event_bus.pending_count() == 0
    assert "RUNTIME_STARTED" not in _event_types(runtime)
    assert runtime.event_bus.dispatch_results
    engine.stop()
    assert runtime.event_bus.dispatch_results


def test_recovered_cluster_resume_failure_never_publishes_runtime_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine_id = OnlyEngineId("event-gate-cluster-resume")
    only_create_tail_failure(tmp_path, engine_id)

    def fail_resume(self: OnlyClusterManager) -> None:
        del self
        raise RuntimeError("TEST_CLUSTER_RESUME_FAILURE")

    monkeypatch.setattr(OnlyClusterManager, "resume_recovered_all", fail_resume)
    engine = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path), services=_services())
    engine.add_cluster(_same_bar_config(tmp_path))
    engine.initialize()
    runtime = engine.runtime_sessions[0].runtime
    with pytest.raises(Exception, match="TEST_CLUSTER_RESUME_FAILURE"):
        engine.start()
    assert engine.state.value == "FAILED"
    assert runtime.event_gate_snapshot.phase is OnlyRuntimeEventGatePhase.CLOSED
    assert all(item.state is not OnlyClusterState.RUNNING for item in runtime.cluster_status())
    assert "RUNTIME_STARTED" not in _event_types(runtime)
    engine.stop()


def test_runtime_started_publication_failure_preserves_original_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("event-gate-lifecycle"), tmp_path))
    engine.add_cluster(
        only_migrate_cluster_to_strategy(OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json"), tmp_path)
    )
    engine.initialize()
    runtime = engine.runtime_sessions[0].runtime

    def fail_lifecycle(self: OnlyRuntimeEventRouter, event: object):  # type: ignore[no-untyped-def]
        del self, event
        raise RuntimeError("TEST_RUNTIME_STARTED_PUBLICATION_FAILURE")

    monkeypatch.setattr(OnlyRuntimeEventRouter, "publish_lifecycle", fail_lifecycle)
    with pytest.raises(Exception, match="TEST_RUNTIME_STARTED_PUBLICATION_FAILURE"):
        engine.start()
    assert engine.state.value == "FAILED"
    assert runtime.status().state is OnlyRuntimeState.CLOSED
    assert runtime.event_gate_snapshot.phase is OnlyRuntimeEventGatePhase.CLOSED
    assert "RUNTIME_STARTED" not in _event_types(runtime)
    engine.stop()
