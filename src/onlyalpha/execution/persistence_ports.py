"""Narrow execution persistence ports shared with the Runtime-owned store."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyOrderId, OnlyRuntimeId, OnlyTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.event.model import OnlyEvent

from .transaction import (
    OnlyCommittedExecutionTransaction,
    OnlyExecutionTransactionCommitResult,
    OnlyPreparedExecutionTransaction,
    OnlyStoredExecutionTransaction,
)


class OnlyExecutionTransactionConflict(ValueError):
    """An idempotency key was reused for a different prepared authority."""


class OnlyRuntimePersistenceStoreError(RuntimeError):
    """The persistence layer failed independently of a business conflict."""


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

    def get_by_fill_identity(
        self, runtime_id: OnlyRuntimeId, fill_identity: str
    ) -> OnlyCommittedExecutionTransaction | None: ...

    def transactions_for_order(
        self, runtime_id: OnlyRuntimeId, order_id: OnlyOrderId
    ) -> tuple[OnlyCommittedExecutionTransaction, ...]: ...

    def latest_fill_for_order(
        self, runtime_id: OnlyRuntimeId, order_id: OnlyOrderId
    ) -> OnlyCommittedExecutionTransaction | None: ...

    def records(
        self, runtime_id: OnlyRuntimeId | None = None, *, after_sequence: int = 0
    ) -> tuple[OnlyCommittedExecutionTransaction, ...]: ...


class OnlyExecutionTransactionRecoveryQueryPort(Protocol):
    def recovery_records(
        self,
        runtime_id: OnlyRuntimeId,
        *,
        after_sequence: int,
    ) -> tuple[OnlyStoredExecutionTransaction, ...]: ...

    def get_recovery_record_by_update(
        self,
        runtime_id: OnlyRuntimeId,
        gateway_id: OnlyBrokerGatewayId,
        account_id: OnlyAccountId,
        update_id: OnlyBrokerUpdateId,
    ) -> OnlyStoredExecutionTransaction | None: ...


class OnlyProjectionReadyExecutionQueryPort(Protocol):
    def ready_records(
        self, runtime_id: OnlyRuntimeId | None = None, *, after_sequence: int = 0
    ) -> tuple[OnlyCommittedExecutionTransaction, ...]: ...

    def ready_count(self, runtime_id: OnlyRuntimeId | None = None) -> int: ...


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

    def outbox_records(self, runtime_id: OnlyRuntimeId) -> tuple[OnlyExecutionTransactionOutboxRecord, ...]: ...
