from pathlib import Path

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngineConfig
from onlyalpha.engine.engine import OnlyEngine
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.result import only_backtest_business_projection
from onlyalpha.runtime.events import OnlyRuntimeEventGatePhase
from onlyalpha.runtime.persistence.store import OnlySqliteRuntimePersistenceStore
from tests.integration.recovery_finalization_support import (
    OnlyAfterCommitCheckpointStoreFactory,
    only_create_tail_failure,
    only_recovery_services,
)
from tests.integration.test_engine_recovery_same_bar_continuation import _same_bar_config, _services


def test_a_b_c_restart_keeps_business_equivalence_and_event_gate_contract(tmp_path: Path) -> None:
    engine_id = OnlyEngineId("event-gate-three-stage")
    engine_a = only_create_tail_failure(tmp_path, engine_id)
    runtime_id = engine_a.runtime_sessions[0].runtime_id
    state_path = OnlyUserDataLayout(tmp_path).runtime_persistence_path(engine_id, runtime_id)

    engine_b = OnlyEngine(
        OnlyEngineConfig(engine_id, tmp_path),
        services=only_recovery_services(OnlyAfterCommitCheckpointStoreFactory()),
    )
    engine_b.add_cluster(_same_bar_config(tmp_path))
    result_b = engine_b.run()
    assert result_b.status == "FAILED"
    assert any("POST_RECOVERY_CHECKPOINT_COMMITTED_BUT_FINALIZATION_INTERRUPTED" in item for item in result_b.failures)
    reader = OnlySqliteRuntimePersistenceStore(state_path)
    committed_b = reader.latest_checkpoint(runtime_id)
    pending_ids = {item.event.event_id for item in reader.outbox_records(runtime_id) if not item.published}
    reader.close()
    assert committed_b is not None
    assert pending_ids

    engine_c = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path), services=_services())
    engine_c.add_cluster(_same_bar_config(tmp_path))
    engine_c.initialize()
    runtime_c = engine_c.runtime_sessions[0].runtime
    assert runtime_c.event_gate_snapshot.phase is OnlyRuntimeEventGatePhase.READY_BLOCKED
    assert runtime_c.event_bus.dispatch_results == ()
    suppressed_before_open = {
        (item.event_type, item.source, item.sequence) for item in runtime_c.event_gate_snapshot.last_suppressed_events
    }
    engine_c.start()
    dispatched_c = tuple(item.event for item in runtime_c.event_bus.dispatch_results)
    assert runtime_c.event_gate_snapshot.phase is OnlyRuntimeEventGatePhase.OPEN
    assert pending_ids <= {item.event_id for item in dispatched_c}
    assert dispatched_c[-1].event_type.value == "RUNTIME_STARTED"
    assert not suppressed_before_open.intersection(
        (item.event_type.value, item.source.value, int(item.sequence)) for item in dispatched_c
    )
    recovered = runtime_c.run()
    engine_c.stop()

    baseline_root = tmp_path / "baseline"
    baseline_engine = OnlyEngine(OnlyEngineConfig(engine_id, baseline_root), services=_services())
    baseline_engine.add_cluster(_same_bar_config(baseline_root))
    baseline_engine.initialize()
    baseline_engine.start()
    expected = baseline_engine.runtime_sessions[0].runtime.run()
    baseline_engine.stop()
    assert only_backtest_business_projection(recovered) == only_backtest_business_projection(expected)  # type: ignore[arg-type]
    assert recovered.result_fingerprint == expected.result_fingerprint  # type: ignore[attr-defined]
    assert recovered.orders == expected.orders  # type: ignore[attr-defined]
    assert recovered.trades == expected.trades  # type: ignore[attr-defined]
    assert recovered.final_positions == expected.final_positions  # type: ignore[attr-defined]
    assert recovered.final_allocations == expected.final_allocations  # type: ignore[attr-defined]
    assert recovered.final_account == expected.final_account  # type: ignore[attr-defined]
    assert recovered.final_ledgers == expected.final_ledgers  # type: ignore[attr-defined]
