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
from onlyalpha.runtime.persistence.store import OnlyRuntimeTransactionOutboxKey, OnlySqliteRuntimePersistenceStore
from tests.execution.support.execution_fault_injection import (
    OnlyFailOnceRuntimePersistenceStore,
    OnlyTestRuntimePersistenceFault,
)
from tests.integration.test_engine_continuous_restart import _sqlite_config


class OnlyPersistentOutboxFailureStore(OnlyFailOnceRuntimePersistenceStore):
    def mark_published(self, key: OnlyRuntimeTransactionOutboxKey, published_at: object) -> None:
        del key, published_at
        raise RuntimeError("injected persistent Engine A outbox acknowledgement failure")


class OnlyOutboxFaultRuntimePersistenceStoreFactory:
    def __init__(self) -> None:
        self._delegate = OnlyDefaultRuntimePersistenceStoreFactory()

    def validate(self, config: OnlyRuntimePersistenceConfig) -> None:
        self._delegate.validate(config)

    def create(self, request: OnlyRuntimePersistenceStoreCreateRequest) -> OnlyPersistentOutboxFailureStore:
        return OnlyPersistentOutboxFailureStore(
            self._delegate.create(request),
            OnlyTestRuntimePersistenceFault.OUTBOX_MARK_PUBLISHED,
        )


def test_engine_restart_retries_same_ready_outbox_event_without_projection_replay(tmp_path: Path) -> None:
    config = _sqlite_config(tmp_path)
    engine_id = OnlyEngineId("outbox-restart")
    engine_a = OnlyEngine(
        OnlyEngineConfig(engine_id, tmp_path),
        services=only_default_engine_services(
            runtime_persistence_store_factory=OnlyOutboxFaultRuntimePersistenceStoreFactory()
        ),
    )
    engine_a.add_cluster(config)
    engine_a.run()
    runtime_id = engine_a.runtime_sessions[0].runtime_id
    path = OnlyUserDataLayout(tmp_path).runtime_persistence_path(engine_id, runtime_id)
    reader = OnlySqliteRuntimePersistenceStore(path)
    assert reader.ready_count(runtime_id) == 2
    before = reader.outbox_records(runtime_id)
    assert before and all(not item.published for item in before)
    assert any(item.attempt_count >= 1 for item in before)
    event_ids = tuple(item.event.event_id for item in before)
    attempts = tuple(item.attempt_count for item in before)
    reader.close()

    engine_b = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path))
    engine_b.add_cluster(config)
    engine_b.initialize()
    engine_b.start()
    engine_b.stop()

    reopened = OnlySqliteRuntimePersistenceStore(path)
    after = reopened.outbox_records(runtime_id)
    assert reopened.ready_count(runtime_id) == 2
    assert reopened.pending_count(runtime_id) == 0
    assert tuple(item.event.event_id for item in after) == event_ids
    assert all(item.published for item in after)
    assert all(item.attempt_count > prior for item, prior in zip(after, attempts, strict=True))
    reopened.close()
