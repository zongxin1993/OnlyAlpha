"""Atomic stores for prepared execution transactions and projection-gated outbox records."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path
from threading import RLock
from typing import Protocol

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyRuntimeId, OnlyTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.event.model import OnlyEvent

from .codec import (
    only_committed_execution_transaction_payload_hash,
    only_decode_committed_execution_transaction,
    only_decode_prepared_execution_transaction,
    only_encode_committed_execution_transaction,
    only_encode_prepared_execution_transaction,
)
from .transaction import (
    OnlyCommittedExecutionTransaction,
    OnlyExecutionTransactionCommitResult,
    OnlyPreparedExecutionTransaction,
)


class OnlyExecutionTransactionConflict(ValueError):
    """An idempotency key was reused for a different prepared authority."""


@dataclass(frozen=True, slots=True)
class OnlyExecutionTransactionOutboxKey:
    runtime_id: OnlyRuntimeId
    execution_sequence: int
    event_sequence: int


@dataclass(frozen=True, slots=True)
class OnlyExecutionTransactionOutboxRecord:
    key: OnlyExecutionTransactionOutboxKey
    event: OnlyEvent
    projection_ready: bool
    published: bool
    attempt_count: int
    last_attempted_at: OnlyTimestamp | None
    published_at: OnlyTimestamp | None
    last_error: str | None


class OnlyExecutionTransactionCommitPort(Protocol):
    def commit(
        self, prepared: OnlyPreparedExecutionTransaction, *, committed_at: OnlyTimestamp
    ) -> OnlyExecutionTransactionCommitResult: ...


class OnlyExecutionTransactionQueryPort(Protocol):
    def get_by_sequence(
        self, runtime_id: OnlyRuntimeId, execution_sequence: int
    ) -> OnlyCommittedExecutionTransaction | None: ...

    def get_by_transaction_id(self, transaction_id: str) -> OnlyCommittedExecutionTransaction | None: ...

    def get_by_trade(
        self,
        runtime_id: OnlyRuntimeId,
        gateway_id: OnlyBrokerGatewayId,
        account_id: OnlyAccountId,
        trade_id: OnlyTradeId,
    ) -> OnlyCommittedExecutionTransaction | None: ...

    def get_by_update(
        self,
        runtime_id: OnlyRuntimeId,
        gateway_id: OnlyBrokerGatewayId,
        account_id: OnlyAccountId,
        update_id: OnlyBrokerUpdateId,
    ) -> OnlyCommittedExecutionTransaction | None: ...

    def records(
        self, runtime_id: OnlyRuntimeId | None = None, *, after_sequence: int = 0
    ) -> tuple[OnlyCommittedExecutionTransaction, ...]: ...


class OnlyExecutionProjectionStatePort(Protocol):
    def mark_projection_ready(
        self,
        runtime_id: OnlyRuntimeId,
        execution_sequence: int,
        *,
        projected_at: OnlyTimestamp,
    ) -> None: ...

    def mark_projection_failed(
        self,
        runtime_id: OnlyRuntimeId,
        execution_sequence: int,
        *,
        failed_at: OnlyTimestamp,
        error: str,
    ) -> None: ...

    def unprojected(
        self, runtime_id: OnlyRuntimeId, *, after_sequence: int = 0
    ) -> tuple[OnlyCommittedExecutionTransaction, ...]: ...


class OnlyExecutionTransactionOutboxPort(Protocol):
    def pending(self, runtime_id: OnlyRuntimeId, *, limit: int) -> tuple[OnlyExecutionTransactionOutboxRecord, ...]: ...

    def begin_attempt(
        self, key: OnlyExecutionTransactionOutboxKey, attempted_at: OnlyTimestamp
    ) -> OnlyExecutionTransactionOutboxRecord: ...

    def mark_published(self, key: OnlyExecutionTransactionOutboxKey, published_at: OnlyTimestamp) -> None: ...

    def mark_failed(self, key: OnlyExecutionTransactionOutboxKey, failed_at: OnlyTimestamp, error: str) -> None: ...

    def pending_count(self, runtime_id: OnlyRuntimeId) -> int: ...


def _finalize(
    prepared: OnlyPreparedExecutionTransaction, execution_sequence: int, committed_at: OnlyTimestamp
) -> OnlyCommittedExecutionTransaction:
    if committed_at < prepared.prepared_at:
        raise ValueError("execution transaction commit cannot precede prepare")
    transaction = OnlyCommittedExecutionTransaction(
        runtime_id=prepared.runtime_id,
        execution_sequence=execution_sequence,
        transaction_id=prepared.transaction_id,
        fact=prepared.fact_draft.finalize(execution_sequence, committed_at),
        projections=prepared.projections,
        outbox_events=prepared.outbox_events,
        committed_at=committed_at,
        prepared_authority_hash=prepared.authority_hash,
        prepared_payload_hash=prepared.payload_hash,
        committed_payload_hash="",
    )
    return replace(
        transaction,
        committed_payload_hash=only_committed_execution_transaction_payload_hash(transaction),
    )


def _with_projection_state(
    transaction: OnlyCommittedExecutionTransaction,
    *,
    ready: bool,
    at: OnlyTimestamp,
    error: str | None,
) -> OnlyCommittedExecutionTransaction:
    updated = replace(
        transaction,
        projection_ready=ready,
        projected_at=at if ready else None,
        projection_error=error,
        projection_failed_at=None if ready else at,
        committed_payload_hash="",
    )
    return replace(updated, committed_payload_hash=only_committed_execution_transaction_payload_hash(updated))


class OnlyInMemoryExecutionTransactionStore:
    """Thread-safe reference store; all indexes and outbox rows share one commit lock."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._records: dict[tuple[OnlyRuntimeId, int], OnlyCommittedExecutionTransaction] = {}
        self._by_transaction: dict[str, tuple[OnlyRuntimeId, int]] = {}
        self._by_trade: dict[
            tuple[OnlyRuntimeId, OnlyBrokerGatewayId, OnlyAccountId, OnlyTradeId], tuple[OnlyRuntimeId, int]
        ] = {}
        self._by_update: dict[
            tuple[OnlyRuntimeId, OnlyBrokerGatewayId, OnlyAccountId, OnlyBrokerUpdateId], tuple[OnlyRuntimeId, int]
        ] = {}
        self._outbox: dict[tuple[OnlyRuntimeId, int, int], OnlyExecutionTransactionOutboxRecord] = {}

    def commit(
        self, prepared: OnlyPreparedExecutionTransaction, *, committed_at: OnlyTimestamp
    ) -> OnlyExecutionTransactionCommitResult:
        prepared_payload = only_encode_prepared_execution_transaction(prepared)
        if only_decode_prepared_execution_transaction(prepared_payload) != prepared:
            raise ValueError("prepared transaction is not round-trippable")
        with self._lock:
            existing = self._find_idempotent(prepared)
            if existing is not None:
                return OnlyExecutionTransactionCommitResult(existing, False)
            sequence = 1 + max(
                (item.execution_sequence for item in self._records.values() if item.runtime_id == prepared.runtime_id),
                default=0,
            )
            transaction = _finalize(prepared, sequence, committed_at)
            if (
                only_decode_committed_execution_transaction(only_encode_committed_execution_transaction(transaction))
                != transaction
            ):
                raise ValueError("committed transaction is not round-trippable")
            key = prepared.runtime_id, sequence
            outbox_records = tuple(
                (
                    (prepared.runtime_id, sequence, event_sequence),
                    OnlyExecutionTransactionOutboxRecord(
                        OnlyExecutionTransactionOutboxKey(prepared.runtime_id, sequence, event_sequence),
                        event,
                        False,
                        False,
                        0,
                        None,
                        None,
                        None,
                    ),
                )
                for event_sequence, event in enumerate(prepared.outbox_events, start=1)
            )
            self._records[key] = transaction
            self._by_transaction[prepared.transaction_id] = key
            self._by_trade[self._trade_key(prepared)] = key
            self._by_update[self._update_key(prepared)] = key
            self._outbox.update(outbox_records)
            return OnlyExecutionTransactionCommitResult(transaction, True)

    def get_by_sequence(
        self, runtime_id: OnlyRuntimeId, execution_sequence: int
    ) -> OnlyCommittedExecutionTransaction | None:
        with self._lock:
            return self._records.get((runtime_id, execution_sequence))

    def get_by_transaction_id(self, transaction_id: str) -> OnlyCommittedExecutionTransaction | None:
        with self._lock:
            key = self._by_transaction.get(transaction_id)
            return None if key is None else self._records[key]

    def get_by_trade(
        self,
        runtime_id: OnlyRuntimeId,
        gateway_id: OnlyBrokerGatewayId,
        account_id: OnlyAccountId,
        trade_id: OnlyTradeId,
    ) -> OnlyCommittedExecutionTransaction | None:
        with self._lock:
            key = self._by_trade.get((runtime_id, gateway_id, account_id, trade_id))
            return None if key is None else self._records[key]

    def get_by_update(
        self,
        runtime_id: OnlyRuntimeId,
        gateway_id: OnlyBrokerGatewayId,
        account_id: OnlyAccountId,
        update_id: OnlyBrokerUpdateId,
    ) -> OnlyCommittedExecutionTransaction | None:
        with self._lock:
            key = self._by_update.get((runtime_id, gateway_id, account_id, update_id))
            return None if key is None else self._records[key]

    def records(
        self, runtime_id: OnlyRuntimeId | None = None, *, after_sequence: int = 0
    ) -> tuple[OnlyCommittedExecutionTransaction, ...]:
        with self._lock:
            return tuple(
                item
                for item in sorted(
                    self._records.values(), key=lambda value: (str(value.runtime_id), value.execution_sequence)
                )
                if item.execution_sequence > after_sequence and (runtime_id is None or item.runtime_id == runtime_id)
            )

    def mark_projection_ready(
        self,
        runtime_id: OnlyRuntimeId,
        execution_sequence: int,
        *,
        projected_at: OnlyTimestamp,
    ) -> None:
        with self._lock:
            key = runtime_id, execution_sequence
            transaction = self._require_transaction(key)
            if transaction.projection_ready:
                return
            updated = _with_projection_state(transaction, ready=True, at=projected_at, error=None)
            self._records[key] = updated
            for outbox_key, record in tuple(self._outbox.items()):
                if outbox_key[:2] == key:
                    self._outbox[outbox_key] = replace(record, projection_ready=True)

    def mark_projection_failed(
        self,
        runtime_id: OnlyRuntimeId,
        execution_sequence: int,
        *,
        failed_at: OnlyTimestamp,
        error: str,
    ) -> None:
        if not error.strip():
            raise ValueError("projection failure requires an error")
        with self._lock:
            key = runtime_id, execution_sequence
            transaction = self._require_transaction(key)
            if transaction.projection_ready:
                raise ValueError("projection-ready transaction cannot be marked failed")
            self._records[key] = _with_projection_state(transaction, ready=False, at=failed_at, error=error)

    def unprojected(
        self, runtime_id: OnlyRuntimeId, *, after_sequence: int = 0
    ) -> tuple[OnlyCommittedExecutionTransaction, ...]:
        return tuple(
            item for item in self.records(runtime_id, after_sequence=after_sequence) if not item.projection_ready
        )

    def pending(self, runtime_id: OnlyRuntimeId, *, limit: int) -> tuple[OnlyExecutionTransactionOutboxRecord, ...]:
        if limit <= 0:
            raise ValueError("outbox pending limit must be positive")
        with self._lock:
            return tuple(
                record
                for key in sorted(self._outbox, key=lambda item: (str(item[0]), item[1], item[2]))
                if (record := self._outbox[key]).key.runtime_id == runtime_id
                and record.projection_ready
                and not record.published
            )[:limit]

    def begin_attempt(
        self, key: OnlyExecutionTransactionOutboxKey, attempted_at: OnlyTimestamp
    ) -> OnlyExecutionTransactionOutboxRecord:
        with self._lock:
            record = self._require_outbox(key)
            if not record.projection_ready:
                raise ValueError("outbox event is not projection-ready")
            updated = replace(
                record, attempt_count=record.attempt_count + 1, last_attempted_at=attempted_at, last_error=None
            )
            self._outbox[key.runtime_id, key.execution_sequence, key.event_sequence] = updated
            return updated

    def mark_published(self, key: OnlyExecutionTransactionOutboxKey, published_at: OnlyTimestamp) -> None:
        with self._lock:
            record = self._require_outbox(key)
            if not record.projection_ready:
                raise ValueError("outbox event is not projection-ready")
            self._outbox[key.runtime_id, key.execution_sequence, key.event_sequence] = replace(
                record, published=True, published_at=published_at, last_error=None
            )

    def mark_failed(self, key: OnlyExecutionTransactionOutboxKey, failed_at: OnlyTimestamp, error: str) -> None:
        with self._lock:
            record = self._require_outbox(key)
            self._outbox[key.runtime_id, key.execution_sequence, key.event_sequence] = replace(
                record, published=False, last_attempted_at=failed_at, published_at=None, last_error=error
            )

    def outbox_records(self, runtime_id: OnlyRuntimeId) -> tuple[OnlyExecutionTransactionOutboxRecord, ...]:
        with self._lock:
            return tuple(
                self._outbox[key]
                for key in sorted(self._outbox, key=lambda item: (str(item[0]), item[1], item[2]))
                if key[0] == runtime_id
            )

    def pending_count(self, runtime_id: OnlyRuntimeId) -> int:
        with self._lock:
            return sum(
                record.key.runtime_id == runtime_id and record.projection_ready and not record.published
                for record in self._outbox.values()
            )

    def _find_idempotent(self, prepared: OnlyPreparedExecutionTransaction) -> OnlyCommittedExecutionTransaction | None:
        keys = (
            self._by_transaction.get(prepared.transaction_id),
            self._by_trade.get(self._trade_key(prepared)),
            self._by_update.get(self._update_key(prepared)),
        )
        existing_keys = {key for key in keys if key is not None}
        if not existing_keys:
            return None
        if len(existing_keys) != 1:
            raise OnlyExecutionTransactionConflict("execution idempotency indexes refer to different transactions")
        existing = self._records[existing_keys.pop()]
        if existing.prepared_authority_hash != prepared.authority_hash:
            raise OnlyExecutionTransactionConflict("execution idempotency key conflicts with another authority hash")
        return existing

    @staticmethod
    def _trade_key(
        prepared: OnlyPreparedExecutionTransaction,
    ) -> tuple[OnlyRuntimeId, OnlyBrokerGatewayId, OnlyAccountId, OnlyTradeId]:
        return prepared.runtime_id, prepared.gateway_id, prepared.account_id, prepared.trade_id

    @staticmethod
    def _update_key(
        prepared: OnlyPreparedExecutionTransaction,
    ) -> tuple[OnlyRuntimeId, OnlyBrokerGatewayId, OnlyAccountId, OnlyBrokerUpdateId]:
        return prepared.runtime_id, prepared.gateway_id, prepared.account_id, prepared.broker_update_id

    def _require_transaction(self, key: tuple[OnlyRuntimeId, int]) -> OnlyCommittedExecutionTransaction:
        try:
            return self._records[key]
        except KeyError as exc:
            raise KeyError(f"unknown committed execution transaction: {key}") from exc

    def _require_outbox(self, key: OnlyExecutionTransactionOutboxKey) -> OnlyExecutionTransactionOutboxRecord:
        try:
            return self._outbox[key.runtime_id, key.execution_sequence, key.event_sequence]
        except KeyError as exc:
            raise KeyError(f"unknown execution transaction outbox record: {key}") from exc


