from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.execution import (
    OnlyResearchCancellationRecoveryReconciler,
    OnlyResearchExecutionOwnershipLostError,
    OnlyResearchSemanticCompletionInspection,
    OnlyResearchSemanticCompletionStatus,
    OnlyResearchVerifiedSemanticCompletionProbe,
)
from onlyalpha.research.run import (
    OnlyResearchRun,
    OnlyResearchRunFailure,
    OnlyResearchRunFailurePhase,
    OnlyResearchRunId,
    OnlyResearchRunState,
    only_research_admission_resolution_fingerprint,
)
from onlyalpha.research.specification import OnlyResearchSpecificationResolver
from tests.research.specification.support import registry, specification
from tests.runtime.research.support import workload_case

NOW = datetime(2026, 8, 18, 2, 0, tzinfo=UTC)


class _Error(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _Reader:
    def __init__(self, value: object = None, error: Exception | None = None) -> None:
        self.value = value
        self.error = error
        self.calls: list[str] = []

    def load_verified(self, fingerprint: str) -> object:
        self.calls.append(fingerprint)
        if self.error is not None:
            raise self.error
        return self.value


class _EvidenceReader:
    def __init__(self, value: object = None, error: Exception | None = None) -> None:
        self.value = value or SimpleNamespace(evidence_fingerprint="8" * 64)
        self.error = error

    def require_for_result(self, result: object) -> object:
        del result
        if self.error is not None:
            raise self.error
        return self.value


def _semantic_values() -> tuple[object, object]:
    result_manifest = SimpleNamespace(
        research_result_plan_fingerprint="a" * 64,
        research_result_content_fingerprint="b" * 64,
        research_result_fingerprint="c" * 64,
        dataset_snapshot_fingerprint="d" * 64,
        calculation_results=(
            SimpleNamespace(calculation_fingerprint="f" * 64, calculation_result_fingerprint="7" * 64),
        ),
    )
    artifact_manifest = SimpleNamespace(
        research_result_plan_fingerprint="a" * 64,
        research_result_content_fingerprint="b" * 64,
        research_result_fingerprint="c" * 64,
        dataset_snapshot_fingerprint="d" * 64,
        artifact_content_fingerprint="e" * 64,
    )
    return SimpleNamespace(manifest=result_manifest), SimpleNamespace(manifest=artifact_manifest)


def _completion_probe(
    result_reader: object,
    artifact_reader: object,
    calculation_reader: object | None = None,
    evidence_reader: object | None = None,
) -> OnlyResearchVerifiedSemanticCompletionProbe:
    calculation = SimpleNamespace(manifest=SimpleNamespace(calculation_result_fingerprint="7" * 64))
    return OnlyResearchVerifiedSemanticCompletionProbe(
        result_reader,  # type: ignore[arg-type]
        artifact_reader,  # type: ignore[arg-type]
        calculation_reader or _Reader(calculation),  # type: ignore[arg-type]
        evidence_reader or _EvidenceReader(),  # type: ignore[arg-type]
    )


def test_verified_completion_probe_distinguishes_complete_absent_and_corrupt() -> None:
    result, artifact = _semantic_values()
    complete = _completion_probe(_Reader(result), _Reader(artifact)).inspect(
        research_result_plan_fingerprint="a" * 64,
        dataset_snapshot_fingerprint="d" * 64,
        calculation_fingerprints=("f" * 64,),
    )
    assert complete == OnlyResearchSemanticCompletionInspection(
        status=OnlyResearchSemanticCompletionStatus.COMPLETE,
        research_result_fingerprint="c" * 64,
        artifact_content_fingerprint="e" * 64,
        calculation_execution_evidence_fingerprints=("8" * 64,),
    )

    artifact_reader = _Reader(error=_Error("ARTIFACT_NOT_FOUND"))
    partial = _completion_probe(_Reader(result), artifact_reader).inspect(
        research_result_plan_fingerprint="a" * 64,
        dataset_snapshot_fingerprint="d" * 64,
        calculation_fingerprints=("f" * 64,),
    )
    assert partial.status is OnlyResearchSemanticCompletionStatus.ABSENT

    corrupt = _completion_probe(_Reader(result), _Reader(error=_Error("ARTIFACT_CORRUPT"))).inspect(
        research_result_plan_fingerprint="a" * 64,
        dataset_snapshot_fingerprint="d" * 64,
        calculation_fingerprints=("f" * 64,),
    )
    assert corrupt.status is OnlyResearchSemanticCompletionStatus.CORRUPT
    assert corrupt.failure is not None
    assert corrupt.failure.code == "CANCELLATION_RECOVERY_ARTIFACT_VERIFICATION_FAILED"


def test_completion_inspection_contract_rejects_incoherent_evidence() -> None:
    failure = OnlyResearchRunFailure(OnlyResearchRunFailurePhase.RESULT_COMMIT, "CORRUPT", "corrupt")
    invalid = (
        (OnlyResearchSemanticCompletionStatus.COMPLETE, None, None, (), None),
        (OnlyResearchSemanticCompletionStatus.CORRUPT, "a" * 64, None, (), failure),
        (OnlyResearchSemanticCompletionStatus.ABSENT, None, None, (), failure),
    )
    for status, result, artifact, evidence, item_failure in invalid:
        with pytest.raises(ValueError):
            OnlyResearchSemanticCompletionInspection(status, result, artifact, evidence, item_failure)


def test_verified_completion_probe_fails_closed_for_result_errors_and_linkage_mismatch() -> None:
    artifact = _semantic_values()[1]
    missing = _completion_probe(_Reader(error=_Error("RESEARCH_RESULT_NOT_FOUND")), _Reader(artifact)).inspect(
        research_result_plan_fingerprint="a" * 64,
        dataset_snapshot_fingerprint="d" * 64,
        calculation_fingerprints=("f" * 64,),
    )
    assert missing.status is OnlyResearchSemanticCompletionStatus.ABSENT

    corrupt = _completion_probe(_Reader(error=_Error("RESEARCH_RESULT_CORRUPT")), _Reader(artifact)).inspect(
        research_result_plan_fingerprint="a" * 64,
        dataset_snapshot_fingerprint="d" * 64,
        calculation_fingerprints=("f" * 64,),
    )
    assert corrupt.status is OnlyResearchSemanticCompletionStatus.CORRUPT
    assert corrupt.failure is not None
    assert corrupt.failure.code == "CANCELLATION_RECOVERY_RESULT_VERIFICATION_FAILED"

    result, _ = _semantic_values()
    result.manifest.dataset_snapshot_fingerprint = "f" * 64
    mismatch = _completion_probe(_Reader(result), _Reader(artifact)).inspect(
        research_result_plan_fingerprint="a" * 64,
        dataset_snapshot_fingerprint="d" * 64,
        calculation_fingerprints=("f" * 64,),
    )
    assert mismatch.status is OnlyResearchSemanticCompletionStatus.CORRUPT


def test_verified_completion_probe_rejects_artifact_linkage_mismatch() -> None:
    result, artifact = _semantic_values()
    artifact.manifest.research_result_content_fingerprint = "f" * 64
    mismatch = _completion_probe(_Reader(result), _Reader(artifact)).inspect(
        research_result_plan_fingerprint="a" * 64,
        dataset_snapshot_fingerprint="d" * 64,
        calculation_fingerprints=("f" * 64,),
    )
    assert mismatch.status is OnlyResearchSemanticCompletionStatus.CORRUPT
    assert mismatch.failure is not None
    assert mismatch.failure.code == "CANCELLATION_RECOVERY_ARTIFACT_VERIFICATION_FAILED"


class _Probe:
    def __init__(self, inspection: OnlyResearchSemanticCompletionInspection) -> None:
        self.inspection = inspection
        self.calls = 0

    def inspect(self, **kwargs: object) -> OnlyResearchSemanticCompletionInspection:
        assert set(kwargs) == {
            "research_result_plan_fingerprint",
            "dataset_snapshot_fingerprint",
            "calculation_fingerprints",
        }
        self.calls += 1
        return self.inspection


class _RecoveryStore:
    def __init__(self, run: OnlyResearchRun) -> None:
        self.run = run

    def load_cancellation_recovery_candidate(self) -> OnlyResearchRun | None:
        return self.run if self.run.state is OnlyResearchRunState.CANCEL_REQUESTED else None

    def reconcile_cancellation(
        self,
        *,
        expected: OnlyResearchRun,
        run_finished_at: datetime,
        inspection: OnlyResearchSemanticCompletionInspection,
    ) -> OnlyResearchRun:
        if expected != self.run:
            raise OnlyResearchExecutionOwnershipLostError("stale")
        if inspection.status is OnlyResearchSemanticCompletionStatus.COMPLETE:
            assert inspection.research_result_fingerprint is not None
            assert inspection.artifact_content_fingerprint is not None
            target = self.run.transition(
                OnlyResearchRunState.COMPLETED,
                at=run_finished_at,
                research_result_fingerprint=inspection.research_result_fingerprint,
                artifact_content_fingerprint=inspection.artifact_content_fingerprint,
                calculation_execution_evidence_fingerprints=(inspection.calculation_execution_evidence_fingerprints),
            )
        elif inspection.status is OnlyResearchSemanticCompletionStatus.ABSENT:
            target = self.run.transition(OnlyResearchRunState.CANCELLED, at=run_finished_at)
        else:
            assert inspection.failure is not None
            target = self.run.transition(OnlyResearchRunState.FAILED, at=run_finished_at, failure=inspection.failure)
        self.run = target
        return target


def _cancel_requested(tmp_path: Path) -> tuple[OnlyResearchRun, OnlyResearchSpecificationResolver]:
    _, workload = workload_case(tmp_path)
    resolver = OnlyResearchSpecificationResolver(registry())
    spec = specification(workload.dataset_snapshot_fingerprint)
    resolution = resolver.resolve(spec)
    queued = OnlyResearchRun.queued(
        run_id=OnlyResearchRunId("00000000-0000-4000-8000-000000000401"),
        specification=spec,
        canonical_specification_payload=only_canonical_json(spec.to_dict()),
        admission_resolution_fingerprint=only_research_admission_resolution_fingerprint(resolution),
        queued_at=NOW,
    )
    running = queued.transition(OnlyResearchRunState.RUNNING, at=NOW + timedelta(seconds=1))
    return running.transition(OnlyResearchRunState.CANCEL_REQUESTED, at=NOW + timedelta(seconds=2)), resolver


@pytest.mark.parametrize(
    ("inspection", "expected_state"),
    (
        (
            OnlyResearchSemanticCompletionInspection(
                OnlyResearchSemanticCompletionStatus.COMPLETE,
                "b" * 64,
                "c" * 64,
                ("e" * 64,),
            ),
            OnlyResearchRunState.COMPLETED,
        ),
        (
            OnlyResearchSemanticCompletionInspection(OnlyResearchSemanticCompletionStatus.ABSENT),
            OnlyResearchRunState.CANCELLED,
        ),
        (
            OnlyResearchSemanticCompletionInspection(
                OnlyResearchSemanticCompletionStatus.CORRUPT,
                failure=OnlyResearchRunFailure(
                    OnlyResearchRunFailurePhase.ARTIFACT_COMMIT,
                    "CANCELLATION_RECOVERY_ARTIFACT_VERIFICATION_FAILED",
                    "corrupt",
                ),
            ),
            OnlyResearchRunState.FAILED,
        ),
    ),
)
def test_reconciler_projects_complete_absent_and_corrupt_without_semantic_work(
    tmp_path: Path,
    inspection: OnlyResearchSemanticCompletionInspection,
    expected_state: OnlyResearchRunState,
) -> None:
    run, resolver = _cancel_requested(tmp_path)
    store = _RecoveryStore(run)
    probe = _Probe(inspection)
    reconciled = OnlyResearchCancellationRecoveryReconciler(
        execution_store=store,
        resolver=resolver,
        completion_probe=probe,
        now_utc=lambda: NOW + timedelta(minutes=1),
    ).reconcile_once()
    assert reconciled is not None and reconciled.state is expected_state
    assert reconciled.cancel_requested_at == run.cancel_requested_at
    assert probe.calls == 1


def test_reconciler_handles_no_candidate_wrong_state_drift_and_resolution_failure(tmp_path: Path) -> None:
    run, resolver = _cancel_requested(tmp_path)
    terminal_store = _RecoveryStore(run.transition(OnlyResearchRunState.CANCELLED, at=NOW + timedelta(minutes=1)))
    reconciler = OnlyResearchCancellationRecoveryReconciler(
        execution_store=terminal_store,
        resolver=resolver,
        completion_probe=_Probe(OnlyResearchSemanticCompletionInspection(OnlyResearchSemanticCompletionStatus.ABSENT)),
        now_utc=lambda: NOW + timedelta(minutes=2),
    )
    assert reconciler.reconcile_once() is None

    wrong_store = SimpleNamespace(
        load_cancellation_recovery_candidate=lambda: SimpleNamespace(state=OnlyResearchRunState.RUNNING)
    )
    with pytest.raises(OnlyResearchExecutionOwnershipLostError):
        OnlyResearchCancellationRecoveryReconciler(
            execution_store=wrong_store,
            resolver=resolver,
            completion_probe=_Probe(
                OnlyResearchSemanticCompletionInspection(OnlyResearchSemanticCompletionStatus.ABSENT)
            ),
            now_utc=lambda: NOW,
        ).reconcile_once()

    drifted = replace(run, admission_resolution_fingerprint="f" * 64)
    drift_store = _RecoveryStore(drifted)
    drift = OnlyResearchCancellationRecoveryReconciler(
        execution_store=drift_store,
        resolver=resolver,
        completion_probe=_Probe(OnlyResearchSemanticCompletionInspection(OnlyResearchSemanticCompletionStatus.ABSENT)),
        now_utc=lambda: NOW + timedelta(minutes=2),
    ).reconcile_once()
    assert drift is not None and drift.state is OnlyResearchRunState.FAILED
    assert drift.failure is not None and drift.failure.code == "CANCELLATION_RECOVERY_SEMANTIC_DRIFT"

    class _BrokenResolver:
        def resolve(self, value: object) -> object:
            del value
            raise RuntimeError("broken")

    run, _ = _cancel_requested(tmp_path / "broken")
    broken_store = _RecoveryStore(run)
    broken = OnlyResearchCancellationRecoveryReconciler(
        execution_store=broken_store,
        resolver=_BrokenResolver(),  # type: ignore[arg-type]
        completion_probe=_Probe(OnlyResearchSemanticCompletionInspection(OnlyResearchSemanticCompletionStatus.ABSENT)),
        now_utc=lambda: NOW + timedelta(minutes=2),
    ).reconcile_once()
    assert broken is not None and broken.state is OnlyResearchRunState.FAILED
    assert broken.failure is not None and broken.failure.code == "CANCELLATION_RECOVERY_RESOLUTION_FAILED"
