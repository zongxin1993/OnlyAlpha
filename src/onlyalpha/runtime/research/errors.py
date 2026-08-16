"""Stable phase-aware failures for the finite Research Runtime product."""

from __future__ import annotations

from enum import StrEnum


class OnlyResearchRuntimePhase(StrEnum):
    PLAN_VALIDATION = "PLAN_VALIDATION"
    DATASET_VERIFICATION = "DATASET_VERIFICATION"
    JOB_EXECUTION = "JOB_EXECUTION"
    SWEEP_EXECUTION = "SWEEP_EXECUTION"
    STATISTICS_EXECUTION = "STATISTICS_EXECUTION"
    RESULT_ASSEMBLY = "RESULT_ASSEMBLY"
    RESULT_COMMIT = "RESULT_COMMIT"
    ARTIFACT_MATERIALIZATION = "ARTIFACT_MATERIALIZATION"
    ARTIFACT_COMMIT = "ARTIFACT_COMMIT"
    FINAL_VERIFICATION = "FINAL_VERIFICATION"


class OnlyResearchRuntimeError(RuntimeError):
    def __init__(self, phase: OnlyResearchRuntimePhase, code: str, detail: str) -> None:
        self.phase = phase
        self.code = code
        self.detail = detail
        super().__init__(f"{phase.value}: {code}: {detail}")


__all__ = ["OnlyResearchRuntimeError", "OnlyResearchRuntimePhase"]
