"""Finite Research Runtime orchestration over existing immutable authorities."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import TypeVar

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.core.errors import OnlyLifecycleError
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.research.artifact.materializer import OnlyResearchArtifactCandidate, OnlyResearchArtifactMaterializer
from onlyalpha.research.artifact.scientific_materializer import (
    OnlyResearchScientificArtifactCandidate,
    OnlyResearchScientificArtifactMaterializer,
)
from onlyalpha.research.artifact.scientific_store import OnlyParquetResearchScientificArtifactStore
from onlyalpha.research.artifact.store import OnlyParquetResearchArtifactStore
from onlyalpha.research.dataset import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.evaluation.execution import OnlyResearchStatisticsExecutor
from onlyalpha.research.evaluation.result import OnlyResearchStatisticsOutcome
from onlyalpha.research.job import OnlyResearchJobExecutor, OnlyResearchJobOutcome
from onlyalpha.research.result.assembler import OnlyResearchResultAssembler
from onlyalpha.research.result.result import OnlyResearchResultDisposition, OnlyResearchResultOutcome
from onlyalpha.research.result.result_store import OnlyJsonResearchResultStore
from onlyalpha.research.sweep.executor import OnlyResearchSweepExecutor
from onlyalpha.research.sweep.outcome import OnlyResearchSweepOutcome
from onlyalpha.runtime.result import OnlyRuntimeResultStatus

from .control import (
    OnlyResearchRuntimeBoundary,
    OnlyResearchRuntimeControlSignal,
    OnlyResearchRuntimeExecutionControl,
)
from .environment import OnlyResearchRuntimeEnvironmentIdentity
from .errors import OnlyResearchRuntimeError, OnlyResearchRuntimePhase
from .plan import OnlyResearchWorkloadPlan
from .result import OnlyResearchRuntimeResult

_T = TypeVar("_T")


class OnlyResearchRuntimeState(StrEnum):
    CREATED = "CREATED"
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CLOSED = "CLOSED"


class OnlyResearchRuntime:
    """Finite product coordinator; it owns no durable Research authority."""

    runtime_type = "RESEARCH"
    is_finite_runtime = True

    def __init__(
        self,
        runtime_id: OnlyRuntimeId,
        environment: OnlyResearchRuntimeEnvironmentIdentity,
        workload: OnlyResearchWorkloadPlan,
        dataset_store: OnlyParquetResearchDatasetSnapshotStore,
        job_executor: OnlyResearchJobExecutor,
        sweep_executor: OnlyResearchSweepExecutor,
        statistics_executor: OnlyResearchStatisticsExecutor,
        result_assembler: OnlyResearchResultAssembler,
        result_store: OnlyJsonResearchResultStore,
        artifact_materializer: OnlyResearchArtifactMaterializer | OnlyResearchScientificArtifactMaterializer,
        artifact_store: OnlyParquetResearchArtifactStore | OnlyParquetResearchScientificArtifactStore,
    ) -> None:
        self.runtime_id = runtime_id
        self.environment = environment
        self.workload = workload
        self._dataset_store = dataset_store
        self._job_executor = job_executor
        self._sweep_executor = sweep_executor
        self._statistics_executor = statistics_executor
        self._result_assembler = result_assembler
        self._result_store = result_store
        self._artifact_materializer = artifact_materializer
        self._artifact_store = artifact_store
        self.state = OnlyResearchRuntimeState.CREATED

    def initialize(self) -> None:
        if self.state is OnlyResearchRuntimeState.READY:
            return
        if self.state is not OnlyResearchRuntimeState.CREATED:
            raise OnlyLifecycleError(f"Research Runtime cannot initialize from {self.state}")
        self.state = OnlyResearchRuntimeState.READY

    def start(self) -> None:
        if self.state is not OnlyResearchRuntimeState.READY:
            raise OnlyLifecycleError(f"Research Runtime cannot start from {self.state}")
        self.state = OnlyResearchRuntimeState.RUNNING

    def run(self, control: OnlyResearchRuntimeExecutionControl | None = None) -> OnlyResearchRuntimeResult:
        if self.state is not OnlyResearchRuntimeState.RUNNING:
            raise OnlyLifecycleError(f"Research Runtime cannot run from {self.state}")
        direct: tuple[OnlyResearchJobOutcome, ...] = ()
        sweeps: tuple[OnlyResearchSweepOutcome, ...] = ()
        statistics: tuple[OnlyResearchStatisticsOutcome, ...] = ()
        try:
            self._checkpoint(control, OnlyResearchRuntimeBoundary.BEFORE_DATASET_VERIFICATION)
            self._invoke(
                OnlyResearchRuntimePhase.DATASET_VERIFICATION,
                lambda: self._dataset_store.load_verified_table(self.workload.dataset_snapshot_fingerprint),
            )
            direct_values: list[OnlyResearchJobOutcome] = []
            for job_plan in self.workload.direct_jobs:
                self._checkpoint(control, OnlyResearchRuntimeBoundary.BEFORE_DIRECT_JOB)
                try:
                    direct_values.append(self._job_executor.execute(job_plan))
                except Exception as exc:
                    raise self._error(OnlyResearchRuntimePhase.JOB_EXECUTION, exc) from exc
            direct = tuple(direct_values)
            sweep_values: list[OnlyResearchSweepOutcome] = []
            for sweep_plan in self.workload.sweeps:
                self._checkpoint(control, OnlyResearchRuntimeBoundary.BEFORE_SWEEP)
                try:
                    sweep_values.append(self._sweep_executor.execute(sweep_plan))
                except Exception as exc:
                    raise self._error(OnlyResearchRuntimePhase.SWEEP_EXECUTION, exc) from exc
            sweeps = tuple(sweep_values)
            statistics_values: list[OnlyResearchStatisticsOutcome] = []
            for statistics_plan in self.workload.statistics_plans:
                self._checkpoint(control, OnlyResearchRuntimeBoundary.BEFORE_STATISTICS)
                try:
                    statistics_values.append(self._statistics_executor.execute(statistics_plan))
                except Exception as exc:
                    raise self._error(OnlyResearchRuntimePhase.STATISTICS_EXECUTION, exc) from exc
            statistics = tuple(statistics_values)
            self._checkpoint(control, OnlyResearchRuntimeBoundary.BEFORE_RESULT_COMMIT)
            result_outcome = self._result(direct, sweeps, statistics)
            self._checkpoint(control, OnlyResearchRuntimeBoundary.BEFORE_ARTIFACT_COMMIT)
            candidate = self._invoke(
                OnlyResearchRuntimePhase.ARTIFACT_MATERIALIZATION,
                lambda: self._artifact_materializer.materialize(result_outcome.research_result_plan_fingerprint),
            )
            if isinstance(self._artifact_store, OnlyParquetResearchScientificArtifactStore):
                if not isinstance(candidate, OnlyResearchScientificArtifactCandidate):
                    raise ValueError("Scientific Artifact Store received an incompatible candidate")
                scientific_store = self._artifact_store
                scientific_candidate = candidate
                artifact_outcome = self._invoke(
                    OnlyResearchRuntimePhase.ARTIFACT_COMMIT,
                    lambda: scientific_store.commit(scientific_candidate),
                )
            else:
                if not isinstance(candidate, OnlyResearchArtifactCandidate):
                    raise ValueError("Statistics Artifact Store received an incompatible candidate")
                statistics_store = self._artifact_store
                statistics_candidate = candidate
                artifact_outcome = self._invoke(
                    OnlyResearchRuntimePhase.ARTIFACT_COMMIT,
                    lambda: statistics_store.commit(statistics_candidate),
                )
            research_result = self._invoke(
                OnlyResearchRuntimePhase.FINAL_VERIFICATION,
                lambda: self._result_store.load_verified(result_outcome.research_result_plan_fingerprint),
            )
            artifact = self._invoke(
                OnlyResearchRuntimePhase.FINAL_VERIFICATION,
                lambda: self._artifact_store.load_verified(result_outcome.research_result_fingerprint),
            )
            determinism = only_canonical_fingerprint(
                {
                    "dataset_snapshot_fingerprint": self.workload.dataset_snapshot_fingerprint,
                    "calculation_results": sorted(
                        [item.calculation_result_fingerprint for item in direct]
                        + [cell.calculation_result_fingerprint for sweep in sweeps for cell in sweep.cells]
                    ),
                    "statistics_results": sorted(item.statistics_result_fingerprint for item in statistics),
                    "research_result_fingerprint": research_result.manifest.research_result_fingerprint,
                    "artifact_content_fingerprint": artifact.manifest.artifact_content_fingerprint,
                }
            )
            self.state = OnlyResearchRuntimeState.COMPLETED
            execution_evidence = tuple(
                sorted(
                    {
                        *(item.calculation_execution_evidence_fingerprint for item in direct),
                        *(cell.calculation_execution_evidence_fingerprint for sweep in sweeps for cell in sweep.cells),
                    }
                )
            )
            return OnlyResearchRuntimeResult(
                self.runtime_id,
                OnlyRuntimeResultStatus.COMPLETED,
                self.workload.dataset_snapshot_fingerprint,
                direct,
                sweeps,
                statistics,
                result_outcome.research_result_plan_fingerprint,
                result_outcome.research_result_fingerprint,
                artifact_outcome.artifact_content_fingerprint,
                execution_evidence,
                determinism,
            )
        except OnlyResearchRuntimeControlSignal:
            self.state = OnlyResearchRuntimeState.FAILED
            raise
        except OnlyResearchRuntimeError as exc:
            self.state = OnlyResearchRuntimeState.FAILED
            return OnlyResearchRuntimeResult(
                self.runtime_id,
                OnlyRuntimeResultStatus.FAILED,
                self.workload.dataset_snapshot_fingerprint,
                direct,
                sweeps,
                statistics,
                self.workload.result_plan.fingerprint,
                phase=exc.phase,
                code=exc.code,
                detail=exc.detail,
            )

    def close(self) -> None:
        if self.state is OnlyResearchRuntimeState.CLOSED:
            return
        self.state = OnlyResearchRuntimeState.CLOSED

    def _result(
        self, direct: tuple[object, ...], sweeps: tuple[object, ...], statistics: tuple[object, ...]
    ) -> OnlyResearchResultOutcome:
        del direct, sweeps, statistics
        plan = self.workload.result_plan
        try:
            existing = self._result_store.load_verified(plan.fingerprint)
        except Exception as exc:
            if _error_code(exc) != "RESEARCH_RESULT_NOT_FOUND":
                raise self._error(OnlyResearchRuntimePhase.RESULT_COMMIT, exc) from exc
        else:
            return OnlyResearchResultOutcome(
                OnlyResearchResultDisposition.REUSED,
                existing.manifest.research_result_plan_fingerprint,
                existing.manifest.research_result_fingerprint,
            )
        candidate = self._invoke(
            OnlyResearchRuntimePhase.RESULT_ASSEMBLY, lambda: self._result_assembler.assemble(plan)
        )
        return self._invoke(OnlyResearchRuntimePhase.RESULT_COMMIT, lambda: self._result_store.commit(candidate))

    def _invoke(self, phase: OnlyResearchRuntimePhase, operation: Callable[[], _T]) -> _T:
        try:
            return operation()
        except Exception as exc:
            raise self._error(phase, exc) from exc

    @staticmethod
    def _checkpoint(control: OnlyResearchRuntimeExecutionControl | None, boundary: OnlyResearchRuntimeBoundary) -> None:
        if control is not None:
            control.checkpoint(boundary)

    @staticmethod
    def _error(phase: OnlyResearchRuntimePhase, exc: Exception) -> OnlyResearchRuntimeError:
        return OnlyResearchRuntimeError(phase, _error_code(exc), str(getattr(exc, "detail", str(exc))))


def _error_code(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code:
        return code
    value = str(exc).split(":", 1)[0].strip()
    return value if value and " " not in value else f"RESEARCH_{type(exc).__name__.upper()}"


__all__ = ["OnlyResearchRuntime", "OnlyResearchRuntimeState"]
