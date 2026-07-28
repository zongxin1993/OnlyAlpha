"""Test-only execution fault decorators; production code contains no fault switches."""

from __future__ import annotations

from enum import StrEnum

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyRuntimeId, OnlyTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.execution import (
    OnlyAppliedProjectionLedger,
    OnlyAppliedProjectionRecord,
    OnlyCommittedExecutionTransaction,
    OnlyExecutionProjectionApplyContext,
    OnlyExecutionProjectionComponent,
    OnlyExecutionProjectionTarget,
    OnlyExecutionTransactionCommitResult,
    OnlyExecutionTransactionOutboxKey,
    OnlyExecutionTransactionOutboxRecord,
    OnlyExecutionTransactionStorePort,
    OnlyPreparedExecutionTransaction,
    OnlyProjectionApplyResult,
)
from onlyalpha.execution.transaction_store import OnlyExecutionTransactionStoreError


class OnlyTestExecutionStoreFault(StrEnum):
    COMMIT = "COMMIT"
    AFTER_COMMIT = "AFTER_COMMIT"
    MARK_READY = "MARK_READY"
    MARK_FAILED = "MARK_FAILED"
    OUTBOX_BEGIN_ATTEMPT = "OUTBOX_BEGIN_ATTEMPT"
    OUTBOX_MARK_PUBLISHED = "OUTBOX_MARK_PUBLISHED"
    OUTBOX_MARK_FAILED = "OUTBOX_MARK_FAILED"
    QUERY = "QUERY"


class OnlyFailOnceExecutionProjectionTarget:
    def __init__(
        self,
        delegate: OnlyExecutionProjectionTarget,
        *,
        fail_before: bool = False,
        fail_after: bool = False,
    ) -> None:
        if fail_before == fail_after:
            raise ValueError("exactly one projection target fault position is required")
        self._delegate = delegate
        self._fail_before = fail_before
        self._fail_after = fail_after
        self._failed = False

    @property
    def component(self) -> OnlyExecutionProjectionComponent:
        return self._delegate.component

    def apply_execution_projection(self, context: OnlyExecutionProjectionApplyContext) -> OnlyProjectionApplyResult:
        if self._fail_before and not self._failed:
            self._failed = True
            raise RuntimeError(f"injected failure before {self.component.value}")
        result = self._delegate.apply_execution_projection(context)
        if self._fail_after and not self._failed:
            self._failed = True
            raise RuntimeError(f"injected failure after {self.component.value}")
        return result


class OnlyFailOnceAppliedProjectionLedger:
    def __init__(
        self,
        delegate: OnlyAppliedProjectionLedger,
        component: OnlyExecutionProjectionComponent,
    ) -> None:
        self._delegate = delegate
        self._component = component
        self._failed = False

    def get(
        self, execution_sequence: int, component: OnlyExecutionProjectionComponent
    ) -> OnlyAppliedProjectionRecord | None:
        return self._delegate.get(execution_sequence, component)

    def record(self, record: OnlyAppliedProjectionRecord) -> None:
        if record.component is self._component and not self._failed:
            self._failed = True
            raise RuntimeError(f"injected Applied Ledger failure for {record.component.value}")
        self._delegate.record(record)


