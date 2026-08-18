"""Operational-neutral cooperative control boundary for finite Research execution."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol


class OnlyResearchRuntimeBoundary(StrEnum):
    BEFORE_DATASET_VERIFICATION = "BEFORE_DATASET_VERIFICATION"
    BEFORE_DIRECT_JOB = "BEFORE_DIRECT_JOB"
    BEFORE_SWEEP = "BEFORE_SWEEP"
    BEFORE_STATISTICS = "BEFORE_STATISTICS"
    BEFORE_RESULT_COMMIT = "BEFORE_RESULT_COMMIT"
    BEFORE_ARTIFACT_COMMIT = "BEFORE_ARTIFACT_COMMIT"


class OnlyResearchRuntimeControlSignal(RuntimeError):
    """A cooperative interruption that must escape semantic failure mapping."""


class OnlyResearchRuntimeCancellationRequested(OnlyResearchRuntimeControlSignal):
    pass


class OnlyResearchRuntimeOwnershipLost(OnlyResearchRuntimeControlSignal):
    pass


class OnlyResearchRuntimeExecutionControl(Protocol):
    def checkpoint(self, boundary: OnlyResearchRuntimeBoundary) -> None: ...


__all__ = [name for name in globals() if name.startswith("Only")]
