from __future__ import annotations

from dataclasses import replace
from threading import Barrier, Lock, Thread

import pytest

from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.research.command import OnlyResearchCommandService, OnlyResearchSubmitDisposition
from onlyalpha.research.command.errors import OnlyNoveltyResearchAdmissionError, OnlyResearchSubmissionConflictError
from onlyalpha.research.command.novelty_admission import (
    OnlyResearchNoveltyAdmissionV1,
    OnlyResearchNoveltyAdmissionV2,
    only_novelty_same_subject_guard_key,
)
from onlyalpha.research.evaluation import OnlyExactEvaluationIntentResolverV1
from onlyalpha.research.memory.projector import OnlyExperimentMemoryProjectionV1
from onlyalpha.research.memory.source_manifest import MANDATORY_FAMILIES, OnlyExperimentMemorySourceCutManifestV1
from onlyalpha.research.memory.store import OnlyExperimentMemoryRevisionStore
from onlyalpha.research.novelty import (
    OnlyNoveltyDecisionAuthority,
    OnlyNoveltyDecisionGroupV1,
    OnlyNoveltyDecisionRequestV2,
    OnlyNoveltyPolicyOutcome,
    OnlyNoveltyPolicyStore,
)
from onlyalpha.research.run import OnlyResearchRunAdmissionService, OnlyResearchRunState
from onlyalpha.research.source_cut import OnlySourceClosedCutV1
from onlyalpha.research.specification import OnlyResearchSpecificationResolver
from tests.research.command.test_service import (
    NOW,
    _DatasetStore,
    _ProductAdmissions,
    _RuntimeAdmissionResolver,
    _Store,
)
from tests.research.evaluation.test_subject import _resolve, _scientific
from tests.research.novelty.test_decision import _projection, _projection_for_subject
from tests.research.novelty.test_policy import policy
from tests.research.specification.support import registry
from tests.runtime_support.generation_support import OnlyTestRuntimeGenerationAuthority


def _manifest(frontier: int = 0) -> OnlyExperimentMemorySourceCutManifestV1:
    postgres = {
        "RESEARCH_RUN",
        "RESEARCH_ATTEMPT",
        "PRODUCT_COMMAND_ADMISSION",
        "PRODUCT_COMMAND_RECEIPT",
    }
    return OnlyExperimentMemorySourceCutManifestV1.from_cuts(
        [
            OnlySourceClosedCutV1(
                family,
                1,
                (),
                f"JOURNAL_INDEX:{frontier}" if family in postgres else "TEST_CLOSED_CUT_V1",
                "SOURCE_TRANSACTIONAL_JOURNAL_V1" if family in postgres else "TEST_COMPLETE_V1",
            )
            for family in MANDATORY_FAMILIES
        ]
    )


class _MemoryBuilder:
    def __init__(self, revisions: OnlyExperimentMemoryRevisionStore, *, stale_subject=None) -> None:  # type: ignore[no-untyped-def]
        self.revisions = revisions
        self.manifest = _manifest()
        self.stale_subject = stale_subject

    def capture_manifest(self) -> OnlyExperimentMemorySourceCutManifestV1:
        return self.manifest

    def publish_and_activate(
        self, manifest: OnlyExperimentMemorySourceCutManifestV1
    ) -> OnlyExperimentMemoryProjectionV1:
        records = ()
        if self.stale_subject is not None:
            cuts = {cut.source_family: cut.cut_fingerprint for cut in manifest.cuts}
            source = next(
                record
                for record in _projection_for_subject(_projection(), self.stale_subject).records
                if record.kind == "EvaluationProjectionRecord"
                and record.facets.get("candidate_fingerprint") == self.stale_subject.candidate_fingerprint
            )
            records = tuple(
                type(record)(
                    record.kind,
                    record.facets,
                    tuple(replace(ref, cut_fingerprint=cuts[ref.source_family]) for ref in record.source_refs),
                )
                for record in (source,)
            )
        projection = OnlyExperimentMemoryProjectionV1(manifest, records)
        fingerprint = self.revisions._publish_and_activate(projection)
        return self.revisions.load_verified(fingerprint)