class OnlySqliteExecutionTransactionStore:
    """SQLite contract implementation with sequence allocation inside BEGIN IMMEDIATE."""

    def __init__(self, path: Path | str) -> None:
        self._connection = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._lock = RLock()
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS execution_transactions (
                    runtime_id TEXT NOT NULL,
                    execution_sequence INTEGER NOT NULL,
                    transaction_id TEXT NOT NULL UNIQUE,
                    gateway_id TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    trade_id TEXT NOT NULL,
                    broker_update_id TEXT NOT NULL,
                    source_sequence INTEGER NOT NULL,
                    prepared_payload TEXT NOT NULL,
                    prepared_authority_hash TEXT NOT NULL,
                    prepared_payload_hash TEXT NOT NULL,
                    committed_payload TEXT NOT NULL,
                    committed_payload_hash TEXT NOT NULL,
                    committed_at INTEGER NOT NULL,
                    projection_ready INTEGER NOT NULL DEFAULT 0,
                    projected_at INTEGER,
                    projection_error TEXT,
                    projection_failed_at INTEGER,
                    PRIMARY KEY(runtime_id, execution_sequence),
                    UNIQUE(runtime_id, gateway_id, account_id, trade_id),
                    UNIQUE(runtime_id, gateway_id, account_id, broker_update_id)
                );
                CREATE TABLE IF NOT EXISTS execution_transaction_outbox (
                    runtime_id TEXT NOT NULL,
                    execution_sequence INTEGER NOT NULL,
                    event_sequence INTEGER NOT NULL,
                    event_id TEXT NOT NULL,
                    event_payload TEXT NOT NULL,
                    projection_ready INTEGER NOT NULL DEFAULT 0,
                    published INTEGER NOT NULL DEFAULT 0,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_attempted_at INTEGER,
                    published_at INTEGER,
                    last_error TEXT,
                    PRIMARY KEY(runtime_id, execution_sequence, event_sequence),
                    UNIQUE(event_id)
                );
                """
            )

    def commit(
        self, prepared: OnlyPreparedExecutionTransaction, *, committed_at: OnlyTimestamp
    ) -> OnlyExecutionTransactionCommitResult:
        prepared_payload = only_encode_prepared_execution_transaction(prepared)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    "SELECT COALESCE(MAX(execution_sequence), 0) AS value FROM execution_transactions WHERE runtime_id=?",
                    (str(prepared.runtime_id),),
                ).fetchone()
                sequence = int(row["value"]) + 1
                transaction = _finalize(prepared, sequence, committed_at)
                committed_payload = only_encode_committed_execution_transaction(transaction)
                self._connection.execute(
                    "INSERT INTO execution_transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL, NULL)",
                    (
                        str(prepared.runtime_id),
                        sequence,
                        prepared.transaction_id,
                        str(prepared.gateway_id),
                        str(prepared.account_id),
                        str(prepared.trade_id),
                        str(prepared.broker_update_id),
                        prepared.source_sequence,
                        prepared_payload,
                        prepared.authority_hash,
                        prepared.payload_hash,
                        committed_payload,
                        transaction.committed_payload_hash,
                        committed_at.unix_nanos,
                    ),
                )
                for event_sequence, event in enumerate(prepared.outbox_events, start=1):
                    self._connection.execute(
                        "INSERT INTO execution_transaction_outbox(runtime_id, execution_sequence, event_sequence, event_id, event_payload) VALUES (?, ?, ?, ?, ?)",
                        (
                            str(prepared.runtime_id),
                            sequence,
                            event_sequence,
                            str(event.event_id),
                            json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True),
                        ),
                    )
                self._connection.execute("COMMIT")
                return OnlyExecutionTransactionCommitResult(transaction, True)
            except sqlite3.IntegrityError:
                self._connection.execute("ROLLBACK")
                existing = self._find_idempotent(prepared)
                if existing is None:
                    raise OnlyExecutionTransactionConflict("execution transaction unique-key conflict") from None
                return OnlyExecutionTransactionCommitResult(existing, False)
            except BaseException:
                self._connection.execute("ROLLBACK")
                raise

    def get_by_sequence(
        self, runtime_id: OnlyRuntimeId, execution_sequence: int
    ) -> OnlyCommittedExecutionTransaction | None:
        return self._find("runtime_id=? AND execution_sequence=?", (str(runtime_id), execution_sequence))

    def get_by_transaction_id(self, transaction_id: str) -> OnlyCommittedExecutionTransaction | None:
        return self._find("transaction_id=?", (transaction_id,))

    def get_by_trade(
        self,
        runtime_id: OnlyRuntimeId,
        gateway_id: OnlyBrokerGatewayId,
        account_id: OnlyAccountId,
        trade_id: OnlyTradeId,
    ) -> OnlyCommittedExecutionTransaction | None:
        return self._find(
            "runtime_id=? AND gateway_id=? AND account_id=? AND trade_id=?",
            (str(runtime_id), str(gateway_id), str(account_id), str(trade_id)),
        )

    def get_by_update(
        self,
        runtime_id: OnlyRuntimeId,
        gateway_id: OnlyBrokerGatewayId,
        account_id: OnlyAccountId,
        update_id: OnlyBrokerUpdateId,
    ) -> OnlyCommittedExecutionTransaction | None:
        return self._find(
            "runtime_id=? AND gateway_id=? AND account_id=? AND broker_update_id=?",
            (str(runtime_id), str(gateway_id), str(account_id), str(update_id)),
        )

    def records(
        self, runtime_id: OnlyRuntimeId | None = None, *, after_sequence: int = 0
    ) -> tuple[OnlyCommittedExecutionTransaction, ...]:
        clause, values = (
            ("execution_sequence>?", (after_sequence,))
            if runtime_id is None
            else ("runtime_id=? AND execution_sequence>?", (str(runtime_id), after_sequence))
        )
        with self._lock:
            rows = self._connection.execute(
                f"SELECT * FROM execution_transactions WHERE {clause} ORDER BY runtime_id, execution_sequence", values
            ).fetchall()
        return tuple(self._decode_row(row) for row in rows)

    def mark_projection_ready(
        self,
        runtime_id: OnlyRuntimeId,
        execution_sequence: int,
        *,
        projected_at: OnlyTimestamp,
    ) -> None:
        self._mark_projection(runtime_id, execution_sequence, ready=True, at=projected_at, error=None)

    def mark_projection_failed(
        self,
        runtime_id: OnlyRuntimeId,
        execution_sequence: int,
        *,
        failed_at: OnlyTimestamp,
        error: str,
    ) -> None:
        if not error.strip():
            raise ValueError("projection failure requires an error")
        self._mark_projection(runtime_id, execution_sequence, ready=False, at=failed_at, error=error)

    def unprojected(
        self, runtime_id: OnlyRuntimeId, *, after_sequence: int = 0
    ) -> tuple[OnlyCommittedExecutionTransaction, ...]:
        return tuple(
            item for item in self.records(runtime_id, after_sequence=after_sequence) if not item.projection_ready
        )

    def pending(self, runtime_id: OnlyRuntimeId, *, limit: int) -> tuple[OnlyExecutionTransactionOutboxRecord, ...]:
        if limit <= 0:
            raise ValueError("outbox pending limit must be positive")
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM execution_transaction_outbox WHERE runtime_id=? AND projection_ready=1 AND published=0 ORDER BY execution_sequence, event_sequence LIMIT ?",
                (str(runtime_id), limit),
            ).fetchall()
        return tuple(self._decode_outbox(row) for row in rows)

    def begin_attempt(
        self, key: OnlyExecutionTransactionOutboxKey, attempted_at: OnlyTimestamp
    ) -> OnlyExecutionTransactionOutboxRecord:
        self._update_outbox(
            key,
            "attempt_count=attempt_count+1, last_attempted_at=?, last_error=NULL",
            (attempted_at.unix_nanos,),
            require_ready=True,
        )
        return self._require_outbox(key)

    def mark_published(self, key: OnlyExecutionTransactionOutboxKey, published_at: OnlyTimestamp) -> None:
        self._update_outbox(
            key, "published=1, published_at=?, last_error=NULL", (published_at.unix_nanos,), require_ready=True
        )

    def mark_failed(self, key: OnlyExecutionTransactionOutboxKey, failed_at: OnlyTimestamp, error: str) -> None:
        self._update_outbox(
            key,
            "published=0, published_at=NULL, last_attempted_at=?, last_error=?",
            (failed_at.unix_nanos, error),
            require_ready=False,
        )

    def outbox_records(self, runtime_id: OnlyRuntimeId) -> tuple[OnlyExecutionTransactionOutboxRecord, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM execution_transaction_outbox WHERE runtime_id=? ORDER BY execution_sequence, event_sequence",
                (str(runtime_id),),
            ).fetchall()
        return tuple(self._decode_outbox(row) for row in rows)

    def pending_count(self, runtime_id: OnlyRuntimeId) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT COUNT(*) AS value FROM execution_transaction_outbox WHERE runtime_id=? AND projection_ready=1 AND published=0",
                (str(runtime_id),),
            ).fetchone()
        return int(row["value"])

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _find(self, clause: str, values: tuple[object, ...]) -> OnlyCommittedExecutionTransaction | None:
        with self._lock:
            row = self._connection.execute(f"SELECT * FROM execution_transactions WHERE {clause}", values).fetchone()
        return None if row is None else self._decode_row(row)

    def _find_idempotent(self, prepared: OnlyPreparedExecutionTransaction) -> OnlyCommittedExecutionTransaction | None:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM execution_transactions WHERE transaction_id=? OR (runtime_id=? AND gateway_id=? AND account_id=? AND (trade_id=? OR broker_update_id=?))",
                (
                    prepared.transaction_id,
                    str(prepared.runtime_id),
                    str(prepared.gateway_id),
                    str(prepared.account_id),
                    str(prepared.trade_id),
                    str(prepared.broker_update_id),
                ),
            ).fetchall()
        if not rows:
            return None
        transactions = tuple(self._decode_row(row) for row in rows)
        if (
            len({item.prepared_authority_hash for item in transactions}) != 1
            or transactions[0].prepared_authority_hash != prepared.authority_hash
        ):
            raise OnlyExecutionTransactionConflict("execution idempotency key conflicts with another authority hash")
        return transactions[0]

    def _mark_projection(
        self,
        runtime_id: OnlyRuntimeId,
        execution_sequence: int,
        *,
        ready: bool,
        at: OnlyTimestamp,
        error: str | None,
    ) -> None:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    "SELECT * FROM execution_transactions WHERE runtime_id=? AND execution_sequence=?",
                    (str(runtime_id), execution_sequence),
                ).fetchone()
                if row is None:
                    raise KeyError("unknown committed execution transaction")
                current = self._decode_row(row)
                if current.projection_ready:
                    if ready:
                        self._connection.execute("COMMIT")
                        return
                    raise ValueError("projection-ready transaction cannot be marked failed")
                updated = _with_projection_state(current, ready=ready, at=at, error=error)
                payload = only_encode_committed_execution_transaction(updated)
                self._connection.execute(
                    "UPDATE execution_transactions SET committed_payload=?, committed_payload_hash=?, projection_ready=?, projected_at=?, projection_error=?, projection_failed_at=? WHERE runtime_id=? AND execution_sequence=?",
                    (
                        payload,
                        updated.committed_payload_hash,
                        int(ready),
                        at.unix_nanos if ready else None,
                        error,
                        None if ready else at.unix_nanos,
                        str(runtime_id),
                        execution_sequence,
                    ),
                )
                if ready:
                    self._connection.execute(
                        "UPDATE execution_transaction_outbox SET projection_ready=1 WHERE runtime_id=? AND execution_sequence=?",
                        (str(runtime_id), execution_sequence),
                    )
                self._connection.execute("COMMIT")
            except BaseException:
                self._connection.execute("ROLLBACK")
                raise

    def _decode_row(self, row: sqlite3.Row) -> OnlyCommittedExecutionTransaction:
        prepared_payload = str(row["prepared_payload"])
        prepared = only_decode_prepared_execution_transaction(prepared_payload)
        if prepared.authority_hash != str(row["prepared_authority_hash"]):
            raise ValueError("prepared execution transaction stored authority hash mismatch")
        if prepared.payload_hash != str(row["prepared_payload_hash"]):
            raise ValueError("prepared execution transaction stored payload hash mismatch")
        transaction = only_decode_committed_execution_transaction(str(row["committed_payload"]))
        if transaction.committed_payload_hash != str(row["committed_payload_hash"]):
            raise ValueError("committed execution transaction stored payload hash mismatch")
        if transaction.prepared_authority_hash != prepared.authority_hash:
            raise ValueError("prepared and committed authority hashes disagree")
        if transaction.prepared_payload_hash != prepared.payload_hash:
            raise ValueError("prepared and committed payload hashes disagree")
        return transaction

    def _decode_outbox(self, row: sqlite3.Row) -> OnlyExecutionTransactionOutboxRecord:
        event = OnlyEvent.from_dict(json.loads(str(row["event_payload"])))
        if str(event.event_id) != str(row["event_id"]):
            raise ValueError("execution outbox event identity mismatch")
        transaction_row = self._connection.execute(
            "SELECT committed_payload FROM execution_transactions WHERE runtime_id=? AND execution_sequence=?",
            (str(row["runtime_id"]), int(row["execution_sequence"])),
        ).fetchone()
        if transaction_row is None:
            raise ValueError("execution outbox transaction is missing")
        transaction = only_decode_committed_execution_transaction(str(transaction_row["committed_payload"]))
        event_sequence = int(row["event_sequence"])
        if event_sequence > len(transaction.outbox_events) or transaction.outbox_events[event_sequence - 1] != event:
            raise ValueError("execution outbox event payload mismatch")
        return OnlyExecutionTransactionOutboxRecord(
            OnlyExecutionTransactionOutboxKey(
                OnlyRuntimeId(str(row["runtime_id"])), int(row["execution_sequence"]), event_sequence
            ),
            event,
            bool(row["projection_ready"]),
            bool(row["published"]),
            int(row["attempt_count"]),
            self._timestamp(row["last_attempted_at"]),
            self._timestamp(row["published_at"]),
            None if row["last_error"] is None else str(row["last_error"]),
        )

    def _require_outbox(self, key: OnlyExecutionTransactionOutboxKey) -> OnlyExecutionTransactionOutboxRecord:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM execution_transaction_outbox WHERE runtime_id=? AND execution_sequence=? AND event_sequence=?",
                (str(key.runtime_id), key.execution_sequence, key.event_sequence),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown execution transaction outbox record: {key}")
        return self._decode_outbox(row)

    def _update_outbox(
        self,
        key: OnlyExecutionTransactionOutboxKey,
        assignments: str,
        values: tuple[object, ...],
        *,
        require_ready: bool,
    ) -> None:
        ready_clause = " AND projection_ready=1" if require_ready else ""
        with self._lock, self._connection:
            cursor = self._connection.execute(
                f"UPDATE execution_transaction_outbox SET {assignments} WHERE runtime_id=? AND execution_sequence=? AND event_sequence=?{ready_clause}",
                values + (str(key.runtime_id), key.execution_sequence, key.event_sequence),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown or non-ready execution transaction outbox record: {key}")

    @staticmethod
    def _timestamp(value: object) -> OnlyTimestamp | None:
        return None if value is None else OnlyTimestamp.from_unix_nanos(int(str(value)))


__all__ = [name for name in globals() if name.startswith("Only")]
