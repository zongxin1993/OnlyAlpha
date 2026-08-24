from pathlib import Path

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.runtime.events import OnlyRuntimeEventGatePhase
from tests.integration.recovery_finalization_support import only_create_tail_failure
from tests.integration.test_engine_recovery_same_bar_continuation import _same_bar_config, _services


def test_historical_direct_events_are_suppressed_and_never_flushed(tmp_path: Path) -> None:
    engine_id = OnlyEngineId("recovery-direct-suppression")
    only_create_tail_failure(tmp_path, engine_id)
    engine = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path), services=_services())
    engine.add_cluster(_same_bar_config(tmp_path))
    engine.initialize()
    runtime = engine.runtime_sessions[0].runtime
    before_start = runtime.event_gate_snapshot
    assert before_start.phase is OnlyRuntimeEventGatePhase.READY_BLOCKED
    assert before_start.suppressed_direct_count > 0
    assert before_start.last_suppressed_events
    assert runtime.event_bus.dispatch_results == ()
    suppressed_projection = tuple(
        (item.event_type, item.source, item.sequence) for item in before_start.last_suppressed_events
    )

    engine.start()
    dispatched_projection = {
        (item.event.event_type.value, item.event.source.value, int(item.event.sequence))
        for item in runtime.event_bus.dispatch_results
    }
    assert not dispatched_projection.intersection(suppressed_projection)
    assert runtime.event_gate_snapshot.suppressed_direct_count == before_start.suppressed_direct_count
    engine.stop()
