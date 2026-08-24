from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.dataset import OnlyResearchDatasetCorruptError, OnlyResearchDatasetNotFoundError
from onlyalpha.research.run import (
    OnlyResearchRun,
    OnlyResearchRunAdmissionError,
    OnlyResearchRunAdmissionService,
    OnlyResearchRunFailure,
    OnlyResearchRunFailurePhase,
    OnlyResearchRunId,
    OnlyResearchRunIntegrityError,
    OnlyResearchRunState,
    OnlyResearchRunStateConflictError,
    only_research_admission_resolution_fingerprint,
)
from onlyalpha.research.specification import (
    RESEARCH_SPECIFICATION_SCIENTIFIC_SCHEMA_VERSION,
    OnlyResearchScientificEvidenceSpec,
    OnlyResearchSeriesSelector,
    OnlyResearchSignalEvidenceSpec,
    OnlyResearchSpecification,
    OnlyResearchSpecificationError,
    OnlyResearchSpecificationPhase,
    OnlyResearchSpecificationResolver,
)
from tests.research.specification.support import registry, specification

NOW = datetime(2026, 8, 17, 1, 2, 3, tzinfo=UTC)
RESULT = "b" * 64
ARTIFACT = "c" * 64


def _queued(run_id: str = "00000000-0000-4000-8000-000000000001") -> OnlyResearchRun:
    spec = specification()
    resolution = OnlyResearchSpecificationResolver(registry()).resolve(spec)
    return OnlyResearchRun.queued(
        run_id=OnlyResearchRunId(run_id),
        specification=spec,
        canonical_specification_payload=only_canonical_json(spec.to_dict()),
        admission_resolution_fingerprint=only_research_admission_resolution_fingerprint(resolution),
        queued_at=NOW,
    )


def test_v2_scientific_membership_survives_exact_run_payload_round_trip() -> None:
    v1 = specification()
    v2 = OnlyResearchSpecification(
        v1.dataset_snapshot_fingerprint,
        v1.calculations,
        v1.statistics,
        OnlyResearchScientificEvidenceSpec(
            "feature",
            (OnlyResearchSeriesSelector("feature", "momentum", "factor_value"),),
            OnlyResearchSignalEvidenceSpec(),
        ),
        RESEARCH_SPECIFICATION_SCIENTIFIC_SCHEMA_VERSION,
    )
    resolution = OnlyResearchSpecificationResolver(registry()).resolve(v2)
    run = OnlyResearchRun.queued(
        run_id=OnlyResearchRunId("00000000-0000-4000-8000-000000000099"),
        specification=v2,
        canonical_specification_payload=only_canonical_json(v2.to_dict()),
        admission_resolution_fingerprint=only_research_admission_resolution_fingerprint(resolution),
        queued_at=NOW,
    )
    restored = OnlyResearchSpecification.from_dict(run.specification.to_dict())
    fresh = OnlyResearchSpecificationResolver(registry()).resolve(restored)
    assert restored == v2
    assert fresh.workload.result_plan == resolution.workload.result_plan
    assert [item.candidate_fingerprint for item in fresh.candidates] == [
        item.candidate_fingerprint for item in resolution.candidates
    ]


def test_run_identity_is_uuid4_and_independent_from_specification_identity() -> None:
    first = _queued()
    second = _queued("00000000-0000-4000-8000-000000000002")

    assert first.run_id != second.run_id
    assert first.specification_fingerprint == second.specification_fingerprint
    with pytest.raises(ValueError):
        OnlyResearchRunId("00000000-0000-1000-8000-000000000001")
    with pytest.raises(ValueError):
        OnlyResearchRunId("invalid")
    assert isinstance(OnlyResearchRunId.new(), OnlyResearchRunId)
    assert str(first.run_id) == first.run_id.value


