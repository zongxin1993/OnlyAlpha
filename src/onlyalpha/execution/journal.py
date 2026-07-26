"""Durable authority for Runtime committed execution facts.

The journal deliberately owns neither Managers nor Broker adapters.  A fact is
made durable before it is eligible for event publication; Manager state is a
projection of this log, not a second execution history.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Protocol

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyRuntimeId, OnlyTradeId
from onlyalpha.event.model import OnlyEvent

from .committed import OnlyCommittedExecutionFact


@dataclass(frozen=True, slots=True)
class OnlyDurableExecutionCommit:
    """One atomically persisted execution fact and its durable outbox."""

    transaction_id: str
    fact: OnlyCommittedExecutionFact
    outbox_events: tuple[OnlyEvent, ...] = ()
    checkpoint_payload: str | None = None

    def __post_init__(self) -> None:
        if not self.transaction_id:
            raise ValueError("durable execution commit requires a transaction_id")


@dataclass(frozen=True, slots=True)
class OnlyJournalAppendResult:
    fact: OnlyCommittedExecutionFact
    inserted: bool


@dataclass(frozen=True, slots=True)
class OnlyExecutionOutboxRecord:
    runtime_id: OnlyRuntimeId
    execution_sequence: int
    event_sequence: int
    event: OnlyEvent
    attempt_count: int


class OnlyCommittedExecutionJournalPort(Protocol):
    """Append-only committed-execution authority, scoped by Runtime."""

    def next_sequence(self, runtime_id: OnlyRuntimeId) -> int: ...

    def append_transaction(self, transaction: OnlyDurableExecutionCommit) -> OnlyJournalAppendResult: ...

    def get_by_trade(
        self,
        runtime_id: OnlyRuntimeId,
        gateway_id: OnlyBrokerGatewayId,
        account_id: OnlyAccountId,
        trade_id: OnlyTradeId,
    ) -> OnlyCommittedExecutionFact | None: ...

    def get_by_update(
        self,
        runtime_id: OnlyRuntimeId,
        gateway_id: OnlyBrokerGatewayId,
        account_id: OnlyAccountId,
        update_id: OnlyBrokerUpdateId,
    ) -> OnlyCommittedExecutionFact | None: ...

    def records(
        self, runtime_id: OnlyRuntimeId | None = None, *, after_sequence: int = 0
    ) -> tuple[OnlyCommittedExecutionFact, ...]: ...

    def pending_outbox(self, runtime_id: OnlyRuntimeId) -> tuple[OnlyExecutionOutboxRecord, ...]: ...

    def mark_outbox_published(
        self, runtime_id: OnlyRuntimeId, execution_sequence: int, event_sequence: int
    ) -> None: ...


def _fact_payload(fact: OnlyCommittedExecutionFact) -> str:
    return fact.to_json()


def _fact_hash(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class OnlyInMemoryCommittedExecutionJournal:
    """Contract-equivalent, process-local implementation for deterministic backtests."""

    def __init__(self, runtime_id: OnlyRuntimeId, gateway_ids: tuple[OnlyBrokerGatewayId, ...]) -> None:
        if not gateway_ids:
            raise ValueError("committed execution journal requires at least one Gateway scope")
        self._runtime_id = runtime_id
        self._gateway_ids = frozenset(gateway_ids)
        self._records: list[OnlyCommittedExecutionFact] = []
        self._by_trade: dict[tuple[OnlyBrokerGatewayId, OnlyAccountId, OnlyTradeId], OnlyCommittedExecutionFact] = {}
        self._by_update: dict[
            tuple[OnlyBrokerGatewayId, OnlyAccountId, OnlyBrokerUpdateId], OnlyCommittedExecutionFact
        ] = {}
        self._outbox: dict[tuple[int, int], OnlyExecutionOutboxRecord] = {}

    def next_sequence(self, runtime_id: OnlyRuntimeId) -> int:
        self._require_runtime(runtime_id)
        return len(self._records) + 1

    def append_transaction(self, transaction: OnlyDurableExecutionCommit) -> OnlyJournalAppendResult:
        fact = transaction.fact
        self._require_fact_scope(fact)
        trade_key = fact.gateway_id, fact.account_id, fact.trade_id
        update_key = fact.gateway_id, fact.account_id, fact.broker_update_id
        existing = self._by_trade.get(trade_key) or self._by_update.get(update_key)
        if existing is not None:
            if existing.stable_hash != fact.stable_hash:
                raise ValueError("idempotency key conflicts with a different committed execution")
            return OnlyJournalAppendResult(existing, False)
        if fact.execution_sequence != self.next_sequence(fact.runtime_id):
            raise ValueError("committed execution sequence must be contiguous")
        # Validate the exact stable payload before exposing it through the log.
        if OnlyCommittedExecutionFact.from_json(_fact_payload(fact)) != fact:
            raise ValueError("committed execution payload is not round-trippable")
        self._records.append(fact)
        self._by_trade[trade_key] = fact
        self._by_update[update_key] = fact
        for index, event in enumerate(transaction.outbox_events, start=1):
            self._outbox[fact.execution_sequence, index] = OnlyExecutionOutboxRecord(
                fact.runtime_id, fact.execution_sequence, index, event, 0
            )
        return OnlyJournalAppendResult(fact, True)

    def get_by_trade(
        self,
        runtime_id: OnlyRuntimeId,
        gateway_id: OnlyBrokerGatewayId,
        account_id: OnlyAccountId,
        trade_id: OnlyTradeId,
    ) -> OnlyCommittedExecutionFact | None:
        self._require_runtime(runtime_id)
        return self._by_trade.get((gateway_id, account_id, trade_id))

    def get_by_update(
        self,
        runtime_id: OnlyRuntimeId,
        gateway_id: OnlyBrokerGatewayId,
        account_id: OnlyAccountId,
        update_id: OnlyBrokerUpdateId,
    ) -> OnlyCommittedExecutionFact | None:
        self._require_runtime(runtime_id)
        return self._by_update.get((gateway_id, account_id, update_id))

    def records(
        self, runtime_id: OnlyRuntimeId | None = None, *, after_sequence: int = 0
    ) -> tuple[OnlyCommittedExecutionFact, ...]:
        if runtime_id is not None:
            self._require_runtime(runtime_id)
        return tuple(item for item in self._records if item.execution_sequence > after_sequence)

    def pending_outbox(self, runtime_id: OnlyRuntimeId) -> tuple[OnlyExecutionOutboxRecord, ...]:
        self._require_runtime(runtime_id)
        return tuple(self._outbox[key] for key in sorted(self._outbox))

    def mark_outbox_published(self, runtime_id: OnlyRuntimeId, execution_sequence: int, event_sequence: int) -> None:
        self._require_runtime(runtime_id)
        self._outbox.pop((execution_sequence, event_sequence), None)

    def __len__(self) -> int:
        return len(self._records)

    def _require_runtime(self, runtime_id: OnlyRuntimeId) -> None:
        if runtime_id != self._runtime_id:
            raise ValueError("committed execution belongs to another Runtime")

    def _require_fact_scope(self, fact: OnlyCommittedExecutionFact) -> None:
        self._require_runtime(fact.runtime_id)
        if fact.gateway_id not in self._gateway_ids:
            raise ValueError("committed execution belongs to an unknown Gateway")


class OnlySqliteCommittedExecutionJournal:
    """SQLite journal with one transaction for fact, checkpoint and outbox rows."""

    def __init__(self, path: Path | str) -> None:
        self._connection = sqlite3.connect(str(path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = RLock()
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS execution_commits (
                    runtime_id TEXT NOT NULL, execution_sequence INTEGER NOT NULL, transaction_id TEXT NOT NULL UNIQUE,
                    gateway_id TEXT NOT NULL, account_id TEXT NOT NULL, trade_id TEXT NOT NULL, broker_update_id TEXT NOT NULL,
                    fact_schema_version INTEGER NOT NULL, fact_payload TEXT NOT NULL, fact_hash TEXT NOT NULL, committed_at INTEGER NOT NULL,
                    PRIMARY KEY(runtime_id, execution_sequence),
                    UNIQUE(runtime_id, gateway_id, account_id, trade_id),
                    UNIQUE(runtime_id, gateway_id, account_id, broker_update_id)
                );
                CREATE TABLE IF NOT EXISTS execution_outbox (
                    runtime_id TEXT NOT NULL, execution_sequence INTEGER NOT NULL, event_sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL, event_payload TEXT NOT NULL, published INTEGER NOT NULL DEFAULT 0,
                    published_at INTEGER, attempt_count INTEGER NOT NULL DEFAULT 0, last_error TEXT,
                    PRIMARY KEY(runtime_id, execution_sequence, event_sequence)
                );
                CREATE TABLE IF NOT EXISTS runtime_execution_checkpoint (
                    runtime_id TEXT PRIMARY KEY, last_execution_sequence INTEGER NOT NULL, state_version INTEGER NOT NULL,
                    checkpoint_payload TEXT, checkpoint_hash TEXT, updated_at INTEGER NOT NULL
                );
                """
            )

    def next_sequence(self, runtime_id: OnlyRuntimeId) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT COALESCE(MAX(execution_sequence), 0) AS value FROM execution_commits WHERE runtime_id=?",
                (str(runtime_id),),
            ).fetchone()
            return int(row["value"]) + 1

    def append_transaction(self, transaction: OnlyDurableExecutionCommit) -> OnlyJournalAppendResult:
        fact = transaction.fact
        payload = _fact_payload(fact)
        if OnlyCommittedExecutionFact.from_json(payload) != fact:
            raise ValueError("committed execution payload is not round-trippable")
        digest = _fact_hash(payload)
        with self._lock:
            try:
                with self._connection:
                    expected = self.next_sequence(fact.runtime_id)
                    # A sequence ahead of the durable head is never valid.  A
                    # sequence behind it is deliberately attempted so SQLite's
                    # unique constraints, not a racy pre-query, decide whether
                    # this is an idempotent retry or a conflicting fact.
                    if fact.execution_sequence > expected:
                        raise ValueError("committed execution sequence must be contiguous")
                    self._connection.execute(
                        "INSERT INTO execution_commits VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            str(fact.runtime_id),
                            fact.execution_sequence,
                            transaction.transaction_id,
                            str(fact.gateway_id),
                            str(fact.account_id),
                            str(fact.trade_id),
                            str(fact.broker_update_id),
                            fact.schema_version,
                            payload,
                            digest,
                            fact.ts_committed.unix_nanos,
                        ),
                    )
                    for index, event in enumerate(transaction.outbox_events, start=1):
                        self._connection.execute(
                            "INSERT INTO execution_outbox(runtime_id, execution_sequence, event_sequence, event_type, event_payload) VALUES (?, ?, ?, ?, ?)",
                            (
                                str(fact.runtime_id),
                                fact.execution_sequence,
                                index,
                                str(event.event_type),
                                json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":")),
                            ),
                        )
                    checkpoint = transaction.checkpoint_payload
                    self._connection.execute(
                        "INSERT INTO runtime_execution_checkpoint VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(runtime_id) DO UPDATE SET last_execution_sequence=excluded.last_execution_sequence, state_version=excluded.state_version, checkpoint_payload=excluded.checkpoint_payload, checkpoint_hash=excluded.checkpoint_hash, updated_at=excluded.updated_at",
                        (
                            str(fact.runtime_id),
                            fact.execution_sequence,
                            1,
                            checkpoint,
                            None if checkpoint is None else _fact_hash(checkpoint),
                            fact.ts_committed.unix_nanos,
                        ),
                    )
                return OnlyJournalAppendResult(fact, True)
            except sqlite3.IntegrityError:
                existing = self.get_by_trade(fact.runtime_id, fact.gateway_id, fact.account_id, fact.trade_id)
                existing = existing or self.get_by_update(
                    fact.runtime_id, fact.gateway_id, fact.account_id, fact.broker_update_id
                )
                if existing is None or existing.stable_hash != fact.stable_hash:
                    raise ValueError("idempotency key conflicts with a different committed execution") from None
                return OnlyJournalAppendResult(existing, False)

    def get_by_trade(
        self,
        runtime_id: OnlyRuntimeId,
        gateway_id: OnlyBrokerGatewayId,
        account_id: OnlyAccountId,
        trade_id: OnlyTradeId,
    ) -> OnlyCommittedExecutionFact | None:
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
    ) -> OnlyCommittedExecutionFact | None:
        return self._find(
            "runtime_id=? AND gateway_id=? AND account_id=? AND broker_update_id=?",
            (str(runtime_id), str(gateway_id), str(account_id), str(update_id)),
        )

    def records(
        self, runtime_id: OnlyRuntimeId | None = None, *, after_sequence: int = 0
    ) -> tuple[OnlyCommittedExecutionFact, ...]:
        clause, values = (
            ("execution_sequence>?", (after_sequence,))
            if runtime_id is None
            else ("runtime_id=? AND execution_sequence>?", (str(runtime_id), after_sequence))
        )
        with self._lock:
            rows = self._connection.execute(
                f"SELECT fact_payload, fact_hash FROM execution_commits WHERE {clause} ORDER BY runtime_id, execution_sequence",
                values,
            ).fetchall()
        return tuple(self._decode(row["fact_payload"], row["fact_hash"]) for row in rows)

    def pending_outbox(self, runtime_id: OnlyRuntimeId) -> tuple[OnlyExecutionOutboxRecord, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM execution_outbox WHERE runtime_id=? AND published=0 ORDER BY execution_sequence, event_sequence",
                (str(runtime_id),),
            ).fetchall()
        return tuple(
            OnlyExecutionOutboxRecord(
                runtime_id,
                int(row["execution_sequence"]),
                int(row["event_sequence"]),
                OnlyEvent.from_dict(json.loads(row["event_payload"])),
                int(row["attempt_count"]),
            )
            for row in rows
        )

    def mark_outbox_published(self, runtime_id: OnlyRuntimeId, execution_sequence: int, event_sequence: int) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE execution_outbox SET published=1 WHERE runtime_id=? AND execution_sequence=? AND event_sequence=?",
                (str(runtime_id), execution_sequence, event_sequence),
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _find(self, clause: str, values: tuple[str, ...]) -> OnlyCommittedExecutionFact | None:
        with self._lock:
            row = self._connection.execute(
                f"SELECT fact_payload, fact_hash FROM execution_commits WHERE {clause}", values
            ).fetchone()
        return None if row is None else self._decode(row["fact_payload"], row["fact_hash"])

    @staticmethod
    def _decode(payload: str, digest: str) -> OnlyCommittedExecutionFact:
        if _fact_hash(payload) != digest:
            raise ValueError("committed execution journal payload hash mismatch")
        return OnlyCommittedExecutionFact.from_json(payload)


__all__ = [
    "OnlyCommittedExecutionJournalPort",
    "OnlyDurableExecutionCommit",
    "OnlyExecutionOutboxRecord",
    "OnlyInMemoryCommittedExecutionJournal",
    "OnlyJournalAppendResult",
    "OnlySqliteCommittedExecutionJournal",
]