class _GatedStore(_Store):
    def __init__(self) -> None:
        super().__init__()
        self.admissions: dict[
            OnlyProductCommandId, OnlyResearchNoveltyAdmissionV1 | OnlyResearchNoveltyAdmissionV2
        ] = {}
        self.lock = Lock()
        self.fail_before_commit = False
        self.fail_after_commit = False

    def load_novelty_admission(
        self, command_id: OnlyProductCommandId
    ) -> OnlyResearchNoveltyAdmissionV1 | OnlyResearchNoveltyAdmissionV2 | None:
        return self.admissions.get(command_id)

    @staticmethod
    def _subjects(admission):  # type: ignore[no-untyped-def]
        if isinstance(admission, OnlyResearchNoveltyAdmissionV1):
            return {admission.evaluation_subject_fingerprint}
        return {item.evaluation_subject_fingerprint for item in admission.members}

    def _create_queued_with_verified_novelty_admission(self, run, receipt, admission, *, expected_source_frontier):  # type: ignore[no-untyped-def]
        assert expected_source_frontier == 0
        with self.lock:
            existing = self.receipts.get(receipt.command_id)
            if existing is not None:
                return existing
            if self.fail_before_commit:
                raise RuntimeError("injected DB rollback")
            subjects = self._subjects(admission)
            if any(
                subjects & self._subjects(value)
                and self.runs[value.run_id].state in {OnlyResearchRunState.QUEUED, OnlyResearchRunState.RUNNING}
                for value in self.admissions.values()
            ):
                raise OnlyNoveltyResearchAdmissionError(
                    "NOVELTY_SAME_SUBJECT_IN_FLIGHT", "same canonical subject is already active"
                )
            self.runs[run.run_id] = run
            self.receipts[receipt.command_id] = receipt
            self.admissions[receipt.command_id] = admission
            if self.fail_after_commit:
                raise RuntimeError("injected response loss")
            return receipt


def _system(tmp_path, command_id, *, outcome=OnlyNoveltyPolicyOutcome.ADMIT, stale=False):  # type: ignore[no-untyped-def]
    specification = _scientific()
    subject = _resolve(specification)
    revisions = OnlyExperimentMemoryRevisionStore(tmp_path / "experiment-memory")
    initial = OnlyExperimentMemoryProjectionV1(_manifest(), ())
    revisions._publish_and_activate(initial)
    policies = OnlyNoveltyPolicyStore(tmp_path)
    policies.put(policy())
    decisions = OnlyNoveltyDecisionAuthority(tmp_path)
    bundle = decisions.seal_from_request(
        OnlyNoveltyDecisionRequestV2(command_id, "default-novelty", "1", subject),
        initial.revision_fingerprint,
        revisions,
        policies,
    )
    decision_reader = decisions
    if outcome is not OnlyNoveltyPolicyOutcome.ADMIT:
        changed = replace(bundle, decision=replace(bundle.decision, outcome=outcome))

        class _DecisionReader:
            def load_group_exact(self, requested):  # type: ignore[no-untyped-def]
                from onlyalpha.research.novelty.decision_store import OnlyNoveltyDecisionNotFoundError

                raise OnlyNoveltyDecisionNotFoundError(requested.value)

            def load_exact(self, requested):  # type: ignore[no-untyped-def]
                assert requested == command_id
                return changed

        decision_reader = _DecisionReader()  # type: ignore[assignment]
    store = _GatedStore()
    runtime = OnlyTestRuntimeGenerationAuthority()
    admission = OnlyResearchRunAdmissionService(
        resolver=OnlyResearchSpecificationResolver(registry()),
        dataset_store=_DatasetStore(),  # type: ignore[arg-type]
        now_utc=lambda: NOW,
    )
    service = OnlyResearchCommandService(
        admission=admission,
        store=store,  # type: ignore[arg-type]
        now_utc=lambda: NOW,
        runtime_generations=runtime,
        command_admissions=_ProductAdmissions(),
        runtime_generation_resolver=_RuntimeAdmissionResolver(),
        novelty_decisions=decision_reader,  # type: ignore[arg-type]
        memory_builder=_MemoryBuilder(revisions, stale_subject=subject if stale else None),  # type: ignore[arg-type]
        memory_revisions=revisions,
    )
    return service, store, runtime, specification, subject