def test_state_machine_and_revision_are_central_and_exact() -> None:
    queued = _queued()
    running = queued.transition(OnlyResearchRunState.RUNNING, at=NOW + timedelta(seconds=1))
    cancel_requested = running.transition(OnlyResearchRunState.CANCEL_REQUESTED, at=NOW + timedelta(seconds=2))
    completed = cancel_requested.transition(
        OnlyResearchRunState.COMPLETED,
        at=NOW + timedelta(seconds=3),
        research_result_fingerprint=RESULT,
        artifact_content_fingerprint=ARTIFACT,
    )

    assert [queued.revision, running.revision, cancel_requested.revision, completed.revision] == [0, 1, 2, 3]
    assert cancel_requested.cancel_requested_at is not None
    assert completed.cancel_requested_at == cancel_requested.cancel_requested_at
    assert completed.is_exact_successor_of(cancel_requested)
    with pytest.raises(OnlyResearchRunStateConflictError):
        completed.transition(OnlyResearchRunState.RUNNING, at=NOW + timedelta(seconds=4))


def test_all_v1_transition_edges_and_terminal_immutability() -> None:
    failure = OnlyResearchRunFailure(OnlyResearchRunFailurePhase.EXECUTION, "EXECUTION_BROKE", "boom")
    running = _queued().transition(OnlyResearchRunState.RUNNING, at=NOW + timedelta(seconds=1))
    outcomes = (
        running.transition(
            OnlyResearchRunState.COMPLETED,
            at=NOW + timedelta(seconds=2),
            research_result_fingerprint=RESULT,
            artifact_content_fingerprint=ARTIFACT,
        ),
        running.transition(OnlyResearchRunState.FAILED, at=NOW + timedelta(seconds=2), failure=failure),
        _queued().transition(OnlyResearchRunState.CANCELLED, at=NOW + timedelta(seconds=1)),
    )
    requested = running.transition(OnlyResearchRunState.CANCEL_REQUESTED, at=NOW + timedelta(seconds=2))
    outcomes += (
        requested.transition(OnlyResearchRunState.CANCELLED, at=NOW + timedelta(seconds=3)),
        requested.transition(
            OnlyResearchRunState.COMPLETED,
            at=NOW + timedelta(seconds=3),
            research_result_fingerprint=RESULT,
            artifact_content_fingerprint=ARTIFACT,
        ),
        requested.transition(OnlyResearchRunState.FAILED, at=NOW + timedelta(seconds=3), failure=failure),
    )
    assert all(item.state.terminal for item in outcomes)
    for outcome in outcomes:
        with pytest.raises(OnlyResearchRunStateConflictError):
            outcome.transition(OnlyResearchRunState.RUNNING, at=NOW + timedelta(seconds=4))


def test_failed_run_preserves_semantic_facts_committed_before_artifact_failure() -> None:
    running = _queued().transition(OnlyResearchRunState.RUNNING, at=NOW + timedelta(seconds=1))
    failure = OnlyResearchRunFailure(
        OnlyResearchRunFailurePhase.ARTIFACT_COMMIT, "ARTIFACT_COMMIT_FAILED", "artifact unavailable"
    )
    failed = running.transition(
        OnlyResearchRunState.FAILED,
        at=NOW + timedelta(seconds=2),
        failure=failure,
        research_result_fingerprint=RESULT,
    )

    assert failed.research_result_fingerprint == RESULT
    assert failed.artifact_content_fingerprint is None
    assert failed.failure == failure


def test_execution_evidence_references_are_canonical_valid_linked_and_terminal_only() -> None:
    running = _queued().transition(OnlyResearchRunState.RUNNING, at=NOW + timedelta(seconds=1))
    invalid = (
        (
            {
                "research_result_fingerprint": RESULT,
                "calculation_execution_evidence_fingerprints": ("b" * 64, "a" * 64),
            },
            "canonical and unique",
        ),
        (
            {
                "research_result_fingerprint": RESULT,
                "calculation_execution_evidence_fingerprints": ("a" * 64, "a" * 64),
            },
            "canonical and unique",
        ),
        (
            {"research_result_fingerprint": RESULT, "calculation_execution_evidence_fingerprints": ("invalid",)},
            "lower-case SHA256",
        ),
        (
            {"calculation_execution_evidence_fingerprints": ("a" * 64,)},
            "require Research Result",
        ),
        (
            {"research_result_fingerprint": RESULT, "calculation_execution_evidence_fingerprints": ("a" * 64,)},
            "active Run cannot contain finalized",
        ),
    )
    for changes, message in invalid:
        with pytest.raises(OnlyResearchRunIntegrityError, match=message):
            replace(running, **changes)


