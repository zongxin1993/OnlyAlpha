"""Durable commit, ordered projection, and recovery coordination."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp

from .delivery import OnlyExecutionEventDeliveryIntent, OnlyExecutionEventDeliveryMode
from .projection import OnlyExecutionProjectionComponent
from .projection_applier import (
    OnlyExecutionProjectionApplier,
    OnlyExecutionProjectionBatchResult,
    OnlyExecutionProjectionBatchStatus,
)
from .transaction import OnlyCommittedExecutionTransaction, OnlyPreparedExecutionTransaction
from .transaction_store import (
    OnlyExecutionProjectionStatePort,
    OnlyExecutionTransactionCommitPort,
    OnlyExecutionTransactionConflict,
    OnlyExecutionTransactionQueryPort,
    OnlyExecutionTransactionStoreError,
)


class OnlyExecutionCommitCoordinationStatus(StrEnum):
    COMMITTED_AND_PROJECTED = "COMMITTED_AND_PROJECTED"
    ALREADY_READY = "ALREADY_READY"
    PROJECTION_FAILED = "PROJECTION_FAILED"
    SEQUENCE_BLOCKED = "SEQUENCE_BLOCKED"
    TRANSACTION_CONFLICT = "TRANSACTION_CONFLICT"
    STORE_FAILURE = "STORE_FAILURE"
    INVALID_TRANSACTION = "INVALID_TRANSACTION"


@dataclass(frozen=True, slots=True)
class OnlyExecutionCommitCoordinationResult:
    transaction: OnlyCommittedExecutionTransaction | None
    transaction_inserted: bool
    status: OnlyExecutionCommitCoordinationStatus
    projection_result: OnlyExecutionProjectionBatchResult | None
    delivery_intent: OnlyExecutionEventDeliveryIntent
    failure_component: OnlyExecutionProjectionComponent | None
    error: str | None


class OnlyExecutionCommitCoordinator:
    """The sole Trade transaction coordinator for one Runtime product path."""

    def __init__(
        self,
        *,
        commit_port: OnlyExecutionTransactionCommitPort,
        query_port: OnlyExecutionTransactionQueryPort,
        projection_state_port: OnlyExecutionProjectionStatePort,
        projection_applier: OnlyExecutionProjectionApplier,
        now: Callable[[], OnlyTimestamp],
    ) -> None:
        self._commit_port = commit_port
        self._query_port = query_port
        self._projection_state_port = projection_state_port
        self._projection_applier = projection_applier
        self._now = now

    def commit(
        self,
        prepared: OnlyPreparedExecutionTransaction,
        *,
        committed_at: OnlyTimestamp,
        projected_at: OnlyTimestamp,
    ) -> OnlyExecutionCommitCoordinationResult:
        invalid = self._validate_prepared(prepared)
        if invalid is not None:
            return self._result(OnlyExecutionCommitCoordinationStatus.INVALID_TRANSACTION, error=invalid)
        try:
            committed = self._commit_port.commit(prepared, committed_at=committed_at)
        except OnlyExecutionTransactionConflict as exc:
            return self._result(OnlyExecutionCommitCoordinationStatus.TRANSACTION_CONFLICT, error=str(exc))
        except (OnlyExecutionTransactionStoreError, OSError, RuntimeError, ValueError) as exc:
            return self._result(
                OnlyExecutionCommitCoordinationStatus.STORE_FAILURE,
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
    ) -> tuple[OnlyExecutionCommitCoordinationResult, ...]:
        if limit is not None and limit <= 0:
            raise ValueError("execution recovery limit must be positive")
        try:
            transactions = self._projection_state_port.unprojected(runtime_id)
        except (OnlyExecutionTransactionStoreError, OSError, RuntimeError, ValueError) as exc:
            return (
                self._result(
                    OnlyExecutionCommitCoordinationStatus.STORE_FAILURE,
                    error=f"{type(exc).__name__}: {exc}",
                ),
            )
        ordered = tuple(sorted(transactions, key=lambda item: item.execution_sequence))
        selected = ordered if limit is None else ordered[:limit]
        results: list[OnlyExecutionCommitCoordinationResult] = []
        for transaction in selected:
            result = self._coordinate(
                transaction,
                transaction_inserted=False,
                projected_at=self._now(),
            )
            results.append(result)
            if result.status not in {
                OnlyExecutionCommitCoordinationStatus.COMMITTED_AND_PROJECTED,
                OnlyExecutionCommitCoordinationStatus.ALREADY_READY,
            }:
                break
        return tuple(results)

    def _coordinate(
        self,
        transaction: OnlyCommittedExecutionTransaction,
        *,
        transaction_inserted: bool,
        projected_at: OnlyTimestamp,
    ) -> OnlyExecutionCommitCoordinationResult:
        try:
            current = self._query_port.get_by_sequence(transaction.runtime_id, transaction.execution_sequence)
        except (OnlyExecutionTransactionStoreError, OSError, RuntimeError, ValueError) as exc:
            return self._result(
                OnlyExecutionCommitCoordinationStatus.STORE_FAILURE,
                transaction=transaction,
                transaction_inserted=transaction_inserted,
                error=f"{type(exc).__name__}: {exc}",
            )
        if current is None:
            return self._result(
                OnlyExecutionCommitCoordinationStatus.STORE_FAILURE,
                transaction=transaction,
                transaction_inserted=transaction_inserted,
                error="committed transaction cannot be queried by its assigned sequence",
            )
        if current.projection_ready:
            return self._result(
                OnlyExecutionCommitCoordinationStatus.ALREADY_READY,
                transaction=current,
                transaction_inserted=transaction_inserted,
                delivery=True,
            )
        if current.execution_sequence > 1:
            try:
                previous = self._query_port.get_by_sequence(current.runtime_id, current.execution_sequence - 1)
            except (OnlyExecutionTransactionStoreError, OSError, RuntimeError, ValueError) as exc:
                return self._result(
                    OnlyExecutionCommitCoordinationStatus.STORE_FAILURE,
                    transaction=current,
                    transaction_inserted=transaction_inserted,
                    error=f"{type(exc).__name__}: {exc}",
                )
            if previous is None or not previous.projection_ready:
                return self._result(
                    OnlyExecutionCommitCoordinationStatus.SEQUENCE_BLOCKED,
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
        if projection_result.status is OnlyExecutionProjectionBatchStatus.FAILED:
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
        except (OnlyExecutionTransactionStoreError, OSError, RuntimeError, ValueError) as exc:
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
            OnlyExecutionCommitCoordinationStatus.COMMITTED_AND_PROJECTED,
            transaction=ready,
            transaction_inserted=transaction_inserted,
            projection_result=projection_result,
            delivery=True,
        )

    def _projection_failure(
        self,
        transaction: OnlyCommittedExecutionTransaction,
        *,
        transaction_inserted: bool,
        projected_at: OnlyTimestamp,
        projection_result: OnlyExecutionProjectionBatchResult | None,
        error: str,
        failure_component: OnlyExecutionProjectionComponent | None = None,
    ) -> OnlyExecutionCommitCoordinationResult:
        try:
            self._projection_state_port.mark_projection_failed(
                transaction.runtime_id,
                transaction.execution_sequence,
                failed_at=projected_at,
                error=error,
            )
        except (OnlyExecutionTransactionStoreError, OSError, RuntimeError, ValueError) as exc:
            return self._result(
                OnlyExecutionCommitCoordinationStatus.STORE_FAILURE,
                transaction=transaction,
                transaction_inserted=transaction_inserted,
                projection_result=projection_result,
                failure_component=failure_component,
                error=f"{error}; mark projection failed failed: {type(exc).__name__}: {exc}",
            )
        return self._result(
            OnlyExecutionCommitCoordinationStatus.PROJECTION_FAILED,
            transaction=transaction,
            transaction_inserted=transaction_inserted,
            projection_result=projection_result,
            failure_component=failure_component,
            error=error,
        )

    def _projection_state_failure(
        self,
        transaction: OnlyCommittedExecutionTransaction,
        *,
        transaction_inserted: bool,
        projected_at: OnlyTimestamp,
        projection_result: OnlyExecutionProjectionBatchResult,
        error: str,
    ) -> OnlyExecutionCommitCoordinationResult:
        try:
            self._projection_state_port.mark_projection_failed(
                transaction.runtime_id,
                transaction.execution_sequence,
                failed_at=projected_at,
                error=error,
            )
        except (OnlyExecutionTransactionStoreError, OSError, RuntimeError, ValueError) as exc:
            error = f"{error}; mark projection failed failed: {type(exc).__name__}: {exc}"
        return self._result(
            OnlyExecutionCommitCoordinationStatus.STORE_FAILURE,
            transaction=transaction,
            transaction_inserted=transaction_inserted,
            projection_result=projection_result,
            error=error,
        )

    @staticmethod
    def _validate_prepared(prepared: OnlyPreparedExecutionTransaction) -> str | None:
        if not prepared.transaction_id.strip():
            return "prepared transaction identity is empty"
        if not prepared.authority_hash or not prepared.payload_hash:
            return "prepared transaction hashes are missing"
        if not prepared.projections:
            return "prepared transaction has no projections"
        return None

    @staticmethod
    def _result(
        status: OnlyExecutionCommitCoordinationStatus,
        *,
        transaction: OnlyCommittedExecutionTransaction | None = None,
        transaction_inserted: bool = False,
        projection_result: OnlyExecutionProjectionBatchResult | None = None,
        delivery: bool = False,
        failure_component: OnlyExecutionProjectionComponent | None = None,
        error: str | None = None,
    ) -> OnlyExecutionCommitCoordinationResult:
        intent = (
            OnlyExecutionEventDeliveryIntent(
                OnlyExecutionEventDeliveryMode.DURABLE_OUTBOX,
                committed_execution_sequence=transaction.execution_sequence,
            )
            if delivery and transaction is not None
            else OnlyExecutionEventDeliveryIntent(OnlyExecutionEventDeliveryMode.NONE)
        )
        return OnlyExecutionCommitCoordinationResult(
            transaction,
            transaction_inserted,
            status,
            projection_result,
            intent,
            failure_component,
            error,
        )


__all__ = [
    "OnlyExecutionCommitCoordinationResult",
    "OnlyExecutionCommitCoordinationStatus",
    "OnlyExecutionCommitCoordinator",
]
