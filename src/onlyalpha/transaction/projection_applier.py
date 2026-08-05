"""Ordered execution projection application without event or store side effects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.transaction.applied_projection import OnlyRuntimeProjectionApplyContext
from onlyalpha.transaction.projection import (
    OnlyProjectionApplyResult,
    OnlyProjectionApplyStatus,
    OnlyRuntimeProjection,
    OnlyRuntimeProjectionComponent,
    OnlyRuntimeProjectionTarget,
)
from onlyalpha.transaction.transaction import OnlyCommittedRuntimeTransaction


class OnlyRuntimeProjectionBatchStatus(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class OnlyRuntimeProjectionBatchResult:
    execution_sequence: int
    applied: tuple[OnlyProjectionApplyResult, ...]
    idempotent: tuple[OnlyProjectionApplyResult, ...]
    recovered: tuple[OnlyProjectionApplyResult, ...]
    failed_projection: OnlyRuntimeProjection | None
    status: OnlyRuntimeProjectionBatchStatus
    error: str | None


class OnlyRuntimeProjectionApplier:
    def __init__(
        self,
        targets: Mapping[OnlyRuntimeProjectionComponent, OnlyRuntimeProjectionTarget],
    ) -> None:
        copied = dict(targets)
        for component, target in copied.items():
            if target.component is not component:
                raise ValueError("projection target mapping component mismatch")
        self._targets = copied

    def apply(self, transaction: OnlyCommittedRuntimeTransaction) -> OnlyRuntimeProjectionBatchResult:
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
                return OnlyRuntimeProjectionBatchResult(
                    transaction.execution_sequence,
                    tuple(applied),
                    tuple(idempotent),
                    tuple(recovered),
                    projection,
                    OnlyRuntimeProjectionBatchStatus.FAILED,
                    f"missing projection target for {identity.component.value}",
                )
            try:
                result = target.apply_execution_projection(
                    OnlyRuntimeProjectionApplyContext(
                        transaction.transaction_id,
                        transaction.execution_sequence,
                        transaction.fact,
                        projection,
                    )
                )
            except Exception as exc:
                return OnlyRuntimeProjectionBatchResult(
                    transaction.execution_sequence,
                    tuple(applied),
                    tuple(idempotent),
                    tuple(recovered),
                    projection,
                    OnlyRuntimeProjectionBatchStatus.FAILED,
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
            return OnlyRuntimeProjectionBatchResult(
                transaction.execution_sequence,
                tuple(applied),
                tuple(idempotent),
                tuple(recovered),
                projection,
                OnlyRuntimeProjectionBatchStatus.FAILED,
                result.status.value,
            )
        return OnlyRuntimeProjectionBatchResult(
            transaction.execution_sequence,
            tuple(applied),
            tuple(idempotent),
            tuple(recovered),
            None,
            OnlyRuntimeProjectionBatchStatus.COMPLETED,
            None,
        )


__all__ = [
    "OnlyRuntimeProjectionApplier",
    "OnlyRuntimeProjectionBatchResult",
    "OnlyRuntimeProjectionBatchStatus",
]