def test_lifecycle_time_order_and_reference_consistency_fail_closed() -> None:
    running = _queued().transition(OnlyResearchRunState.RUNNING, at=NOW + timedelta(seconds=2))
    requested = running.transition(OnlyResearchRunState.CANCEL_REQUESTED, at=NOW + timedelta(seconds=4))
    completed = requested.transition(
        OnlyResearchRunState.COMPLETED,
        at=NOW + timedelta(seconds=6),
        research_result_fingerprint=RESULT,
        artifact_content_fingerprint=ARTIFACT,
    )
    invalid = (
        (requested, {"cancel_requested_at": NOW + timedelta(seconds=1)}, "precedes started_at"),
        (completed, {"finished_at": NOW + timedelta(seconds=1)}, "precedes started_at"),
        (completed, {"finished_at": NOW + timedelta(seconds=3)}, "precedes cancel_requested_at"),
        (running, {"cancel_requested_at": NOW + timedelta(seconds=3)}, "RUNNING cannot"),
        (running, {"artifact_content_fingerprint": ARTIFACT}, "requires Research Result"),
    )
    for run, changes, message in invalid:
        with pytest.raises(OnlyResearchRunIntegrityError, match=message):
            replace(run, **changes)


def test_cancelled_lifecycle_allows_only_direct_queued_or_requested_running_shape() -> None:
    direct = _queued().transition(OnlyResearchRunState.CANCELLED, at=NOW + timedelta(seconds=1))
    running = _queued().transition(OnlyResearchRunState.RUNNING, at=NOW + timedelta(seconds=1))
    requested = running.transition(OnlyResearchRunState.CANCEL_REQUESTED, at=NOW + timedelta(seconds=2))
    after_start = requested.transition(OnlyResearchRunState.CANCELLED, at=NOW + timedelta(seconds=3))

    assert direct.started_at is None and direct.cancel_requested_at is None
    assert after_start.started_at is not None and after_start.cancel_requested_at is not None
    with pytest.raises(OnlyResearchRunIntegrityError, match="direct from QUEUED"):
        replace(direct, started_at=NOW)


def test_completed_and_failed_require_started_execution_fact() -> None:
    queued = _queued()
    failure = OnlyResearchRunFailure(OnlyResearchRunFailurePhase.EXECUTION, "EXECUTION_FAILED", "detail")
    with pytest.raises(OnlyResearchRunIntegrityError, match="COMPLETED requires started execution"):
        replace(
            queued,
            state=OnlyResearchRunState.COMPLETED,
            finished_at=NOW + timedelta(seconds=1),
            research_result_fingerprint=RESULT,
            artifact_content_fingerprint=ARTIFACT,
        )
    with pytest.raises(OnlyResearchRunIntegrityError, match="FAILED requires started execution"):
        replace(
            queued,
            state=OnlyResearchRunState.FAILED,
            finished_at=NOW + timedelta(seconds=1),
            failure=failure,
        )


class _RunStore:
    def __init__(self) -> None:
        self.runs: dict[OnlyResearchRunId, OnlyResearchRun] = {}

    def create_queued(self, run: OnlyResearchRun) -> OnlyResearchRun:
        self.runs[run.run_id] = run
        return run


class _DatasetStore:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.loaded: list[str] = []

    def load_verified_table(self, fingerprint: str) -> object:
        self.loaded.append(fingerprint)
        if self.fail:
            raise RuntimeError("corrupt")
        return object()


def test_admission_verifies_dataset_before_durable_queued_acknowledgement() -> None:
    spec = specification()
    dataset = _DatasetStore()
    store = _RunStore()
    service = OnlyResearchRunAdmissionService(
        resolver=OnlyResearchSpecificationResolver(registry()),
        dataset_store=dataset,  # type: ignore[arg-type]
        run_store=store,  # type: ignore[arg-type]
        now_utc=lambda: NOW,
        run_id_factory=lambda: OnlyResearchRunId("00000000-0000-4000-8000-000000000003"),
    )

    run = service.submit(spec)

    assert dataset.loaded == [spec.dataset_snapshot_fingerprint]
    assert store.runs[run.run_id] == run
    assert run.state is OnlyResearchRunState.QUEUED
    service.verify_resolution(run)