def _multi_system(tmp_path, command_id, *, stale_index: int | None = None):  # type: ignore[no-untyped-def]
    specification = _scientific(swept=True)
    resolving_runtime = OnlyTestRuntimeGenerationAuthority()
    resolving_runtime.bind_new_work("resolve", actor="test", occurred_at=NOW)
    subjects = OnlyExactEvaluationIntentResolverV1(
        runtime_generations=resolving_runtime,
        runtime_resolution=_RuntimeAdmissionResolver(),
    ).resolve_all(specification, runtime_work_id="resolve")
    revisions = OnlyExperimentMemoryRevisionStore(tmp_path / "experiment-memory")
    initial = OnlyExperimentMemoryProjectionV1(_manifest(), ())
    revisions._publish_and_activate(initial)
    policies = OnlyNoveltyPolicyStore(tmp_path)
    policies.put(policy())
    decisions = OnlyNoveltyDecisionAuthority(tmp_path)
    group = decisions.seal_group_from_requests(
        tuple(OnlyNoveltyDecisionRequestV2(command_id, "default-novelty", "1", item) for item in subjects),
        initial.revision_fingerprint,
        revisions,
        policies,
    )
    store = _GatedStore()
    runtime = OnlyTestRuntimeGenerationAuthority()
    admission = OnlyResearchRunAdmissionService(
        resolver=OnlyResearchSpecificationResolver(registry()),
        dataset_store=_DatasetStore(),  # type: ignore[arg-type]
        now_utc=lambda: NOW,
    )
    service = OnlyResearchCommandService(
        admission=admission,
        store=store,  # type: ignore[arg-type]
        now_utc=lambda: NOW,
        runtime_generations=runtime,
        command_admissions=_ProductAdmissions(),
        runtime_generation_resolver=_RuntimeAdmissionResolver(),
        novelty_decisions=decisions,
        memory_builder=_MemoryBuilder(
            revisions,
            stale_subject=None if stale_index is None else subjects[stale_index],
        ),  # type: ignore[arg-type]
        memory_revisions=revisions,
    )
    return service, store, runtime, specification, subjects, group


def test_admit_creates_one_atomic_relation_and_retry_replays(tmp_path) -> None:  # type: ignore[no-untyped-def]
    command_id = OnlyProductCommandId("00000000-0000-4000-8000-000000000101")
    service, store, runtime, specification, _ = _system(tmp_path, command_id)

    created = service.submit_research_run(command_id, specification)
    replayed = service.submit_research_run(command_id, specification)

    assert created.disposition is OnlyResearchSubmitDisposition.CREATED
    assert replayed.disposition is OnlyResearchSubmitDisposition.REUSED
    assert replayed.run == created.run
    assert len(store.runs) == len(store.receipts) == len(store.admissions) == 1
    assert runtime.require_work_binding(created.run.run_id.value).active


def test_multi_subject_all_admit_creates_one_aggregate_run_and_retry_replays(tmp_path) -> None:  # type: ignore[no-untyped-def]
    command_id = OnlyProductCommandId("00000000-0000-4000-8000-000000000121")
    service, store, runtime, specification, subjects, group = _multi_system(tmp_path, command_id)

    created = service.submit_research_run(command_id, specification)
    replayed = service.submit_research_run(command_id, specification)

    admission = store.admissions[command_id]
    assert isinstance(admission, OnlyResearchNoveltyAdmissionV2)
    assert tuple(item.evaluation_subject_fingerprint for item in admission.members) == tuple(
        item.subject_fingerprint for item in subjects
    )
    assert admission.decision_group_fingerprint == group.group_fingerprint
    assert created.disposition is OnlyResearchSubmitDisposition.CREATED
    assert replayed.disposition is OnlyResearchSubmitDisposition.REUSED
    assert replayed.run == created.run
    assert len(store.runs) == len(store.receipts) == len(store.admissions) == 1
    assert runtime.require_work_binding(created.run.run_id.value).active


def test_committed_group_replay_rejects_changed_intent_as_command_conflict(tmp_path) -> None:  # type: ignore[no-untyped-def]
    command_id = OnlyProductCommandId("00000000-0000-4000-8000-000000000124")
    service, store, _, specification, _, _ = _multi_system(tmp_path, command_id)
    created = service.submit_research_run(command_id, specification)

    with pytest.raises(OnlyResearchSubmissionConflictError):
        service.submit_research_run(command_id, _scientific(dataset="b" * 64, swept=True))

    assert len(store.runs) == len(store.receipts) == len(store.admissions) == 1
    assert next(iter(store.runs.values())) == created.run


