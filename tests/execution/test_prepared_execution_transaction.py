import sqlite3
from collections.abc import Iterator
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.execution import (
    OnlyCommittedExecutionFactDraft,
    OnlyExecutionPrecondition,
    OnlyExecutionProjectionComponent,
    OnlyExecutionProjectionIdentity,
    OnlyExecutionTransactionConflict,
    OnlyInMemoryExecutionTransactionStore,
    OnlyPreparedExecutionTransaction,
    OnlySettlementExecutionProjection,
    OnlySqliteExecutionTransactionStore,
    only_decode_committed_execution_transaction,
    only_decode_prepared_execution_transaction,
    only_encode_committed_execution_transaction,
    only_encode_prepared_execution_transaction,
    only_with_execution_projection_hash,
)
from tests.execution.test_committed_execution_journal import _fact
from tests.execution.test_execution_outbox import _events

type TransactionStore = OnlyInMemoryExecutionTransactionStore | OnlySqliteExecutionTransactionStore


def _prepared(*, transaction_id: str = "transaction") -> OnlyPreparedExecutionTransaction:
    fact = _fact()
    projection = only_with_execution_projection_hash(
        OnlySettlementExecutionProjection(
            OnlyExecutionProjectionIdentity(
                OnlyExecutionProjectionComponent.SETTLEMENT,
                "settlement",
                0,
                1,
                1,
                "a" * 64,
            ),
            "instruction",
            "PENDING",
            "SETTLED",
            ("record",),
        )
    )
    return OnlyPreparedExecutionTransaction(
        transaction_id,
        fact.runtime_id,
        fact.gateway_id,
        fact.account_id,
        fact.broker_update_id,
        fact.trade_id,
        fact.source_sequence,
        fact.ts_init,
        OnlyCommittedExecutionFactDraft.from_committed(fact),
        (projection,),
        _events(),
        (OnlyExecutionPrecondition(OnlyExecutionProjectionComponent.SETTLEMENT, "settlement", 0),),
    )


def test_prepared_transaction_is_immutable_canonical_and_round_trippable() -> None:
    prepared = _prepared()
    payload = only_encode_prepared_execution_transaction(prepared)

    assert only_decode_prepared_execution_transaction(payload) == prepared
    assert only_encode_prepared_execution_transaction(only_decode_prepared_execution_transaction(payload)) == payload
    assert len(prepared.stable_hash) == 64
    with pytest.raises(FrozenInstanceError):
        prepared.transaction_id = "changed"  # type: ignore[misc]


def test_prepared_transaction_rejects_scope_sequence_order_and_hash_errors() -> None:
    prepared = _prepared()
    with pytest.raises(ValueError, match="scopes disagree"):
        replace(prepared, source_sequence=prepared.source_sequence + 1, stable_hash="")
    with pytest.raises(ValueError, match="contiguous"):
        replace(
            prepared,
            projections=(
                replace(
                    prepared.projections[0], identity=replace(prepared.projections[0].identity, projection_sequence=2)
                ),
            ),
            stable_hash="",
        )
    with pytest.raises(ValueError, match="hash mismatch"):
        replace(prepared, stable_hash="0" * 64)


@pytest.fixture(params=("memory", "sqlite"))
def transaction_store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[TransactionStore]:
    store = (
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

    assert first.inserted
    assert not duplicate.inserted
    assert duplicate.transaction == first.transaction
    assert first.transaction.execution_sequence == 1
    assert first.transaction.fact.execution_sequence == 1
    assert transaction_store.pending(prepared.runtime_id, limit=10) == ()
    assert transaction_store.pending_count(prepared.runtime_id) == 0
    assert transaction_store.unprojected(prepared.runtime_id) == (first.transaction,)
    payload = only_encode_committed_execution_transaction(first.transaction)
    assert only_decode_committed_execution_transaction(payload) == first.transaction

    projected_at = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 2, tzinfo=UTC))
    transaction_store.mark_projection_ready(prepared.runtime_id, 1, projected_at=projected_at)
    pending = transaction_store.pending(prepared.runtime_id, limit=10)
    assert len(pending) == 2
    assert transaction_store.pending_count(prepared.runtime_id) == 2
    assert all(record.projection_ready for record in pending)
    assert tuple(record.event.event_id for record in pending) == tuple(
        event.event_id for event in prepared.outbox_events
    )
    attempted = transaction_store.begin_attempt(pending[0].key, projected_at)
    assert attempted.attempt_count == 1
    transaction_store.mark_published(pending[0].key, projected_at)
    assert transaction_store.outbox_records(prepared.runtime_id)[0].published
    assert transaction_store.pending_count(prepared.runtime_id) == 1


def test_memory_and_sqlite_share_contiguous_sequence_conflict_and_projection_failure_contract(
    transaction_store: TransactionStore,
) -> None:
    first = _prepared()
    timestamp = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 1, tzinfo=UTC))
    transaction_store.commit(first, committed_at=timestamp)
    second_trade = type(first.trade_id)("trade-2")
    second_update = type(first.broker_update_id)("update-2")
    second = replace(
        first,
        transaction_id="transaction-2",
        trade_id=second_trade,
        broker_update_id=second_update,
        fact_draft=replace(
            first.fact_draft,
            execution_id="EXEC-2",
            trade_id=second_trade,
            broker_update_id=second_update,
        ),
        stable_hash="",
    )
    committed = transaction_store.commit(second, committed_at=timestamp).transaction
    assert committed.execution_sequence == 2

    conflicting = replace(first, prepared_at=OnlyTimestamp(first.prepared_at.unix_nanos + 1), stable_hash="")
    with pytest.raises(OnlyExecutionTransactionConflict):
        transaction_store.commit(conflicting, committed_at=timestamp)

    transaction_store.mark_projection_failed(
        second.runtime_id,
        2,
        failed_at=OnlyTimestamp(timestamp.unix_nanos + 1),
        error="projection failed",
    )
    failed = transaction_store.get_by_sequence(second.runtime_id, 2)
    assert failed is not None
    assert failed.projection_error == "projection failed"
    assert not failed.projection_ready
    assert transaction_store.pending(second.runtime_id, limit=10) == ()


def test_sqlite_restart_restores_complete_transaction_and_ready_gate(tmp_path: Path) -> None:
    path = tmp_path / "restart.sqlite3"
    prepared = _prepared()
    committed_at = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 1, tzinfo=UTC))
    store = OnlySqliteExecutionTransactionStore(path)
    expected = store.commit(prepared, committed_at=committed_at).transaction
    store.close()

    recovered = OnlySqliteExecutionTransactionStore(path)
    assert recovered.get_by_sequence(prepared.runtime_id, 1) == expected
    assert recovered.pending(prepared.runtime_id, limit=10) == ()
    recovered.close()


def test_sqlite_detects_committed_payload_corruption(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.sqlite3"
    prepared = _prepared()
    committed_at = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 1, tzinfo=UTC))
    store = OnlySqliteExecutionTransactionStore(path)
    store.commit(prepared, committed_at=committed_at)
    store.close()
    connection = sqlite3.connect(path)
    with connection:
        connection.execute("UPDATE execution_transactions SET committed_payload='{}'")
    connection.close()

    recovered = OnlySqliteExecutionTransactionStore(path)
    with pytest.raises(ValueError):
        recovered.get_by_sequence(prepared.runtime_id, 1)
    recovered.close()
