"""Narrow execution persistence ports shared with the Runtime-owned store."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyOrderId, OnlyRuntimeId, OnlyTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.event.model import OnlyEvent
from onlyalpha.transaction.transaction import (
    OnlyCommittedRuntimeTransaction,
    OnlyPreparedRuntimeTransaction,
    OnlyRuntimeTransactionCommitResult,
    OnlyStoredRuntimeTransaction,
)


class OnlyRuntimeTransactionConflict(ValueError):
    """An idempotency key was reused for a different prepared authority."""


class OnlyRuntimePersistenceStoreError(RuntimeError):
    """The persistence layer failed independently of a business conflict."""


@dataclass(frozen=True, slots=True)
class OnlyRuntimeTransactionOutboxKey:
    runtime_id: OnlyRuntimeId
    execution_sequence: int
    event_sequence: int


@dataclass(frozen=True, slots=True)
class OnlyRuntimeTransactionOutboxRecord:
    key: OnlyRuntimeTransactionOutboxKey
    event: OnlyEvent
    projection_ready: bool
    published: bool
    attempt_count: int
    last_attempted_at: OnlyTimestamp | None
    published_at: OnlyTimestamp | None
    last_error: str | None


class OnlyRuntimeTransactionCommitPort(Protocol):
    def commit(
        self, prepared: OnlyPreparedRuntimeTransaction, *, committed_at: OnlyTimestamp
    ) -> OnlyRuntimeTransactionCommitResult: ...


class OnlyRuntimeTransactionQueryPort(Protocol):
    def get_by_sequence(
        self, runtime_id: OnlyRuntimeId, execution_sequence: int
    ) -> OnlyCommittedRuntimeTransaction | None: ...

    def get_by_transaction_id(self, transaction_id: str) -> OnlyCommittedRuntimeTransaction | None: ...

    def get_by_trade(
        self,
        runtime_id: OnlyRuntimeId,
        gateway_id: OnlyBrokerGatewayId,
        account_id: OnlyAccountId,
        trade_id: OnlyTradeId,
    ) -> OnlyCommittedRuntimeTransaction | None: ...

    def get_by_update(
        self,
        runtime_id: OnlyRuntimeId,
        gateway_id: OnlyBrokerGatewayId,
        account_id: OnlyAccountId,
        update_id: OnlyBrokerUpdateId,
    ) -> OnlyCommittedRuntimeTransaction | None: ...

    def get_by_fill_identity(
        self, runtime_id: OnlyRuntimeId, fill_identity: str
    ) -> OnlyCommittedRuntimeTransaction | None: ...

    def transactions_for_order(
        self, runtime_id: OnlyRuntimeId, order_id: OnlyOrderId
    ) -> tuple[OnlyCommittedRuntimeTransaction, ...]: ...

    def latest_fill_for_order(
        self, runtime_id: OnlyRuntimeId, order_id: OnlyOrderId
    ) -> OnlyCommittedRuntimeTransaction | None: ...

    def records(
        self, runtime_id: OnlyRuntimeId | None = None, *, after_sequence: int = 0
    ) -> tuple[OnlyCommittedRuntimeTransaction, ...]: ...


class OnlyRuntimeTransactionRecoveryQueryPort(Protocol):
    def recovery_records(
        self,
        runtime_id: OnlyRuntimeId,
        *,
        after_sequence: int,
    ) -> tuple[OnlyStoredRuntimeTransaction, ...]: ...

    def get_recovery_record_by_update(
        self,
        runtime_id: OnlyRuntimeId,
        gateway_id: OnlyBrokerGatewayId,
        account_id: OnlyAccountId,
        update_id: OnlyBrokerUpdateId,
    ) -> OnlyStoredRuntimeTransaction | None: ...


class OnlyProjectionReadyRuntimeQueryPort(Protocol):
    def ready_records(
        self, runtime_id: OnlyRuntimeId | None = None, *, after_sequence: int = 0
    ) -> tuple[OnlyCommittedRuntimeTransaction, ...]: ...

    def ready_count(self, runtime_id: OnlyRuntimeId | None = None) -> int: ...


class OnlyRuntimeProjectionStatePort(Protocol):
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
    ) -> tuple[OnlyCommittedRuntimeTransaction, ...]: ...


class OnlyRuntimeTransactionOutboxPort(Protocol):
    def pending(self, runtime_id: OnlyRuntimeId, *, limit: int) -> tuple[OnlyRuntimeTransactionOutboxRecord, ...]: ...

    def begin_attempt(
        self, key: OnlyRuntimeTransactionOutboxKey, attempted_at: OnlyTimestamp
    ) -> OnlyRuntimeTransactionOutboxRecord: ...

    def mark_published(self, key: OnlyRuntimeTransactionOutboxKey, published_at: OnlyTimestamp) -> None: ...

    def mark_failed(self, key: OnlyRuntimeTransactionOutboxKey, failed_at: OnlyTimestamp, error: str) -> None: ...

    def pending_count(self, runtime_id: OnlyRuntimeId) -> int: ...

    def outbox_records(self, runtime_id: OnlyRuntimeId) -> tuple[OnlyRuntimeTransactionOutboxRecord, ...]: ...
