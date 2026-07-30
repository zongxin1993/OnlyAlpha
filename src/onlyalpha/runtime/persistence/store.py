"""Unified Runtime persistence for checkpoints, execution transactions, and outbox."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from threading import RLock
from typing import Protocol

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyOrderId, OnlyRuntimeId, OnlyTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.event.model import OnlyEvent
from onlyalpha.execution.codec import (
    only_committed_execution_transaction_payload_hash,
    only_decode_committed_execution_transaction,
    only_decode_prepared_execution_transaction,
    only_encode_committed_execution_transaction,
    only_encode_prepared_execution_transaction,
)
from onlyalpha.execution.persistence_ports import (
    OnlyExecutionProjectionStatePort,
    OnlyExecutionTransactionCommitPort,
    OnlyExecutionTransactionConflict,
    OnlyExecutionTransactionOutboxKey,
    OnlyExecutionTransactionOutboxPort,
    OnlyExecutionTransactionOutboxRecord,
    OnlyExecutionTransactionQueryPort,
    OnlyExecutionTransactionRecoveryQueryPort,
    OnlyProjectionReadyExecutionQueryPort,
    OnlyRuntimePersistenceStoreError,
)
from onlyalpha.execution.transaction import (
    OnlyCommittedExecutionTransaction,
    OnlyExecutionTransactionCommitResult,
    OnlyPreparedExecutionTransaction,
    OnlyStoredExecutionTransaction,
)
from onlyalpha.runtime.checkpoint.codec import (
    only_decode_replay_cursor,
    only_encode_replay_cursor,
    only_validate_runtime_checkpoint,
)
from onlyalpha.runtime.checkpoint.model import (
    OnlyRuntimeCheckpoint,
    OnlyRuntimeCheckpointComponent,
    OnlyRuntimeCheckpointHeader,
)

ONLY_RUNTIME_PERSISTENCE_SCHEMA_VERSION = "2"


class OnlyRuntimePersistenceIdentityMismatch(OnlyRuntimePersistenceStoreError):
    """An existing Store belongs to another stable Runtime identity."""


class OnlyRuntimePersistenceSchemaUnsupported(OnlyRuntimePersistenceStoreError):
    """An existing Store uses an unsupported schema version."""


class OnlyRuntimePersistenceMetadataCorrupt(OnlyRuntimePersistenceStoreError):
    """An existing Store is missing required schema or identity metadata."""


class OnlyRuntimeCheckpointWritePort(Protocol):
    def write_checkpoint(self, checkpoint: OnlyRuntimeCheckpoint, *, retain_last: int) -> None: ...


class OnlyRuntimeCheckpointQueryPort(Protocol):
    def latest_checkpoint(self, runtime_id: OnlyRuntimeId) -> OnlyRuntimeCheckpoint | None: ...

    def checkpoints(self, runtime_id: OnlyRuntimeId) -> tuple[OnlyRuntimeCheckpoint, ...]: ...


class OnlyRuntimePersistenceStorePort(
    OnlyExecutionTransactionCommitPort,
    OnlyExecutionTransactionQueryPort,
    OnlyExecutionTransactionRecoveryQueryPort,
    OnlyProjectionReadyExecutionQueryPort,
    OnlyExecutionProjectionStatePort,
    OnlyExecutionTransactionOutboxPort,
    OnlyRuntimeCheckpointWritePort,
    OnlyRuntimeCheckpointQueryPort,
    Protocol,
):
    """Complete composition-root store contract; consumers receive narrower ports."""

    def bind_participant_registry_fingerprint(self, fingerprint: str) -> None: ...

    def close(self) -> None: ...


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


class OnlyInMemoryRuntimePersistenceStore:
    """Thread-safe reference store; all indexes and outbox rows share one commit lock."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._records: dict[tuple[OnlyRuntimeId, int], OnlyCommittedExecutionTransaction] = {}
        self._prepared_records: dict[tuple[OnlyRuntimeId, int], OnlyPreparedExecutionTransaction] = {}
        self._by_transaction: dict[str, tuple[OnlyRuntimeId, int]] = {}
        self._by_trade: dict[
            tuple[OnlyRuntimeId, OnlyBrokerGatewayId, OnlyAccountId, OnlyTradeId], tuple[OnlyRuntimeId, int]
        ] = {}
        self._by_update: dict[
            tuple[OnlyRuntimeId, OnlyBrokerGatewayId, OnlyAccountId, OnlyBrokerUpdateId], tuple[OnlyRuntimeId, int]
        ] = {}
        self._outbox: dict[tuple[OnlyRuntimeId, int, int], OnlyExecutionTransactionOutboxRecord] = {}
        self._checkpoints: dict[tuple[OnlyRuntimeId, int], OnlyRuntimeCheckpoint] = {}
        self._participant_registry_fingerprint: str | None = None

    def commit(
        self, prepared: OnlyPreparedExecutionTransaction, *, committed_at: OnlyTimestamp
    ) -> OnlyExecutionTransactionCommitResult:
        with self._lock:
            snapshots = (
                dict(self._records),
                dict(self._prepared_records),
                dict(self._by_transaction),
                dict(self._by_trade),
                dict(self._by_update),
                dict(self._outbox),
            )
            try:
                prepared_payload = only_encode_prepared_execution_transaction(prepared)
                if only_decode_prepared_execution_transaction(prepared_payload) != prepared:
                    raise ValueError("prepared transaction is not round-trippable")
                existing = self._find_idempotent(prepared)
                if existing is not None:
                    return OnlyExecutionTransactionCommitResult(existing, False)
                self._validate_fill_index(prepared)
                sequence = 1 + max(
                    (
                        item.execution_sequence
                        for item in self._records.values()
                        if item.runtime_id == prepared.runtime_id
                    ),
                    default=0,
                )
                transaction = _finalize(prepared, sequence, committed_at)
                if (
                    only_decode_committed_execution_transaction(
                        only_encode_committed_execution_transaction(transaction)
                    )
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
                self._prepared_records[key] = prepared
                self._by_transaction[prepared.transaction_id] = key
                self._by_trade[self._trade_key(prepared)] = key
                self._by_update[self._update_key(prepared)] = key
                self._outbox.update(outbox_records)
                return OnlyExecutionTransactionCommitResult(transaction, True)
            except OnlyExecutionTransactionConflict:
                raise
            except Exception as exc:
                (
                    self._records,
                    self._prepared_records,
                    self._by_transaction,
                    self._by_trade,
                    self._by_update,
                    self._outbox,
                ) = snapshots
                raise OnlyRuntimePersistenceStoreError("in-memory execution transaction commit failed") from exc

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

    def get_by_fill_identity(
        self, runtime_id: OnlyRuntimeId, fill_identity: str
    ) -> OnlyCommittedExecutionTransaction | None:
        with self._lock:
            return next(
                (
                    item
                    for item in self._records.values()
                    if item.runtime_id == runtime_id and item.fact.fill_identity == fill_identity
                ),
                None,
            )

    def transactions_for_order(
        self, runtime_id: OnlyRuntimeId, order_id: OnlyOrderId
    ) -> tuple[OnlyCommittedExecutionTransaction, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (
                        item
                        for item in self._records.values()
                        if item.runtime_id == runtime_id and item.fact.order_id == order_id
                    ),
                    key=lambda item: (item.fact.fill_index, item.execution_sequence),
                )
            )

    def latest_fill_for_order(
        self, runtime_id: OnlyRuntimeId, order_id: OnlyOrderId
    ) -> OnlyCommittedExecutionTransaction | None:
        records = self.transactions_for_order(runtime_id, order_id)
        return None if not records else records[-1]

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

    def recovery_records(
        self,
        runtime_id: OnlyRuntimeId,
        *,
        after_sequence: int,
    ) -> tuple[OnlyStoredExecutionTransaction, ...]:
        with self._lock:
            return tuple(
                OnlyStoredExecutionTransaction(self._prepared_records[key], transaction)
                for key, transaction in sorted(self._records.items(), key=lambda item: item[0][1])
                if key[0] == runtime_id and transaction.execution_sequence > after_sequence
            )

    def get_recovery_record_by_update(
        self,
        runtime_id: OnlyRuntimeId,
        gateway_id: OnlyBrokerGatewayId,
        account_id: OnlyAccountId,
        update_id: OnlyBrokerUpdateId,
    ) -> OnlyStoredExecutionTransaction | None:
        with self._lock:
            key = self._by_update.get((runtime_id, gateway_id, account_id, update_id))
            if key is None:
                return None
            return OnlyStoredExecutionTransaction(self._prepared_records[key], self._records[key])

    def ready_records(
        self, runtime_id: OnlyRuntimeId | None = None, *, after_sequence: int = 0
    ) -> tuple[OnlyCommittedExecutionTransaction, ...]:
        with self._lock:
            return tuple(
                item
                for item in sorted(
                    self._records.values(), key=lambda value: (str(value.runtime_id), value.execution_sequence)
                )
                if item.projection_ready
                and item.execution_sequence > after_sequence
                and (runtime_id is None or item.runtime_id == runtime_id)
            )

    def ready_count(self, runtime_id: OnlyRuntimeId | None = None) -> int:
        with self._lock:
            return sum(
                item.projection_ready and (runtime_id is None or item.runtime_id == runtime_id)
                for item in self._records.values()
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

    def close(self) -> None:
        """Release the Store resource; Memory has no external handle."""

    def bind_participant_registry_fingerprint(self, fingerprint: str) -> None:
        if not fingerprint.strip():
            raise ValueError("participant registry fingerprint is required")
        if self._participant_registry_fingerprint not in {None, fingerprint}:
            raise OnlyRuntimePersistenceStoreError("participant registry fingerprint mismatch")
        self._participant_registry_fingerprint = fingerprint

    def write_checkpoint(self, checkpoint: OnlyRuntimeCheckpoint, *, retain_last: int) -> None:
        if retain_last < 1:
            raise ValueError("checkpoint retention must be positive")
        only_validate_runtime_checkpoint(checkpoint)
        with self._lock:
            key = checkpoint.header.runtime_id, checkpoint.header.checkpoint_sequence
            existing = self._checkpoints.get(key)
            if existing is not None and existing != checkpoint:
                raise OnlyRuntimePersistenceStoreError("checkpoint sequence conflicts with existing payload")
            self._checkpoints[key] = checkpoint
            sequences = sorted(
                sequence for runtime_id, sequence in self._checkpoints if runtime_id == checkpoint.header.runtime_id
            )
            for sequence in sequences[:-retain_last]:
                del self._checkpoints[checkpoint.header.runtime_id, sequence]

    def latest_checkpoint(self, runtime_id: OnlyRuntimeId) -> OnlyRuntimeCheckpoint | None:
        records = self.checkpoints(runtime_id)
        return None if not records else records[-1]

    def checkpoints(self, runtime_id: OnlyRuntimeId) -> tuple[OnlyRuntimeCheckpoint, ...]:
        with self._lock:
            return tuple(
                self._checkpoints[key]
                for key in sorted(self._checkpoints, key=lambda item: (str(item[0]), item[1]))
                if key[0] == runtime_id
            )

    def _find_idempotent(self, prepared: OnlyPreparedExecutionTransaction) -> OnlyCommittedExecutionTransaction | None:
        keys = (
            self._by_transaction.get(prepared.transaction_id),
            self._by_trade.get(self._trade_key(prepared)),
            self._by_update.get(self._update_key(prepared)),
        )
        existing_keys = {key for key in keys if key is not None}
        if not existing_keys:
            fill_existing = self.get_by_fill_identity(prepared.runtime_id, prepared.fact_draft.fill_identity)
            if fill_existing is None:
                return None
            if fill_existing.fact.fill_payload_fingerprint != prepared.fact_draft.fill_payload_fingerprint:
                raise OnlyExecutionTransactionConflict("Fill identity conflicts with another payload fingerprint")
            return fill_existing
        if len(existing_keys) != 1:
            raise OnlyExecutionTransactionConflict("execution idempotency indexes refer to different transactions")
        existing = self._records[existing_keys.pop()]
        if (
            existing.prepared_authority_hash != prepared.authority_hash
            or existing.prepared_payload_hash != prepared.payload_hash
        ):
            raise OnlyExecutionTransactionConflict("execution idempotency key conflicts with another prepared payload")
        return existing

    def _validate_fill_index(self, prepared: OnlyPreparedExecutionTransaction) -> None:
        for existing in self.transactions_for_order(prepared.runtime_id, prepared.fact_draft.order_id):
            if existing.fact.fill_index == prepared.fact_draft.fill_index:
                raise OnlyExecutionTransactionConflict("Fill index conflicts with another durable Order Fill")

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


class OnlySqliteRuntimePersistenceStore:
    """SQLite contract implementation with sequence allocation inside BEGIN IMMEDIATE."""

    def __init__(self, path: Path | str, *, identity: Mapping[str, str] | None = None) -> None:
        self._lock = RLock()
        self._closed = False
        selected_path = Path(path)
        existed = selected_path.exists() and selected_path.stat().st_size > 0
        try:
            self._connection = sqlite3.connect(str(selected_path), check_same_thread=False, isolation_level=None)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys=ON")
            if existed:
                self._validate_existing_schema(identity)
            else:
                with self._connection:
                    self._connection.executescript(
                        """
                CREATE TABLE runtime_persistence_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
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
                CREATE TABLE runtime_checkpoints (
                    runtime_id TEXT NOT NULL,
                    checkpoint_sequence INTEGER NOT NULL,
                    covered_execution_sequence INTEGER NOT NULL,
                    checkpoint_schema_version INTEGER NOT NULL,
                    replay_cursor_payload TEXT NOT NULL,
                    config_fingerprint TEXT NOT NULL,
                    participant_registry_fingerprint TEXT NOT NULL,
                    aggregate_payload_hash TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    pending_outbox_count INTEGER NOT NULL,
                    PRIMARY KEY(runtime_id, checkpoint_sequence)
                );
                CREATE TABLE runtime_checkpoint_components (
                    runtime_id TEXT NOT NULL,
                    checkpoint_sequence INTEGER NOT NULL,
                    component_id TEXT NOT NULL,
                    component_schema_version INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(runtime_id, checkpoint_sequence, component_id),
                    FOREIGN KEY(runtime_id, checkpoint_sequence)
                        REFERENCES runtime_checkpoints(runtime_id, checkpoint_sequence)
                        ON DELETE CASCADE
                );
                """
                    )
                    created_at_row = self._connection.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ', 'now')").fetchone()
                    if created_at_row is None:
                        raise OnlyRuntimePersistenceStoreError("SQLite could not create persistence metadata time")
                    metadata = {
                        "schema_version": ONLY_RUNTIME_PERSISTENCE_SCHEMA_VERSION,
                        "created_at": str(created_at_row[0]),
                        **({} if identity is None else dict(identity)),
                    }
                    self._connection.executemany(
                        "INSERT INTO runtime_persistence_metadata(key, value) VALUES (?, ?)",
                        tuple(sorted(metadata.items())),
                    )
        except OnlyRuntimePersistenceStoreError:
            self._connection.close()
            raise
        except sqlite3.Error as exc:
            if hasattr(self, "_connection"):
                self._connection.close()
            raise OnlyRuntimePersistenceStoreError("SQLite Runtime persistence schema initialization failed") from exc

    def commit(
        self, prepared: OnlyPreparedExecutionTransaction, *, committed_at: OnlyTimestamp
    ) -> OnlyExecutionTransactionCommitResult:
        prepared_payload = only_encode_prepared_execution_transaction(prepared)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                existing = self._find_idempotent(prepared)
                if existing is not None:
                    self._connection.execute("ROLLBACK")
                    return OnlyExecutionTransactionCommitResult(existing, False)
                self._validate_fill_index(prepared)
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
            except sqlite3.IntegrityError as exc:
                self._connection.execute("ROLLBACK")
                try:
                    existing = self._find_idempotent(prepared)
                except OnlyExecutionTransactionConflict:
                    raise
                if existing is None:
                    raise OnlyRuntimePersistenceStoreError(
                        "SQLite execution transaction integrity failure is not a business conflict"
                    ) from exc
                return OnlyExecutionTransactionCommitResult(existing, False)
            except sqlite3.Error as exc:
                self._connection.execute("ROLLBACK")
                raise OnlyRuntimePersistenceStoreError("SQLite execution transaction commit failed") from exc
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

    def get_by_fill_identity(
        self, runtime_id: OnlyRuntimeId, fill_identity: str
    ) -> OnlyCommittedExecutionTransaction | None:
        return next(
            (item for item in self.records(runtime_id) if item.fact.fill_identity == fill_identity),
            None,
        )

    def transactions_for_order(
        self, runtime_id: OnlyRuntimeId, order_id: OnlyOrderId
    ) -> tuple[OnlyCommittedExecutionTransaction, ...]:
        return tuple(
            sorted(
                (item for item in self.records(runtime_id) if item.fact.order_id == order_id),
                key=lambda item: (item.fact.fill_index, item.execution_sequence),
            )
        )

    def latest_fill_for_order(
        self, runtime_id: OnlyRuntimeId, order_id: OnlyOrderId
    ) -> OnlyCommittedExecutionTransaction | None:
        records = self.transactions_for_order(runtime_id, order_id)
        return None if not records else records[-1]

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

    def recovery_records(
        self,
        runtime_id: OnlyRuntimeId,
        *,
        after_sequence: int,
    ) -> tuple[OnlyStoredExecutionTransaction, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM execution_transactions WHERE runtime_id=? AND execution_sequence>? "
                "ORDER BY execution_sequence",
                (str(runtime_id), after_sequence),
            ).fetchall()
        return tuple(self._decode_recovery_row(row) for row in rows)

    def get_recovery_record_by_update(
        self,
        runtime_id: OnlyRuntimeId,
        gateway_id: OnlyBrokerGatewayId,
        account_id: OnlyAccountId,
        update_id: OnlyBrokerUpdateId,
    ) -> OnlyStoredExecutionTransaction | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM execution_transactions WHERE runtime_id=? AND gateway_id=? AND account_id=? "
                "AND broker_update_id=?",
                (str(runtime_id), str(gateway_id), str(account_id), str(update_id)),
            ).fetchone()
        return None if row is None else self._decode_recovery_row(row)

    def ready_records(
        self, runtime_id: OnlyRuntimeId | None = None, *, after_sequence: int = 0
    ) -> tuple[OnlyCommittedExecutionTransaction, ...]:
        clause, values = (
            ("projection_ready=1 AND execution_sequence>?", (after_sequence,))
            if runtime_id is None
            else (
                "runtime_id=? AND projection_ready=1 AND execution_sequence>?",
                (str(runtime_id), after_sequence),
            )
        )
        with self._lock:
            rows = self._connection.execute(
                f"SELECT * FROM execution_transactions WHERE {clause} ORDER BY runtime_id, execution_sequence",
                values,
            ).fetchall()
        return tuple(self._decode_row(row) for row in rows)

    def ready_count(self, runtime_id: OnlyRuntimeId | None = None) -> int:
        clause, values = (
            ("projection_ready=1", ())
            if runtime_id is None
            else ("runtime_id=? AND projection_ready=1", (str(runtime_id),))
        )
        with self._lock:
            row = self._connection.execute(
                f"SELECT COUNT(*) AS value FROM execution_transactions WHERE {clause}", values
            ).fetchone()
        return int(row["value"])

    def bind_participant_registry_fingerprint(self, fingerprint: str) -> None:
        if not fingerprint.strip():
            raise ValueError("participant registry fingerprint is required")
        with self._lock:
            row = self._connection.execute(
                "SELECT value FROM runtime_persistence_metadata WHERE key='participant_registry_fingerprint'"
            ).fetchone()
            current = None if row is None else str(row["value"])
            if current not in {None, fingerprint}:
                raise OnlyRuntimePersistenceIdentityMismatch(
                    "RUNTIME_PERSISTENCE_IDENTITY_MISMATCH: participant_registry_fingerprint"
                )
            with self._connection:
                self._connection.execute(
                    "INSERT INTO runtime_persistence_metadata(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    ("participant_registry_fingerprint", fingerprint),
                )

    def write_checkpoint(self, checkpoint: OnlyRuntimeCheckpoint, *, retain_last: int) -> None:
        if retain_last < 1:
            raise ValueError("checkpoint retention must be positive")
        only_validate_runtime_checkpoint(checkpoint)
        header = checkpoint.header
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._connection.execute(
                    "INSERT INTO runtime_checkpoints VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(header.runtime_id),
                        header.checkpoint_sequence,
                        header.covered_execution_sequence,
                        header.checkpoint_schema_version,
                        only_encode_replay_cursor(header.replay_cursor),
                        header.config_fingerprint,
                        header.participant_registry_fingerprint,
                        header.aggregate_payload_hash,
                        header.created_at.unix_nanos,
                        header.pending_outbox_count,
                    ),
                )
                self._connection.executemany(
                    "INSERT INTO runtime_checkpoint_components VALUES (?, ?, ?, ?, ?, ?)",
                    tuple(
                        (
                            str(header.runtime_id),
                            header.checkpoint_sequence,
                            item.component_id,
                            item.component_schema_version,
                            item.payload,
                            item.payload_hash,
                        )
                        for item in checkpoint.components
                    ),
                )
                row = self._connection.execute(
                    "SELECT COUNT(*) AS value FROM runtime_checkpoint_components "
                    "WHERE runtime_id=? AND checkpoint_sequence=?",
                    (str(header.runtime_id), header.checkpoint_sequence),
                ).fetchone()
                if int(row["value"]) != len(checkpoint.components):
                    raise OnlyRuntimePersistenceStoreError("checkpoint component count mismatch")
                self._connection.execute(
                    "DELETE FROM runtime_checkpoints "
                    "WHERE runtime_id=? AND checkpoint_sequence NOT IN ("
                    "SELECT checkpoint_sequence FROM runtime_checkpoints "
                    "WHERE runtime_id=? ORDER BY checkpoint_sequence DESC LIMIT ?)",
                    (str(header.runtime_id), str(header.runtime_id), retain_last),
                )
                self._connection.execute("COMMIT")
            except sqlite3.Error as exc:
                self._connection.execute("ROLLBACK")
                raise OnlyRuntimePersistenceStoreError("Runtime checkpoint write failed") from exc
            except BaseException:
                self._connection.execute("ROLLBACK")
                raise

    def latest_checkpoint(self, runtime_id: OnlyRuntimeId) -> OnlyRuntimeCheckpoint | None:
        checkpoints = self.checkpoints(runtime_id)
        return None if not checkpoints else checkpoints[-1]

    def checkpoints(self, runtime_id: OnlyRuntimeId) -> tuple[OnlyRuntimeCheckpoint, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM runtime_checkpoints WHERE runtime_id=? ORDER BY checkpoint_sequence",
                (str(runtime_id),),
            ).fetchall()
            result: list[OnlyRuntimeCheckpoint] = []
            for row in rows:
                component_rows = self._connection.execute(
                    "SELECT * FROM runtime_checkpoint_components "
                    "WHERE runtime_id=? AND checkpoint_sequence=? ORDER BY component_id",
                    (str(runtime_id), int(row["checkpoint_sequence"])),
                ).fetchall()
                components = tuple(
                    OnlyRuntimeCheckpointComponent(
                        str(item["component_id"]),
                        int(item["component_schema_version"]),
                        str(item["payload"]),
                        str(item["payload_hash"]),
                    )
                    for item in component_rows
                )
                header = OnlyRuntimeCheckpointHeader(
                    OnlyRuntimeId(str(row["runtime_id"])),
                    int(row["checkpoint_sequence"]),
                    int(row["covered_execution_sequence"]),
                    int(row["checkpoint_schema_version"]),
                    OnlyTimestamp.from_unix_nanos(int(row["created_at"])),
                    only_decode_replay_cursor(str(row["replay_cursor_payload"])),
                    str(row["config_fingerprint"]),
                    str(row["participant_registry_fingerprint"]),
                    str(row["aggregate_payload_hash"]),
                    int(row["pending_outbox_count"]),
                )
                checkpoint = OnlyRuntimeCheckpoint(header, components)
                only_validate_runtime_checkpoint(checkpoint)
                result.append(checkpoint)
        return tuple(result)

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
            if self._closed:
                return
            self._connection.close()
            self._closed = True

    def metadata(self) -> Mapping[str, str]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT key, value FROM runtime_persistence_metadata ORDER BY key"
            ).fetchall()
        return {str(row["key"]): str(row["value"]) for row in rows}

    def _validate_existing_schema(self, identity: Mapping[str, str] | None) -> None:
        try:
            tables = {
                str(row["name"])
                for row in self._connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            if "execution_store_metadata" in tables:
                raise OnlyRuntimePersistenceSchemaUnsupported("RUNTIME_PERSISTENCE_SCHEMA_UNSUPPORTED: '1'")
            required = {
                "runtime_persistence_metadata",
                "execution_transactions",
                "execution_transaction_outbox",
                "runtime_checkpoints",
                "runtime_checkpoint_components",
            }
            if not required <= tables:
                missing_tables = ", ".join(sorted(required - tables))
                raise OnlyRuntimePersistenceMetadataCorrupt(
                    f"RUNTIME_PERSISTENCE_METADATA_CORRUPT: missing tables: {missing_tables}"
                )
            metadata = self.metadata()
        except sqlite3.Error as exc:
            raise OnlyRuntimePersistenceMetadataCorrupt("RUNTIME_PERSISTENCE_METADATA_CORRUPT") from exc
        schema_version = metadata.get("schema_version")
        if schema_version != ONLY_RUNTIME_PERSISTENCE_SCHEMA_VERSION:
            raise OnlyRuntimePersistenceSchemaUnsupported(f"RUNTIME_PERSISTENCE_SCHEMA_UNSUPPORTED: {schema_version!r}")
        if identity is None:
            return
        missing = sorted(set(identity) - set(metadata))
        if missing:
            raise OnlyRuntimePersistenceMetadataCorrupt(
                f"RUNTIME_PERSISTENCE_METADATA_CORRUPT: missing keys: {', '.join(missing)}"
            )
        mismatches = sorted(key for key, value in identity.items() if metadata.get(key) != value)
        if mismatches:
            raise OnlyRuntimePersistenceIdentityMismatch(
                f"RUNTIME_PERSISTENCE_IDENTITY_MISMATCH: {', '.join(mismatches)}"
            )

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
            fill_existing = self.get_by_fill_identity(prepared.runtime_id, prepared.fact_draft.fill_identity)
            if fill_existing is None:
                return None
            if fill_existing.fact.fill_payload_fingerprint != prepared.fact_draft.fill_payload_fingerprint:
                raise OnlyExecutionTransactionConflict("Fill identity conflicts with another payload fingerprint")
            return fill_existing
        transactions = tuple(self._decode_row(row) for row in rows)
        if (
            len({(item.prepared_authority_hash, item.prepared_payload_hash) for item in transactions}) != 1
            or transactions[0].prepared_authority_hash != prepared.authority_hash
            or transactions[0].prepared_payload_hash != prepared.payload_hash
        ):
            raise OnlyExecutionTransactionConflict("execution idempotency key conflicts with another prepared payload")
        return transactions[0]

    def _validate_fill_index(self, prepared: OnlyPreparedExecutionTransaction) -> None:
        for existing in self.transactions_for_order(prepared.runtime_id, prepared.fact_draft.order_id):
            if existing.fact.fill_index == prepared.fact_draft.fill_index:
                raise OnlyExecutionTransactionConflict("Fill index conflicts with another durable Order Fill")

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
        try:
            prepared_payload = str(row["prepared_payload"])
            prepared_value = json.loads(prepared_payload)
            if not isinstance(prepared_value, dict):
                raise ValueError("stored prepared execution payload is not an object")
            prepared_without_hash = dict(prepared_value)
            embedded_payload_digest = str(prepared_without_hash.pop("payload_hash"))
            calculated_payload_digest = hashlib.sha256(
                json.dumps(
                    prepared_without_hash,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            if (
                embedded_payload_digest != str(row["prepared_payload_hash"])
                or calculated_payload_digest != embedded_payload_digest
            ):
                raise ValueError("prepared execution transaction stored payload hash mismatch")
            payload = str(row["committed_payload"])
            value = json.loads(payload)
            historical_fill_authority = (
                isinstance(value, dict) and isinstance(value.get("fact"), dict) and "fill_identity" not in value["fact"]
            )
            transaction = only_decode_committed_execution_transaction(payload)
            if not historical_fill_authority and transaction.committed_payload_hash != str(
                row["committed_payload_hash"]
            ):
                raise ValueError("committed execution transaction stored payload hash mismatch")
            return transaction
        except OnlyRuntimePersistenceStoreError:
            raise
        except Exception as exc:
            raise OnlyRuntimePersistenceStoreError("stored committed execution transaction is malformed") from exc

    def _decode_recovery_row(self, row: sqlite3.Row) -> OnlyStoredExecutionTransaction:
        try:
            prepared_payload = str(row["prepared_payload"])
            prepared_json = json.loads(prepared_payload)
            historical_fill_authority = (
                isinstance(prepared_json, dict)
                and isinstance(prepared_json.get("fact_draft"), dict)
                and "fill_identity" not in prepared_json["fact_draft"]
            )
            prepared = only_decode_prepared_execution_transaction(prepared_payload)
            if not historical_fill_authority and prepared.authority_hash != str(row["prepared_authority_hash"]):
                raise ValueError("prepared execution transaction stored authority hash mismatch")
            if not historical_fill_authority and prepared.payload_hash != str(row["prepared_payload_hash"]):
                raise ValueError("prepared execution transaction stored payload hash mismatch")
            transaction = only_decode_committed_execution_transaction(str(row["committed_payload"]))
            if not historical_fill_authority and transaction.committed_payload_hash != str(
                row["committed_payload_hash"]
            ):
                raise ValueError("committed execution transaction stored payload hash mismatch")
            if not historical_fill_authority and transaction.prepared_authority_hash != prepared.authority_hash:
                raise ValueError("prepared and committed authority hashes disagree")
            if not historical_fill_authority and transaction.prepared_payload_hash != prepared.payload_hash:
                raise ValueError("prepared and committed payload hashes disagree")
            return OnlyStoredExecutionTransaction(prepared, transaction)
        except OnlyRuntimePersistenceStoreError:
            raise
        except Exception as exc:
            raise OnlyRuntimePersistenceStoreError("stored execution transaction is malformed") from exc

    def _decode_outbox(self, row: sqlite3.Row) -> OnlyExecutionTransactionOutboxRecord:
        try:
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
            if (
                event_sequence > len(transaction.outbox_events)
                or transaction.outbox_events[event_sequence - 1] != event
            ):
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
        except OnlyRuntimePersistenceStoreError:
            raise
        except Exception as exc:
            raise OnlyRuntimePersistenceStoreError("stored execution outbox record is malformed") from exc

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
