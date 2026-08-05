"""Durable commit, ordered projection, and recovery coordination."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.transaction.delivery import OnlyExecutionEventDeliveryIntent, OnlyExecutionEventDeliveryMode
from onlyalpha.transaction.persistence_ports import (
    OnlyRuntimePersistenceStoreError,
    OnlyRuntimeProjectionStatePort,
    OnlyRuntimeTransactionCommitPort,
    OnlyRuntimeTransactionConflict,
    OnlyRuntimeTransactionQueryPort,
)
from onlyalpha.transaction.projection import OnlyRuntimeProjectionComponent
from onlyalpha.transaction.projection_applier import (
    OnlyRuntimeProjectionApplier,
    OnlyRuntimeProjectionBatchResult,
    OnlyRuntimeProjectionBatchStatus,
)
from onlyalpha.transaction.transaction import OnlyCommittedRuntimeTransaction, OnlyPreparedRuntimeTransaction


class OnlyRuntimeTransactionCoordinationStatus(StrEnum):
    COMMITTED_AND_PROJECTED = "COMMITTED_AND_PROJECTED"
    ALREADY_READY = "ALREADY_READY"
    PROJECTION_FAILED = "PROJECTION_FAILED"
    SEQUENCE_BLOCKED = "SEQUENCE_BLOCKED"
    TRANSACTION_CONFLICT = "TRANSACTION_CONFLICT"
    STORE_FAILURE = "STORE_FAILURE"
    INVALID_TRANSACTION = "INVALID_TRANSACTION"


@dataclass(frozen=True, slots=True)
class OnlyRuntimeTransactionCoordinationResult:
    transaction: OnlyCommittedRuntimeTransaction | None
    transaction_inserted: bool
    status: OnlyRuntimeTransactionCoordinationStatus
    projection_result: OnlyRuntimeProjectionBatchResult | None
    delivery_intent: OnlyExecutionEventDeliveryIntent
    failure_component: OnlyRuntimeProjectionComponent | None
    error: str | None


class OnlyRuntimeTransactionCoordinator:
    """The sole Trade transaction coordinator for one Runtime product path."""

    def __init__(
        self,
        *,
        commit_port: OnlyRuntimeTransactionCommitPort,
        query_port: OnlyRuntimeTransactionQueryPort,
        projection_state_port: OnlyRuntimeProjectionStatePort,
        projection_applier: OnlyRuntimeProjectionApplier,
        now: Callable[[], OnlyTimestamp],
    ) -> None:
        self._commit_port = commit_port
        self._query_port = query_port
        self._projection_state_port = projection_state_port
        self._projection_applier = projection_applier
        self._now = now

    def commit(
        self,
        prepared: OnlyPreparedRuntimeTransaction,
        *,
        committed_at: OnlyTimestamp,
        projected_at: OnlyTimestamp,
    ) -> OnlyRuntimeTransactionCoordinationResult:
        invalid = self._validate_prepared(prepared)
        if invalid is not None:
            return self._result(OnlyRuntimeTransactionCoordinationStatus.INVALID_TRANSACTION, error=invalid)
        try:
            committed = self._commit_port.commit(prepared, committed_at=committed_at)
        except OnlyRuntimeTransactionConflict as exc:
            return self._result(OnlyRuntimeTransactionCoordinationStatus.TRANSACTION_CONFLICT, error=str(exc))
        except (OnlyRuntimePersistenceStoreError, OSError, RuntimeError, ValueError) as exc:
            return self._result(
                OnlyRuntimeTransactionCoordinationStatus.STORE_FAILURE,
                error=f"{type(exc).__name__}: {exc}",
            )
        return self._coordinate(
            committed.transaction,
            transaction_inserted=committed.inserted,
            projected_at=projected_at,
        )

    def recover_unprojected(
        self,
        runtime_id: OnlyRuntimeId,
        *,
        limit: int | None = None,
    ) -> tuple[OnlyRuntimeTransactionCoordinationResult, ...]:
        if limit is not None and limit <= 0:
            raise ValueError("execution recovery limit must be positive")
        try:
            transactions = self._projection_state_port.unprojected(runtime_id)
        except (OnlyRuntimePersistenceStoreError, OSError, RuntimeError, ValueError) as exc:
            return (
                self._result(
                    OnlyRuntimeTransactionCoordinationStatus.STORE_FAILURE,
                    error=f"{type(exc).__name__}: {exc}",
                ),
            )
        ordered = tuple(sorted(transactions, key=lambda item: item.execution_sequence))
        selected = ordered if limit is None else ordered[:limit]
        results: list[OnlyRuntimeTransactionCoordinationResult] = []
        for transaction in selected:
            result = self._coordinate(
                transaction,
                transaction_inserted=False,
                projected_at=self._now(),
            )
            results.append(result)
            if result.status not in {
                OnlyRuntimeTransactionCoordinationStatus.COMMITTED_AND_PROJECTED,
                OnlyRuntimeTransactionCoordinationStatus.ALREADY_READY,
            }:
                break
        return tuple(results)

    def rehydrate_existing(
        self,
        transaction: OnlyCommittedRuntimeTransaction,
        *,
        projected_at: OnlyTimestamp,
    ) -> OnlyRuntimeTransactionCoordinationResult:
        """Reapply a durable Ready transaction without changing Store or Outbox state."""

        try:
            current = self._query_port.get_by_sequence(transaction.runtime_id, transaction.execution_sequence)
            if current is None or current != transaction or not current.projection_ready:
                return self._result(
                    OnlyRuntimeTransactionCoordinationStatus.TRANSACTION_CONFLICT,
                    transaction=transaction,
                    error="recovery Ready transaction does not match durable Store authority",
                )
            projection_result = self._projection_applier.apply(current)
        except (AssertionError, OnlyRuntimePersistenceStoreError, OSError, RuntimeError, TypeError, ValueError) as exc:
            return self._result(
                OnlyRuntimeTransactionCoordinationStatus.PROJECTION_FAILED,
                transaction=transaction,
                error=f"{type(exc).__name__}: {exc}",
            )
        if projection_result.status is OnlyRuntimeProjectionBatchStatus.FAILED:
            failed = projection_result.failed_projection
            return self._result(
                OnlyRuntimeTransactionCoordinationStatus.PROJECTION_FAILED,
                transaction=current,
                projection_result=projection_result,
                failure_component=None if failed is None else failed.identity.component,
                error=projection_result.error or "recovery projection batch failed",
            )
        return self._result(
            OnlyRuntimeTransactionCoordinationStatus.COMMITTED_AND_PROJECTED,
            transaction=current,
            projection_result=projection_result,
        )

    def recover_existing(
        self,
        transaction: OnlyCommittedRuntimeTransaction,
        *,
        projected_at: OnlyTimestamp,
    ) -> OnlyRuntimeTransactionCoordinationResult:
        """Forward-recover one durable unprojected transaction at its causal update point."""

        return self._coordinate(transaction, transaction_inserted=False, projected_at=projected_at)

    def _coordinate(
        self,
        transaction: OnlyCommittedRuntimeTransaction,
        *,
        transaction_inserted: bool,
        projected_at: OnlyTimestamp,
    ) -> OnlyRuntimeTransactionCoordinationResult:
        try:
            current = self._query_port.get_by_sequence(transaction.runtime_id, transaction.execution_sequence)
        except (OnlyRuntimePersistenceStoreError, OSError, RuntimeError, ValueError) as exc:
            return self._result(
                OnlyRuntimeTransactionCoordinationStatus.STORE_FAILURE,
                transaction=transaction,
                transaction_inserted=transaction_inserted,
                error=f"{type(exc).__name__}: {exc}",
            )
        if current is None:
            return self._result(
                OnlyRuntimeTransactionCoordinationStatus.STORE_FAILURE,
                transaction=transaction,
                transaction_inserted=transaction_inserted,
                error="committed transaction cannot be queried by its assigned sequence",
            )
        if current.projection_ready:
            return self._result(
                OnlyRuntimeTransactionCoordinationStatus.ALREADY_READY,
                transaction=current,
                transaction_inserted=transaction_inserted,
                delivery=True,
            )
        if current.execution_sequence > 1:
            try:
                previous = self._query_port.get_by_sequence(current.runtime_id, current.execution_sequence - 1)
            except (OnlyRuntimePersistenceStoreError, OSError, RuntimeError, ValueError) as exc:
                return self._result(
                    OnlyRuntimeTransactionCoordinationStatus.STORE_FAILURE,
                    transaction=current,
                    transaction_inserted=transaction_inserted,
                    error=f"{type(exc).__name__}: {exc}",
                )
            if previous is None or not previous.projection_ready:
                return self._result(
                    OnlyRuntimeTransactionCoordinationStatus.SEQUENCE_BLOCKED,
                    transaction=current,
                    transaction_inserted=transaction_inserted,
                    error=f"execution sequence {current.execution_sequence - 1} is not projection-ready",
                )
        try:
            projection_result = self._projection_applier.apply(current)
        except (AssertionError, RuntimeError, TypeError, ValueError) as exc:
            error = f"{type(exc).__name__}: {exc}"
            return self._projection_failure(
                current,
                transaction_inserted=transaction_inserted,
                projected_at=projected_at,
                projection_result=None,
                error=error,
            )
        if projection_result.status is OnlyRuntimeProjectionBatchStatus.FAILED:
            failed = projection_result.failed_projection
            return self._projection_failure(
                current,
                transaction_inserted=transaction_inserted,
                projected_at=projected_at,
                projection_result=projection_result,
                failure_component=None if failed is None else failed.identity.component,
                error=projection_result.error or "projection batch failed",
            )
        try:
            self._projection_state_port.mark_projection_ready(
                current.runtime_id,
                current.execution_sequence,
                projected_at=projected_at,
            )
            ready = self._query_port.get_by_sequence(current.runtime_id, current.execution_sequence)
        except (OnlyRuntimePersistenceStoreError, OSError, RuntimeError, ValueError) as exc:
            error = f"mark projection ready failed: {type(exc).__name__}: {exc}"
            return self._projection_state_failure(
                current,
                transaction_inserted=transaction_inserted,
                projected_at=projected_at,
                projection_result=projection_result,
                error=error,
            )
        if ready is None or not ready.projection_ready:
            return self._projection_state_failure(
                current,
                transaction_inserted=transaction_inserted,
                projected_at=projected_at,
                projection_result=projection_result,
                error="projection-ready state was not durably observable after marking",
            )
        return self._result(
            OnlyRuntimeTransactionCoordinationStatus.COMMITTED_AND_PROJECTED,
            transaction=ready,
            transaction_inserted=transaction_inserted,
            projection_result=projection_result,
            delivery=True,
        )

    def _projection_failure(
        self,
        transaction: OnlyCommittedRuntimeTransaction,
        *,
        transaction_inserted: bool,
        projected_at: OnlyTimestamp,
        projection_result: OnlyRuntimeProjectionBatchResult | None,
        error: str,
        failure_component: OnlyRuntimeProjectionComponent | None = None,
    ) -> OnlyRuntimeTransactionCoordinationResult:
        try:
            self._projection_state_port.mark_projection_failed(
                transaction.runtime_id,
                transaction.execution_sequence,
                failed_at=projected_at,
                error=error,
            )
        except (OnlyRuntimePersistenceStoreError, OSError, RuntimeError, ValueError) as exc:
            return self._result(
                OnlyRuntimeTransactionCoordinationStatus.STORE_FAILURE,
                transaction=transaction,
                transaction_inserted=transaction_inserted,
                projection_result=projection_result,
                failure_component=failure_component,
                error=f"{error}; mark projection failed failed: {type(exc).__name__}: {exc}",
            )
        return self._result(
            OnlyRuntimeTransactionCoordinationStatus.PROJECTION_FAILED,
            transaction=transaction,
            transaction_inserted=transaction_inserted,
            projection_result=projection_result,
            failure_component=failure_component,
            error=error,
        )

    def _projection_state_failure(
        self,
        transaction: OnlyCommittedRuntimeTransaction,
        *,
        transaction_inserted: bool,
        projected_at: OnlyTimestamp,
        projection_result: OnlyRuntimeProjectionBatchResult,
        error: str,
    ) -> OnlyRuntimeTransactionCoordinationResult:
        try:
            self._projection_state_port.mark_projection_failed(
                transaction.runtime_id,
                transaction.execution_sequence,
                failed_at=projected_at,
                error=error,
            )
        except (OnlyRuntimePersistenceStoreError, OSError, RuntimeError, ValueError) as exc:
            error = f"{error}; mark projection failed failed: {type(exc).__name__}: {exc}"
        return self._result(
            OnlyRuntimeTransactionCoordinationStatus.STORE_FAILURE,
            transaction=transaction,
            transaction_inserted=transaction_inserted,
            projection_result=projection_result,
            error=error,
        )

    @staticmethod
    def _validate_prepared(prepared: OnlyPreparedRuntimeTransaction) -> str | None:
        if not prepared.transaction_id.strip():
            return "prepared transaction identity is empty"
        if not prepared.authority_hash or not prepared.payload_hash:
            return "prepared transaction hashes are missing"
        if not prepared.projections:
            return "prepared transaction has no projections"
        return None

    @staticmethod
    def _result(
        status: OnlyRuntimeTransactionCoordinationStatus,
        *,
        transaction: OnlyCommittedRuntimeTransaction | None = None,
        transaction_inserted: bool = False,
        projection_result: OnlyRuntimeProjectionBatchResult | None = None,
        delivery: bool = False,
        failure_component: OnlyRuntimeProjectionComponent | None = None,
        error: str | None = None,
    ) -> OnlyRuntimeTransactionCoordinationResult:
        intent = (
            OnlyExecutionEventDeliveryIntent(
                OnlyExecutionEventDeliveryMode.DURABLE_OUTBOX,
                committed_execution_sequence=transaction.execution_sequence,
            )
            if delivery and transaction is not None
            else OnlyExecutionEventDeliveryIntent(OnlyExecutionEventDeliveryMode.NONE)
        )
        return OnlyRuntimeTransactionCoordinationResult(
            transaction,
            transaction_inserted,
            status,
            projection_result,
            intent,
            failure_component,
            error,
        )


__all__ = [
    "OnlyRuntimeTransactionCoordinationResult",
    "OnlyRuntimeTransactionCoordinationStatus",
    "OnlyRuntimeTransactionCoordinator",
]
