from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.event.model import OnlyEventScope
from onlyalpha.execution import (
    OnlyExecutionOutboxPublisher,
    OnlyInMemoryExecutionTransactionStore,
    OnlySqliteExecutionTransactionStore,
)
from tests.execution.factories.transaction_factory import only_test_generic_t0_cash_buy_open_transaction


@pytest.fixture(params=("memory", "sqlite"))
def outbox_store(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[OnlyInMemoryExecutionTransactionStore | OnlySqliteExecutionTransactionStore]:
    store: OnlyInMemoryExecutionTransactionStore | OnlySqliteExecutionTransactionStore
    if request.param == "memory":
        store = OnlyInMemoryExecutionTransactionStore()
    else:
        store = OnlySqliteExecutionTransactionStore(tmp_path / "outbox.sqlite3")
    yield store
    if isinstance(store, OnlySqliteExecutionTransactionStore):
        store.close()


def _append(store: OnlyInMemoryExecutionTransactionStore | OnlySqliteExecutionTransactionStore):
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    committed_at = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 1, tzinfo=UTC))
    committed = store.commit(prepared, committed_at=committed_at).transaction
    store.mark_projection_ready(prepared.runtime_id, committed.execution_sequence, projected_at=committed_at)
    return prepared


def test_memory_and_sqlite_outbox_share_attempt_failure_and_published_semantics(
    outbox_store: OnlyInMemoryExecutionTransactionStore | OnlySqliteExecutionTransactionStore,
) -> None:
    prepared = _append(outbox_store)
    events = prepared.outbox_events
    pending = outbox_store.pending(prepared.runtime_id, limit=100)
    assert tuple(record.key.event_sequence for record in pending) == (1, 2)
    assert tuple(record.event.event_id for record in pending) == tuple(event.event_id for event in events)

    attempted_at = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 1, tzinfo=UTC))
    attempted = outbox_store.begin_attempt(pending[0].key, attempted_at)
    assert attempted.attempt_count == 1
    assert attempted.last_attempted_at == attempted_at

    failed_at = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 2, tzinfo=UTC))
    outbox_store.mark_failed(pending[0].key, failed_at, "RuntimeError: unavailable")
    failed = outbox_store.outbox_records(prepared.runtime_id)[0]
    assert (failed.published, failed.attempt_count, failed.last_attempted_at) == (False, 1, failed_at)
    assert failed.last_error == "RuntimeError: unavailable"

    outbox_store.begin_attempt(pending[0].key, attempted_at)
    published_at = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 3, tzinfo=UTC))
    outbox_store.mark_published(pending[0].key, published_at)
    published = outbox_store.outbox_records(prepared.runtime_id)[0]
    assert (published.published, published.attempt_count, published.published_at) == (True, 2, published_at)
    assert published.last_error is None
    assert tuple(record.key.event_sequence for record in outbox_store.pending(prepared.runtime_id, limit=100)) == (2,)
    assert outbox_store.pending_count(prepared.runtime_id) == 1


def test_sqlite_restart_preserves_pending_payload_and_event_identity(tmp_path: Path) -> None:
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    path = tmp_path / "restart.sqlite3"
    store = OnlySqliteExecutionTransactionStore(path)
    events = _append(store).outbox_events
    store.close()

    recovered = OnlySqliteExecutionTransactionStore(path)
    pending = recovered.pending(prepared.runtime_id, limit=100)
    assert tuple(record.event.event_id for record in pending) == tuple(event.event_id for event in events)
    assert tuple(record.event.to_dict() for record in pending) == tuple(event.to_dict() for event in events)
    recovered.close()


def test_outbox_publisher_stops_on_first_failure_and_retries_same_event_id() -> None:
    store = OnlyInMemoryExecutionTransactionStore()
    prepared = _append(store)
    events = prepared.outbox_events
    bus = OnlyEventBus(capacity=1, scope=OnlyEventScope(OnlyEngineId("engine"), prepared.runtime_id))
    bus.publish(events[0])
    now = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 1, tzinfo=UTC))
    publisher = OnlyExecutionOutboxPublisher(store, bus, lambda: now)

    failed = publisher.publish_pending(prepared.runtime_id)
    records = store.outbox_records(prepared.runtime_id)
    assert (failed.attempted, failed.published, failed.failed, failed.remaining) == (1, 0, 1, 2)
    assert tuple(record.attempt_count for record in records) == (1, 0)
    assert records[0].event.event_id == events[0].event_id

    bus.drain()
    first_retry = publisher.publish_pending(prepared.runtime_id)
    assert (first_retry.attempted, first_retry.published, first_retry.failed) == (2, 1, 1)
    bus.drain()
    final_retry = publisher.publish_pending(prepared.runtime_id)
    assert (final_retry.attempted, final_retry.published, final_retry.failed, final_retry.remaining) == (1, 1, 0, 0)
    assert tuple(record.attempt_count for record in store.outbox_records(prepared.runtime_id)) == (2, 2)


class _OnlyFailPublishedOnceStore(OnlyInMemoryExecutionTransactionStore):
    def __init__(self) -> None:
        super().__init__()
        self._failed = False

    def mark_published(self, key, published_at):  # type: ignore[no-untyped-def]
        if not self._failed:
            self._failed = True
            raise RuntimeError("injected mark published failure")
        super().mark_published(key, published_at)


def test_eventbus_accept_before_mark_published_retries_the_same_stable_event() -> None:
    store = _OnlyFailPublishedOnceStore()
    prepared = _append(store)
    bus = OnlyEventBus(capacity=10, scope=OnlyEventScope(OnlyEngineId("engine"), prepared.runtime_id))
    now = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 1, tzinfo=UTC))
    publisher = OnlyExecutionOutboxPublisher(store, bus, lambda: now)

    failed = publisher.publish_pending(prepared.runtime_id)
    assert (failed.published, failed.failed) == (0, 1)
    recovered = publisher.publish_pending(prepared.runtime_id)
    assert (recovered.published, recovered.failed, recovered.remaining) == (2, 0, 0)

    assert bus.drain() == 3
    assert tuple(item.event.event_id for item in bus.dispatch_results) == (
        prepared.outbox_events[0].event_id,
        prepared.outbox_events[0].event_id,
        prepared.outbox_events[1].event_id,
    )
