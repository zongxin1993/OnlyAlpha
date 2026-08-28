from dataclasses import replace
from pathlib import Path

from onlyalpha.config import OnlyClusterRunConfig, OnlyRuntimePersistenceConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngineConfig
from onlyalpha.engine.engine import OnlyEngine
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.result import only_backtest_business_projection
from onlyalpha.runtime.defaults import only_default_engine_services
from onlyalpha.runtime.persistence.factory import (
    OnlyDefaultRuntimePersistenceStoreFactory,
    OnlyRuntimePersistenceStoreCreateRequest,
)
from onlyalpha.runtime.persistence.store import OnlySqliteRuntimePersistenceStore
from onlyalpha.transaction.enums import OnlyRuntimeOperationKind
from tests.execution.support.execution_fault_injection import (
    OnlyFailOnceRuntimePersistenceStore,
    OnlyTestRuntimePersistenceFault,
)
from tests.integration.test_engine_continuous_restart import _sqlite_config


class OnlySecondCommitFaultFactory:
    def __init__(self) -> None:
        self._delegate = OnlyDefaultRuntimePersistenceStoreFactory()

    def validate(self, config: OnlyRuntimePersistenceConfig) -> None:
        self._delegate.validate(config)

    def create(self, request: OnlyRuntimePersistenceStoreCreateRequest) -> OnlyFailOnceRuntimePersistenceStore:
        return OnlyFailOnceRuntimePersistenceStore(
            self._delegate.create(request),
            OnlyTestRuntimePersistenceFault.AFTER_COMMIT,
            fault_after=1,
            operation_kind=OnlyRuntimeOperationKind.TRADE_FILL,
        )


def _multi_order_config(user_data_root: Path) -> OnlyClusterRunConfig:
    baseline = _sqlite_config(user_data_root)
    actions = (
        {**dict(baseline.cluster.scenario_actions[0]), "action_id": "BUY_1", "sequence": 9},
        {**dict(baseline.cluster.scenario_actions[0]), "action_id": "BUY_2", "sequence": 10},
        {
            **dict(baseline.cluster.scenario_actions[0]),
            "action_id": "SELL_ALL",
            "sequence": 15,
            "side": "SELL",
            "quantity": "200",
            "price": "1.00",
            "offset": "CLOSE",
        },
        {**dict(baseline.cluster.scenario_actions[0]), "action_id": "POST_RECOVERY_BUY", "sequence": 20},
    )
    return replace(baseline, cluster=replace(baseline.cluster, scenario_actions=actions))


def test_engine_recovers_ready_prefix_and_unprojected_suffix_then_continues(tmp_path: Path) -> None:
    config = _multi_order_config(tmp_path)
    engine_id = OnlyEngineId("multi-tail-restart")
    engine_a = OnlyEngine(
        OnlyEngineConfig(engine_id, tmp_path),
        services=only_default_engine_services(runtime_persistence_store_factory=OnlySecondCommitFaultFactory()),
    )
    engine_a.add_cluster(config)
    assert engine_a.run().status == "FAILED"
    failed_runtime = engine_a.runtime_sessions[0].runtime
    assert failed_runtime.historical_replay_service.events
    assert failed_runtime.historical_replay_service.events[-1].result.status.value == "APPLIED"
    assert failed_runtime.result_progress.snapshot().processed_bar_count > 0
    assert config.end_time is not None
    assert failed_runtime.historical_replay_service.events[-1].update.ts_event.to_datetime() < config.end_time
    runtime_id = engine_a.runtime_sessions[0].runtime_id
    path = OnlyUserDataLayout(tmp_path).runtime_persistence_path(engine_id, runtime_id)
    reader = OnlySqliteRuntimePersistenceStore(path)
    tail = reader.records(runtime_id)
    assert tuple(item.execution_sequence for item in tail) == (1, 2, 3, 4)
    assert tuple(item.operation_kind for item in tail) == (
        OnlyRuntimeOperationKind.ORDER_ACCEPTED,
        OnlyRuntimeOperationKind.TRADE_FILL,
        OnlyRuntimeOperationKind.ORDER_ACCEPTED,
        OnlyRuntimeOperationKind.TRADE_FILL,
    )
    assert tuple(item.projection_ready for item in tail) == (True, True, True, False)
    reader.close()

    engine_b = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path))
    engine_b.add_cluster(config)
    recovered = engine_b.run()
    replay_errors = tuple(
        dispatch.error_message
        for event in engine_b.runtime_sessions[0].runtime.historical_replay_service.events
        for dispatch in event.result.dispatches
        if dispatch.error_message is not None
    )
    diagnostic_messages = tuple(
        failure.message for item in recovered.runtime_results for failure in item.diagnostics.failures
    )
    assert not diagnostic_messages, "\n".join(diagnostic_messages)
    assert recovered.status == "COMPLETED", (
        recovered.failures,
        replay_errors,
    )
    diagnostic = engine_b.runtime_sessions[0].runtime.runtime_recovery_diagnostics[-1]
    assert diagnostic.rehydrated_transaction_count == 0
    assert diagnostic.recovered_transaction_count == 1
    assert len(recovered.runtime_results[0].trades) > 2

    baseline_root = tmp_path / "baseline"
    baseline_engine = OnlyEngine(OnlyEngineConfig(engine_id, baseline_root))
    baseline_engine.add_cluster(_multi_order_config(baseline_root))
    baseline = baseline_engine.run()
    assert baseline.status == "COMPLETED"
    assert recovered.runtime_results[0].trades == baseline.runtime_results[0].trades
    assert recovered.runtime_results[0].result_fingerprint == baseline.runtime_results[0].result_fingerprint
    assert only_backtest_business_projection(recovered.runtime_results[0]) == only_backtest_business_projection(
        baseline.runtime_results[0]
    )
