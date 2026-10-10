"""Chart lifecycle values and immutable admission, never fenced execution permission."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from onlyalpha.application.chart_calculation import OnlyChartCalculationError
from onlyalpha.application.chart_calculation_run_admission import (
    only_chart_calculation_queued_run,
    only_verify_chart_calculation_run,
)
from onlyalpha.persistence.postgres.research_run_store import _COLUMNS, OnlyPostgresResearchRunStore
from onlyalpha.research.run.errors import OnlyResearchRunIntegrityError, OnlyResearchRunStateConflictError
from onlyalpha.research.run.model import (
    OnlyResearchRunFailure,
    OnlyResearchRunFailurePhase,
    OnlyResearchRunId,
    OnlyResearchRunState,
)
from tests.application.test_chart_calculation_admission import NOW
from tests.application.test_chart_calculation_compilation import compilation
from tests.support.chart_calculation_compilation import prepared_input

pytestmark = pytest.mark.contract

RESULT, ARTIFACT, EVIDENCE = "a" * 64, "b" * 64, "c" * 64
FAILURE = OnlyResearchRunFailure(OnlyResearchRunFailurePhase.EXECUTION, "EXECUTION_FAILED", "explicit failure")


@pytest.fixture
def admitted(tmp_path):
    frozen = compilation(prepared_input(tmp_path))
    return only_chart_calculation_queued_run(frozen, queued_at=NOW), frozen


def _running(queued):
    return queued.transition(OnlyResearchRunState.RUNNING, at=NOW + timedelta(seconds=1))


def _requested(queued):
    return _running(queued).transition(OnlyResearchRunState.CANCEL_REQUESTED, at=NOW + timedelta(seconds=2))


def _completed(previous):
    return previous.transition(
        OnlyResearchRunState.COMPLETED,
        at=NOW + timedelta(seconds=3),
        research_result_fingerprint=RESULT,
        artifact_content_fingerprint=ARTIFACT,
        calculation_execution_evidence_fingerprints=(EVIDENCE,),
    )


@pytest.mark.parametrize(
    "outcome",
    [
        "queued",
        "direct_cancelled",
        "running",
        "requested",
        "completed",
        "cancel_completed",
        "failed",
        "cancel_failed",
        "cancelled",
        "failed_with_result",
    ],
)
def test_chart_lifecycle_keeps_immutable_admission_and_strict_row_round_trip(admitted, outcome):
    queued, frozen = admitted
    if outcome == "queued":
        previous, run = None, queued
    elif outcome == "direct_cancelled":
        previous = queued
        run = queued.transition(OnlyResearchRunState.CANCELLED, at=NOW + timedelta(seconds=1))
    elif outcome == "running":
        previous, run = queued, _running(queued)
    elif outcome == "requested":
        previous, run = _running(queued), _requested(queued)
    elif outcome in {"completed", "cancel_completed"}:
        previous = _running(queued) if outcome == "completed" else _requested(queued)
        run = _completed(previous)
    else:
        previous = _requested(queued) if outcome in {"cancelled", "cancel_failed"} else _running(queued)
        run = previous.transition(
            OnlyResearchRunState.CANCELLED if outcome == "cancelled" else OnlyResearchRunState.FAILED,
            at=NOW + timedelta(seconds=3),
            failure=None if outcome == "cancelled" else FAILURE,
            research_result_fingerprint=RESULT if outcome == "failed_with_result" else None,
            calculation_execution_evidence_fingerprints=(EVIDENCE,) if outcome == "failed_with_result" else (),
        )
    only_verify_chart_calculation_run(run, frozen)
    assert run.run_id == queued.run_id
    assert run.specification == queued.specification
    assert run.admission_resolution_fingerprint == queued.admission_resolution_fingerprint
    assert run.queued_at == queued.queued_at
    if previous is not None:
        assert run.revision == previous.revision + 1
        assert run.is_exact_successor_of(previous)
        assert run.cancel_requested_at == (
            NOW + timedelta(seconds=2)
            if run.state is OnlyResearchRunState.CANCEL_REQUESTED
            else previous.cancel_requested_at
        )
    row = dict(zip(_COLUMNS, OnlyPostgresResearchRunStore._values(run), strict=True))
    assert OnlyPostgresResearchRunStore._decode(row) == run
    if run.state.terminal:
        with pytest.raises(OnlyResearchRunStateConflictError):
            run.transition(OnlyResearchRunState.RUNNING, at=NOW + timedelta(seconds=4))


@pytest.mark.parametrize("state", ["queued", "running", "requested", "completed", "failed", "cancelled"])
@pytest.mark.parametrize("revision", [0, True, 99])
def test_chart_lifecycle_rejects_wrong_revision_for_the_complete_state_shape(admitted, state, revision):
    queued, _ = admitted
    running, requested = _running(queued), _requested(queued)
    run = {
        "queued": queued,
        "running": running,
        "requested": requested,
        "completed": _completed(requested),
        "failed": requested.transition(OnlyResearchRunState.FAILED, at=NOW + timedelta(seconds=3), failure=FAILURE),
        "cancelled": requested.transition(OnlyResearchRunState.CANCELLED, at=NOW + timedelta(seconds=3)),
    }[state]
    if state == "queued" and type(revision) is int and revision == 0:
        assert replace(run, revision=revision) == run
    else:
        with pytest.raises(OnlyResearchRunIntegrityError):
            replace(run, revision=revision)


@pytest.mark.parametrize("evidence", [(), ("d" * 64, "e" * 64), (EVIDENCE, EVIDENCE)])
def test_chart_completed_requires_one_exact_selected_evidence_reference(admitted, evidence):
    queued, _ = admitted
    with pytest.raises(OnlyResearchRunIntegrityError):
        replace(_completed(_running(queued)), calculation_execution_evidence_fingerprints=evidence)


@pytest.mark.parametrize("state", ["queued", "running", "requested", "cancelled"])
def test_chart_nonpublication_states_cannot_contain_result_or_artifact_projection(admitted, state):
    queued, _ = admitted
    run = {
        "queued": queued,
        "running": _running(queued),
        "requested": _requested(queued),
        "cancelled": _requested(queued).transition(OnlyResearchRunState.CANCELLED, at=NOW + timedelta(seconds=3)),
    }[state]
    for fields in (
        {"research_result_fingerprint": RESULT},
        {"research_result_fingerprint": RESULT, "artifact_content_fingerprint": ARTIFACT},
        {"research_result_fingerprint": RESULT, "calculation_execution_evidence_fingerprints": (EVIDENCE,)},
    ):
        with pytest.raises(OnlyResearchRunIntegrityError):
            replace(run, **fields)


@pytest.mark.parametrize("field", ["run_id", "admission_resolution_fingerprint"])
@pytest.mark.parametrize("state", ["running", "completed", "cancelled"])
def test_chart_admission_verification_never_uses_lifecycle_to_excuse_wrong_owner(admitted, field, state):
    queued, frozen = admitted
    run = {
        "running": _running(queued),
        "completed": _completed(_requested(queued)),
        "cancelled": _requested(queued).transition(OnlyResearchRunState.CANCELLED, at=NOW + timedelta(seconds=3)),
    }[state]
    wrong = OnlyResearchRunId("00000000-0000-4000-8000-000000000001") if field == "run_id" else "f" * 64
    assert getattr(run, field) != wrong
    with pytest.raises(OnlyChartCalculationError, match="CHART_RUN_ADMISSION_RELATION_CORRUPT"):
        only_verify_chart_calculation_run(replace(run, **{field: wrong}), frozen)


def test_chart_domain_successor_never_grants_generic_store_execution_permission(admitted):
    queued, _ = admitted
    running = _running(queued)
    store = OnlyPostgresResearchRunStore("not-a-connection-string")
    with pytest.raises(OnlyResearchRunStateConflictError, match="fenced Research Execution Store"):
        store.commit_transition(queued, running)
    with pytest.raises(OnlyResearchRunStateConflictError, match="fenced Research Execution Store"):
        store.commit_transition(running, _completed(running))
