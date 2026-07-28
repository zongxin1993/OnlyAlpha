import sqlite3
from collections.abc import Iterator
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

import onlyalpha.execution.transaction_store as transaction_store_module
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.event.model import OnlyEventId
from onlyalpha.execution import (
    OnlyExecutionTransactionConflict,
    OnlyExecutionTransactionStoreError,
    OnlyInMemoryExecutionTransactionStore,
    OnlySqliteExecutionTransactionStore,
    only_decode_committed_execution_transaction,
    only_decode_prepared_execution_transaction,
    only_encode_committed_execution_transaction,
    only_encode_prepared_execution_transaction,
)
from tests.execution.factories.transaction_factory import only_test_generic_t0_cash_buy_open_transaction

type TransactionStore = OnlyInMemoryExecutionTransactionStore | OnlySqliteExecutionTransactionStore
_prepared = only_test_generic_t0_cash_buy_open_transaction


def test_prepared_transaction_is_immutable_canonical_and_round_trippable() -> None:
    prepared = _prepared()
    payload = only_encode_prepared_execution_transaction(prepared)
    assert only_decode_prepared_execution_transaction(payload) == prepared
    assert only_encode_prepared_execution_transaction(only_decode_prepared_execution_transaction(payload)) == payload
    assert len(prepared.authority_hash) == len(prepared.payload_hash) == 64
    with pytest.raises(FrozenInstanceError):
        prepared.transaction_id = "changed"  # type: ignore[misc]


def test_identity_event_and_hash_contracts_are_deterministic() -> None:
    first = _prepared()
    later = replace(
        first, prepared_at=OnlyTimestamp(first.prepared_at.unix_nanos + 1), authority_hash="", payload_hash=""
    )
    replay = _prepared()
    assert first.transaction_id == replay.transaction_id
    assert tuple(item.event_id for item in first.outbox_events) == tuple(item.event_id for item in replay.outbox_events)
    assert later.authority_hash == first.authority_hash
    assert later.payload_hash != first.payload_hash
    with pytest.raises(ValueError, match="event identity"):
        replace(
            first,
            outbox_events=(replace(first.outbox_events[0], event_id=OnlyEventId.new()), *first.outbox_events[1:]),
            authority_hash="",
            payload_hash="",
        )


def test_prepared_transaction_rejects_identity_projection_precondition_and_hash_errors() -> None:
    prepared = _prepared()
    with pytest.raises(ValueError, match="requires identity"):
        replace(prepared, transaction_id="arbitrary", authority_hash="", payload_hash="")
    with pytest.raises(ValueError, match="one-to-one"):
        replace(prepared, preconditions=(), authority_hash="", payload_hash="")
    with pytest.raises(ValueError, match="authority hash mismatch"):
        replace(prepared, authority_hash="0" * 64)


@pytest.fixture(params=("memory", "sqlite"))
def transaction_store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[TransactionStore]:
    store: TransactionStore = (
        OnlyInMemoryExecutionTransactionStore()
        if request.param == "memory"
        else OnlySqliteExecutionTransactionStore(tmp_path / "transactions.sqlite3")
    )
    yield store
    if isinstance(store, OnlySqliteExecutionTransactionStore):
        store.close()


def test_memory_and_sqlite_share_commit_idempotency_ready_and_outbox_contract(
    transaction_store: TransactionStore,
) -> None:
    prepared = _prepared()
    committed_at = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 1, tzinfo=UTC))
    first = transaction_store.commit(prepared, committed_at=committed_at)
    duplicate = transaction_store.commit(prepared, committed_at=committed_at)
    assert first.inserted and not duplicate.inserted and duplicate.transaction == first.transaction
    assert first.transaction.execution_sequence == first.transaction.fact.execution_sequence == 1
    assert transaction_store.pending(prepared.runtime_id, limit=10) == ()
    payload = only_encode_committed_execution_transaction(first.transaction)
    assert only_decode_committed_execution_transaction(payload) == first.transaction
    projected_at = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 2, tzinfo=UTC))
    transaction_store.mark_projection_ready(prepared.runtime_id, 1, projected_at=projected_at)
    pending = transaction_store.pending(prepared.runtime_id, limit=10)
    assert tuple(item.event.event_id for item in pending) == tuple(item.event_id for item in prepared.outbox_events)
    attempted = transaction_store.begin_attempt(pending[0].key, projected_at)
    assert attempted.attempt_count == 1
    transaction_store.mark_published(pending[0].key, projected_at)
    assert transaction_store.outbox_records(prepared.runtime_id)[0].published


