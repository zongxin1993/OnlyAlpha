from pathlib import Path

from onlyalpha.config import OnlyExecutionStoreConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.execution import OnlySqliteExecutionTransactionStore
from onlyalpha.execution.transaction_store import OnlyExecutionTransactionOutboxKey
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
from tests.integration.test_engine_execution_store_restart import _sqlite_config


class OnlyPersistentOutboxFailureStore(OnlyFailOnceExecutionTransactionStore):
    def mark_published(self, key: OnlyExecutionTransactionOutboxKey, published_at: object) -> None:
        del key, published_at
        raise RuntimeError("injected persistent Engine A outbox acknowledgement failure")


class OnlyOutboxFaultExecutionTransactionStoreFactory:
    def __init__(self) -> None:
        self._delegate = OnlyDefaultExecutionTransactionStoreFactory()

    def validate(self, config: OnlyExecutionStoreConfig) -> None:
        self._delegate.validate(config)

    def create(self, request: OnlyExecutionTransactionStoreCreateRequest) -> OnlyPersistentOutboxFailureStore:
        return OnlyPersistentOutboxFailureStore(
            self._delegate.create(request),
            OnlyTestExecutionStoreFault.OUTBOX_MARK_PUBLISHED,
        )


def test_engine_restart_retries_same_ready_outbox_event_without_projection_replay(tmp_path: Path) -> None:
    config = _sqlite_config()
    engine_id = OnlyEngineId("outbox-restart")
    engine_a = OnlyEngine(
        OnlyEngineConfig(engine_id, tmp_path),
        services=only_default_engine_services(
            execution_transaction_store_factory=OnlyOutboxFaultExecutionTransactionStoreFactory()
        ),
    )
    engine_a.add_cluster(config)
    engine_a.run()
    runtime_id = engine_a.runtime_sessions[0].runtime_id
    path = OnlyUserDataLayout(tmp_path).execution_store_path(engine_id, runtime_id)
    reader = OnlySqliteExecutionTransactionStore(path)
    assert reader.ready_count(runtime_id) == 1
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

    reopened = OnlySqliteExecutionTransactionStore(path)
    after = reopened.outbox_records(runtime_id)
    assert reopened.ready_count(runtime_id) == 1
    assert reopened.pending_count(runtime_id) == 0
    assert tuple(item.event.event_id for item in after) == event_ids
    assert all(item.published for item in after)
    assert all(item.attempt_count > prior for item, prior in zip(after, attempts, strict=True))
    reopened.close()
