from pathlib import Path

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.runtime.events import OnlyRuntimeEventGatePhase
from tests.integration.recovery_finalization_support import only_create_tail_failure
from tests.integration.test_engine_recovery_same_bar_continuation import _same_bar_config, _services


def test_recovery_discards_temporary_bootstrap_events(tmp_path: Path) -> None:
    engine_id = OnlyEngineId("recovery-bootstrap-discard")
    only_create_tail_failure(tmp_path, engine_id)
    engine = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path), services=_services())
    engine.add_cluster(_same_bar_config(tmp_path))
    engine.initialize()
    runtime = engine.runtime_sessions[0].runtime
    snapshot = runtime.event_gate_snapshot
    assert snapshot.phase is OnlyRuntimeEventGatePhase.READY_BLOCKED
    assert snapshot.staged_count == 0
    assert snapshot.discarded_bootstrap_count > 0
    assert runtime.event_bus.dispatch_results == ()
    engine.start()
    event_types = tuple(item.event.event_type.value for item in runtime.event_bus.dispatch_results)
    assert "ACCOUNT_CREATED" not in event_types
    assert "STRATEGY_LEDGER_CREATED" not in event_types
    assert event_types[-1] == "RUNTIME_STARTED"
    engine.stop()