def test_memory_and_sqlite_conflict_and_contiguous_sequence_contract(transaction_store: TransactionStore) -> None:
    first = _prepared()
    timestamp = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 1, tzinfo=UTC))
    transaction_store.commit(first, committed_at=timestamp)
    changed_fact = replace(first.fact_draft, market_profile_version="conflicting-version")
    conflict = replace(first, fact_draft=changed_fact, authority_hash="", payload_hash="")
    with pytest.raises(OnlyExecutionTransactionConflict):
        transaction_store.commit(conflict, committed_at=timestamp)
    second = _prepared(trade_id=type(first.trade_id)("trade-2"), update_id=type(first.broker_update_id)("update-2"))
    assert transaction_store.commit(second, committed_at=timestamp).transaction.execution_sequence == 2


def test_sqlite_restart_and_payload_corruption_detection(tmp_path: Path) -> None:
    path = tmp_path / "restart.sqlite3"
    prepared = _prepared()
    committed_at = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 1, tzinfo=UTC))
    store = OnlySqliteExecutionTransactionStore(path)
    expected = store.commit(prepared, committed_at=committed_at).transaction
    store.close()
    recovered = OnlySqliteExecutionTransactionStore(path)
    assert recovered.get_by_sequence(prepared.runtime_id, 1) == expected
    recovered.close()
    connection = sqlite3.connect(path)
    with connection:
        connection.execute("UPDATE execution_transactions SET prepared_payload_hash=?", ("0" * 64,))
    connection.close()
    corrupted = OnlySqliteExecutionTransactionStore(path)
    with pytest.raises(OnlyExecutionTransactionStoreError) as captured:
        corrupted.get_by_sequence(prepared.runtime_id, 1)
    assert isinstance(captured.value.__cause__, ValueError)
    corrupted.close()


def test_sqlite_detects_outbox_payload_corruption(tmp_path: Path) -> None:
    path = tmp_path / "outbox-corrupt.sqlite3"
    prepared = _prepared()
    store = OnlySqliteExecutionTransactionStore(path)
    store.commit(
        prepared,
        committed_at=OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 1, tzinfo=UTC)),
    )
    store.mark_projection_ready(
        prepared.runtime_id,
        1,
        projected_at=OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 2, tzinfo=UTC)),
    )
    store.close()
    connection = sqlite3.connect(path)
    with connection:
        payload = connection.execute(
            "SELECT event_payload FROM execution_transaction_outbox WHERE event_sequence=1"
        ).fetchone()[0]
        connection.execute(
            "UPDATE execution_transaction_outbox SET event_payload=? WHERE event_sequence=1",
            (payload.replace('"sequence":1', '"sequence":99'),),
        )
    connection.close()
    corrupted = OnlySqliteExecutionTransactionStore(path)
    with pytest.raises(OnlyExecutionTransactionStoreError) as captured:
        corrupted.pending(prepared.runtime_id, limit=10)
    assert isinstance(captured.value.__cause__, ValueError)
    corrupted.close()


def test_memory_commit_failure_does_not_publish_partial_state(monkeypatch: pytest.MonkeyPatch) -> None:
    prepared = _prepared()
    store = OnlyInMemoryExecutionTransactionStore()

    def fail_outbox(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected outbox failure")

    monkeypatch.setattr(transaction_store_module, "OnlyExecutionTransactionOutboxRecord", fail_outbox)
    with pytest.raises(OnlyExecutionTransactionStoreError) as captured:
        store.commit(
            prepared,
            committed_at=OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 1, tzinfo=UTC)),
        )
    assert isinstance(captured.value.__cause__, RuntimeError)
    assert store.records() == ()
    assert store.get_by_transaction_id(prepared.transaction_id) is None
    assert store.outbox_records(prepared.runtime_id) == ()


def test_sqlite_commit_failure_rolls_back_transaction_and_sequence(tmp_path: Path) -> None:
    path = tmp_path / "rollback.sqlite3"
    bootstrap = OnlySqliteExecutionTransactionStore(path)
    bootstrap.close()
    connection = sqlite3.connect(path)
    with connection:
        connection.execute(
            "CREATE TRIGGER fail_outbox BEFORE INSERT ON execution_transaction_outbox "
            "BEGIN SELECT RAISE(ABORT, 'injected outbox failure'); END"
        )
    connection.close()
    prepared = _prepared()
    store = OnlySqliteExecutionTransactionStore(path)
    with pytest.raises(OnlyExecutionTransactionStoreError) as captured:
        store.commit(
            prepared,
            committed_at=OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 1, tzinfo=UTC)),
        )
    assert isinstance(captured.value.__cause__, sqlite3.IntegrityError)
    assert store.records() == ()
    store.close()
    connection = sqlite3.connect(path)
    with connection:
        connection.execute("DROP TRIGGER fail_outbox")
    connection.close()
    recovered = OnlySqliteExecutionTransactionStore(path)
    result = recovered.commit(
        prepared,
        committed_at=OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 1, tzinfo=UTC)),
    )
    assert result.transaction.execution_sequence == 1
    recovered.close()
