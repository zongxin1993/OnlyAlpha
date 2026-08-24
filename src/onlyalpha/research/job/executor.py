"""Deterministic verified reuse-or-execute Research Job orchestration."""

from __future__ import annotations

from typing import Protocol

from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition
from onlyalpha.research.calculation.errors import (
    OnlyResearchCalculationError,
    OnlyResearchCalculationResultStoreError,
)
from onlyalpha.research.calculation.execution import OnlyResearchCalculationExecution
from onlyalpha.research.calculation.execution_evidence import (
    OnlyResearchCalculationExecutionEvidence,
    OnlyResearchCalculationExecutionEvidenceStore,
)
from onlyalpha.research.calculation.result import OnlyResearchCalculationResult
from onlyalpha.research.calculation.result_ports import OnlyResearchCalculationResultStore

from .errors import OnlyResearchJobError, OnlyResearchJobPhase
from .outcome import OnlyResearchJobDisposition, OnlyResearchJobOutcome, OnlyResearchJobStatus
from .plan import OnlyResearchJobPlan


class _OnlyResearchCalculationExecutor(Protocol):
    def execute(
        self,
        snapshot_fingerprint: str,
        graph: OnlyCalculationGraphDefinition,
    ) -> OnlyResearchCalculationExecution: ...


class OnlyResearchJobExecutor:
    """Execute one exact Job without owning Dataset, Calculation, or Result state."""

    def __init__(
        self,
        calculation_executor: _OnlyResearchCalculationExecutor,
        result_store: OnlyResearchCalculationResultStore,
        execution_evidence_store: OnlyResearchCalculationExecutionEvidenceStore,
    ) -> None:
        self._calculation_executor = calculation_executor
        self._result_store = result_store
        self._execution_evidence_store = execution_evidence_store

    def execute(self, plan: OnlyResearchJobPlan) -> OnlyResearchJobOutcome:
        if not isinstance(plan, OnlyResearchJobPlan):
            raise OnlyResearchJobError(
                OnlyResearchJobPhase.PLAN_VALIDATION,
                "RESEARCH_JOB_INVALID",
                "execute requires an OnlyResearchJobPlan",
            )
        calculation_fingerprint = plan.calculation_fingerprint
        try:
            existing = self._result_store.load_verified(calculation_fingerprint)
        except OnlyResearchCalculationResultStoreError as exc:
            if exc.code != "RESULT_NOT_FOUND":
                raise _job_error(OnlyResearchJobPhase.RESULT_REUSE, exc) from exc
        except Exception as exc:
            raise OnlyResearchJobError(
                OnlyResearchJobPhase.RESULT_REUSE,
                "RESEARCH_JOB_RESULT_REUSE_FAILED",
                str(exc),
            ) from exc
        else:
            try:
                evidence = self._execution_evidence_store.require_for_result(existing)
            except OnlyResearchCalculationError as exc:
                raise _job_error(OnlyResearchJobPhase.RESULT_REUSE, exc) from exc
            return _outcome(
                plan,
                existing,
                evidence,
                OnlyResearchJobDisposition.REUSED,
                OnlyResearchJobPhase.RESULT_REUSE,
            )

        try:
            execution = self._calculation_executor.execute(
                plan.dataset_snapshot_fingerprint,
                plan.calculation_graph,
            )
        except OnlyResearchCalculationError as exc:
            phase = (
                OnlyResearchJobPhase.DATASET_VERIFICATION
                if exc.code == "RESEARCH_DATASET_VERIFICATION_FAILED"
                else OnlyResearchJobPhase.CALCULATION_EXECUTION
            )
            raise _job_error(phase, exc) from exc
        except Exception as exc:
            raise OnlyResearchJobError(
                OnlyResearchJobPhase.CALCULATION_EXECUTION,
                "RESEARCH_JOB_EXECUTION_FAILED",
                str(exc),
            ) from exc

        try:
            committed = self._result_store.commit(execution, plan.calculation_graph)
        except OnlyResearchCalculationResultStoreError as exc:
            raise _job_error(OnlyResearchJobPhase.RESULT_COMMIT, exc) from exc
        except Exception as exc:
            raise OnlyResearchJobError(
                OnlyResearchJobPhase.RESULT_COMMIT,
                "RESEARCH_JOB_RESULT_COMMIT_FAILED",
                str(exc),
            ) from exc
        try:
            evidence = self._execution_evidence_store.commit_execution(execution, committed)
        except OnlyResearchCalculationError as exc:
            raise _job_error(OnlyResearchJobPhase.RESULT_COMMIT, exc) from exc
        return _outcome(
            plan,
            committed,
            evidence,
            OnlyResearchJobDisposition.EXECUTED,
            OnlyResearchJobPhase.RESULT_COMMIT,
        )


def _job_error(phase: OnlyResearchJobPhase, error: OnlyResearchCalculationError) -> OnlyResearchJobError:
    return OnlyResearchJobError(phase, error.code, error.detail)


def _outcome(
    plan: OnlyResearchJobPlan,
    result: OnlyResearchCalculationResult,
    evidence: OnlyResearchCalculationExecutionEvidence,
    disposition: OnlyResearchJobDisposition,
    phase: OnlyResearchJobPhase,
) -> OnlyResearchJobOutcome:
    manifest = result.manifest
    if (
        manifest.calculation_fingerprint != plan.calculation_fingerprint
        or manifest.dataset_snapshot_fingerprint != plan.dataset_snapshot_fingerprint
        or manifest.calculation_graph_fingerprint != plan.calculation_graph.fingerprint
        or evidence.calculation_fingerprint != manifest.calculation_fingerprint
        or evidence.calculation_result_fingerprint != manifest.calculation_result_fingerprint
    ):
        raise OnlyResearchJobError(phase, "RESULT_INVALID", "Result authority does not match Research Job Plan")
    return OnlyResearchJobOutcome(
        OnlyResearchJobStatus.SUCCEEDED,
        disposition,
        manifest.calculation_fingerprint,
        manifest.calculation_result_fingerprint,
        evidence.evidence_fingerprint,
    )
