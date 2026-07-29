import json
from pathlib import Path

from onlyalpha.config import OnlyClusterRunConfig, OnlyRuntimePersistenceConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.result import only_backtest_business_projection
from onlyalpha.runtime.checkpoint.model import OnlyRuntimeCheckpoint
from onlyalpha.runtime.defaults import only_default_engine_services
from onlyalpha.runtime.persistence.factory import (
    OnlyDefaultRuntimePersistenceStoreFactory,
    OnlyRuntimePersistenceStoreCreateRequest,
)
from onlyalpha.runtime.persistence.store import OnlyRuntimePersistenceStorePort, OnlySqliteRuntimePersistenceStore
from tests.execution.support.execution_fault_injection import (
    OnlyFailOnceRuntimePersistenceStore,
    OnlyTestRuntimePersistenceFault,
)
from tests.integration.test_engine_continuous_restart import _sqlite_config


class OnlyTwoBoundaryTailRuntimePersistenceStore(OnlyFailOnceRuntimePersistenceStore):
    """Keep the last stable checkpoint while two later Bar transactions form the tail."""

    def __init__(self, delegate: OnlyRuntimePersistenceStorePort) -> None:
        super().__init__(delegate, OnlyTestRuntimePersistenceFault.AFTER_COMMIT, fault_after=1)
        self._checkpoint_write_count = 0

    def write_checkpoint(self, checkpoint: OnlyRuntimeCheckpoint, *, retain_last: int) -> None:
        self._checkpoint_write_count += 1
        if self._checkpoint_write_count <= 2:
            super().write_checkpoint(checkpoint, retain_last=retain_last)


class OnlyTwoBoundaryTailStoreFactory:
    def __init__(self) -> None:
        self._delegate = OnlyDefaultRuntimePersistenceStoreFactory()

    def validate(self, config: OnlyRuntimePersistenceConfig) -> None:
        self._delegate.validate(config)

    def create(self, request: OnlyRuntimePersistenceStoreCreateRequest) -> OnlyTwoBoundaryTailRuntimePersistenceStore:
        return OnlyTwoBoundaryTailRuntimePersistenceStore(self._delegate.create(request))


def _multi_boundary_config() -> OnlyClusterRunConfig:
    baseline = _sqlite_config()
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["runtime"]["end_time"] = "2026-01-05T01:45:00Z"
    payload["strategy"]["class_path"] = (
        "tests.integration.test_engine_recovery_same_bar_continuation:OnlyPositionTriggeredContinuationStrategy"
    )
    return OnlyClusterRunConfig.from_mapping(payload, source_path=baseline.source_path)


def test_engine_tail_spans_two_exact_market_data_boundaries(tmp_path: Path) -> None:
    config = _multi_boundary_config()
    engine_id = OnlyEngineId("multi-boundary-tail")
    engine_a = OnlyEngine(
        OnlyEngineConfig(engine_id, tmp_path),
        services=only_default_engine_services(runtime_persistence_store_factory=OnlyTwoBoundaryTailStoreFactory()),
    )
    engine_a.add_cluster(config)
    assert engine_a.run().status == "FAILED"

    runtime_id = engine_a.runtime_sessions[0].runtime_id
    state_path = OnlyUserDataLayout(tmp_path).runtime_persistence_path(engine_id, runtime_id)
    reader = OnlySqliteRuntimePersistenceStore(state_path)
    transactions = reader.records(runtime_id)
    assert tuple(item.execution_sequence for item in transactions) == (1, 2)
    assert tuple(item.projection_ready for item in transactions) == (True, False)
    assert transactions[0].fact.ts_event < transactions[1].fact.ts_event
    checkpoint_before_tail = reader.latest_checkpoint(runtime_id)
    assert checkpoint_before_tail is not None
    reader.close()

    engine_b = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path))
    engine_b.add_cluster(config)
    recovered = engine_b.run()
    assert recovered.status == "COMPLETED", recovered.failures
    diagnostic = engine_b.runtime_sessions[0].runtime.runtime_recovery_diagnostics[-1]
    assert diagnostic.catch_up_bar_count >= 2
    assert diagnostic.rehydrated_transaction_count == 1
    assert diagnostic.recovered_transaction_count == 1
    assert diagnostic.final_boundary_update_id is not None

    reopened = OnlySqliteRuntimePersistenceStore(state_path)
    checkpoint_after_recovery = reopened.latest_checkpoint(runtime_id)
    assert checkpoint_after_recovery is not None
    assert checkpoint_after_recovery.header.replay_cursor.last_source_sequence > (
        checkpoint_before_tail.header.replay_cursor.last_source_sequence
    )
    assert checkpoint_after_recovery.header.checkpoint_sequence > checkpoint_before_tail.header.checkpoint_sequence
    reopened.close()

    baseline_engine = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path / "baseline"))
    baseline_engine.add_cluster(config)
    baseline = baseline_engine.run()
    assert baseline.status == "COMPLETED"
    assert only_backtest_business_projection(recovered.runtime_results[0]) == only_backtest_business_projection(
        baseline.runtime_results[0]
    )
