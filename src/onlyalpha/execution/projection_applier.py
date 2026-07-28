"""Ordered execution projection application without event or store side effects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from .applied_projection import OnlyExecutionProjectionApplyContext
from .projection import (
    OnlyExecutionProjection,
    OnlyExecutionProjectionComponent,
    OnlyExecutionProjectionTarget,
    OnlyProjectionApplyResult,
    OnlyProjectionApplyStatus,
)
from .transaction import OnlyCommittedExecutionTransaction


class OnlyExecutionProjectionBatchStatus(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class OnlyExecutionProjectionBatchResult:
    execution_sequence: int
    applied: tuple[OnlyProjectionApplyResult, ...]
    idempotent: tuple[OnlyProjectionApplyResult, ...]
    recovered: tuple[OnlyProjectionApplyResult, ...]
    failed_projection: OnlyExecutionProjection | None
    status: OnlyExecutionProjectionBatchStatus
    error: str | None


class OnlyExecutionProjectionApplier:
    def __init__(
        self,
        targets: Mapping[OnlyExecutionProjectionComponent, OnlyExecutionProjectionTarget],
    ) -> None:
        copied = dict(targets)
        for component, target in copied.items():
            if target.component is not component:
                raise ValueError("projection target mapping component mismatch")
        self._targets = copied

    def apply(self, transaction: OnlyCommittedExecutionTransaction) -> OnlyExecutionProjectionBatchResult:
        ordered = tuple(sorted(transaction.projections, key=lambda item: item.identity.projection_sequence))
        expected = tuple(range(1, len(ordered) + 1))
        if tuple(item.identity.projection_sequence for item in ordered) != expected:
            raise ValueError("transaction projection sequence is not contiguous")
        applied: list[OnlyProjectionApplyResult] = []
        idempotent: list[OnlyProjectionApplyResult] = []
        recovered: list[OnlyProjectionApplyResult] = []
        for projection in ordered:
            identity = projection.identity
            target = self._targets.get(identity.component)
            if target is None:
                return OnlyExecutionProjectionBatchResult(
                    transaction.execution_sequence,
                    tuple(applied),
                    tuple(idempotent),
                    tuple(recovered),
                    projection,
                    OnlyExecutionProjectionBatchStatus.FAILED,
                    f"missing projection target for {identity.component.value}",
                )
            try:
                result = target.apply_execution_projection(
                    OnlyExecutionProjectionApplyContext(
                        transaction.transaction_id,
                        transaction.execution_sequence,
                        transaction.fact,
                        projection,
                    )
                )
            except Exception as exc:
                return OnlyExecutionProjectionBatchResult(
                    transaction.execution_sequence,
                    tuple(applied),
                    tuple(idempotent),
                    tuple(recovered),
                    projection,
                    OnlyExecutionProjectionBatchStatus.FAILED,
                    f"{type(exc).__name__}: {exc}",
                )
            if result.status is OnlyProjectionApplyStatus.APPLIED:
                applied.append(result)
                continue
            if result.status is OnlyProjectionApplyStatus.IDEMPOTENT:
                idempotent.append(result)
                continue
            if result.status is OnlyProjectionApplyStatus.RECOVERED:
                recovered.append(result)
                continue
            return OnlyExecutionProjectionBatchResult(
                transaction.execution_sequence,
                tuple(applied),
                tuple(idempotent),
                tuple(recovered),
                projection,
                OnlyExecutionProjectionBatchStatus.FAILED,
                result.status.value,
            )
        return OnlyExecutionProjectionBatchResult(
            transaction.execution_sequence,
            tuple(applied),
            tuple(idempotent),
            tuple(recovered),
            None,
            OnlyExecutionProjectionBatchStatus.COMPLETED,
            None,
        )


__all__ = [
    "OnlyExecutionProjectionApplier",
    "OnlyExecutionProjectionBatchResult",
    "OnlyExecutionProjectionBatchStatus",
]
