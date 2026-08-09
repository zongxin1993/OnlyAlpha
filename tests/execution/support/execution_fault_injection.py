"""Test-only execution fault decorators; production code contains no fault switches."""

from __future__ import annotations

from enum import StrEnum

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyOrderId, OnlyRuntimeId, OnlyTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.execution import (
    OnlyAppliedRuntimeProjectionLedger,
    OnlyAppliedRuntimeProjectionRecord,
    OnlyCommittedRuntimeTransaction,
    OnlyPreparedRuntimeTransaction,
    OnlyProjectionApplyResult,
    OnlyRuntimeOperationKind,
    OnlyRuntimeProjectionApplyContext,
    OnlyRuntimeProjectionComponent,
    OnlyRuntimeProjectionTarget,
    OnlyRuntimeTransactionCommitResult,
    OnlyRuntimeTransactionOutboxKey,
    OnlyRuntimeTransactionOutboxRecord,
)
from onlyalpha.runtime.checkpoint.model import OnlyRuntimeCheckpoint
from onlyalpha.runtime.persistence.store import OnlyRuntimePersistenceStoreError, OnlyRuntimePersistenceStorePort


class OnlyTestRuntimePersistenceFault(StrEnum):
    COMMIT = "COMMIT"
    AFTER_COMMIT = "AFTER_COMMIT"
    MARK_READY = "MARK_READY"
    MARK_FAILED = "MARK_FAILED"
    OUTBOX_BEGIN_ATTEMPT = "OUTBOX_BEGIN_ATTEMPT"
    OUTBOX_MARK_PUBLISHED = "OUTBOX_MARK_PUBLISHED"
    OUTBOX_MARK_FAILED = "OUTBOX_MARK_FAILED"
    QUERY = "QUERY"
    CHECKPOINT_WRITE = "CHECKPOINT_WRITE"


class OnlyFailOnceExecutionProjectionTarget:
    def __init__(
        self,
        delegate: OnlyRuntimeProjectionTarget,
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
    def component(self) -> OnlyRuntimeProjectionComponent:
        return self._delegate.component

    def apply_execution_projection(self, context: OnlyRuntimeProjectionApplyContext) -> OnlyProjectionApplyResult:
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
        delegate: OnlyAppliedRuntimeProjectionLedger,
        component: OnlyRuntimeProjectionComponent,
    ) -> None:
        self._delegate = delegate
        self._component = component
        self._failed = False

    def get(
        self, execution_sequence: int, component: OnlyRuntimeProjectionComponent
    ) -> OnlyAppliedRuntimeProjectionRecord | None:
        return self._delegate.get(execution_sequence, component)

    def record(self, record: OnlyAppliedRuntimeProjectionRecord) -> None:
        if record.component is self._component and not self._failed:
            self._failed = True
            raise RuntimeError(f"injected Applied Ledger failure for {record.component.value}")
        self._delegate.record(record)


