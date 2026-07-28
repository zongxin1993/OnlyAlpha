import json
from pathlib import Path

from onlyalpha.config import OnlyClusterRunConfig, OnlyExecutionStoreBackend, OnlyExecutionStoreConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.execution import OnlyExecutionRecoveryStatus, OnlySqliteExecutionTransactionStore
from onlyalpha.execution.transaction_store_factory import (
    OnlyDefaultExecutionTransactionStoreFactory,
    OnlyExecutionTransactionStoreCreateRequest,
)
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.runtime.defaults import only_default_engine_services
from tests.execution.support.execution_fault_injection import (
    OnlyFailOnceExecutionTransactionStore,
    OnlyTestExecutionStoreFault,
)


class OnlyFaultInjectingExecutionTransactionStoreFactory:
    def __init__(self) -> None:
        self._delegate = OnlyDefaultExecutionTransactionStoreFactory()

    def validate(self, config: OnlyExecutionStoreConfig) -> None:
        self._delegate.validate(config)

    def create(self, request: OnlyExecutionTransactionStoreCreateRequest) -> OnlyFailOnceExecutionTransactionStore:
        return OnlyFailOnceExecutionTransactionStore(
            self._delegate.create(request),
            OnlyTestExecutionStoreFault.AFTER_COMMIT,
        )


def _sqlite_config() -> OnlyClusterRunConfig:
    baseline = OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json")
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["runtime"]["end_time"] = "2026-01-05T01:53:00Z"
    payload["runtime"]["execution_store"] = {"backend": OnlyExecutionStoreBackend.SQLITE.value}
    return OnlyClusterRunConfig.from_mapping(payload, source_path=baseline.source_path)


def test_engine_factory_reopens_store_and_recovers_without_private_mutation(tmp_path: Path) -> None:
    config = _sqlite_config()
    engine_id = OnlyEngineId("execution-restart")
    engine_a = OnlyEngine(
        OnlyEngineConfig(engine_id, tmp_path),
        services=only_default_engine_services(
            execution_transaction_store_factory=OnlyFaultInjectingExecutionTransactionStoreFactory()
        ),
    )
    engine_a.add_cluster(config)
    result_a = engine_a.run()
    runtime_id = engine_a.runtime_sessions[0].runtime_id
    path = OnlyUserDataLayout(tmp_path).execution_store_path(engine_id, runtime_id)
    assert result_a.status == "FAILED"
    assert path.is_file()
    reader = OnlySqliteExecutionTransactionStore(path)
    committed = reader.records(runtime_id)
    assert len(committed) == 1
    assert not committed[0].projection_ready
    assert reader.ready_count(runtime_id) == 0
    assert len(reader.outbox_records(runtime_id)) > 0
    assert reader.pending_count(runtime_id) == 0
    reader.close()

    engine_b = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path))
    engine_b.add_cluster(config)
    result_b = engine_b.run()
    recovery = engine_b.runtime_sessions[0].runtime.execution_recovery_diagnostics[-1]
    assert recovery.status is OnlyExecutionRecoveryStatus.RECOVERED
    assert result_b.status == "COMPLETED"

    baseline_engine = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path / "baseline"))
    baseline_engine.add_cluster(config)
    baseline_result = baseline_engine.run()
    assert baseline_result.status == "COMPLETED"
    recovered_runtime = result_b.runtime_results[0]
    baseline_runtime = baseline_result.runtime_results[0]
    assert recovered_runtime.final_account.to_dict() == baseline_runtime.final_account.to_dict()
    assert recovered_runtime.final_positions == baseline_runtime.final_positions
    assert recovered_runtime.final_allocations == baseline_runtime.final_allocations
    assert recovered_runtime.final_ledgers == baseline_runtime.final_ledgers
    assert recovered_runtime.orders == baseline_runtime.orders
    assert recovered_runtime.trades == baseline_runtime.trades
    assert recovered_runtime.account_equity_timeline == baseline_runtime.account_equity_timeline
    assert tuple(item.performance for item in recovered_runtime.cluster_results) == tuple(
        item.performance for item in baseline_runtime.cluster_results
    )
    assert recovered_runtime.cluster_equity_timelines == baseline_runtime.cluster_equity_timelines
    assert recovered_runtime.runtime_performance == baseline_runtime.runtime_performance
    assert recovered_runtime.reconciliation == baseline_runtime.reconciliation
    assert recovered_runtime.invariant_results == baseline_runtime.invariant_results
    assert recovered_runtime.facts == baseline_runtime.facts
    assert recovered_runtime.determinism_fingerprint == baseline_runtime.determinism_fingerprint
    assert recovered_runtime.result_fingerprint == baseline_runtime.result_fingerprint

    reopened = OnlySqliteExecutionTransactionStore(path)
    assert reopened.ready_count(runtime_id) == 1
    assert reopened.pending_count(runtime_id) == 0
    assert reopened.records(runtime_id)[0].transaction_id == committed[0].transaction_id
    reopened.close()
