from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry

from onlyalpha.application.product_boundary import (
    OnlyCancelResearchRun,
    OnlyCreateResearchRun,
    OnlyGetResearchRun,
    OnlyListResearchRuns,
    only_compose_research_product_boundary,
)
from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandKind,
    OnlyProductCommandReceipt,
)
from onlyalpha.canonical import only_canonical_json
from onlyalpha.kernel import OnlyAlphaKernelHost
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
from onlyalpha.research.provenance import (
    OnlyResearchAuthoringProvenance,
    only_research_execution_generation_fingerprint,
)
from onlyalpha.research.run import (
    OnlyResearchRun,
    OnlyResearchRunAdmissionError,
    OnlyResearchRunAdmissionService,
    OnlyResearchRunId,
    OnlyResearchRunIntegrityError,
    OnlyResearchRunRevisionConflictError,
    OnlyResearchRunState,
)
from onlyalpha.research.specification import OnlyResearchSpecificationResolver
from tests.research.specification.support import registry, specification
from tests.runtime_generation_support import only_ready_test_generation

NOW = datetime(2026, 8, 18, 1, 2, 3, 456789, tzinfo=UTC)
KEY = OnlyResearchSubmissionKey("00000000-0000-4000-8000-000000000001")
OTHER_KEY = OnlyResearchSubmissionKey("00000000-0000-4000-8000-000000000002")


class _RuntimeGenerations:
    def __init__(self) -> None:
        self.work: set[str] = set()

    def bind_new_work(self, work_id, **_):  # type: ignore[no-untyped-def]
        self.work.add(work_id)

    def release_work(self, work_id, **_):  # type: ignore[no-untyped-def]
        self.work.discard(work_id)

    def require_work_binding(self, work_id):  # type: ignore[no-untyped-def]
        if work_id not in self.work:
            raise ValueError("RUNTIME_WORK_GENERATION_UNBOUND")

    def require_work_generation(self, work_id, process_generation_fingerprint):  # type: ignore[no-untyped-def]
        del process_generation_fingerprint
        return self.require_work_binding(work_id)

    def work_ids_for_generation(self, process_generation_fingerprint):  # type: ignore[no-untyped-def]
        del process_generation_fingerprint
        return tuple(sorted(self.work))

    def verify_hosted_generation(self, generation_fingerprint):  # type: ignore[no-untyped-def]
        del generation_fingerprint


def _provenance(
    *, source_revision: str = "1" * 40, source_locator: str | None = None
) -> OnlyResearchAuthoringProvenance:
    identity = {
        "experiment_id": "exp-" + "a" * 32,
        "source_repository": "OnlyAlpha-alpha",
        "source_revision": source_revision,
        "source_tree": "2" * 40,
        "candidate_provider_id": "private.onlyalpha.alpha.candidate",
        "candidate_provider_version": "candidate-1",
        "candidate_provider_content_fingerprint": "3" * 64,
        "catalog_generation_fingerprint": "4" * 64,
    }
    return OnlyResearchAuthoringProvenance(
        schema_version=1,
        **identity,
        execution_generation_fingerprint=only_research_execution_generation_fingerprint(**identity),
        source_locator=source_locator,
    )


class _DatasetStore:
    def __init__(self, *, fail: bool = False) -> None:
        self.loads = 0
        self.fail = fail

    def load_verified_table(self, _fingerprint: str) -> object:
        self.loads += 1
        if self.fail:
            raise RuntimeError("dataset failed")
        return object()


class _AuthoringGenerations:
    def resolve(self, provenance, research_specification):  # type: ignore[no-untyped-def]
        if provenance.identity_dict() != _provenance().identity_dict():
            raise ValueError("generation mismatch")
        return OnlyResearchSpecificationResolver(registry()).resolve(research_specification)


