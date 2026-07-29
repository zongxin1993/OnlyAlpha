import json
from pathlib import Path

from onlyalpha.config import OnlyClusterRunConfig, OnlyRuntimePersistenceConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.runtime.defaults import only_default_engine_services
from onlyalpha.runtime.persistence.factory import (
    OnlyDefaultRuntimePersistenceStoreFactory,
    OnlyRuntimePersistenceStoreCreateRequest,
)
from onlyalpha.runtime.persistence.store import OnlySqliteRuntimePersistenceStore
from tests.execution.support.execution_fault_injection import (
    OnlyFailOnceRuntimePersistenceStore,
    OnlyTestRuntimePersistenceFault,
)


class OnlyFaultInjectingRuntimePersistenceStoreFactory:
    def __init__(self) -> None:
        self._delegate = OnlyDefaultRuntimePersistenceStoreFactory()

    def validate(self, config: OnlyRuntimePersistenceConfig) -> None:
        self._delegate.validate(config)

    def create(self, request: OnlyRuntimePersistenceStoreCreateRequest) -> OnlyFailOnceRuntimePersistenceStore:
        return OnlyFailOnceRuntimePersistenceStore(
            self._delegate.create(request),
            OnlyTestRuntimePersistenceFault.AFTER_COMMIT,
        )


def _sqlite_config() -> OnlyClusterRunConfig:
    baseline = OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json")
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["runtime"]["end_time"] = "2026-01-05T01:53:00Z"
    payload["runtime"]["persistence"] = {
        "backend": "SQLITE",
        "checkpoint": {"enabled": True, "retain_last": 2},
    }
    return OnlyClusterRunConfig.from_mapping(payload, source_path=baseline.source_path)


def only_assert_engine_restart_equivalence(tmp_path: Path) -> None:
    config = _sqlite_config()
    engine_id = OnlyEngineId("execution-restart")
    engine_a = OnlyEngine(
        OnlyEngineConfig(engine_id, tmp_path),
        services=only_default_engine_services(
            runtime_persistence_store_factory=OnlyFaultInjectingRuntimePersistenceStoreFactory()
        ),
    )
    engine_a.add_cluster(config)
    result_a = engine_a.run()
    runtime_id = engine_a.runtime_sessions[0].runtime_id
    path = OnlyUserDataLayout(tmp_path).runtime_persistence_path(engine_id, runtime_id)
    assert result_a.status == "FAILED"
    assert path.is_file()
    reader = OnlySqliteRuntimePersistenceStore(path)
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
    recovery = engine_b.runtime_sessions[0].runtime.runtime_recovery_diagnostics[-1]
    assert recovery.recovered_transaction_count + recovery.rehydrated_transaction_count == 1
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

    reopened = OnlySqliteRuntimePersistenceStore(path)
    assert reopened.ready_count(runtime_id) == 1
    assert reopened.pending_count(runtime_id) == 0
    assert reopened.records(runtime_id)[0].transaction_id == committed[0].transaction_id
    reopened.close()


def test_engine_factory_reopens_store_and_recovers_without_private_mutation(tmp_path: Path) -> None:
    only_assert_engine_restart_equivalence(tmp_path)