def test_admission_missing_or_corrupt_dataset_creates_no_run() -> None:
    store = _RunStore()
    service = OnlyResearchRunAdmissionService(
        resolver=OnlyResearchSpecificationResolver(registry()),
        dataset_store=_DatasetStore(fail=True),  # type: ignore[arg-type]
        run_store=store,  # type: ignore[arg-type]
        now_utc=lambda: NOW,
    )
    with pytest.raises(OnlyResearchRunAdmissionError):
        service.submit(specification())
    assert store.runs == {}


def test_cross_deployment_resolution_drift_fails_closed() -> None:
    run = _queued()
    drifted = OnlyResearchRun(
        run.run_id,
        run.revision,
        run.state,
        run.specification,
        run.specification_fingerprint,
        run.canonical_specification_payload,
        "d" * 64,
        run.queued_at,
    )
    service = OnlyResearchRunAdmissionService(
        resolver=OnlyResearchSpecificationResolver(registry()),
        dataset_store=_DatasetStore(),  # type: ignore[arg-type]
        run_store=_RunStore(),  # type: ignore[arg-type]
        now_utc=lambda: NOW,
    )
    with pytest.raises(OnlyResearchRunAdmissionError, match="evidence mismatch"):
        service.verify_resolution(drifted)


@pytest.mark.parametrize(
    "changes",
    [
        {"run_id": "bad"},
        {"revision": -1},
        {"revision": True},
        {"revision": "1"},
        {"state": "BAD"},
        {"specification": object()},
        {"specification_fingerprint": "0" * 64},
        {"canonical_specification_payload": "{}"},
        {"admission_resolution_fingerprint": "bad"},
        {"research_result_fingerprint": "bad"},
        {"queued_at": datetime(2026, 8, 17)},
        {"started_at": NOW - timedelta(seconds=1)},
        {"cancel_requested_at": NOW - timedelta(seconds=1)},
        {"finished_at": NOW - timedelta(seconds=1)},
    ],
)
def test_run_row_integrity_rejects_invalid_identity_revision_time_and_linkage(changes: dict[str, object]) -> None:
    with pytest.raises(OnlyResearchRunIntegrityError):
        replace(_queued(), **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"started_at": NOW},
        {"cancel_requested_at": NOW},
        {"finished_at": NOW},
        {"research_result_fingerprint": RESULT},
        {"artifact_content_fingerprint": ARTIFACT},
        {"failure": OnlyResearchRunFailure(OnlyResearchRunFailurePhase.OPERATIONAL, "OPERATIONAL_FAILED", "detail")},
    ],
)
def test_queued_run_rejects_every_later_lifecycle_fact(changes: dict[str, object]) -> None:
    with pytest.raises(OnlyResearchRunIntegrityError):
        replace(_queued(), **changes)


def test_state_specific_invariants_fail_closed() -> None:
    queued = _queued()
    failure = OnlyResearchRunFailure(OnlyResearchRunFailurePhase.EXECUTION, "EXECUTION_FAILED", "detail")
    invalid = (
        {"state": OnlyResearchRunState.RUNNING},
        {"state": OnlyResearchRunState.CANCEL_REQUESTED, "started_at": NOW},
        {"state": OnlyResearchRunState.COMPLETED, "finished_at": NOW},
        {"state": OnlyResearchRunState.FAILED, "finished_at": NOW},
        {"state": OnlyResearchRunState.CANCELLED, "finished_at": None},
        {"state": OnlyResearchRunState.CANCELLED, "finished_at": NOW, "failure": failure},
    )
    for changes in invalid:
        with pytest.raises(OnlyResearchRunIntegrityError):
            replace(queued, **changes)


@pytest.mark.parametrize(
    "args",
    [
        ("bad", "CODE", "detail"),
        (OnlyResearchRunFailurePhase.EXECUTION, "bad-code", "detail"),
        (OnlyResearchRunFailurePhase.EXECUTION, "CODE", ""),
    ],
)
def test_failure_taxonomy_is_strict(args: tuple[object, object, object]) -> None:
    with pytest.raises(ValueError):
        OnlyResearchRunFailure(*args)  # type: ignore[arg-type]


