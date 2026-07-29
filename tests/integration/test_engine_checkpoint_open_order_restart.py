import json
from pathlib import Path

from onlyalpha.config import OnlyRuntimePersistenceConfig
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
    config = _sqlite_config()
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
    assert checkpoint.header.replay_cursor.last_event_time is not None
    assert checkpoint.header.replay_cursor.last_event_time.to_datetime().minute == 51
    order_component = next(item for item in checkpoint.components if item.component_id == "order.authority")
    order_payload = json.loads(order_component.payload)
    assert json.loads(order_payload["orders"][0]["snapshot"])["status"] == "ACCEPTED"
    reader.close()

    engine_b = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path))
    engine_b.add_cluster(config)
    recovered = engine_b.run()
    assert recovered.status == "COMPLETED"
    assert recovered.runtime_results[0].orders[0].status.value == "FILLED"

    baseline_engine = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path / "baseline"))
    baseline_engine.add_cluster(config)
    baseline = baseline_engine.run()
    assert baseline.status == "COMPLETED"
    assert recovered.runtime_results[0].result_fingerprint == baseline.runtime_results[0].result_fingerprint