@pytest.mark.parametrize(
    "outcome",
    (
        OnlyNoveltyPolicyOutcome.REUSE,
        OnlyNoveltyPolicyOutcome.SUPPRESS,
        OnlyNoveltyPolicyOutcome.REVIEW,
        OnlyNoveltyPolicyOutcome.FAIL_CLOSED,
    ),
)
def test_multi_subject_mixed_outcome_blocks_whole_run(tmp_path, outcome) -> None:  # type: ignore[no-untyped-def]
    command_id = OnlyProductCommandId("00000000-0000-4000-8000-000000000122")
    service, store, runtime, specification, _, group = _multi_system(tmp_path, command_id)
    changed = replace(
        group,
        members=(
            group.members[0],
            replace(group.members[1], decision=replace(group.members[1].decision, outcome=outcome)),
        ),
    )

    class _DecisionReader:
        def load_group_exact(self, requested):  # type: ignore[no-untyped-def]
            assert requested == command_id
            return changed

    service._novelty_decisions = _DecisionReader()  # type: ignore[assignment]
    with pytest.raises(OnlyNoveltyResearchAdmissionError) as blocked:
        service.submit_research_run(command_id, specification)
    assert blocked.value.code == "NOVELTY_DECISION_NOT_ADMIT"
    assert not store.runs and not store.receipts and not store.admissions and not runtime.bindings