def test_transition_rejects_invalid_time_and_misplaced_failure() -> None:
    queued = _queued()
    failure = OnlyResearchRunFailure(OnlyResearchRunFailurePhase.EXECUTION, "EXECUTION_FAILED", "detail")
    with pytest.raises(ValueError):
        queued.transition(OnlyResearchRunState.RUNNING, at=datetime(2026, 8, 17))
    with pytest.raises(OnlyResearchRunStateConflictError, match="only valid"):
        queued.transition(OnlyResearchRunState.RUNNING, at=NOW, failure=failure)


def test_exact_successor_rejects_wrong_identity_revision_and_illegal_reconstruction() -> None:
    queued = _queued()
    other = _queued("00000000-0000-4000-8000-000000000099")
    assert not other.transition(OnlyResearchRunState.RUNNING, at=NOW).is_exact_successor_of(queued)
    assert not queued.is_exact_successor_of(queued)
    cancelled = queued.transition(OnlyResearchRunState.CANCELLED, at=NOW)
    artificial = replace(queued, revision=cancelled.revision + 1)
    assert not artificial.is_exact_successor_of(cancelled)


def test_evidence_requires_exact_resolution_type() -> None:
    with pytest.raises(TypeError):
        only_research_admission_resolution_fingerprint(object())  # type: ignore[arg-type]


def test_admission_preserves_stable_admission_error_without_durable_write() -> None:
    class _AdmissionFailureDataset(_DatasetStore):
        def load_verified_table(self, fingerprint: str) -> object:
            raise OnlyResearchRunAdmissionError("stable")

    service = OnlyResearchRunAdmissionService(
        resolver=OnlyResearchSpecificationResolver(registry()),
        dataset_store=_AdmissionFailureDataset(),  # type: ignore[arg-type]
        run_store=_RunStore(),  # type: ignore[arg-type]
        now_utc=lambda: NOW,
    )
    with pytest.raises(OnlyResearchRunAdmissionError, match="stable"):
        service.submit(specification())


@pytest.mark.parametrize(
    ("error", "code"),
    (
        (OnlyResearchDatasetNotFoundError("missing"), "RESEARCH_DATASET_NOT_FOUND"),
        (OnlyResearchDatasetCorruptError("corrupt"), "RESEARCH_DATASET_CORRUPT"),
    ),
)
def test_admission_preserves_typed_dataset_failure(error: Exception, code: str) -> None:
    class _TypedFailureDataset(_DatasetStore):
        def load_verified_table(self, fingerprint: str) -> object:
            raise error

    service = OnlyResearchRunAdmissionService(
        resolver=OnlyResearchSpecificationResolver(registry()),
        dataset_store=_TypedFailureDataset(),  # type: ignore[arg-type]
        run_store=_RunStore(),  # type: ignore[arg-type]
        now_utc=lambda: NOW,
    )
    with pytest.raises(OnlyResearchRunAdmissionError) as caught:
        service.submit(specification())
    assert caught.value.code == code


def test_admission_preserves_typed_specification_resolution_failure() -> None:
    class _FailingResolver:
        def resolve(self, _specification):  # type: ignore[no-untyped-def]
            raise OnlyResearchSpecificationError(
                OnlyResearchSpecificationPhase.TYPE_RESOLUTION,
                "RESEARCH_SPEC_TYPE_UNKNOWN",
                "unknown",
            )

    service = OnlyResearchRunAdmissionService(
        resolver=_FailingResolver(),  # type: ignore[arg-type]
        dataset_store=_DatasetStore(),  # type: ignore[arg-type]
        run_store=_RunStore(),  # type: ignore[arg-type]
        now_utc=lambda: NOW,
    )
    with pytest.raises(OnlyResearchRunAdmissionError) as caught:
        service.submit(specification())
    assert caught.value.code == "RESEARCH_SPEC_TYPE_UNKNOWN"


def test_utc_offset_other_than_zero_is_rejected() -> None:
    with pytest.raises(OnlyResearchRunIntegrityError):
        replace(_queued(), queued_at=NOW.astimezone(timezone(timedelta(hours=8))))
