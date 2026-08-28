from dataclasses import replace
from pathlib import Path

from onlyalpha.config import OnlyClusterRunConfig, OnlyRuntimePersistenceConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngineConfig
from onlyalpha.engine.engine import OnlyEngine
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.result import only_backtest_business_projection
from onlyalpha.runtime.backtest.checkpoint import only_backtest_replay_cursor
from onlyalpha.runtime.checkpoint.model import OnlyRuntimeCheckpoint
from onlyalpha.runtime.defaults import only_default_engine_services
from onlyalpha.runtime.persistence.factory import (
    OnlyDefaultRuntimePersistenceStoreFactory,
    OnlyRuntimePersistenceStoreCreateRequest,
)
from onlyalpha.runtime.persistence.store import OnlyRuntimePersistenceStorePort, OnlySqliteRuntimePersistenceStore
from onlyalpha.transaction.enums import OnlyRuntimeOperationKind
from tests.execution.support.execution_fault_injection import (
    OnlyFailOnceRuntimePersistenceStore,
    OnlyTestRuntimePersistenceFault,
)
from tests.integration.test_engine_continuous_restart import _sqlite_config


class OnlyTwoBoundaryTailRuntimePersistenceStore(OnlyFailOnceRuntimePersistenceStore):
    """Keep the last stable checkpoint while two later Bar transactions form the tail."""

    def __init__(self, delegate: OnlyRuntimePersistenceStorePort) -> None:
        super().__init__(
            delegate,
            OnlyTestRuntimePersistenceFault.AFTER_COMMIT,
            fault_after=1,
            operation_kind=OnlyRuntimeOperationKind.TRADE_FILL,
        )
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


def _multi_boundary_config(user_data_root: Path) -> OnlyClusterRunConfig:
    baseline = _sqlite_config(user_data_root)
    action = dict(baseline.cluster.scenario_actions[0])
    actions = (
        {**action, "action_id": "FIRST", "sequence": 9},
        {**action, "action_id": "SECOND", "sequence": 10},
    )
    return replace(
        baseline,
        runtime=replace(baseline.runtime, end_time=baseline.runtime.start_time.replace(minute=45)),  # type: ignore[union-attr]
        cluster=replace(baseline.cluster, scenario_actions=actions),
    )


def test_engine_tail_spans_two_exact_market_data_boundaries(tmp_path: Path) -> None:
    config = _multi_boundary_config(tmp_path)
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
    assert tuple(item.execution_sequence for item in transactions) == (1, 2, 3, 4)
    assert tuple(item.operation_kind for item in transactions) == (
        OnlyRuntimeOperationKind.ORDER_ACCEPTED,
        OnlyRuntimeOperationKind.TRADE_FILL,
        OnlyRuntimeOperationKind.ORDER_ACCEPTED,
        OnlyRuntimeOperationKind.TRADE_FILL,
    )
    assert tuple(item.projection_ready for item in transactions) == (True, True, True, False)
    assert transactions[1].fact.ts_event < transactions[3].fact.ts_event
    checkpoint_before_tail = reader.latest_checkpoint(runtime_id)
    assert checkpoint_before_tail is not None
    reader.close()

    engine_b = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path))
    engine_b.add_cluster(config)
    recovered = engine_b.run()
    assert recovered.status == "COMPLETED", recovered.failures
    diagnostic = engine_b.runtime_sessions[0].runtime.runtime_recovery_diagnostics[-1]
    assert diagnostic.catch_up_bar_count >= 2
    assert diagnostic.rehydrated_transaction_count == 3
    assert diagnostic.recovered_transaction_count == 1
    assert diagnostic.final_boundary_update_id is not None

    reopened = OnlySqliteRuntimePersistenceStore(state_path)
    checkpoint_after_recovery = reopened.latest_checkpoint(runtime_id)
    assert checkpoint_after_recovery is not None
    assert only_backtest_replay_cursor(checkpoint_after_recovery).last_source_sequence > (
        only_backtest_replay_cursor(checkpoint_before_tail).last_source_sequence
    )
    assert checkpoint_after_recovery.header.checkpoint_sequence > checkpoint_before_tail.header.checkpoint_sequence
    reopened.close()

    baseline_root = tmp_path / "baseline"
    baseline_engine = OnlyEngine(OnlyEngineConfig(engine_id, baseline_root))
    baseline_engine.add_cluster(_multi_boundary_config(baseline_root))
    baseline = baseline_engine.run()
    assert baseline.status == "COMPLETED"
    assert only_backtest_business_projection(recovered.runtime_results[0]) == only_backtest_business_projection(
        baseline.runtime_results[0]
    )