class OnlyFailOnceExecutionTransactionStore:
    def __init__(
        self,
        delegate: OnlyExecutionTransactionStorePort,
        fault: OnlyTestExecutionStoreFault,
    ) -> None:
        self._delegate = delegate
        self._fault = fault
        self._failed = False

    def _raise_once(self, operation: OnlyTestExecutionStoreFault) -> None:
        if self._fault is operation and not self._failed:
            self._failed = True
            raise OnlyExecutionTransactionStoreError(f"injected {operation.value} failure")

    def commit(
        self, prepared: OnlyPreparedExecutionTransaction, *, committed_at: OnlyTimestamp
    ) -> OnlyExecutionTransactionCommitResult:
        self._raise_once(OnlyTestExecutionStoreFault.COMMIT)
        result = self._delegate.commit(prepared, committed_at=committed_at)
        self._raise_once(OnlyTestExecutionStoreFault.AFTER_COMMIT)
        return result

    def get_by_sequence(
        self, runtime_id: OnlyRuntimeId, execution_sequence: int
    ) -> OnlyCommittedExecutionTransaction | None:
        self._raise_once(OnlyTestExecutionStoreFault.QUERY)
        return self._delegate.get_by_sequence(runtime_id, execution_sequence)

    def get_by_transaction_id(self, transaction_id: str) -> OnlyCommittedExecutionTransaction | None:
        self._raise_once(OnlyTestExecutionStoreFault.QUERY)
        return self._delegate.get_by_transaction_id(transaction_id)

    def get_by_trade(
        self,
        runtime_id: OnlyRuntimeId,
        gateway_id: OnlyBrokerGatewayId,
        account_id: OnlyAccountId,
        trade_id: OnlyTradeId,
    ) -> OnlyCommittedExecutionTransaction | None:
        self._raise_once(OnlyTestExecutionStoreFault.QUERY)
        return self._delegate.get_by_trade(runtime_id, gateway_id, account_id, trade_id)

    def get_by_update(
        self,
        runtime_id: OnlyRuntimeId,
        gateway_id: OnlyBrokerGatewayId,
        account_id: OnlyAccountId,
        update_id: OnlyBrokerUpdateId,
    ) -> OnlyCommittedExecutionTransaction | None:
        self._raise_once(OnlyTestExecutionStoreFault.QUERY)
        return self._delegate.get_by_update(runtime_id, gateway_id, account_id, update_id)

    def records(
        self, runtime_id: OnlyRuntimeId | None = None, *, after_sequence: int = 0
    ) -> tuple[OnlyCommittedExecutionTransaction, ...]:
        self._raise_once(OnlyTestExecutionStoreFault.QUERY)
        return self._delegate.records(runtime_id, after_sequence=after_sequence)

    def ready_records(
        self, runtime_id: OnlyRuntimeId | None = None, *, after_sequence: int = 0
    ) -> tuple[OnlyCommittedExecutionTransaction, ...]:
        self._raise_once(OnlyTestExecutionStoreFault.QUERY)
        return self._delegate.ready_records(runtime_id, after_sequence=after_sequence)

    def ready_count(self, runtime_id: OnlyRuntimeId | None = None) -> int:
        self._raise_once(OnlyTestExecutionStoreFault.QUERY)
        return self._delegate.ready_count(runtime_id)

    def mark_projection_ready(
        self,
        runtime_id: OnlyRuntimeId,
        execution_sequence: int,
        *,
        projected_at: OnlyTimestamp,
    ) -> None:
        self._raise_once(OnlyTestExecutionStoreFault.MARK_READY)
        self._delegate.mark_projection_ready(runtime_id, execution_sequence, projected_at=projected_at)

    def mark_projection_failed(
        self,
        runtime_id: OnlyRuntimeId,
        execution_sequence: int,
        *,
        failed_at: OnlyTimestamp,
        error: str,
    ) -> None:
        self._raise_once(OnlyTestExecutionStoreFault.MARK_FAILED)
        self._delegate.mark_projection_failed(runtime_id, execution_sequence, failed_at=failed_at, error=error)

    def unprojected(
        self, runtime_id: OnlyRuntimeId, *, after_sequence: int = 0
    ) -> tuple[OnlyCommittedExecutionTransaction, ...]:
        self._raise_once(OnlyTestExecutionStoreFault.QUERY)
        return self._delegate.unprojected(runtime_id, after_sequence=after_sequence)

    def pending(self, runtime_id: OnlyRuntimeId, *, limit: int) -> tuple[OnlyExecutionTransactionOutboxRecord, ...]:
        self._raise_once(OnlyTestExecutionStoreFault.QUERY)
        return self._delegate.pending(runtime_id, limit=limit)

    def begin_attempt(
        self, key: OnlyExecutionTransactionOutboxKey, attempted_at: OnlyTimestamp
    ) -> OnlyExecutionTransactionOutboxRecord:
        self._raise_once(OnlyTestExecutionStoreFault.OUTBOX_BEGIN_ATTEMPT)
        return self._delegate.begin_attempt(key, attempted_at)

    def mark_published(self, key: OnlyExecutionTransactionOutboxKey, published_at: OnlyTimestamp) -> None:
        self._raise_once(OnlyTestExecutionStoreFault.OUTBOX_MARK_PUBLISHED)
        self._delegate.mark_published(key, published_at)

    def mark_failed(self, key: OnlyExecutionTransactionOutboxKey, failed_at: OnlyTimestamp, error: str) -> None:
        self._raise_once(OnlyTestExecutionStoreFault.OUTBOX_MARK_FAILED)
        self._delegate.mark_failed(key, failed_at, error)

    def pending_count(self, runtime_id: OnlyRuntimeId) -> int:
        self._raise_once(OnlyTestExecutionStoreFault.QUERY)
        return self._delegate.pending_count(runtime_id)

    def outbox_records(self, runtime_id: OnlyRuntimeId) -> tuple[OnlyExecutionTransactionOutboxRecord, ...]:
        self._raise_once(OnlyTestExecutionStoreFault.QUERY)
        return self._delegate.outbox_records(runtime_id)

    def close(self) -> None:
        self._delegate.close()


__all__ = [name for name in globals() if name.startswith("Only")]