def test_multi_subject_one_stale_member_blocks_whole_run_and_releases_binding(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    command_id = OnlyProductCommandId("00000000-0000-4000-8000-000000000123")
    service, store, runtime, specification, subjects, _ = _multi_system(tmp_path, command_id, stale_index=1)
    from onlyalpha.research.memory.query import (
        OnlyMemoryHistoricalMatchV1,
        OnlyMemoryHistoricalProofStatus,
        OnlyMemoryHistoricalProofV1,
    )

    def one_changed_proof(revisions, query):  # type: ignore[no-untyped-def]
        projection = revisions.load_verified(query.projection_revision_fingerprint)
        changed = query.exact_selector.intent_subject == subjects[1]
        matches = ()
        if changed:
            record = next(item for item in projection.records if item.kind == "EvaluationProjectionRecord")
            matches = (OnlyMemoryHistoricalMatchV1(record),)
        return OnlyMemoryHistoricalProofV1(
            query.query_fingerprint,
            projection.revision_fingerprint,
            projection.logical_digest,
            projection.source_manifest.manifest_fingerprint,
            OnlyMemoryHistoricalProofStatus.MATCH if changed else OnlyMemoryHistoricalProofStatus.CERTIFIED_NO_MATCH,
            matches,
        )

    monkeypatch.setattr("onlyalpha.research.memory.query.only_query_experiment_memory_history", one_changed_proof)

    with pytest.raises(OnlyNoveltyResearchAdmissionError) as stale:
        service.submit_research_run(command_id, specification)

    assert stale.value.code == "NOVELTY_DECISION_STALE"
    assert not store.runs and not store.receipts and not store.admissions
    assert runtime.inactive_work_ids == set(runtime.bindings)


@pytest.mark.parametrize(
    ("status", "code"),
    (("PROOF_INCOMPLETE", "NOVELTY_PROOF_INCOMPLETE"), ("PROOF_UNAVAILABLE", "NOVELTY_PROOF_UNAVAILABLE")),
)
def test_multi_subject_incomplete_action_proof_fails_closed(tmp_path, monkeypatch, status, code) -> None:  # type: ignore[no-untyped-def]
    command_id = OnlyProductCommandId("00000000-0000-4000-8000-000000000125")
    service, store, runtime, specification, _, _ = _multi_system(tmp_path, command_id)
    from onlyalpha.research.memory.query import OnlyMemoryHistoricalProofStatus, OnlyMemoryHistoricalProofV1

    def incomplete_proof(revisions, query):  # type: ignore[no-untyped-def]
        projection = revisions.load_verified(query.projection_revision_fingerprint)
        return OnlyMemoryHistoricalProofV1(
            query.query_fingerprint,
            projection.revision_fingerprint,
            projection.logical_digest,
            projection.source_manifest.manifest_fingerprint,
            OnlyMemoryHistoricalProofStatus(status),
            (),
        )

    monkeypatch.setattr("onlyalpha.research.memory.query.only_query_experiment_memory_history", incomplete_proof)
    with pytest.raises(OnlyNoveltyResearchAdmissionError) as unavailable:
        service.submit_research_run(command_id, specification)

    assert unavailable.value.code == code
    assert not store.runs and not store.receipts and not store.admissions
    assert runtime.inactive_work_ids == set(runtime.bindings)


def test_incomplete_decision_group_creates_zero_run(tmp_path) -> None:  # type: ignore[no-untyped-def]
    command_id = OnlyProductCommandId("00000000-0000-4000-8000-000000000126")
    service, store, runtime, specification, _, group = _multi_system(tmp_path, command_id)
    incomplete = OnlyNoveltyDecisionGroupV1(
        group.product_command_id,
        group.specification_fingerprint,
        group.members[:1],
    )

    class _IncompleteGroupReader:
        def load_group_exact(self, requested):  # type: ignore[no-untyped-def]
            assert requested == command_id
            return incomplete

    service._novelty_decisions = _IncompleteGroupReader()  # type: ignore[assignment]
    with pytest.raises(OnlyNoveltyResearchAdmissionError) as mismatch:
        service.submit_research_run(command_id, specification)
    assert mismatch.value.code == "NOVELTY_DECISION_BINDING_MISMATCH"
    assert not store.runs and runtime.inactive_work_ids == set(runtime.bindings)


@pytest.mark.parametrize(
    "outcome",
    (
        OnlyNoveltyPolicyOutcome.REUSE,
        OnlyNoveltyPolicyOutcome.SUPPRESS,
        OnlyNoveltyPolicyOutcome.REVIEW,
        OnlyNoveltyPolicyOutcome.FAIL_CLOSED,
    ),
)
def test_non_admit_outcomes_create_zero_run(tmp_path, outcome) -> None:  # type: ignore[no-untyped-def]
    command_id = OnlyProductCommandId("00000000-0000-4000-8000-000000000102")
    service, store, runtime, specification, _ = _system(tmp_path, command_id, outcome=outcome)

    with pytest.raises(OnlyNoveltyResearchAdmissionError, match="Novelty Decision outcome"):
        service.submit_research_run(command_id, specification)

    assert not store.runs and not store.receipts and not store.admissions and not runtime.bindings


def test_changed_action_time_proof_fails_closed_and_releases_binding(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    command_id = OnlyProductCommandId("00000000-0000-4000-8000-000000000103")
    service, store, runtime, specification, _ = _system(tmp_path, command_id, stale=True)

    def changed_proof(revisions, query):  # type: ignore[no-untyped-def]
        from onlyalpha.research.memory.query import (
            OnlyMemoryHistoricalMatchV1,
            OnlyMemoryHistoricalProofStatus,
            OnlyMemoryHistoricalProofV1,
        )

        projection = revisions.load_verified(query.projection_revision_fingerprint)
        record = next(item for item in projection.records if item.kind == "EvaluationProjectionRecord")
        return OnlyMemoryHistoricalProofV1(
            query.query_fingerprint,
            projection.revision_fingerprint,
            projection.logical_digest,
            projection.source_manifest.manifest_fingerprint,
            OnlyMemoryHistoricalProofStatus.MATCH,
            (OnlyMemoryHistoricalMatchV1(record),),
        )

    monkeypatch.setattr("onlyalpha.research.memory.query.only_query_experiment_memory_history", changed_proof)

    with pytest.raises(OnlyNoveltyResearchAdmissionError, match="material exact historical proof changed"):
        service.submit_research_run(command_id, specification)

    assert not store.runs and not store.receipts
    assert runtime.inactive_work_ids == set(runtime.bindings)


def test_response_loss_replays_committed_run_without_new_freshness(tmp_path) -> None:  # type: ignore[no-untyped-def]
    command_id = OnlyProductCommandId("00000000-0000-4000-8000-000000000104")
    service, store, _, specification, _ = _system(tmp_path, command_id)
    store.fail_after_commit = True

    outcome = service.submit_research_run(command_id, specification)

    assert outcome.disposition is OnlyResearchSubmitDisposition.REUSED
    assert len(store.runs) == len(store.receipts) == len(store.admissions) == 1


def test_db_rollback_releases_exact_runtime_binding(tmp_path) -> None:  # type: ignore[no-untyped-def]
    command_id = OnlyProductCommandId("00000000-0000-4000-8000-000000000105")
    service, store, runtime, specification, _ = _system(tmp_path, command_id)
    store.fail_before_commit = True

    with pytest.raises(RuntimeError, match="injected DB rollback"):
        service.submit_research_run(command_id, specification)

    assert not store.runs and not store.receipts and runtime.inactive_work_ids == set(runtime.bindings)
    store.fail_before_commit = False
    with pytest.raises(OnlyNoveltyResearchAdmissionError) as released:
        service.submit_research_run(command_id, specification)
    assert released.value.code == "RUNTIME_WORK_BINDING_RECOVERY_REQUIRED"
    assert not store.runs


def test_missing_decision_and_subject_mismatch_create_zero_run(tmp_path) -> None:  # type: ignore[no-untyped-def]
    command_id = OnlyProductCommandId("00000000-0000-4000-8000-000000000109")
    service, store, runtime, _, _ = _system(tmp_path, command_id)
    service._novelty_decisions = OnlyNoveltyDecisionAuthority(tmp_path / "missing")
    with pytest.raises(OnlyNoveltyResearchAdmissionError) as missing:
        service.submit_research_run(command_id, _scientific())
    assert missing.value.code == "NOVELTY_DECISION_NOT_FOUND"
    assert not store.runs and not runtime.bindings

    service, store, runtime, _, _ = _system(tmp_path / "mismatch", command_id)
    with pytest.raises(OnlyNoveltyResearchAdmissionError) as mismatch:
        service.submit_research_run(command_id, _scientific(dataset="b" * 64))
    assert mismatch.value.code == "NOVELTY_DECISION_BINDING_MISMATCH"
    assert not store.runs and runtime.inactive_work_ids == set(runtime.bindings)


def test_receipt_replay_rejects_corrupt_read_to_act_relation(tmp_path) -> None:  # type: ignore[no-untyped-def]
    command_id = OnlyProductCommandId("00000000-0000-4000-8000-000000000110")
    service, store, _, specification, _ = _system(tmp_path, command_id)
    service.submit_research_run(command_id, specification)
    corrupt_subject = "9" * 64
    store.admissions[command_id] = replace(
        store.admissions[command_id],
        evaluation_subject_fingerprint=corrupt_subject,
        same_subject_guard_key=only_novelty_same_subject_guard_key(corrupt_subject),
    )

    with pytest.raises(OnlyNoveltyResearchAdmissionError) as corrupt:
        service.submit_research_run(command_id, specification)
    assert corrupt.value.code == "NOVELTY_READ_TO_ACT_CORRUPT"


def test_same_command_concurrency_converges_on_one_run(tmp_path) -> None:  # type: ignore[no-untyped-def]
    command_id = OnlyProductCommandId("00000000-0000-4000-8000-000000000106")
    service, store, _, specification, _ = _system(tmp_path, command_id)
    barrier = Barrier(2)
    outcomes = []

    def submit() -> None:
        barrier.wait()
        outcomes.append(service.submit_research_run(command_id, specification))

    threads = [Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(outcomes) == 2
    assert outcomes[0].run == outcomes[1].run
    assert len(store.runs) == len(store.receipts) == len(store.admissions) == 1


def test_different_commands_same_subject_create_at_most_one_run(tmp_path) -> None:  # type: ignore[no-untyped-def]
    first_id = OnlyProductCommandId("00000000-0000-4000-8000-000000000107")
    second_id = OnlyProductCommandId("00000000-0000-4000-8000-000000000108")
    first, store, runtime, specification, subject = _system(tmp_path, first_id)
    first.submit_research_run(first_id, specification)

    revisions = first._memory_revisions
    decisions = first._novelty_decisions
    assert revisions is not None and decisions is not None
    policies = OnlyNoveltyPolicyStore(tmp_path)
    projection = revisions.load_active_verified()
    decisions.seal_from_request(
        OnlyNoveltyDecisionRequestV2(second_id, "default-novelty", "1", subject),
        projection.revision_fingerprint,
        revisions,
        policies,
    )
    second = OnlyResearchCommandService(
        admission=first._admission,
        store=store,  # type: ignore[arg-type]
        now_utc=lambda: NOW,
        runtime_generations=runtime,
        command_admissions=_ProductAdmissions(),
        runtime_generation_resolver=_RuntimeAdmissionResolver(),
        novelty_decisions=decisions,
        memory_builder=first._memory_builder,
        memory_revisions=revisions,
    )

    with pytest.raises(OnlyNoveltyResearchAdmissionError, match="same canonical subject"):
        second.submit_research_run(second_id, specification)

    assert len(store.runs) == 1
    assert len(runtime.inactive_work_ids) == 1
