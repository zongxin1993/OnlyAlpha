"""Stable fail-closed errors for deterministic Research Sweep composition."""

from __future__ import annotations

from collections.abc import Mapping

from onlyalpha.calculation.definition import OnlyCalculationScalar
from onlyalpha.research.job import OnlyResearchJobPhase


class OnlyResearchSweepError(RuntimeError):
    def __init__(
        self,
        code: str,
        detail: str,
        *,
        ordinal: int | None = None,
        assignment: Mapping[str, OnlyCalculationScalar] | None = None,
        job_phase: OnlyResearchJobPhase | None = None,
        job_code: str | None = None,
    ) -> None:
        self.code = code
        self.detail = detail
        self.ordinal = ordinal
        self.assignment = dict(assignment or {})
        self.job_phase = job_phase
        self.job_code = job_code
        prefix = f"cell={ordinal}/" if ordinal is not None else ""
        job = f"/{job_phase.value}/{job_code}" if job_phase is not None and job_code is not None else ""
        super().__init__(f"{prefix}{code}{job}: {detail}")
