import json
from dataclasses import replace
from pathlib import Path

from onlyalpha.config import OnlyRuntimePersistenceConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.runtime.backtest.checkpoint import only_backtest_replay_cursor
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
from tests.integration.test_engine_continuous_restart import _sqlite_config


class OnlyOpenOrderCheckpointFaultFactory:
    def __init__(self) -> None:
        self._delegate = OnlyDefaultRuntimePersistenceStoreFactory()

    def validate(self, config: OnlyRuntimePersistenceConfig) -> None:
        self._delegate.validate(config)

    def create(self, request: OnlyRuntimePersistenceStoreCreateRequest) -> OnlyFailOnceRuntimePersistenceStore:
        return OnlyFailOnceRuntimePersistenceStore(
            self._delegate.create(request),
            OnlyTestRuntimePersistenceFault.CHECKPOINT_WRITE,
            fault_after=22,
        )


def test_engine_restart_restores_open_order_and_virtual_broker_before_fill(tmp_path: Path) -> None:
    config = _sqlite_config(tmp_path)
    action = dict(config.cluster.scenario_actions[0])
    action["sequence"] = 21
    config = replace(config, cluster=replace(config.cluster, scenario_actions=(action,)))
    engine_id = OnlyEngineId("open-order-restart")
    engine_a = OnlyEngine(
        OnlyEngineConfig(engine_id, tmp_path),
        services=only_default_engine_services(runtime_persistence_store_factory=OnlyOpenOrderCheckpointFaultFactory()),
    )
    engine_a.add_cluster(config)
    assert engine_a.run().status == "FAILED"
    runtime_id = engine_a.runtime_sessions[0].runtime_id
    path = OnlyUserDataLayout(tmp_path).runtime_persistence_path(engine_id, runtime_id)
    reader = OnlySqliteRuntimePersistenceStore(path)
    checkpoint = reader.latest_checkpoint(runtime_id)
    assert checkpoint is not None
    cursor = only_backtest_replay_cursor(checkpoint)
    assert cursor.last_event_time is not None
    assert cursor.last_event_time.to_datetime().minute == 51
    order_component = next(item for item in checkpoint.components if item.component_id == "order.authority")
    order_payload = json.loads(order_component.payload)
    assert json.loads(order_payload["orders"][0]["snapshot"])["status"] == "ACCEPTED"
    reader.close()

    engine_b = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path))
    engine_b.add_cluster(config)
    recovered = engine_b.run()
    assert recovered.status == "COMPLETED"
    assert recovered.runtime_results[0].orders[0].status.value == "FILLED"

    baseline_root = tmp_path / "baseline"
    baseline_engine = OnlyEngine(OnlyEngineConfig(engine_id, baseline_root))
    baseline_config = _sqlite_config(baseline_root)
    baseline_action = dict(baseline_config.cluster.scenario_actions[0])
    baseline_action["sequence"] = 21
    baseline_engine.add_cluster(
        replace(baseline_config, cluster=replace(baseline_config.cluster, scenario_actions=(baseline_action,)))
    )
    baseline = baseline_engine.run()
    assert baseline.status == "COMPLETED"
    assert recovered.runtime_results[0].result_fingerprint == baseline.runtime_results[0].result_fingerprint