class OnlyFailOnceRuntimePersistenceStore:
    def __init__(
        self,
        delegate: OnlyRuntimePersistenceStorePort,
        fault: OnlyTestRuntimePersistenceFault,
        *,
        fault_after: int = 0,
        operation_kind: OnlyRuntimeOperationKind | None = None,
    ) -> None:
        self._delegate = delegate
        self._fault = fault
        self._failed = False
        self._fault_after = fault_after
        self._operation_kind = operation_kind
        self._operation_counts: dict[OnlyTestRuntimePersistenceFault, int] = {}

    def _raise_once(self, operation: OnlyTestRuntimePersistenceFault) -> None:
        count = self._operation_counts.get(operation, 0)
        self._operation_counts[operation] = count + 1
        if self._fault is operation and not self._failed and count >= self._fault_after:
            self._failed = True
            raise OnlyRuntimePersistenceStoreError(f"injected {operation.value} failure")

    def _raise_once_for_operation(
        self,
        operation: OnlyTestRuntimePersistenceFault,
        operation_kind: OnlyRuntimeOperationKind,
    ) -> None:
        if self._operation_kind is None or operation_kind is self._operation_kind:
            self._raise_once(operation)

    def _raise_once_for_sequence(
        self,
        operation: OnlyTestRuntimePersistenceFault,
        runtime_id: OnlyRuntimeId,
        execution_sequence: int,
    ) -> None:
        transaction = self._delegate.get_by_sequence(runtime_id, execution_sequence)
        if transaction is None:
            raise RuntimeError("fault decorator could not resolve transaction sequence")
        self._raise_once_for_operation(operation, transaction.operation_kind)

    def commit(
        self, prepared: OnlyPreparedRuntimeTransaction, *, committed_at: OnlyTimestamp
    ) -> OnlyRuntimeTransactionCommitResult:
        self._raise_once_for_operation(OnlyTestRuntimePersistenceFault.COMMIT, prepared.operation_kind)
        result = self._delegate.commit(prepared, committed_at=committed_at)
        self._raise_once_for_operation(OnlyTestRuntimePersistenceFault.AFTER_COMMIT, prepared.operation_kind)
        return result

    def get_by_sequence(
        self, runtime_id: OnlyRuntimeId, execution_sequence: int
    ) -> OnlyCommittedRuntimeTransaction | None:
        self._raise_once(OnlyTestRuntimePersistenceFault.QUERY)
        return self._delegate.get_by_sequence(runtime_id, execution_sequence)

    def get_by_transaction_id(self, transaction_id: str) -> OnlyCommittedRuntimeTransaction | None:
        self._raise_once(OnlyTestRuntimePersistenceFault.QUERY)
        return self._delegate.get_by_transaction_id(transaction_id)

    def get_by_trade(
        self,
        runtime_id: OnlyRuntimeId,
        gateway_id: OnlyBrokerGatewayId,
        account_id: OnlyAccountId,
        trade_id: OnlyTradeId,
    ) -> OnlyCommittedRuntimeTransaction | None:
        self._raise_once(OnlyTestRuntimePersistenceFault.QUERY)
        return self._delegate.get_by_trade(runtime_id, gateway_id, account_id, trade_id)

    def get_by_update(
        self,
        runtime_id: OnlyRuntimeId,
        gateway_id: OnlyBrokerGatewayId,
        account_id: OnlyAccountId,
        update_id: OnlyBrokerUpdateId,
    ) -> OnlyCommittedRuntimeTransaction | None:
        self._raise_once(OnlyTestRuntimePersistenceFault.QUERY)
        return self._delegate.get_by_update(runtime_id, gateway_id, account_id, update_id)

    def get_by_fill_identity(
        self, runtime_id: OnlyRuntimeId, fill_identity: str
    ) -> OnlyCommittedRuntimeTransaction | None:
        self._raise_once(OnlyTestRuntimePersistenceFault.QUERY)
        return self._delegate.get_by_fill_identity(runtime_id, fill_identity)

    def transactions_for_order(
        self, runtime_id: OnlyRuntimeId, order_id: OnlyOrderId
    ) -> tuple[OnlyCommittedRuntimeTransaction, ...]:
        self._raise_once(OnlyTestRuntimePersistenceFault.QUERY)
        return self._delegate.transactions_for_order(runtime_id, order_id)

    def latest_fill_for_order(
        self, runtime_id: OnlyRuntimeId, order_id: OnlyOrderId
    ) -> OnlyCommittedRuntimeTransaction | None:
        self._raise_once(OnlyTestRuntimePersistenceFault.QUERY)
        return self._delegate.latest_fill_for_order(runtime_id, order_id)

    def records(
        self, runtime_id: OnlyRuntimeId | None = None, *, after_sequence: int = 0
    ) -> tuple[OnlyCommittedRuntimeTransaction, ...]:
        self._raise_once(OnlyTestRuntimePersistenceFault.QUERY)
        return self._delegate.records(runtime_id, after_sequence=after_sequence)

    def recovery_records(self, runtime_id: OnlyRuntimeId, *, after_sequence: int) -> tuple[object, ...]:
        self._raise_once(OnlyTestRuntimePersistenceFault.QUERY)
        return self._delegate.recovery_records(runtime_id, after_sequence=after_sequence)

    def get_recovery_record_by_update(
        self,
        runtime_id: OnlyRuntimeId,
        gateway_id: OnlyBrokerGatewayId,
        account_id: OnlyAccountId,
        update_id: OnlyBrokerUpdateId,
    ) -> object | None:
        self._raise_once(OnlyTestRuntimePersistenceFault.QUERY)
        return self._delegate.get_recovery_record_by_update(runtime_id, gateway_id, account_id, update_id)

    def ready_records(
        self, runtime_id: OnlyRuntimeId | None = None, *, after_sequence: int = 0
    ) -> tuple[OnlyCommittedRuntimeTransaction, ...]:
        self._raise_once(OnlyTestRuntimePersistenceFault.QUERY)
        return self._delegate.ready_records(runtime_id, after_sequence=after_sequence)

    def ready_count(self, runtime_id: OnlyRuntimeId | None = None) -> int:
        self._raise_once(OnlyTestRuntimePersistenceFault.QUERY)
        return self._delegate.ready_count(runtime_id)

    def mark_projection_ready(
        self,
        runtime_id: OnlyRuntimeId,
        execution_sequence: int,
        *,
        projected_at: OnlyTimestamp,
    ) -> None:
        self._raise_once_for_sequence(
            OnlyTestRuntimePersistenceFault.MARK_READY,
            runtime_id,
            execution_sequence,
        )
        self._delegate.mark_projection_ready(runtime_id, execution_sequence, projected_at=projected_at)

    def mark_projection_failed(
        self,
        runtime_id: OnlyRuntimeId,
        execution_sequence: int,
        *,
        failed_at: OnlyTimestamp,
        error: str,
    ) -> None:
        self._raise_once_for_sequence(
            OnlyTestRuntimePersistenceFault.MARK_FAILED,
            runtime_id,
            execution_sequence,
        )
        self._delegate.mark_projection_failed(runtime_id, execution_sequence, failed_at=failed_at, error=error)

    def unprojected(
        self, runtime_id: OnlyRuntimeId, *, after_sequence: int = 0
    ) -> tuple[OnlyCommittedRuntimeTransaction, ...]:
        self._raise_once(OnlyTestRuntimePersistenceFault.QUERY)
        return self._delegate.unprojected(runtime_id, after_sequence=after_sequence)

    def pending(self, runtime_id: OnlyRuntimeId, *, limit: int) -> tuple[OnlyRuntimeTransactionOutboxRecord, ...]:
        self._raise_once(OnlyTestRuntimePersistenceFault.QUERY)
        return self._delegate.pending(runtime_id, limit=limit)

    def begin_attempt(
        self, key: OnlyRuntimeTransactionOutboxKey, attempted_at: OnlyTimestamp
    ) -> OnlyRuntimeTransactionOutboxRecord:
        self._raise_once_for_sequence(
            OnlyTestRuntimePersistenceFault.OUTBOX_BEGIN_ATTEMPT,
            key.runtime_id,
            key.execution_sequence,
        )
        return self._delegate.begin_attempt(key, attempted_at)

    def mark_published(self, key: OnlyRuntimeTransactionOutboxKey, published_at: OnlyTimestamp) -> None:
        self._raise_once_for_sequence(
            OnlyTestRuntimePersistenceFault.OUTBOX_MARK_PUBLISHED,
            key.runtime_id,
            key.execution_sequence,
        )
        self._delegate.mark_published(key, published_at)

    def mark_failed(self, key: OnlyRuntimeTransactionOutboxKey, failed_at: OnlyTimestamp, error: str) -> None:
        self._raise_once_for_sequence(
            OnlyTestRuntimePersistenceFault.OUTBOX_MARK_FAILED,
            key.runtime_id,
            key.execution_sequence,
        )
        self._delegate.mark_failed(key, failed_at, error)

    def pending_count(self, runtime_id: OnlyRuntimeId) -> int:
        self._raise_once(OnlyTestRuntimePersistenceFault.QUERY)
        return self._delegate.pending_count(runtime_id)

    def outbox_records(self, runtime_id: OnlyRuntimeId) -> tuple[OnlyRuntimeTransactionOutboxRecord, ...]:
        self._raise_once(OnlyTestRuntimePersistenceFault.QUERY)
        return self._delegate.outbox_records(runtime_id)

    def write_checkpoint(self, checkpoint: OnlyRuntimeCheckpoint, *, retain_last: int) -> None:
        self._raise_once(OnlyTestRuntimePersistenceFault.CHECKPOINT_WRITE)
        self._delegate.write_checkpoint(checkpoint, retain_last=retain_last)

    def latest_checkpoint(self, runtime_id: OnlyRuntimeId) -> OnlyRuntimeCheckpoint | None:
        return self._delegate.latest_checkpoint(runtime_id)

    def checkpoints(self, runtime_id: OnlyRuntimeId) -> tuple[OnlyRuntimeCheckpoint, ...]:
        return self._delegate.checkpoints(runtime_id)

    def bind_participant_registry_fingerprint(self, fingerprint: str) -> None:
        self._delegate.bind_participant_registry_fingerprint(fingerprint)

    def close(self) -> None:
        self._delegate.close()


__all__ = [name for name in globals() if name.startswith("Only")]
