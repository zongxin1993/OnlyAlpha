"""Deterministic startup recovery for committed execution transaction tails."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.domain.identifiers import OnlyRuntimeId

from .commit_coordinator import (
    OnlyExecutionCommitCoordinationResult,
    OnlyExecutionCommitCoordinationStatus,
    OnlyExecutionCommitCoordinator,
)
from .projection import OnlyExecutionProjectionComponent


class OnlyExecutionRecoveryStatus(StrEnum):
    NO_WORK = "NO_WORK"
    RECOVERED = "RECOVERED"
    FAILED = "FAILED"
    SEQUENCE_BLOCKED = "SEQUENCE_BLOCKED"
    STORE_FAILURE = "STORE_FAILURE"


@dataclass(frozen=True, slots=True)
class OnlyExecutionRecoveryResult:
    runtime_id: OnlyRuntimeId
    status: OnlyExecutionRecoveryStatus
    attempted_transactions: int
    completed_transactions: int
    recovered_transactions: int
    idempotent_transactions: int
    failed_sequence: int | None
    failed_transaction_id: str | None
    blocked_sequence: int | None
    failure_component: OnlyExecutionProjectionComponent | None
    coordinator_status: OnlyExecutionCommitCoordinationStatus | None
    projection_error: str | None
    error: str | None

    @property
    def succeeded(self) -> bool:
        return self.status in {OnlyExecutionRecoveryStatus.NO_WORK, OnlyExecutionRecoveryStatus.RECOVERED}


class OnlyExecutionRecoveryService:
    """Translate Coordinator tail recovery into one stable Runtime lifecycle result."""

    def __init__(self, coordinator: OnlyExecutionCommitCoordinator) -> None:
        self._coordinator = coordinator

    def recover(
        self,
        runtime_id: OnlyRuntimeId,
        *,
        limit: int | None = None,
    ) -> OnlyExecutionRecoveryResult:
        results = self._coordinator.recover_unprojected(runtime_id, limit=limit)
        if not results:
            return OnlyExecutionRecoveryResult(
                runtime_id,
                OnlyExecutionRecoveryStatus.NO_WORK,
                0,
                0,
                0,
                0,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            )
        completed = tuple(result for result in results if self._completed(result))
        failed = next((result for result in results if not self._completed(result)), None)
        if failed is None:
            return OnlyExecutionRecoveryResult(
                runtime_id,
                OnlyExecutionRecoveryStatus.RECOVERED,
                len(results),
                len(completed),
                sum(bool(item.projection_result and item.projection_result.recovered) for item in completed),
                sum(
                    item.status is OnlyExecutionCommitCoordinationStatus.ALREADY_READY
                    or bool(item.projection_result and item.projection_result.idempotent)
                    for item in completed
                ),
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            )
        transaction = failed.transaction
        failed_sequence = None if transaction is None else transaction.execution_sequence
        status = self._failure_status(failed.status)
        return OnlyExecutionRecoveryResult(
            runtime_id,
            status,
            len(results),
            len(completed),
            sum(bool(item.projection_result and item.projection_result.recovered) for item in completed),
            sum(
                item.status is OnlyExecutionCommitCoordinationStatus.ALREADY_READY
                or bool(item.projection_result and item.projection_result.idempotent)
                for item in completed
            ),
            failed_sequence,
            None if transaction is None else transaction.transaction_id,
            failed_sequence if status is OnlyExecutionRecoveryStatus.SEQUENCE_BLOCKED else None,
            failed.failure_component,
            failed.status,
            None if transaction is None else transaction.projection_error,
            failed.error,
        )

    @staticmethod
    def _completed(result: OnlyExecutionCommitCoordinationResult) -> bool:
        return result.status in {
            OnlyExecutionCommitCoordinationStatus.COMMITTED_AND_PROJECTED,
            OnlyExecutionCommitCoordinationStatus.ALREADY_READY,
        }

    @staticmethod
    def _failure_status(status: OnlyExecutionCommitCoordinationStatus) -> OnlyExecutionRecoveryStatus:
        if status is OnlyExecutionCommitCoordinationStatus.SEQUENCE_BLOCKED:
            return OnlyExecutionRecoveryStatus.SEQUENCE_BLOCKED
        if status is OnlyExecutionCommitCoordinationStatus.STORE_FAILURE:
            return OnlyExecutionRecoveryStatus.STORE_FAILURE
        return OnlyExecutionRecoveryStatus.FAILED


__all__ = [
    "OnlyExecutionRecoveryResult",
    "OnlyExecutionRecoveryService",
    "OnlyExecutionRecoveryStatus",
]
