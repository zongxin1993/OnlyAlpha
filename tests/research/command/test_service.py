from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from threading import Barrier, Lock, Thread
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
from onlyalpha.application.product_command_authority import (
    OnlyProductCommandConflictError,
    OnlyProductCommandPutDisposition,
)
from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandAdmissionV1,
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandOutcomeRef,
    OnlyProductCommandReceipt,
)
from onlyalpha.application.search_product import only_search_experiment_work_id
from onlyalpha.canonical import only_canonical_json
from onlyalpha.kernel import OnlyAlphaKernelHost
from onlyalpha.research.command import (
    OnlyDerivedResearchSubmitCommandV2,
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
    OnlyResearchSubmitCommand,
    OnlyResearchSubmitDisposition,
    only_derived_research_run_id,
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

    def bind_derived_work(self, parent_work_id, child_work_id, **_):  # type: ignore[no-untyped-def]
        if parent_work_id not in self.work:
            raise ValueError("RUNTIME_DERIVED_PARENT_GENERATION_UNBOUND")
        self.work.add(child_work_id)

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


class _ProductAdmissions:
    def __init__(self) -> None:
        self.values: dict[OnlyProductCommandId, OnlyProductCommandAdmissionV1] = {}
        self.lock = Lock()

    def admit_exact(self, admission):  # type: ignore[no-untyped-def]
        with self.lock:
            existing = self.values.get(admission.command_id)
            if existing is not None:
                if existing != admission:
                    raise OnlyProductCommandConflictError(admission.command_id.value)
                return OnlyProductCommandPutDisposition.REUSED
            self.values[admission.command_id] = admission
            return OnlyProductCommandPutDisposition.CREATED

    def load_admission(self, command_id):  # type: ignore[no-untyped-def]
        with self.lock:
            return self.values.get(command_id)


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
    command_admissions: object | None = None,
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
        command_admissions=command_admissions or _ProductAdmissions(),  # type: ignore[arg-type]
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


def test_search_derived_research_inherits_parent_generation_while_standalone_uses_active(tmp_path) -> None:
    authority = OnlyRuntimeGenerationRegistry(tmp_path / "runtime-authority")
    g1 = only_ready_test_generation(authority, "a", NOW)
    g2 = only_ready_test_generation(authority, "b", NOW + timedelta(seconds=1))
    authority.activate_for_new_work(
        expected_current=None, target=g1, actor="operator", occurred_at=NOW + timedelta(seconds=2)
    )
    parent = only_search_experiment_work_id("1" * 64)
    authority.bind_work_exact(parent, g1, actor="search", occurred_at=NOW + timedelta(seconds=3))
    authority.activate_for_new_work(
        expected_current=g1, target=g2, actor="operator", occurred_at=NOW + timedelta(seconds=4)
    )
    store = _Store()
    service = _service(
        store,
        _DatasetStore(),
        ids=[
            "00000000-0000-4000-8000-000000000020",
            "00000000-0000-4000-8000-000000000021",
        ],
        runtime_generations=authority,
    )
    derived_key = OnlyResearchSubmissionKey("00000000-0000-4000-8000-000000000004")
    derived = service.submit_research_run(
        derived_key,
        specification(),
        parent_runtime_work_id=parent,
    ).run
    assert authority.require_work_binding(derived.run_id.value).runtime_generation_fingerprint == g1
    assert (
        service.submit_research_run(
            derived_key,
            specification(),
            parent_runtime_work_id=parent,
        ).run
        == derived
    )

    standalone_key = OnlyResearchSubmissionKey("00000000-0000-4000-8000-000000000005")
    standalone = service.submit_research_run(standalone_key, specification()).run
    assert authority.require_work_binding(standalone.run_id.value).runtime_generation_fingerprint == g2


def test_search_derived_research_prebound_to_another_generation_fails_before_run_commit(tmp_path) -> None:
    authority = OnlyRuntimeGenerationRegistry(tmp_path / "runtime-authority")
    g1 = only_ready_test_generation(authority, "a", NOW)
    g2 = only_ready_test_generation(authority, "b", NOW + timedelta(seconds=1))
    authority.activate_for_new_work(
        expected_current=None, target=g1, actor="operator", occurred_at=NOW + timedelta(seconds=2)
    )
    parent = only_search_experiment_work_id("2" * 64)
    authority.bind_work_exact(parent, g1, actor="search", occurred_at=NOW + timedelta(seconds=3))
    authority.activate_for_new_work(
        expected_current=g1, target=g2, actor="operator", occurred_at=NOW + timedelta(seconds=4)
    )
    derived_key = OnlyResearchSubmissionKey("00000000-0000-4000-8000-000000000006")
    child_id = only_derived_research_run_id(derived_key).value
    authority.bind_new_work(child_id, actor="conflicting-root", occurred_at=NOW + timedelta(seconds=5))
    store = _Store()
    service = _service(
        store,
        _DatasetStore(),
        ids=[child_id],
        runtime_generations=authority,
    )
    with pytest.raises(ValueError, match="RUNTIME_DERIVED_WORK_GENERATION_BINDING_CONFLICT"):
        service.submit_research_run(
            derived_key,
            specification(),
            parent_runtime_work_id=parent,
        )
    assert store.runs == {}
    assert store.receipts == {}


def test_derived_identity_and_parent_operational_intent_are_deterministic() -> None:
    first_parent = only_search_experiment_work_id("a" * 64)
    second_parent = only_search_experiment_work_id("b" * 64)
    first = OnlyDerivedResearchSubmitCommandV2(KEY, specification(), first_parent)
    same = OnlyDerivedResearchSubmitCommandV2(KEY, specification(), first_parent)
    changed_parent = OnlyDerivedResearchSubmitCommandV2(KEY, specification(), second_parent)

    assert first.command_fingerprint == same.command_fingerprint
    assert first.command_fingerprint != changed_parent.command_fingerprint
    assert only_derived_research_run_id(KEY) == only_derived_research_run_id(KEY)
    assert only_derived_research_run_id(KEY) != only_derived_research_run_id(OTHER_KEY)
    assert OnlyResearchSubmitCommand(KEY, specification()).command_fingerprint == (
        "221f9baaf1fe4c15ba25d9ccb4cb9e6e02722ee17b046e4a8ed66a2a0f3c0c08"
    )


def test_derived_replay_rejects_wrong_existing_run_even_when_runtime_generation_matches(tmp_path) -> None:
    class LoadRecordingStore(_Store):
        def __init__(self) -> None:
            super().__init__()
            self.loaded_run_ids: list[OnlyResearchRunId] = []

        def load(self, run_id: OnlyResearchRunId) -> OnlyResearchRun:
            self.loaded_run_ids.append(run_id)
            return super().load(run_id)

    authority = OnlyRuntimeGenerationRegistry(tmp_path / "runtime-authority")
    generation = only_ready_test_generation(authority, "a", NOW)
    authority.activate_for_new_work(
        expected_current=None,
        target=generation,
        actor="operator",
        occurred_at=NOW + timedelta(seconds=1),
    )
    parent = only_search_experiment_work_id("c" * 64)
    authority.bind_work_exact(parent, generation, actor="search", occurred_at=NOW + timedelta(seconds=2))
    store = LoadRecordingStore()
    admissions = _ProductAdmissions()
    service = _service(
        store,
        _DatasetStore(),
        ids=["00000000-0000-4000-8000-000000000030"],
        runtime_generations=authority,
        command_admissions=admissions,
    )
    wrong_run = service.submit_research_run(OTHER_KEY, specification()).run
    derived_key = OnlyResearchSubmissionKey("00000000-0000-4000-8000-00000000000e")
    command = OnlyDerivedResearchSubmitCommandV2(derived_key, specification(), parent)
    admissions.admit_exact(
        OnlyProductCommandAdmissionV1(
            derived_key,
            OnlyProductCommandKind.CREATE_RESEARCH_RUN,
            command.command_fingerprint,
        )
    )
    store.receipts[derived_key] = OnlyProductCommandReceipt(
        derived_key,
        OnlyProductCommandKind.CREATE_RESEARCH_RUN,
        command.command_fingerprint,
        OnlyProductCommandOutcomeRef(OnlyProductCommandOutcomeKind.RESEARCH_RUN, wrong_run.run_id.value),
        NOW,
    )
    runs_before = dict(store.runs)
    receipts_before = dict(store.receipts)
    bindings_before = dict(authority.projection().work_bindings)
    loads_before = tuple(store.loaded_run_ids)

    with pytest.raises(OnlyResearchSubmissionConflictError):
        service.submit_research_run(derived_key, specification(), parent_runtime_work_id=parent)

    assert store.runs == runs_before
    assert store.receipts == receipts_before
    assert dict(authority.projection().work_bindings) == bindings_before
    assert tuple(store.loaded_run_ids) == loads_before
    assert only_derived_research_run_id(derived_key) not in store.runs


def test_derived_post_create_winning_receipt_must_reference_canonical_run(tmp_path) -> None:
    derived_key = OnlyResearchSubmissionKey("00000000-0000-4000-8000-00000000000f")
    parent = only_search_experiment_work_id("d" * 64)
    command = OnlyDerivedResearchSubmitCommandV2(derived_key, specification(), parent)

    class WinningReceiptStore(_Store):
        hide_receipt_once = True

        def find_product_command_receipt(self, key):  # type: ignore[no-untyped-def]
            if key == derived_key and self.hide_receipt_once:
                self.hide_receipt_once = False
                return None
            return super().find_product_command_receipt(key)

        def create_queued_with_receipt(self, run, receipt):  # type: ignore[no-untyped-def]
            del run, receipt
            return self.receipts[derived_key]

    authority = OnlyRuntimeGenerationRegistry(tmp_path / "runtime-authority")
    generation = only_ready_test_generation(authority, "a", NOW)
    authority.activate_for_new_work(
        expected_current=None,
        target=generation,
        actor="operator",
        occurred_at=NOW + timedelta(seconds=1),
    )
    authority.bind_work_exact(parent, generation, actor="search", occurred_at=NOW + timedelta(seconds=2))
    expected_run_id = only_derived_research_run_id(derived_key)
    authority.bind_derived_work(
        parent,
        expected_run_id.value,
        actor="concurrent-derived-admission",
        occurred_at=NOW + timedelta(seconds=3),
    )
    store = WinningReceiptStore()
    wrong_run = OnlyResearchRun.queued(
        run_id=OnlyResearchRunId("00000000-0000-4000-8000-000000000031"),
        specification=specification(),
        canonical_specification_payload=only_canonical_json(specification().to_dict()),
        admission_resolution_fingerprint="a" * 64,
        queued_at=NOW,
    )
    store.runs[wrong_run.run_id] = wrong_run
    store.receipts[derived_key] = OnlyProductCommandReceipt(
        derived_key,
        OnlyProductCommandKind.CREATE_RESEARCH_RUN,
        command.command_fingerprint,
        OnlyProductCommandOutcomeRef(OnlyProductCommandOutcomeKind.RESEARCH_RUN, wrong_run.run_id.value),
        NOW,
    )
    admissions = _ProductAdmissions()
    admissions.admit_exact(
        OnlyProductCommandAdmissionV1(
            derived_key,
            OnlyProductCommandKind.CREATE_RESEARCH_RUN,
            command.command_fingerprint,
        )
    )
    service = _service(
        store,
        _DatasetStore(),
        runtime_generations=authority,
        command_admissions=admissions,
    )
    runs_before = dict(store.runs)
    receipts_before = dict(store.receipts)
    bindings_before = dict(authority.projection().work_bindings)

    with pytest.raises(OnlyResearchSubmissionConflictError):
        service.submit_research_run(derived_key, specification(), parent_runtime_work_id=parent)

    assert store.runs == runs_before
    assert store.receipts == receipts_before
    assert dict(authority.projection().work_bindings) == bindings_before


def test_derived_binding_crash_before_run_commit_recovers_same_run_without_orphan(tmp_path) -> None:
    class CrashOnceStore(_Store):
        crash = True

        def create_queued_with_receipt(self, run, receipt):  # type: ignore[no-untyped-def]
            if self.crash:
                self.crash = False
                raise RuntimeError("injected crash after Runtime binding")
            return super().create_queued_with_receipt(run, receipt)

    authority = OnlyRuntimeGenerationRegistry(tmp_path / "runtime-authority")
    generation = only_ready_test_generation(authority, "a", NOW)
    authority.activate_for_new_work(
        expected_current=None,
        target=generation,
        actor="operator",
        occurred_at=NOW + timedelta(seconds=1),
    )
    parent = only_search_experiment_work_id("3" * 64)
    authority.bind_work_exact(parent, generation, actor="search", occurred_at=NOW + timedelta(seconds=2))
    store = CrashOnceStore()
    admissions = _ProductAdmissions()
    service = _service(
        store,
        _DatasetStore(),
        runtime_generations=authority,
        command_admissions=admissions,
    )
    derived_key = OnlyResearchSubmissionKey("00000000-0000-4000-8000-000000000007")
    expected_run_id = only_derived_research_run_id(derived_key)

    with pytest.raises(RuntimeError, match="injected crash"):
        service.submit_research_run(derived_key, specification(), parent_runtime_work_id=parent)
    assert store.runs == {}
    assert store.receipts == {}
    assert set(authority.projection().work_bindings) == {parent, expected_run_id.value}

    recovered = service.submit_research_run(
        derived_key,
        specification(),
        parent_runtime_work_id=parent,
    )
    assert recovered.run.run_id == expected_run_id
    assert tuple(store.runs) == (expected_run_id,)
    assert tuple(store.receipts) == (derived_key,)
    assert set(authority.projection().work_bindings) == {parent, expected_run_id.value}


def test_derived_retry_conflicts_on_different_parent_even_when_generation_matches(tmp_path) -> None:
    class AlwaysCrashStore(_Store):
        def create_queued_with_receipt(self, run, receipt):  # type: ignore[no-untyped-def]
            raise RuntimeError("injected crash after Runtime binding")

    authority = OnlyRuntimeGenerationRegistry(tmp_path / "runtime-authority")
    generation = only_ready_test_generation(authority, "a", NOW)
    authority.activate_for_new_work(
        expected_current=None,
        target=generation,
        actor="operator",
        occurred_at=NOW + timedelta(seconds=1),
    )
    parents = tuple(only_search_experiment_work_id(value * 64) for value in ("4", "5"))
    for offset, parent in enumerate(parents, start=2):
        authority.bind_work_exact(parent, generation, actor="search", occurred_at=NOW + timedelta(seconds=offset))
    admissions = _ProductAdmissions()
    service = _service(
        AlwaysCrashStore(),
        _DatasetStore(),
        runtime_generations=authority,
        command_admissions=admissions,
    )
    derived_key = OnlyResearchSubmissionKey("00000000-0000-4000-8000-000000000008")
    with pytest.raises(RuntimeError, match="injected crash"):
        service.submit_research_run(derived_key, specification(), parent_runtime_work_id=parents[0])
    with pytest.raises(OnlyResearchSubmissionConflictError):
        service.submit_research_run(derived_key, specification(), parent_runtime_work_id=parents[1])
    assert (
        admissions.values[derived_key].command_fingerprint
        == OnlyDerivedResearchSubmitCommandV2(
            derived_key,
            specification(),
            parents[0],
        ).command_fingerprint
    )


def test_terminal_derived_replay_uses_historical_inactive_binding(tmp_path) -> None:
    authority = OnlyRuntimeGenerationRegistry(tmp_path / "runtime-authority")
    generation = only_ready_test_generation(authority, "a", NOW)
    authority.activate_for_new_work(
        expected_current=None,
        target=generation,
        actor="operator",
        occurred_at=NOW + timedelta(seconds=1),
    )
    parent = only_search_experiment_work_id("6" * 64)
    authority.bind_work_exact(parent, generation, actor="search", occurred_at=NOW + timedelta(seconds=2))
    store = _Store()
    service = _service(store, _DatasetStore(), runtime_generations=authority)
    derived_key = OnlyResearchSubmissionKey("00000000-0000-4000-8000-000000000009")
    created = service.submit_research_run(derived_key, specification(), parent_runtime_work_id=parent).run
    completed = created.transition(OnlyResearchRunState.RUNNING, at=NOW + timedelta(seconds=3)).transition(
        OnlyResearchRunState.COMPLETED,
        at=NOW + timedelta(seconds=4),
        research_result_fingerprint="e" * 64,
        artifact_content_fingerprint="f" * 64,
    )
    store.runs[created.run_id] = completed
    authority.release_work(created.run_id.value, actor="worker", occurred_at=NOW + timedelta(seconds=5))

    replayed = service.submit_research_run(
        derived_key,
        specification(),
        parent_runtime_work_id=parent,
    )
    assert replayed.disposition is OnlyResearchSubmitDisposition.REUSED
    assert replayed.run == completed
    assert authority.require_work_binding(created.run_id.value).active is False


def test_new_derived_work_requires_active_parent_but_bound_recovery_does_not(tmp_path) -> None:
    class CrashOnceStore(_Store):
        crash = True

        def create_queued_with_receipt(self, run, receipt):  # type: ignore[no-untyped-def]
            if self.crash:
                self.crash = False
                raise RuntimeError("injected crash after Runtime binding")
            return super().create_queued_with_receipt(run, receipt)

    authority = OnlyRuntimeGenerationRegistry(tmp_path / "runtime-authority")
    generation = only_ready_test_generation(authority, "a", NOW)
    authority.activate_for_new_work(
        expected_current=None,
        target=generation,
        actor="operator",
        occurred_at=NOW + timedelta(seconds=1),
    )
    parent = only_search_experiment_work_id("7" * 64)
    authority.bind_work_exact(parent, generation, actor="search", occurred_at=NOW + timedelta(seconds=2))
    store = CrashOnceStore()
    service = _service(store, _DatasetStore(), runtime_generations=authority)
    recovery_key = OnlyResearchSubmissionKey("00000000-0000-4000-8000-00000000000a")
    with pytest.raises(RuntimeError, match="injected crash"):
        service.submit_research_run(recovery_key, specification(), parent_runtime_work_id=parent)
    authority.release_work(parent, actor="search", occurred_at=NOW + timedelta(seconds=3))
    assert service.submit_research_run(
        recovery_key,
        specification(),
        parent_runtime_work_id=parent,
    ).run.run_id == only_derived_research_run_id(recovery_key)

    new_key = OnlyResearchSubmissionKey("00000000-0000-4000-8000-00000000000b")
    with pytest.raises(ValueError, match="RUNTIME_DERIVED_PARENT_GENERATION_UNBOUND"):
        service.submit_research_run(new_key, specification(), parent_runtime_work_id=parent)
    assert only_derived_research_run_id(new_key).value not in authority.projection().work_bindings


def test_concurrent_same_derived_command_converges_on_one_run_and_receipt(tmp_path) -> None:
    gate = Barrier(2)
    commit_lock = Lock()

    class RacingStore(_Store):
        def create_queued_with_receipt(self, run, receipt):  # type: ignore[no-untyped-def]
            gate.wait()
            with commit_lock:
                return super().create_queued_with_receipt(run, receipt)

    authority = OnlyRuntimeGenerationRegistry(tmp_path / "runtime-authority")
    generation = only_ready_test_generation(authority, "a", NOW)
    authority.activate_for_new_work(
        expected_current=None,
        target=generation,
        actor="operator",
        occurred_at=NOW + timedelta(seconds=1),
    )
    parent = only_search_experiment_work_id("8" * 64)
    authority.bind_work_exact(parent, generation, actor="search", occurred_at=NOW + timedelta(seconds=2))
    store = RacingStore()
    service = _service(store, _DatasetStore(), runtime_generations=authority)
    derived_key = OnlyResearchSubmissionKey("00000000-0000-4000-8000-00000000000c")
    outcomes: list[OnlyResearchRun] = []

    def submit() -> None:
        outcomes.append(
            service.submit_research_run(
                derived_key,
                specification(),
                parent_runtime_work_id=parent,
            ).run
        )

    threads = (Thread(target=submit), Thread(target=submit))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    expected = only_derived_research_run_id(derived_key)
    assert [item.run_id for item in outcomes] == [expected, expected]
    assert tuple(store.runs) == (expected,)
    assert tuple(store.receipts) == (derived_key,)
    assert set(authority.projection().work_bindings) == {parent, expected.value}


def test_concurrent_same_key_different_parent_has_one_product_intent_winner(tmp_path) -> None:
    admission_gate = Barrier(2)

    class RacingAdmissions(_ProductAdmissions):
        def admit_exact(self, admission):  # type: ignore[no-untyped-def]
            admission_gate.wait()
            return super().admit_exact(admission)

    authority = OnlyRuntimeGenerationRegistry(tmp_path / "runtime-authority")
    generation = only_ready_test_generation(authority, "a", NOW)
    authority.activate_for_new_work(
        expected_current=None,
        target=generation,
        actor="operator",
        occurred_at=NOW + timedelta(seconds=1),
    )
    parents = tuple(only_search_experiment_work_id(value * 64) for value in ("9", "a"))
    for offset, parent in enumerate(parents, start=2):
        authority.bind_work_exact(parent, generation, actor="search", occurred_at=NOW + timedelta(seconds=offset))
    store = _Store()
    service = _service(
        store,
        _DatasetStore(),
        runtime_generations=authority,
        command_admissions=RacingAdmissions(),
    )
    derived_key = OnlyResearchSubmissionKey("00000000-0000-4000-8000-00000000000d")
    outcomes: list[str] = []

    def submit(parent: str) -> None:
        try:
            result = service.submit_research_run(
                derived_key,
                specification(),
                parent_runtime_work_id=parent,
            )
            outcomes.append(result.run.run_id.value)
        except OnlyResearchSubmissionConflictError:
            outcomes.append("CONFLICT")

    threads = tuple(Thread(target=submit, args=(parent,)) for parent in parents)
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    expected = only_derived_research_run_id(derived_key)
    assert sorted(outcomes) == sorted([expected.value, "CONFLICT"])
    assert tuple(store.runs) == (expected,)
    assert tuple(store.receipts) == (derived_key,)
    assert set(authority.projection().work_bindings) == {*parents, expected.value}


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
