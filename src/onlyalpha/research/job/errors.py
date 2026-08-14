"""Phase-aware fail-closed Research Job errors."""

from __future__ import annotations

from enum import StrEnum


class OnlyResearchJobPhase(StrEnum):
    PLAN_VALIDATION = "PLAN_VALIDATION"
    DATASET_VERIFICATION = "DATASET_VERIFICATION"
    RESULT_REUSE = "RESULT_REUSE"
    CALCULATION_EXECUTION = "CALCULATION_EXECUTION"
    RESULT_COMMIT = "RESULT_COMMIT"


class OnlyResearchJobError(RuntimeError):
    def __init__(self, phase: OnlyResearchJobPhase, code: str, detail: str) -> None:
        self.phase = phase
        self.code = code
        self.detail = detail
        super().__init__(f"{phase.value}/{code}: {detail}")
