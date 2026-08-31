from pathlib import Path

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngineConfig
from onlyalpha.engine.engine import OnlyEngine
from onlyalpha.output.user_data import OnlyUserDataLayout
from onlyalpha.runtime.events import OnlyRuntimeEventGatePhase
from onlyalpha.runtime.persistence.store import OnlySqliteRuntimePersistenceStore
from tests.integration.recovery_finalization_support import only_create_tail_failure
from tests.integration.test_engine_recovery_same_bar_continuation import _same_bar_config, _services


def test_continuation_outbox_delivers_only_after_runtime_open(tmp_path: Path) -> None:
    engine_id = OnlyEngineId("recovery-continuation-delivery")
    failed = only_create_tail_failure(tmp_path, engine_id)
    runtime_id = failed.runtime_sessions[0].runtime_id
    engine = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path), services=_services())
    engine.add_cluster(_same_bar_config(tmp_path))
    engine.initialize()
    runtime = engine.runtime_sessions[0].runtime
    state_path = OnlyUserDataLayout(tmp_path).runtime_persistence_path(engine_id, runtime_id)
    reader = OnlySqliteRuntimePersistenceStore(state_path)
    continuation = tuple(item for item in reader.outbox_records(runtime_id) if item.key.execution_sequence == 5)
    assert continuation and all(not item.published for item in continuation)
    event_ids = {item.event.event_id for item in continuation}
    reader.close()
    assert runtime.event_gate_snapshot.phase is OnlyRuntimeEventGatePhase.READY_BLOCKED
    assert not event_ids.intersection(item.event.event_id for item in runtime.event_bus.dispatch_results)

    engine.start()
    dispatched = tuple(item.event for item in runtime.event_bus.dispatch_results)
    assert event_ids <= {item.event_id for item in dispatched}
    runtime_started = next(index for index, item in enumerate(dispatched) if item.event_type.value == "RUNTIME_STARTED")
    assert all(
        next(index for index, item in enumerate(dispatched) if item.event_id == event_id) < runtime_started
        for event_id in event_ids
    )
    reader = OnlySqliteRuntimePersistenceStore(state_path)
    assert all(item.published for item in reader.outbox_records(runtime_id) if item.event.event_id in event_ids)
    reader.close()
    engine.stop()
