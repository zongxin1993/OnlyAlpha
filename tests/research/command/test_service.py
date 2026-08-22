from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.command import (
    OnlyResearchCancellationConflictError,
    OnlyResearchCommandConcurrencyError,
    OnlyResearchCommandService,
    OnlyResearchRunCursorError,
    OnlyResearchRunPageCursor,
    OnlyResearchRunPageLimitError,
    OnlyResearchRunQueryService,
    OnlyResearchSubmissionConflictError,
    OnlyResearchSubmissionKey,
    OnlyResearchSubmissionRecord,
    OnlyResearchSubmitDisposition,
)
from onlyalpha.research.run import (
    OnlyResearchRun,
    OnlyResearchRunAdmissionError,
    OnlyResearchRunAdmissionService,
    OnlyResearchRunId,
    OnlyResearchRunRevisionConflictError,
    OnlyResearchRunState,
)
from onlyalpha.research.specification import OnlyResearchSpecificationResolver
from tests.research.specification.support import registry, specification

NOW = datetime(2026, 8, 18, 1, 2, 3, 456789, tzinfo=UTC)
KEY = OnlyResearchSubmissionKey("00000000-0000-4000-8000-000000000001")
OTHER_KEY = OnlyResearchSubmissionKey("00000000-0000-4000-8000-000000000002")


class _DatasetStore:
    def __init__(self, *, fail: bool = False) -> None:
        self.loads = 0
        self.fail = fail

    def load_verified_table(self, _fingerprint: str) -> object:
        self.loads += 1
        if self.fail:
            raise RuntimeError("dataset failed")
        return object()


class _Store:
    def __init__(self) -> None:
        self.runs: dict[OnlyResearchRunId, OnlyResearchRun] = {}
        self.submissions: dict[OnlyResearchSubmissionKey, OnlyResearchSubmissionRecord] = {}
        self.conflicts = 0

    def create_queued(self, run: OnlyResearchRun) -> OnlyResearchRun:
        self.runs[run.run_id] = run
        return run

    def find_submission(self, key: OnlyResearchSubmissionKey) -> OnlyResearchSubmissionRecord | None:
        return self.submissions.get(key)

    def create_queued_submission(
        self, run: OnlyResearchRun, key: OnlyResearchSubmissionKey, command_fingerprint: str
    ) -> OnlyResearchSubmissionRecord:
        existing = self.submissions.get(key)
        if existing is not None:
            return existing
        self.runs[run.run_id] = run
        record = OnlyResearchSubmissionRecord(key, command_fingerprint, run.run_id)
        self.submissions[key] = record
        return record

    def load(self, run_id: OnlyResearchRunId) -> OnlyResearchRun:
        return self.runs[run_id]

    def commit_transition(self, previous: OnlyResearchRun, transitioned: OnlyResearchRun) -> OnlyResearchRun:
        if self.conflicts:
            self.conflicts -= 1
            raise OnlyResearchRunRevisionConflictError("race")
        self.runs[previous.run_id] = transitioned
        return transitioned

    def list_recent(self, *, limit: int, after: OnlyResearchRunPageCursor | None = None) -> tuple[OnlyResearchRun, ...]:
        ordered = sorted(self.runs.values(), key=lambda item: (item.queued_at, item.run_id), reverse=True)
        if after is not None:
            ordered = [item for item in ordered if (item.queued_at, item.run_id) < (after.queued_at, after.run_id)]
        return tuple(ordered[:limit])