class _Store:
    def __init__(self) -> None:
        self.runs: dict[OnlyResearchRunId, OnlyResearchRun] = {}
        self.receipts: dict[OnlyResearchSubmissionKey, OnlyProductCommandReceipt] = {}
        self.conflicts = 0

    def create_queued(self, run: OnlyResearchRun) -> OnlyResearchRun:
        self.runs[run.run_id] = run
        return run

    def find_product_command_receipt(self, key: OnlyResearchSubmissionKey) -> OnlyProductCommandReceipt | None:
        return self.receipts.get(key)

    def create_queued_with_receipt(
        self, run: OnlyResearchRun, receipt: OnlyProductCommandReceipt
    ) -> OnlyProductCommandReceipt:
        existing = self.receipts.get(receipt.command_id)
        if existing is not None:
            return existing
        self.runs[run.run_id] = run
        self.receipts[receipt.command_id] = receipt
        return receipt

    def request_cancellation_with_receipt(
        self, run_id: OnlyResearchRunId, receipt: OnlyProductCommandReceipt
    ) -> OnlyProductCommandReceipt:
        existing = self.receipts.get(receipt.command_id)
        if existing is not None:
            return existing
        current = self.runs[run_id]
        if current.state in {OnlyResearchRunState.COMPLETED, OnlyResearchRunState.FAILED}:
            raise OnlyResearchCancellationConflictError()
        if current.state not in {OnlyResearchRunState.CANCEL_REQUESTED, OnlyResearchRunState.CANCELLED}:
            target = (
                OnlyResearchRunState.CANCELLED
                if current.state is OnlyResearchRunState.QUEUED
                else OnlyResearchRunState.CANCEL_REQUESTED
            )
            self.runs[run_id] = current.transition(target, at=receipt.accepted_at)
        self.receipts[receipt.command_id] = receipt
        return receipt

    def load(self, run_id: OnlyResearchRunId) -> OnlyResearchRun:
        try:
            return self.runs[run_id]
        except KeyError as exc:
            from onlyalpha.research.run import OnlyResearchRunNotFoundError

            raise OnlyResearchRunNotFoundError(run_id.value) from exc

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
    store: _Store,
    dataset: _DatasetStore,
    *,
    ids: list[str] | None = None,
    times: list[datetime] | None = None,
    runtime_generations: object | None = None,
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
        authoring_generation_resolver=_AuthoringGenerations(),
    )
    return OnlyResearchCommandService(
        admission=admission,
        store=store,
        now_utc=lambda: next(clock),
        runtime_generations=runtime_generations or _RuntimeGenerations(),  # type: ignore[arg-type]
    )  # type: ignore[arg-type]


def test_formal_runs_bind_active_generation_across_activation_rollback_and_restart(tmp_path) -> None:  # type: ignore[no-untyped-def]
    authority = OnlyRuntimeGenerationRegistry(tmp_path / "runtime-authority")
    g1 = only_ready_test_generation(authority, "a", NOW)
    g2 = only_ready_test_generation(authority, "b", NOW + timedelta(seconds=1))
    authority.activate_for_new_work(
        expected_current=None,
        target=g1,
        actor="operator",
        occurred_at=NOW + timedelta(seconds=2),
    )
    store = _Store()
    service = _service(
        store,
        _DatasetStore(),
        ids=[
            "00000000-0000-4000-8000-000000000010",
            "00000000-0000-4000-8000-000000000011",
            "00000000-0000-4000-8000-000000000012",
        ],
        runtime_generations=authority,
    )
    r1 = service.submit_research_run(KEY, specification()).run
    authority.activate_for_new_work(
        expected_current=g1,
        target=g2,
        actor="operator",
        occurred_at=NOW + timedelta(seconds=3),
    )
    r2 = service.submit_research_run(OTHER_KEY, specification()).run
    authority.activate_for_new_work(
        expected_current=g2,
        target=g1,
        actor="operator",
        occurred_at=NOW + timedelta(seconds=4),
    )
    third = OnlyResearchSubmissionKey("00000000-0000-4000-8000-000000000003")
    r3 = service.submit_research_run(third, specification()).run

    restarted = OnlyRuntimeGenerationRegistry(tmp_path / "runtime-authority")
    assert restarted.require_work_binding(r1.run_id.value).runtime_generation_fingerprint == g1
    assert restarted.require_work_binding(r2.run_id.value).runtime_generation_fingerprint == g2
    assert restarted.require_work_binding(r3.run_id.value).runtime_generation_fingerprint == g1
    with pytest.raises(ValueError, match="RUNTIME_WORK_GENERATION_MISMATCH"):
        restarted.require_work_generation(r1.run_id.value, g2)
    assert restarted.require_work_binding(r1.run_id.value).runtime_generation_fingerprint == g1


