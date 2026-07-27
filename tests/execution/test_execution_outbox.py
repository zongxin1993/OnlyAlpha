from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.event.model import OnlyEvent, OnlyEventScope
from onlyalpha.execution import (
    OnlyDurableExecutionCommit,
    OnlyExecutionOutboxPublisher,
    OnlyInMemoryCommittedExecutionJournal,
    OnlySqliteCommittedExecutionJournal,
)
from tests.execution.test_committed_execution_journal import _fact


def _events() -> tuple[OnlyEvent, ...]:
    fact = _fact()
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    return tuple(
        OnlyEvent(
            f"TRADE_EVENT_{sequence}",
            timestamp,
            OnlyEngineId("engine"),
            fact.runtime_id,
            "execution",
            sequence,
            payload={"sequence": sequence},
        )
        for sequence in (1, 2)
    )


@pytest.fixture(params=("memory", "sqlite"))
def outbox_store(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[OnlyInMemoryCommittedExecutionJournal | OnlySqliteCommittedExecutionJournal]:
    fact = _fact()
    store: OnlyInMemoryCommittedExecutionJournal | OnlySqliteCommittedExecutionJournal
    if request.param == "memory":
        store = OnlyInMemoryCommittedExecutionJournal(fact.runtime_id, (fact.gateway_id,))
    else:
        store = OnlySqliteCommittedExecutionJournal(tmp_path / "outbox.sqlite3")
    yield store
    if isinstance(store, OnlySqliteCommittedExecutionJournal):
        store.close()


def _append(store: object) -> tuple[OnlyEvent, ...]:
    fact = _fact()
    events = _events()
    assert isinstance(store, OnlyInMemoryCommittedExecutionJournal | OnlySqliteCommittedExecutionJournal)
    store.append_transaction(OnlyDurableExecutionCommit("transaction", fact, events))
    return events


def test_memory_and_sqlite_outbox_share_attempt_failure_and_published_semantics(
    outbox_store: OnlyInMemoryCommittedExecutionJournal | OnlySqliteCommittedExecutionJournal,
) -> None:
    events = _append(outbox_store)
    pending = outbox_store.pending(_fact().runtime_id, limit=100)
    assert tuple(record.key.event_sequence for record in pending) == (1, 2)
    assert tuple(record.event.event_id for record in pending) == tuple(event.event_id for event in events)

    attempted_at = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 1, tzinfo=UTC))
    attempted = outbox_store.begin_attempt(pending[0].key, attempted_at)
    assert attempted.attempt_count == 1
    assert attempted.last_attempted_at == attempted_at

    failed_at = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 2, tzinfo=UTC))
    outbox_store.mark_failed(pending[0].key, failed_at, "RuntimeError: unavailable")
    failed = outbox_store.outbox_records(_fact().runtime_id)[0]
    assert (failed.published, failed.attempt_count, failed.last_attempted_at) == (False, 1, failed_at)
    assert failed.last_error == "RuntimeError: unavailable"

    outbox_store.begin_attempt(pending[0].key, attempted_at)
    published_at = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 3, tzinfo=UTC))
    outbox_store.mark_published(pending[0].key, published_at)
    published = outbox_store.outbox_records(_fact().runtime_id)[0]
    assert (published.published, published.attempt_count, published.published_at) == (True, 2, published_at)
    assert published.last_error is None
    assert tuple(record.key.event_sequence for record in outbox_store.pending(_fact().runtime_id, limit=100)) == (2,)
    assert outbox_store.pending_count(_fact().runtime_id) == 1


def test_sqlite_restart_preserves_pending_payload_and_event_identity(tmp_path: Path) -> None:
    fact = _fact()
    path = tmp_path / "restart.sqlite3"
    store = OnlySqliteCommittedExecutionJournal(path)
    events = _append(store)
    store.close()

    recovered = OnlySqliteCommittedExecutionJournal(path)
    pending = recovered.pending(fact.runtime_id, limit=100)
    assert tuple(record.event.event_id for record in pending) == tuple(event.event_id for event in events)
    assert tuple(record.event.to_dict() for record in pending) == tuple(event.to_dict() for event in events)
    recovered.close()


def test_outbox_publisher_stops_on_first_failure_and_retries_same_event_id() -> None:
    fact = _fact()
    store = OnlyInMemoryCommittedExecutionJournal(fact.runtime_id, (fact.gateway_id,))
    events = _append(store)
    bus = OnlyEventBus(capacity=1, scope=OnlyEventScope(OnlyEngineId("engine"), fact.runtime_id))
    bus.publish(events[0])
    now = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 1, tzinfo=UTC))
    publisher = OnlyExecutionOutboxPublisher(store, bus, lambda: now)

    failed = publisher.publish_pending(fact.runtime_id)
    records = store.outbox_records(fact.runtime_id)
    assert (failed.attempted, failed.published, failed.failed, failed.remaining) == (1, 0, 1, 2)
    assert tuple(record.attempt_count for record in records) == (1, 0)
    assert records[0].event.event_id == events[0].event_id

    bus.drain()
    first_retry = publisher.publish_pending(fact.runtime_id)
    assert (first_retry.attempted, first_retry.published, first_retry.failed) == (2, 1, 1)
    bus.drain()
    final_retry = publisher.publish_pending(fact.runtime_id)
    assert (final_retry.attempted, final_retry.published, final_retry.failed, final_retry.remaining) == (1, 1, 0, 0)
    assert tuple(record.attempt_count for record in store.outbox_records(fact.runtime_id)) == (2, 2)