def _service(
    store: _Store, dataset: _DatasetStore, *, ids: list[str] | None = None, times: list[datetime] | None = None
) -> OnlyResearchCommandService:
    run_ids = iter(
        ids
        or [
            "00000000-0000-4000-8000-000000000010",
            "00000000-0000-4000-8000-000000000011",
        ]
    )
    clock = iter(times or [NOW] * 20)
    admission = OnlyResearchRunAdmissionService(
        resolver=OnlyResearchSpecificationResolver(registry()),
        dataset_store=dataset,  # type: ignore[arg-type]
        run_store=store,  # type: ignore[arg-type]
        now_utc=lambda: next(clock),
        run_id_factory=lambda: OnlyResearchRunId(next(run_ids)),
    )
    return OnlyResearchCommandService(admission=admission, store=store, now_utc=lambda: next(clock))  # type: ignore[arg-type]


def test_submission_key_requires_canonical_uuid4() -> None:
    assert str(KEY) == KEY.value
    for invalid in ("bad", "00000000-0000-1000-8000-000000000001", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa".upper()):
        with pytest.raises(ValueError):
            OnlyResearchSubmissionKey(invalid)


def test_command_constructor_record_and_cursor_evidence_fail_closed() -> None:
    run_id = OnlyResearchRunId("00000000-0000-4000-8000-000000000099")
    with pytest.raises(ValueError, match="positive"):
        OnlyResearchCommandService(  # type: ignore[arg-type]
            admission=object(), store=object(), now_utc=lambda: NOW, cancellation_cas_attempts=0
        )
    with pytest.raises(ValueError, match="record"):
        OnlyResearchSubmissionRecord(cast(object, KEY), "bad", run_id)
    with pytest.raises(ValueError, match="timezone-aware"):
        OnlyResearchRunPageCursor(datetime(2026, 8, 18), run_id).encode()

    cursor = OnlyResearchRunPageCursor(NOW, run_id)
    payload = only_canonical_json({"queued_at": NOW.isoformat(), "run_id": run_id.value, "v": 1})
    noncanonical = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    assert noncanonical != cursor.encode()
    with pytest.raises(OnlyResearchRunCursorError):
        OnlyResearchRunPageCursor.decode(noncanonical)


def test_submission_detects_conflicting_record_created_by_store() -> None:
    class ConflictingStore(_Store):
        def create_queued_submission(self, run, key, command_fingerprint):  # type: ignore[no-untyped-def]
            self.runs[run.run_id] = run
            return OnlyResearchSubmissionRecord(key, "f" * 64, run.run_id)

    with pytest.raises(OnlyResearchSubmissionConflictError):
        _service(ConflictingStore(), _DatasetStore()).submit_research_run(KEY, specification())


def test_submit_replay_is_durable_and_skips_environment_dependent_admission() -> None:
    store, dataset = _Store(), _DatasetStore()
    service = _service(store, dataset)
    created = service.submit_research_run(KEY, specification())
    dataset.fail = True
    reused = service.submit_research_run(KEY, specification())

    assert created.disposition is OnlyResearchSubmitDisposition.CREATED
    assert reused.disposition is OnlyResearchSubmitDisposition.REUSED
    assert reused.run.run_id == created.run.run_id
    assert dataset.loads == 1
    assert len(store.runs) == 1


def test_same_key_different_command_conflicts_but_different_keys_create_distinct_runs() -> None:
    store, dataset = _Store(), _DatasetStore()
    service = _service(
        store,
        dataset,
        ids=["00000000-0000-4000-8000-000000000010", "00000000-0000-4000-8000-000000000011"],
    )
    spec = specification()
    first = service.submit_research_run(KEY, spec)
    second = service.submit_research_run(OTHER_KEY, spec)
    assert first.run.run_id != second.run.run_id
    record = store.submissions[KEY]
    store.submissions[KEY] = OnlyResearchSubmissionRecord(KEY, "f" * 64, record.run_id)
    with pytest.raises(OnlyResearchSubmissionConflictError):
        service.submit_research_run(KEY, spec)


def test_admission_failure_persists_nothing() -> None:
    store = _Store()
    with pytest.raises(OnlyResearchRunAdmissionError):
        _service(store, _DatasetStore(fail=True)).submit_research_run(KEY, specification())
    assert store.runs == {}
    assert store.submissions == {}


def test_cancellation_state_matrix_and_idempotency() -> None:
    store, dataset = _Store(), _DatasetStore()
    service = _service(store, dataset)
    queued = service.submit_research_run(KEY, specification()).run
    cancelled = service.request_research_run_cancellation(queued.run_id)
    assert cancelled.state is OnlyResearchRunState.CANCELLED
    assert service.request_research_run_cancellation(queued.run_id) == cancelled

    running = service.submit_research_run(OTHER_KEY, specification()).run.transition(
        OnlyResearchRunState.RUNNING, at=NOW
    )
    store.runs[running.run_id] = running
    requested = service.request_research_run_cancellation(running.run_id)
    assert requested.state is OnlyResearchRunState.CANCEL_REQUESTED
    assert service.request_research_run_cancellation(running.run_id) == requested

    for state in (OnlyResearchRunState.COMPLETED, OnlyResearchRunState.FAILED):
        terminal = running
        if state is OnlyResearchRunState.COMPLETED:
            terminal = running.transition(
                state,
                at=NOW + timedelta(seconds=3),
                research_result_fingerprint="a" * 64,
                artifact_content_fingerprint="b" * 64,
            )
        else:
            from onlyalpha.research.run import OnlyResearchRunFailure, OnlyResearchRunFailurePhase

            terminal = running.transition(
                state,
                at=NOW + timedelta(seconds=3),
                failure=OnlyResearchRunFailure(OnlyResearchRunFailurePhase.EXECUTION, "FAILED", "detail"),
            )
        store.runs[running.run_id] = terminal
        with pytest.raises(OnlyResearchCancellationConflictError):
            service.request_research_run_cancellation(running.run_id)


def test_cancellation_reloads_after_cas_conflict_and_is_bounded() -> None:
    store, dataset = _Store(), _DatasetStore()
    times = [NOW + timedelta(seconds=value) for value in range(10)]
    service = _service(store, dataset, times=times)
    queued = service.submit_research_run(KEY, specification()).run
    store.conflicts = 1
    cancelled = service.request_research_run_cancellation(queued.run_id)
    assert cancelled.finished_at == NOW + timedelta(seconds=2)

    store.runs[queued.run_id] = queued
    store.conflicts = 3
    with pytest.raises(OnlyResearchCommandConcurrencyError):
        service.request_research_run_cancellation(queued.run_id)


def test_cursor_round_trip_rejects_noncanonical_input_and_pages_stably() -> None:
    cursor = OnlyResearchRunPageCursor(NOW, OnlyResearchRunId("00000000-0000-4000-8000-000000000010"))
    assert OnlyResearchRunPageCursor.decode(cursor.encode()) == cursor
    for invalid in ("", cursor.encode() + "=", "not-base64", "e30"):
        with pytest.raises(OnlyResearchRunCursorError):
            OnlyResearchRunPageCursor.decode(invalid)

    store, dataset = _Store(), _DatasetStore()
    service = _service(
        store,
        dataset,
        ids=[f"00000000-0000-4000-8000-{value:012d}" for value in (10, 11, 12)],
        times=[NOW, NOW, NOW],
    )
    for key in (KEY, OTHER_KEY, OnlyResearchSubmissionKey("00000000-0000-4000-8000-000000000003")):
        service.submit_research_run(key, specification())
    query = OnlyResearchRunQueryService(store)  # type: ignore[arg-type]
    first = query.list_runs(limit=2)
    second = query.list_runs(limit=2, cursor=first.next_cursor)
    assert first.has_more and first.next_cursor is not None
    assert not set(item.run_id for item in first.runs) & set(item.run_id for item in second.runs)
    assert [item.run_id.value for item in first.runs] == sorted(
        [item.run_id.value for item in first.runs], reverse=True
    )
    with pytest.raises(OnlyResearchRunPageLimitError):
        query.list_runs(limit=0)