def test_submission_key_requires_canonical_uuid4() -> None:
    assert str(KEY) == KEY.value
    for invalid in ("bad", "00000000-0000-1000-8000-000000000001", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa".upper()):
        with pytest.raises(ValueError):
            OnlyResearchSubmissionKey(invalid)


def test_command_constructor_record_and_cursor_evidence_fail_closed() -> None:
    run_id = OnlyResearchRunId("00000000-0000-4000-8000-000000000099")
    with pytest.raises(ValueError, match="positive"):
        OnlyResearchCommandService(  # type: ignore[arg-type]
            admission=object(),
            store=object(),
            now_utc=lambda: NOW,
            runtime_generations=_RuntimeGenerations(),
            cancellation_cas_attempts=0,
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
        def create_queued_with_receipt(self, run, receipt):  # type: ignore[no-untyped-def]
            self.runs[run.run_id] = run
            return OnlyProductCommandReceipt(
                receipt.command_id,
                receipt.command_kind,
                "f" * 64,
                receipt.outcome_ref,
                receipt.accepted_at,
            )

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


def test_dangling_receipt_fails_closed_without_creating_replacement_run() -> None:
    store, dataset = _Store(), _DatasetStore()
    service = _service(store, dataset)
    created = service.submit_research_run(KEY, specification())
    del store.runs[created.run.run_id]

    with pytest.raises(OnlyResearchRunIntegrityError, match="missing Research Run"):
        service.submit_research_run(KEY, specification())
    assert len(store.receipts) == 1


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
    record = store.receipts[KEY]
    store.receipts[KEY] = OnlyProductCommandReceipt(
        KEY,
        OnlyProductCommandKind.CREATE_RESEARCH_RUN,
        "f" * 64,
        record.outcome_ref,
        record.accepted_at,
    )
    with pytest.raises(OnlyResearchSubmissionConflictError):
        service.submit_research_run(KEY, spec)


def test_submission_identity_binds_authoritative_provenance_but_not_source_locator() -> None:
    store, dataset = _Store(), _DatasetStore()
    service = _service(store, dataset)
    created = service.submit_research_run(KEY, specification(), _provenance(source_locator="/first"))

    replayed = service.submit_research_run(KEY, specification(), _provenance(source_locator="/second"))
    assert replayed.disposition is OnlyResearchSubmitDisposition.REUSED
    assert replayed.run == created.run
    assert replayed.run.authoring_provenance == _provenance(source_locator="/first")

    with pytest.raises(OnlyResearchSubmissionConflictError):
        service.submit_research_run(KEY, specification(), _provenance(source_revision="5" * 40))


def test_admission_failure_persists_nothing() -> None:
    store = _Store()
    with pytest.raises(OnlyResearchRunAdmissionError):
        _service(store, _DatasetStore(fail=True)).submit_research_run(KEY, specification())
    assert store.runs == {}
    assert store.receipts == {}


def test_keyed_cancellation_uses_global_command_identity_and_replays_current_run() -> None:
    store, dataset = _Store(), _DatasetStore()
    service = _service(store, dataset)
    queued = service.submit_research_run(KEY, specification()).run
    cancel_key = OTHER_KEY

    cancelled = service.request_research_run_cancellation(queued.run_id, cancel_key)
    assert cancelled.state is OnlyResearchRunState.CANCELLED
    assert service.request_research_run_cancellation(queued.run_id, cancel_key) == cancelled
    assert len(store.receipts) == 2

    with pytest.raises(OnlyResearchSubmissionConflictError):
        service.request_research_run_cancellation(
            OnlyResearchRunId("00000000-0000-4000-8000-000000000099"),
            cancel_key,
        )
    with pytest.raises(OnlyResearchSubmissionConflictError):
        service.request_research_run_cancellation(queued.run_id, KEY)


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


def test_product_boundary_is_semantically_equivalent_to_direct_research_authorities() -> None:
    direct_store, boundary_store = _Store(), _Store()
    direct_dataset, boundary_dataset = _DatasetStore(), _DatasetStore()
    direct = _service(direct_store, direct_dataset)
    delegated = _service(boundary_store, boundary_dataset)
    kernel = OnlyAlphaKernelHost()
    kernel.start()
    boundary = only_compose_research_product_boundary(
        admission=kernel,
        commands=delegated,
        queries=OnlyResearchRunQueryService(boundary_store),  # type: ignore[arg-type]
    )
    spec = specification()

    direct_created = direct.submit_research_run(KEY, spec)
    boundary_created = boundary.commands.dispatch(OnlyCreateResearchRun(KEY, spec))
    assert boundary_created == direct_created
    assert boundary_dataset.loads == direct_dataset.loads == 1

    direct_get = OnlyResearchRunQueryService(direct_store).get_run(direct_created.run.run_id)  # type: ignore[arg-type]
    boundary_get = boundary.queries.dispatch(OnlyGetResearchRun(direct_created.run.run_id))
    assert boundary_get == direct_get

    direct_page = OnlyResearchRunQueryService(direct_store).list_runs(limit=1)  # type: ignore[arg-type]
    boundary_page = boundary.queries.dispatch(OnlyListResearchRuns(limit=1))
    assert boundary_page == direct_page

    direct_cancelled = direct.request_research_run_cancellation(direct_created.run.run_id)
    boundary_cancelled = boundary.commands.dispatch(OnlyCancelResearchRun(direct_created.run.run_id))
    assert boundary_cancelled == direct_cancelled
