from pathlib import Path

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.runtime.events import OnlyRuntimeEventGatePhase


def test_fresh_runtime_flushes_bootstrap_fifo_before_runtime_started(tmp_path: Path) -> None:
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("fresh-event-gate"), tmp_path))
    engine.add_cluster(OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json"))
    engine.initialize()
    runtime = engine.runtime_sessions[0].runtime
    assert runtime.event_gate_snapshot.phase is OnlyRuntimeEventGatePhase.READY_BLOCKED
    staged_count = runtime.event_gate_snapshot.staged_count
    assert staged_count > 0
    assert runtime.event_bus.dispatch_results == ()

    engine.start()
    dispatched = tuple(item.event for item in runtime.event_bus.dispatch_results)
    assert runtime.event_gate_snapshot.phase is OnlyRuntimeEventGatePhase.OPEN
    assert runtime.event_gate_snapshot.staged_count == 0
    assert dispatched
    assert dispatched[-1].event_type.value == "RUNTIME_STARTED"
    assert len(dispatched[:-1]) == staged_count
    for source in {event.source for event in dispatched[:-1]}:
        sequences = [int(event.sequence) for event in dispatched[:-1] if event.source == source]
        assert sequences == sorted(sequences)
    engine.stop()
