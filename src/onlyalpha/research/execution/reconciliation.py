"""Read-only semantic inspection and cancellation-recovery reconciliation."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from onlyalpha.research.artifact.model import OnlyResearchArtifact
from onlyalpha.research.calculation.execution_evidence import OnlyResearchCalculationExecutionEvidence
from onlyalpha.research.calculation.result import OnlyResearchCalculationResult
from onlyalpha.research.result.result import OnlyResearchResult
from onlyalpha.research.run import (
    OnlyResearchRun,
    OnlyResearchRunFailure,
    OnlyResearchRunFailurePhase,
    OnlyResearchRunState,
)
from onlyalpha.research.run.evidence import only_research_admission_resolution_fingerprint
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver

from .errors import OnlyResearchExecutionOwnershipLostError

_LOG = logging.getLogger(__name__)


class OnlyResearchSemanticCompletionStatus(StrEnum):
    ABSENT = "ABSENT"
    COMPLETE = "COMPLETE"
    CORRUPT = "CORRUPT"


@dataclass(frozen=True, slots=True)
class OnlyResearchSemanticCompletionInspection:
    status: OnlyResearchSemanticCompletionStatus
    research_result_fingerprint: str | None = None
    artifact_content_fingerprint: str | None = None
    calculation_execution_evidence_fingerprints: tuple[str, ...] = ()
    failure: OnlyResearchRunFailure | None = None

    def __post_init__(self) -> None:
        references = (self.research_result_fingerprint, self.artifact_content_fingerprint)
        if self.status is self.status.COMPLETE:
            evidence = tuple(sorted(self.calculation_execution_evidence_fingerprints))
            if (
                any(value is None for value in references)
                or not evidence
                or evidence != self.calculation_execution_evidence_fingerprints
                or len(evidence) != len(set(evidence))
                or self.failure is not None
            ):
                raise ValueError(
                    "COMPLETE inspection requires exact Result, Artifact, and Execution Evidence references"
                )
        elif self.status is self.status.CORRUPT:
            if (
                any(value is not None for value in references)
                or self.calculation_execution_evidence_fingerprints
                or self.failure is None
            ):
                raise ValueError("CORRUPT inspection requires one structured failure")
        elif (
            any(value is not None for value in references)
            or self.calculation_execution_evidence_fingerprints
            or self.failure is not None
        ):
            raise ValueError("ABSENT inspection cannot carry semantic references or failure")


class _ResearchResultReader(Protocol):
    def load_verified(self, research_result_plan_fingerprint: str) -> OnlyResearchResult: ...


class _ResearchArtifactReader(Protocol):
    def load_verified(self, research_result_fingerprint: str) -> OnlyResearchArtifact: ...


class _CalculationResultReader(Protocol):
    def load_verified(self, calculation_fingerprint: str) -> OnlyResearchCalculationResult: ...


class _CalculationExecutionEvidenceReader(Protocol):
    def require_for_result(self, result: OnlyResearchCalculationResult) -> OnlyResearchCalculationExecutionEvidence: ...


class OnlyResearchSemanticCompletionProbe(Protocol):
    def inspect(
        self,
        *,
        research_result_plan_fingerprint: str,
        dataset_snapshot_fingerprint: str,
        calculation_fingerprints: tuple[str, ...],
    ) -> OnlyResearchSemanticCompletionInspection: ...


class OnlyResearchVerifiedSemanticCompletionProbe:
    """Prove completion from existing immutable authorities without producing work."""

    def __init__(
        self,
        result_reader: _ResearchResultReader,
        artifact_reader: _ResearchArtifactReader,
        calculation_result_reader: _CalculationResultReader,
        execution_evidence_reader: _CalculationExecutionEvidenceReader,
    ) -> None:
        self._result_reader = result_reader
        self._artifact_reader = artifact_reader
        self._calculation_result_reader = calculation_result_reader
        self._execution_evidence_reader = execution_evidence_reader

    def inspect(
        self,
        *,
        research_result_plan_fingerprint: str,
        dataset_snapshot_fingerprint: str,
        calculation_fingerprints: tuple[str, ...],
    ) -> OnlyResearchSemanticCompletionInspection:
        try:
            result = self._result_reader.load_verified(research_result_plan_fingerprint)
        except Exception as exc:
            if _error_code(exc) == "RESEARCH_RESULT_NOT_FOUND":
                return OnlyResearchSemanticCompletionInspection(OnlyResearchSemanticCompletionStatus.ABSENT)
            return _corrupt(
                OnlyResearchRunFailurePhase.RESULT_COMMIT,
                "CANCELLATION_RECOVERY_RESULT_VERIFICATION_FAILED",
                exc,
            )
        manifest = result.manifest
        if (
            manifest.research_result_plan_fingerprint != research_result_plan_fingerprint
            or manifest.dataset_snapshot_fingerprint != dataset_snapshot_fingerprint
        ):
            return _corrupt(
                OnlyResearchRunFailurePhase.RESULT_COMMIT,
                "CANCELLATION_RECOVERY_RESULT_VERIFICATION_FAILED",
                ValueError("verified Research Result linkage mismatch"),
            )
        try:
            artifact = self._artifact_reader.load_verified(manifest.research_result_fingerprint)
        except Exception as exc:
            if _error_code(exc) == "ARTIFACT_NOT_FOUND":
                return OnlyResearchSemanticCompletionInspection(OnlyResearchSemanticCompletionStatus.ABSENT)
            return _corrupt(
                OnlyResearchRunFailurePhase.ARTIFACT_COMMIT,
                "CANCELLATION_RECOVERY_ARTIFACT_VERIFICATION_FAILED",
                exc,
            )
        artifact_manifest = artifact.manifest
        if (
            artifact_manifest.research_result_plan_fingerprint != research_result_plan_fingerprint
            or artifact_manifest.research_result_content_fingerprint != manifest.research_result_content_fingerprint
            or artifact_manifest.research_result_fingerprint != manifest.research_result_fingerprint
            or artifact_manifest.dataset_snapshot_fingerprint != dataset_snapshot_fingerprint
        ):
            return _corrupt(
                OnlyResearchRunFailurePhase.ARTIFACT_COMMIT,
                "CANCELLATION_RECOVERY_ARTIFACT_VERIFICATION_FAILED",
                ValueError("verified Research Artifact linkage mismatch"),
            )
        try:
            evidence_fingerprints: list[str] = []
            exact_results = {item.calculation_fingerprint: item for item in manifest.calculation_results}
            for calculation_fingerprint in calculation_fingerprints:
                calculation = self._calculation_result_reader.load_verified(calculation_fingerprint)
                reference = exact_results.get(calculation_fingerprint)
                if (
                    reference is not None
                    and calculation.manifest.calculation_result_fingerprint != reference.calculation_result_fingerprint
                ):
                    raise ValueError("verified Calculation Result linkage mismatch")
                evidence = self._execution_evidence_reader.require_for_result(calculation)
                evidence_fingerprints.append(evidence.evidence_fingerprint)
            evidence_references = tuple(sorted(evidence_fingerprints))
            if not evidence_references or len(evidence_references) != len(set(evidence_references)):
                raise ValueError("exact Calculation Execution Evidence membership is unavailable")
        except Exception as exc:
            return _corrupt(
                OnlyResearchRunFailurePhase.RESULT_COMMIT,
                "CANCELLATION_RECOVERY_EXECUTION_EVIDENCE_VERIFICATION_FAILED",
                exc,
            )
        return OnlyResearchSemanticCompletionInspection(
            status=OnlyResearchSemanticCompletionStatus.COMPLETE,
            research_result_fingerprint=manifest.research_result_fingerprint,
            artifact_content_fingerprint=artifact_manifest.artifact_content_fingerprint,
            calculation_execution_evidence_fingerprints=evidence_references,
        )


class _CancellationRecoveryStore(Protocol):
    def load_cancellation_recovery_candidate(
        self,
        eligible_run_ids: tuple[str, ...] | None = None,
    ) -> OnlyResearchRun | None: ...

    def reconcile_cancellation(
        self,
        *,
        expected: OnlyResearchRun,
        run_finished_at: datetime,
        inspection: OnlyResearchSemanticCompletionInspection,
    ) -> OnlyResearchRun: ...


class OnlyResearchCancellationRecoveryReconciler:
    """Application boundary joining operational intent with semantic evidence."""

    def __init__(
        self,
        *,
        execution_store: _CancellationRecoveryStore,
        resolver: OnlyResearchSpecificationResolver,
        completion_probe: OnlyResearchSemanticCompletionProbe,
        now_utc: Callable[[], datetime],
    ) -> None:
        self._execution_store = execution_store
        self._resolver = resolver
        self._completion_probe = completion_probe
        self._now_utc = now_utc

    def reconcile_once(self, eligible_run_ids: tuple[str, ...] | None = None) -> OnlyResearchRun | None:
        run = self._execution_store.load_cancellation_recovery_candidate(eligible_run_ids)
        if run is None:
            return None
        if run.state is not OnlyResearchRunState.CANCEL_REQUESTED:
            raise OnlyResearchExecutionOwnershipLostError("Cancellation recovery candidate changed state")
        try:
            resolution = self._resolver.resolve(run.specification)
            if only_research_admission_resolution_fingerprint(resolution) != run.admission_resolution_fingerprint:
                inspection = _corrupt(
                    OnlyResearchRunFailurePhase.ADMISSION,
                    "CANCELLATION_RECOVERY_SEMANTIC_DRIFT",
                    ValueError("admission resolution evidence changed"),
                )
            else:
                inspection = self._completion_probe.inspect(
                    research_result_plan_fingerprint=resolution.workload.result_plan.fingerprint,
                    dataset_snapshot_fingerprint=resolution.workload.dataset_snapshot_fingerprint,
                    calculation_fingerprints=tuple(
                        item.calculation_fingerprint for item in resolution.workload.calculation_jobs
                    ),
                )
        except Exception as exc:
            inspection = _corrupt(
                OnlyResearchRunFailurePhase.ADMISSION,
                "CANCELLATION_RECOVERY_RESOLUTION_FAILED",
                exc,
            )
        reconciled = self._execution_store.reconcile_cancellation(
            expected=run,
            run_finished_at=self._now_utc(),
            inspection=inspection,
        )
        _LOG.info(
            "Research cancellation recovery run_id=%s source_state=%s decision=%s "
            "research_result_fingerprint=%s artifact_content_fingerprint=%s failure_code=%s",
            run.run_id,
            run.state,
            reconciled.state,
            reconciled.research_result_fingerprint,
            reconciled.artifact_content_fingerprint,
            None if reconciled.failure is None else reconciled.failure.code,
        )
        return reconciled


def _corrupt(
    phase: OnlyResearchRunFailurePhase,
    code: str,
    exc: Exception,
) -> OnlyResearchSemanticCompletionInspection:
    return OnlyResearchSemanticCompletionInspection(
        status=OnlyResearchSemanticCompletionStatus.CORRUPT,
        failure=OnlyResearchRunFailure(phase, code, f"Verified semantic inspection failed: {type(exc).__name__}"),
    )


def _error_code(exc: Exception) -> str | None:
    code = getattr(exc, "code", None)
    return code if isinstance(code, str) else None


__all__ = [name for name in globals() if name.startswith("Only")]
