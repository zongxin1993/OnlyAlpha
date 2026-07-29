"""Rebuild Manager authority for projection-ready transactions after a checkpoint."""

from onlyalpha.execution.projection_applier import (
    OnlyExecutionProjectionApplier,
    OnlyExecutionProjectionBatchStatus,
)
from onlyalpha.execution.transaction import OnlyCommittedExecutionTransaction


class OnlyExecutionReadyTailRehydrationService:
    def __init__(self, projection_applier: OnlyExecutionProjectionApplier) -> None:
        self._projection_applier = projection_applier

    def rehydrate(self, transactions: tuple[OnlyCommittedExecutionTransaction, ...]) -> int:
        completed = 0
        for transaction in transactions:
            result = self._projection_applier.apply(transaction)
            if result.status is not OnlyExecutionProjectionBatchStatus.COMPLETED:
                raise RuntimeError(f"READY_TAIL_REHYDRATION_FAILED at {transaction.execution_sequence}: {result.error}")
            completed += 1
        return completed
