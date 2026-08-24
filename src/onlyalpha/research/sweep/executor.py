"""Canonical sequential Sweep execution through the existing Job authority."""

from __future__ import annotations

from onlyalpha.research.job import OnlyResearchJobDisposition, OnlyResearchJobError, OnlyResearchJobExecutor

from .errors import OnlyResearchSweepError
from .outcome import OnlyResearchSweepCellOutcome, OnlyResearchSweepOutcome
from .planning import OnlyResearchSweepPlan


class OnlyResearchSweepExecutor:
    def __init__(self, job_executor: OnlyResearchJobExecutor) -> None:
        if not isinstance(job_executor, OnlyResearchJobExecutor):
            raise TypeError("Sweep Executor requires OnlyResearchJobExecutor")
        self._job_executor = job_executor

    def execute(self, plan: OnlyResearchSweepPlan) -> OnlyResearchSweepOutcome:
        if not isinstance(plan, OnlyResearchSweepPlan):
            raise OnlyResearchSweepError("SWEEP_DEFINITION_INVALID", "execute requires a Sweep Plan")
        outcomes: list[OnlyResearchSweepCellOutcome] = []
        for cell in plan.cells:
            try:
                job_outcome = self._job_executor.execute(cell.job_plan)
            except OnlyResearchJobError as exc:
                raise OnlyResearchSweepError(
                    "SWEEP_JOB_FAILED",
                    exc.detail,
                    ordinal=cell.ordinal,
                    assignment=cell.assignment_by_key,
                    job_phase=exc.phase,
                    job_code=exc.code,
                ) from exc
            outcomes.append(
                OnlyResearchSweepCellOutcome(
                    cell.ordinal,
                    tuple((item.target, item.value) for item in cell.assignment),
                    job_outcome.calculation_fingerprint,
                    job_outcome.calculation_result_fingerprint,
                    job_outcome.calculation_execution_evidence_fingerprint,
                    job_outcome.disposition,
                )
            )
        cells = tuple(outcomes)
        return OnlyResearchSweepOutcome(
            len(cells),
            sum(cell.disposition is OnlyResearchJobDisposition.EXECUTED for cell in cells),
            sum(cell.disposition is OnlyResearchJobDisposition.REUSED for cell in cells),
            cells,
        )
