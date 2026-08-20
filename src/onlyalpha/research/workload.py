"""Application composition plan for one finite Research workload."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.research.evaluation.plan import OnlyResearchStatisticsPlan
from onlyalpha.research.job import OnlyResearchJobPlan
from onlyalpha.research.result.plan import OnlyResearchResultPlan
from onlyalpha.research.runtime_errors import OnlyResearchRuntimeError, OnlyResearchRuntimePhase
from onlyalpha.research.sweep.planning import OnlyResearchSweepPlan


@dataclass(frozen=True, slots=True)
class OnlyResearchWorkloadPlan:
    """Resolved composition only; this adds no Research semantic identity."""

    direct_jobs: tuple[OnlyResearchJobPlan, ...]
    sweeps: tuple[OnlyResearchSweepPlan, ...]
    statistics_plans: tuple[OnlyResearchStatisticsPlan, ...]
    result_plan: OnlyResearchResultPlan

    def __post_init__(self) -> None:
        try:
            self._validate()
        except OnlyResearchRuntimeError:
            raise
        except Exception as exc:
            raise OnlyResearchRuntimeError(
                OnlyResearchRuntimePhase.PLAN_VALIDATION,
                "RESEARCH_WORKLOAD_INVALID",
                str(exc),
            ) from exc

    @property
    def calculation_jobs(self) -> tuple[OnlyResearchJobPlan, ...]:
        return self.direct_jobs + tuple(cell.job_plan for sweep in self.sweeps for cell in sweep.cells)

    @property
    def dataset_snapshot_fingerprint(self) -> str:
        return self.calculation_jobs[0].dataset_snapshot_fingerprint

    def _validate(self) -> None:
        if not isinstance(self.direct_jobs, tuple) or any(
            not isinstance(item, OnlyResearchJobPlan) for item in self.direct_jobs
        ):
            raise ValueError("direct_jobs must contain Research Job Plans")
        if not isinstance(self.sweeps, tuple) or any(
            not isinstance(item, OnlyResearchSweepPlan) for item in self.sweeps
        ):
            raise ValueError("sweeps must contain Research Sweep Plans")
        if not isinstance(self.statistics_plans, tuple) or any(
            not isinstance(item, OnlyResearchStatisticsPlan) for item in self.statistics_plans
        ):
            raise ValueError("statistics_plans must contain Statistics Plans")
        if not isinstance(self.result_plan, OnlyResearchResultPlan):
            raise ValueError("result_plan must be a Research Result Plan")
        jobs = self.calculation_jobs
        if not jobs:
            self._fail("RESEARCH_WORKLOAD_EMPTY", "at least one Direct Job or Sweep cell is required")
        datasets = {item.dataset_snapshot_fingerprint for item in jobs}
        if len(datasets) != 1:
            self._fail("RESEARCH_WORKLOAD_DATASET_MISMATCH", "all calculation workloads must use one Dataset Snapshot")
        calculations = tuple(item.calculation_fingerprint for item in jobs)
        if len(calculations) != len(set(calculations)):
            self._fail("RESEARCH_WORKLOAD_DUPLICATE_CALCULATION", "Calculation ownership must be globally unique")
        closure = set(calculations)
        statistics = tuple(item.statistics_fingerprint for item in self.statistics_plans)
        if len(statistics) != len(set(statistics)):
            self._fail("RESEARCH_WORKLOAD_DUPLICATE_STATISTICS", "Statistics identities must be unique")
        for plan in self.statistics_plans:
            if plan.feature.calculation_fingerprint not in closure:
                self._fail("RESEARCH_WORKLOAD_UNKNOWN_FEATURE", plan.feature.calculation_fingerprint)
            if plan.target.calculation_fingerprint not in closure:
                self._fail("RESEARCH_WORKLOAD_UNKNOWN_TARGET", plan.target.calculation_fingerprint)
        if set(statistics) != set(self.result_plan.statistics_fingerprints):
            self._fail(
                "RESEARCH_WORKLOAD_RESULT_STATISTICS_MISMATCH",
                "Result Plan must reference exactly the supplied Statistics Plans",
            )
        if self.result_plan.schema_version == 2:
            if self.result_plan.dataset_snapshot_fingerprint != self.dataset_snapshot_fingerprint:
                self._fail("RESEARCH_WORKLOAD_RESULT_DATASET_MISMATCH", "Result Plan Dataset must match workload")
            if {item.calculation_fingerprint for item in self.result_plan.calculations} != closure:
                self._fail(
                    "RESEARCH_WORKLOAD_RESULT_CALCULATION_MISMATCH",
                    "Result Plan must reference exactly the supplied Calculation Jobs",
                )

    @staticmethod
    def _fail(code: str, detail: str) -> None:
        raise OnlyResearchRuntimeError(OnlyResearchRuntimePhase.PLAN_VALIDATION, code, detail)


__all__ = ["OnlyResearchWorkloadPlan"]
