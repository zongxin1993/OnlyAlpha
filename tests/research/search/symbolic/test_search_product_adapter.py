from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from threading import Barrier, Thread
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest

from onlyalpha.application.product_boundary import only_compose_research_product_boundary
from onlyalpha.application.product_command_authority import OnlyProductCommandPutDisposition
from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandAdmissionV1,
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandOutcomeRef,
    OnlyProductCommandReceipt,
)
from onlyalpha.application.search_product import (
    OnlyAdvanceSearchExperimentV1,
    OnlyGetSearchExperimentV1,
    OnlyGetSearchIterationLedgerV1,
    OnlyGetSearchTerminalDecisionV1,
    OnlySearchBoundedOperationV1,
    OnlySearchMethodV1,
    OnlySearchProductCapabilityUnsupported,
    OnlySearchProductCommandConflict,
    OnlySearchProductCommandServiceV1,
    OnlySearchProductEffectStateV1,
    OnlySearchProductExpectedStateMismatch,
    OnlySearchProductQueryServiceV1,
    OnlySearchProductReceiptCorrupt,
    OnlySearchProductSemanticFactCorrupt,
    OnlySearchRuntimeGenerationBindingConflict,
    OnlySearchRuntimeGenerationInvalid,
    OnlySearchRuntimeGenerationUnbound,
    OnlySubmitSymbolicSearchExperimentV1,
    OnlySubmitSymbolicSearchExperimentV2,
    OnlySymbolicExpectedStateV1,
    only_search_experiment_work_id,
)
from onlyalpha.canonical import only_canonical_json
from onlyalpha.quant_assets import OnlyQuantAssetCatalogManager
from onlyalpha.research.command.model import OnlyResearchSubmitDisposition
from onlyalpha.research.experiment import (
    OnlyJsonSearchProvenanceStore,
    OnlySearchBudgetV1,
    OnlySearchDecisionEngineBindingV1,
    OnlySearchDecisionMode,
    OnlySearchHypothesisV1,
    OnlySearchResearchResultReferenceV1,
    OnlySearchWorkflowBindingV1,
)
from onlyalpha.research.run.model import OnlyResearchRun, OnlyResearchRunId, OnlyResearchRunState
from onlyalpha.research.search.parameter import parameter_submission_key
from onlyalpha.research.search.symbolic import (
    OnlyJsonSymbolicSearchStore,
    OnlySymbolicEnumerationResultV1,
    OnlySymbolicResearchEvaluationContractV1,
    OnlySymbolicSearchContextResolver,
    OnlySymbolicSearchProductAdapterV1,
    only_deterministic_enumeration_implementation,
    symbolic_submission_key,
)
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver
from tests.research.specification.support import registry as specification_registry
from tests.runtime_generation_support import OnlyTestRuntimeGenerationAuthority

from .support import space, verified_dataset
from .test_research_and_provenance_integration import _scientific_template


class _Candidates:
    def __init__(self) -> None:
        self.values: set[str] = set()

    def load_verified(self, fingerprint: str):  # type: ignore[no-untyped-def]
        if fingerprint not in self.values:
            raise KeyError(fingerprint)
        return SimpleNamespace(candidate_fingerprint=fingerprint)


class _Results:
    def __init__(self, candidates: _Candidates, dataset: str) -> None:
        self.candidates = candidates
        self.dataset = dataset
        self.values: dict[str, object] = {}

    def add(self, locator: str, result: str, candidate: str) -> None:
        self.candidates.values.add(candidate)
        self.values[locator] = SimpleNamespace(
            manifest=SimpleNamespace(
                research_result_plan_fingerprint=locator,
                research_result_fingerprint=result,
                dataset_snapshot_fingerprint=self.dataset,
                plan=SimpleNamespace(candidates=(SimpleNamespace(candidate_fingerprint=candidate),)),
            )
        )

    def load_verified(self, fingerprint: str):  # type: ignore[no-untyped-def]
        return self.values[fingerprint]


class _Commands:
    def __init__(self, authority: _ProductAuthority, results: _Results) -> None:
        self.authority = authority
        self.results = results
        self.state = OnlyResearchRunState.QUEUED
        self.calls = 0
        self.runs: dict[OnlyResearchRunId, OnlyResearchRun] = {}

    def submit_symbolic_research(self, *, plan, resolved):  # type: ignore[no-untyped-def]
        from onlyalpha.research.search.symbolic import symbolic_submission_key

        self.calls += 1
        command_id = symbolic_submission_key(plan)
        run_id = OnlyResearchRunId(command_id.value)
        admission = OnlyProductCommandAdmissionV1(
            command_id,
            self.authority.research_kind,
            "9" * 64,
        )
        self.authority.admissions.setdefault(command_id, admission)
        self.authority.receipts.setdefault(
            command_id,
            OnlyProductCommandReceipt(
                command_id,
                self.authority.research_kind,
                "9" * 64,
                OnlyProductCommandOutcomeRef(OnlyProductCommandOutcomeKind.RESEARCH_RUN, run_id.value),
                datetime(2026, 9, 8, tzinfo=UTC),
            ),
        )
        run = OnlyResearchRun.queued(
            run_id=run_id,
            specification=resolved.specification,
            canonical_specification_payload=only_canonical_json(resolved.specification.to_dict()),
            admission_resolution_fingerprint="6" * 64,
            queued_at=datetime(2026, 9, 8, tzinfo=UTC),
        )
        if self.state is not OnlyResearchRunState.QUEUED:
            run = run.transition(OnlyResearchRunState.RUNNING, at=datetime(2026, 9, 8, 0, 0, 1, tzinfo=UTC))
        if self.state is OnlyResearchRunState.COMPLETED:
            result_fingerprint = hashlib.sha256(
                cast(str, resolved.candidate.candidate_fingerprint).encode()
            ).hexdigest()
            run = run.transition(
                OnlyResearchRunState.COMPLETED,
                at=datetime(2026, 9, 8, 0, 0, 2, tzinfo=UTC),
                research_result_fingerprint=result_fingerprint,
                artifact_content_fingerprint="5" * 64,
            )
        self.runs[run_id] = run
        return SimpleNamespace(disposition=OnlyResearchSubmitDisposition.REUSED, run=run)

    def get_run(self, run_id: OnlyResearchRunId) -> OnlyResearchRun:
        return self.runs[run_id]

    def research_result_reference(self, *, outcome, resolved):  # type: ignore[no-untyped-def]
        del outcome
        candidate = resolved.candidate.candidate_fingerprint
        assert candidate is not None
        reference = OnlySearchResearchResultReferenceV1(
            hashlib.sha256(f"locator:{candidate}".encode()).hexdigest(),
            hashlib.sha256(candidate.encode()).hexdigest(),
        )
        self.results.add(reference.locator_fingerprint, reference.result_fingerprint, candidate)
        return reference


class _Datasets:
    def __init__(self, fingerprint: str) -> None:
        self.value = verified_dataset(fingerprint)

    def load_verified_table(self, fingerprint: str):  # type: ignore[no-untyped-def]
        if fingerprint != self.value.snapshot.snapshot_fingerprint:
            raise KeyError(fingerprint)
        return self.value


class _ProductAuthority:
    research_kind = OnlyProductCommandKind.CREATE_RESEARCH_RUN

    def __init__(self) -> None:
        self.admissions: dict[OnlyProductCommandId, OnlyProductCommandAdmissionV1] = {}
        self.receipts: dict[OnlyProductCommandId, OnlyProductCommandReceipt] = {}
        self.fail_next_receipt = False

    def admit_exact(self, admission: OnlyProductCommandAdmissionV1) -> OnlyProductCommandPutDisposition:
        current = self.admissions.setdefault(admission.command_id, admission)
        if current != admission:
            from onlyalpha.application.product_command_authority import OnlyProductCommandConflictError

            raise OnlyProductCommandConflictError(admission.command_id.value)
        return (
            OnlyProductCommandPutDisposition.CREATED
            if current is admission
            else OnlyProductCommandPutDisposition.REUSED
        )

    def load_admission(self, command_id: OnlyProductCommandId):  # type: ignore[no-untyped-def]
        return self.admissions.get(command_id)

    def load_verified_receipt(self, command_id: OnlyProductCommandId):  # type: ignore[no-untyped-def]
        return self.receipts.get(command_id)

    def put_verified_receipt(self, receipt: OnlyProductCommandReceipt) -> OnlyProductCommandPutDisposition:
        if self.fail_next_receipt:
            self.fail_next_receipt = False
            raise RuntimeError("injected failure before Product Receipt commit")
        if self.admissions.get(receipt.command_id) != OnlyProductCommandAdmissionV1(
            receipt.command_id,
            receipt.command_kind,
            receipt.command_fingerprint,
        ):
            raise RuntimeError("receipt lacks exact Admission")
        current = self.receipts.setdefault(receipt.command_id, receipt)
        if current != receipt:
            raise RuntimeError("receipt conflict")
        return (
            OnlyProductCommandPutDisposition.CREATED if current is receipt else OnlyProductCommandPutDisposition.REUSED
        )


def _command_id() -> OnlyProductCommandId:
    return OnlyProductCommandId(str(uuid4()))


def _reconcile_expected(state: OnlySymbolicExpectedStateV1, plan_fingerprint: str):
    return OnlySymbolicExpectedStateV1(
        state.experiment_fingerprint,
        state.enumeration_result_fingerprint,
        state.ordered_plan_states,
        state.next_iteration_ordinal,
        state.research_attempt_count,
        state.qualification_attempt_count,
        plan_fingerprint,
    )


def _case(tmp_path, *, authority=None, runtime_generations=None):  # type: ignore[no-untyped-def]
    generation, search_space = space(max_nodes=3)
    dataset = "a" * 64
    symbolic = OnlyJsonSymbolicSearchStore(tmp_path)
    contexts = OnlySymbolicSearchContextResolver(
        symbolic_store=symbolic,
        catalogs=OnlyQuantAssetCatalogManager(generation),
        datasets=_Datasets(dataset),
        research_calculation_registry=specification_registry(),
    )
    candidates = _Candidates()
    results = _Results(candidates, dataset)
    provenance = OnlyJsonSearchProvenanceStore(
        tmp_path,
        catalogs=OnlyQuantAssetCatalogManager(generation),
        datasets=_Datasets(dataset),
        candidates=candidates,
        research_results=results,
        search_contexts=contexts,
    )
    authority = authority or _ProductAuthority()
    runtime_generations = runtime_generations or OnlyTestRuntimeGenerationAuthority(
        generation_fingerprint="f" * 64,
        catalog_generation_fingerprint=generation.generation_fingerprint,
    )
    commands = _Commands(authority, results)
    adapter = OnlySymbolicSearchProductAdapterV1(
        symbolic_store=symbolic,
        provenance=cast(object, provenance),
        contexts=contexts,
        resolver=OnlyResearchSpecificationResolver(specification_registry()),
        research_commands=commands,
        product_receipts=authority,
        research_runs=commands,
    )
    service = OnlySearchProductCommandServiceV1(
        command_admissions=authority,
        command_receipts=authority,
        runtime_generations=runtime_generations,
        adapters=(adapter,),
        now_utc=lambda: datetime(2026, 9, 8, tzinfo=UTC),
    )
    query = OnlySearchProductQueryServiceV1((adapter,))
    evaluation = OnlySymbolicResearchEvaluationContractV1.from_specification(_scientific_template(dataset), "feature")
    submit = OnlySubmitSymbolicSearchExperimentV2(
        _command_id(),
        OnlySearchHypothesisV1("bounded Product symbolic hypothesis"),
        search_space,
        evaluation,
        OnlySearchBudgetV1(3, 3, 1),
        only_deterministic_enumeration_implementation(),
        OnlySearchWorkflowBindingV1("symbolic.factor.search", "1"),
        OnlySearchDecisionEngineBindingV1(OnlySearchDecisionMode.DETERMINISTIC),
        generation.generation_fingerprint,
        dataset,
        runtime_generation_fingerprint=runtime_generations.generation_fingerprint,
    )
    return service, query, authority, commands, submit


def test_submit_and_bounded_symbolic_advance_reconcile_recovery(tmp_path) -> None:
    service, query, authority, commands, submit = _case(tmp_path)
    created = service.submit(submit)
    experiment = created.experiment.experiment_fingerprint
    initial = query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment))
    assert initial.plans == ()
    assert cast(OnlySymbolicExpectedStateV1, initial.expected_state).enumeration_result_fingerprint is None

    advance = OnlyAdvanceSearchExperimentV1(
        _command_id(),
        OnlySearchMethodV1.SYMBOLIC,
        OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE,
        initial.expected_state,
    )
    advanced = service.advance(advance)
    assert len(advanced.ledger.plans) == 1
    assert advanced.ledger.results == (None,)
    plan = advanced.ledger.plans[0]
    assert symbolic_submission_key(plan) == symbolic_submission_key(plan)
    assert symbolic_submission_key(plan) != parameter_submission_key(plan)
    assert symbolic_submission_key(plan) != advance.command_id
    replay = service.advance(advance)
    assert replay.replayed
    assert len(replay.ledger.plans) == 1

    illegal_open_advance = OnlyAdvanceSearchExperimentV1(
        _command_id(),
        OnlySearchMethodV1.SYMBOLIC,
        OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE,
        advanced.ledger.expected_state,
    )
    with pytest.raises(OnlySearchProductExpectedStateMismatch):
        service.advance(illegal_open_advance)

    open_state = cast(OnlySymbolicExpectedStateV1, advanced.ledger.expected_state)
    reconcile_state = OnlySymbolicExpectedStateV1(
        open_state.experiment_fingerprint,
        open_state.enumeration_result_fingerprint,
        open_state.ordered_plan_states,
        open_state.next_iteration_ordinal,
        open_state.research_attempt_count,
        open_state.qualification_attempt_count,
        open_state.ordered_plan_states[0].plan_fingerprint,
    )
    reconcile = OnlyAdvanceSearchExperimentV1(
        _command_id(),
        OnlySearchMethodV1.SYMBOLIC,
        OnlySearchBoundedOperationV1.RECONCILE_ONE_SYMBOLIC_OCCURRENCE,
        reconcile_state,
    )
    service.advance(reconcile)
    assert commands.calls == 1
    assert service.advance(reconcile).replayed
    assert commands.calls == 1

    commands.state = OnlyResearchRunState.COMPLETED
    observed = query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment)).expected_state
    observed = cast(OnlySymbolicExpectedStateV1, observed)
    terminal_reconcile = OnlyAdvanceSearchExperimentV1(
        _command_id(),
        OnlySearchMethodV1.SYMBOLIC,
        OnlySearchBoundedOperationV1.RECONCILE_ONE_SYMBOLIC_OCCURRENCE,
        OnlySymbolicExpectedStateV1(
            observed.experiment_fingerprint,
            observed.enumeration_result_fingerprint,
            observed.ordered_plan_states,
            observed.next_iteration_ordinal,
            observed.research_attempt_count,
            observed.qualification_attempt_count,
            observed.ordered_plan_states[0].plan_fingerprint,
        ),
    )
    terminal = service.advance(terminal_reconcile)
    assert terminal.ledger.results[0] is not None

    next_advance = OnlyAdvanceSearchExperimentV1(
        _command_id(),
        OnlySearchMethodV1.SYMBOLIC,
        OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE,
        terminal.ledger.expected_state,
    )
    later = service.advance(next_advance)
    assert len(later.ledger.plans) == 2

    # A command admitted from an illegal open-Plan pre-state can never claim a later Plan effect.
    with pytest.raises(OnlySearchProductExpectedStateMismatch):
        service.advance(illegal_open_advance)
    assert illegal_open_advance.command_id not in authority.receipts

    # Lost outer Receipt repairs from exact ordinal history even after later valid progress.
    del authority.receipts[advance.command_id]
    repaired = service.advance(advance)
    assert len(repaired.ledger.plans) == 2
    assert advance.command_id in authority.receipts


def test_search_command_fingerprint_excludes_product_identity_and_conflicts_before_search(tmp_path) -> None:
    service, query, authority, _commands, submit = _case(tmp_path)
    same_intent = OnlySubmitSymbolicSearchExperimentV2(
        _command_id(),
        submit.hypothesis,
        submit.search_space,
        submit.evaluation_contract,
        submit.search_budget,
        submit.algorithm_manifest,
        submit.workflow_binding,
        submit.decision_engine_binding,
        submit.catalog_generation_fingerprint,
        submit.dataset_snapshot_fingerprint,
        runtime_generation_fingerprint=submit.runtime_generation_fingerprint,
    )
    assert same_intent.command_fingerprint == submit.command_fingerprint
    # Admission-only recovery performs the exact same Submit and no iteration work.
    authority.admit_exact(
        OnlyProductCommandAdmissionV1(
            submit.command_id,
            OnlyProductCommandKind.CREATE_SYMBOLIC_SEARCH_EXPERIMENT,
            submit.command_fingerprint,
        )
    )
    first = service.submit(submit)
    second = service.submit(same_intent)
    assert first.experiment.experiment_fingerprint == second.experiment.experiment_fingerprint
    assert query.get_ledger(OnlyGetSearchIterationLedgerV1(first.experiment.experiment_fingerprint)).plans == ()
    # Experiment committed / Receipt lost repairs the Receipt without creating iteration work.
    del authority.receipts[submit.command_id]
    repaired = service.submit(submit)
    assert repaired.experiment == first.experiment
    assert repaired.ledger.plans == ()
    conflict = OnlySubmitSymbolicSearchExperimentV2(
        submit.command_id,
        OnlySearchHypothesisV1("different intent"),
        submit.search_space,
        submit.evaluation_contract,
        submit.search_budget,
        submit.algorithm_manifest,
        submit.workflow_binding,
        submit.decision_engine_binding,
        submit.catalog_generation_fingerprint,
        submit.dataset_snapshot_fingerprint,
        runtime_generation_fingerprint=submit.runtime_generation_fingerprint,
    )
    with pytest.raises(OnlySearchProductCommandConflict):
        service.submit(conflict)


def test_submit_v1_fingerprint_is_frozen_and_v2_separates_science_from_runtime_identity(tmp_path) -> None:
    service, query, _authority, _commands, submit = _case(tmp_path)
    v1 = OnlySubmitSymbolicSearchExperimentV1(
        _command_id(),
        submit.hypothesis,
        submit.search_space,
        submit.evaluation_contract,
        submit.search_budget,
        submit.algorithm_manifest,
        submit.workflow_binding,
        submit.decision_engine_binding,
        submit.catalog_generation_fingerprint,
        submit.dataset_snapshot_fingerprint,
    )
    assert v1.command_fingerprint == "1ef8a1a55ab2d8021ff14391d81b7edde3e32cf1ce3528c35f1681564acb2e7b"
    with pytest.raises(OnlySearchRuntimeGenerationUnbound):
        service.submit(v1)

    other_generation = replace(submit, command_id=_command_id(), runtime_generation_fingerprint="d" * 64)
    adapter = query._adapters[OnlySearchMethodV1.SYMBOLIC]  # type: ignore[attr-defined]
    assert adapter.derive_submit_experiment(submit).experiment_fingerprint == (
        adapter.derive_submit_experiment(other_generation).experiment_fingerprint
    )
    assert submit.command_fingerprint != other_generation.command_fingerprint
    experiment = adapter.derive_submit_experiment(submit).experiment_fingerprint
    assert only_search_experiment_work_id(experiment) == f"search-experiment:{experiment}"
    service.submit(submit)
    service._runtime_generations.activate(  # type: ignore[attr-defined]
        other_generation.runtime_generation_fingerprint,
        catalog_generation_fingerprint=submit.catalog_generation_fingerprint,
    )
    with pytest.raises(OnlySearchRuntimeGenerationBindingConflict):
        service.submit(other_generation)


def test_legacy_unbound_search_queries_but_product_mutation_fails_closed(tmp_path) -> None:
    service, query, _authority, _commands, submit = _case(tmp_path)
    created = service.submit(submit)
    experiment = created.experiment.experiment_fingerprint
    initial = query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment))
    first = service.advance(
        OnlyAdvanceSearchExperimentV1(
            _command_id(),
            OnlySearchMethodV1.SYMBOLIC,
            OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE,
            initial.expected_state,
        )
    )
    service._runtime_generations.bindings.clear()  # type: ignore[attr-defined]

    assert query.get_experiment(OnlyGetSearchExperimentV1(experiment)).experiment == created.experiment
    ledger = query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment))
    assert query.get_terminal(OnlyGetSearchTerminalDecisionV1(experiment)).experiment_fingerprint == experiment
    advance = OnlyAdvanceSearchExperimentV1(
        _command_id(),
        OnlySearchMethodV1.SYMBOLIC,
        OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE,
        ledger.expected_state,
    )
    with pytest.raises(OnlySearchRuntimeGenerationUnbound):
        service.advance(advance)
    reconcile = OnlyAdvanceSearchExperimentV1(
        _command_id(),
        OnlySearchMethodV1.SYMBOLIC,
        OnlySearchBoundedOperationV1.RECONCILE_ONE_SYMBOLIC_OCCURRENCE,
        _reconcile_expected(
            cast(OnlySymbolicExpectedStateV1, ledger.expected_state),
            first.ledger.plans[0].iteration_plan_fingerprint,
        ),
    )
    with pytest.raises(OnlySearchRuntimeGenerationUnbound):
        service.advance(reconcile)


def test_historical_v1_admission_with_exact_binding_recovers_without_generation_guess(tmp_path) -> None:
    service, query, authority, _commands, submit = _case(tmp_path)
    historical = OnlySubmitSymbolicSearchExperimentV1(
        _command_id(),
        submit.hypothesis,
        submit.search_space,
        submit.evaluation_contract,
        submit.search_budget,
        submit.algorithm_manifest,
        submit.workflow_binding,
        submit.decision_engine_binding,
        submit.catalog_generation_fingerprint,
        submit.dataset_snapshot_fingerprint,
    )
    adapter = query._adapters[historical.method]  # type: ignore[attr-defined]
    experiment = adapter.derive_submit_experiment(historical)
    authority.admit_exact(
        OnlyProductCommandAdmissionV1(
            historical.command_id,
            OnlyProductCommandKind.CREATE_SYMBOLIC_SEARCH_EXPERIMENT,
            historical.command_fingerprint,
        )
    )
    service._runtime_generations.bind_work_exact(  # type: ignore[attr-defined]
        only_search_experiment_work_id(experiment.experiment_fingerprint),
        submit.runtime_generation_fingerprint,
    )

    recovered = service.submit(historical)

    assert recovered.experiment == experiment
    assert historical.command_id in authority.receipts


def test_admitted_submit_recovers_original_generation_after_activation_switch(tmp_path) -> None:
    service, _query, authority, _commands, submit = _case(tmp_path)
    authority.admit_exact(
        OnlyProductCommandAdmissionV1(
            submit.command_id,
            OnlyProductCommandKind.CREATE_SYMBOLIC_SEARCH_EXPERIMENT,
            submit.command_fingerprint,
        )
    )
    service._runtime_generations.activate(  # type: ignore[attr-defined]
        "d" * 64,
        catalog_generation_fingerprint=submit.catalog_generation_fingerprint,
    )
    recovered = service.submit(submit)
    work_id = only_search_experiment_work_id(recovered.experiment.experiment_fingerprint)
    assert service._runtime_generations.bindings[work_id] == submit.runtime_generation_fingerprint  # type: ignore[attr-defined]


def test_concurrent_product_admission_and_runtime_binding_converge_on_same_search(tmp_path) -> None:
    admission_barrier = Barrier(2)
    binding_barrier = Barrier(2)

    class RacingProductAuthority(_ProductAuthority):
        def admit_exact(self, admission):  # type: ignore[no-untyped-def]
            admission_barrier.wait()
            return super().admit_exact(admission)

    class RacingRuntimeAuthority(OnlyTestRuntimeGenerationAuthority):
        def bind_work_exact(self, work_id, runtime_generation_fingerprint, **context):  # type: ignore[no-untyped-def]
            binding_barrier.wait()
            return super().bind_work_exact(work_id, runtime_generation_fingerprint, **context)

    generation, _ = space(max_nodes=3)
    authority = RacingProductAuthority()
    runtime = RacingRuntimeAuthority(catalog_generation_fingerprint=generation.generation_fingerprint)
    service, _query, _authority, _commands, submit = _case(
        tmp_path,
        authority=authority,
        runtime_generations=runtime,
    )
    other = replace(submit, command_id=_command_id())
    outcomes: list[object] = []
    failures: list[BaseException] = []

    def execute(command):  # type: ignore[no-untyped-def]
        try:
            outcomes.append(service.submit(command))
        except BaseException as exc:
            failures.append(exc)

    threads = (Thread(target=execute, args=(submit,)), Thread(target=execute, args=(other,)))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    assert len(outcomes) == 2
    fingerprints = {outcome.experiment.experiment_fingerprint for outcome in outcomes}  # type: ignore[union-attr]
    assert len(fingerprints) == 1
    experiment_fingerprint = fingerprints.pop()
    assert runtime.bindings == {
        only_search_experiment_work_id(experiment_fingerprint): submit.runtime_generation_fingerprint
    }
    assert set(authority.receipts) == {submit.command_id, other.command_id}


def test_submit_rejects_non_exact_runtime_authority_results_before_search_effect(tmp_path) -> None:
    class InvalidBindingAuthority(OnlyTestRuntimeGenerationAuthority):
        def bind_work_exact(self, work_id, runtime_generation_fingerprint, **context):  # type: ignore[no-untyped-def]
            super().bind_work_exact(work_id, runtime_generation_fingerprint, **context)
            return SimpleNamespace(
                work_id=work_id,
                runtime_generation_fingerprint="0" * 64,
                active=True,
            )

    generation, _ = space(max_nodes=3)
    runtime = InvalidBindingAuthority(catalog_generation_fingerprint=generation.generation_fingerprint)
    service, query, authority, _commands, submit = _case(tmp_path, runtime_generations=runtime)
    expected = query._adapters[submit.method].derive_submit_experiment(submit)  # type: ignore[attr-defined]

    with pytest.raises(OnlySearchRuntimeGenerationInvalid):
        service.submit(submit)

    assert submit.command_id in authority.admissions
    assert submit.command_id not in authority.receipts
    with pytest.raises(OnlySearchProductSemanticFactCorrupt):
        query.get_experiment(OnlyGetSearchExperimentV1(expected.experiment_fingerprint))


def test_symbolic_factor_qualification_workflow_is_unsupported_and_creates_no_effect(tmp_path) -> None:
    service, _query, authority, _commands, submit = _case(tmp_path)
    unsupported = replace(
        submit,
        workflow_binding=OnlySearchWorkflowBindingV1("symbolic.factor.qualification", "1"),
    )

    with pytest.raises(OnlySearchProductCapabilityUnsupported):
        service.submit(unsupported)

    assert unsupported.command_id not in authority.admissions
    assert unsupported.command_id not in authority.receipts


def test_concurrent_symbolic_advances_from_same_pre_state_converge_on_one_plan(tmp_path) -> None:
    service, query, _authority, _commands, submit = _case(tmp_path)
    experiment = service.submit(submit).experiment.experiment_fingerprint
    expected = query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment)).expected_state
    barrier = Barrier(2)
    outcomes: list[object] = []

    def execute() -> None:
        command = OnlyAdvanceSearchExperimentV1(
            _command_id(),
            OnlySearchMethodV1.SYMBOLIC,
            OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE,
            expected,
        )
        barrier.wait()
        try:
            outcomes.append(service.advance(command))
        except Exception as exc:  # deterministic exact loser outcome is evidence
            outcomes.append(exc)

    threads = (Thread(target=execute), Thread(target=execute))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not any(isinstance(item, Exception) for item in outcomes)
    ledger = query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment))
    assert len(ledger.plans) == 1


def test_search_effect_committed_before_outer_receipt_repairs_without_next_effect(tmp_path) -> None:
    service, query, authority, _commands, submit = _case(tmp_path)
    experiment = service.submit(submit).experiment.experiment_fingerprint
    expected = query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment)).expected_state
    command = OnlyAdvanceSearchExperimentV1(
        _command_id(),
        OnlySearchMethodV1.SYMBOLIC,
        OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE,
        expected,
    )
    authority.fail_next_receipt = True
    with pytest.raises(OnlySearchProductReceiptCorrupt):
        service.advance(command)
    assert len(query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment)).plans) == 1
    repaired = service.advance(command)
    assert len(repaired.ledger.plans) == 1


def test_fresh_symbolic_product_service_repairs_committed_effect_from_durable_authorities(tmp_path) -> None:
    service, query, authority, _commands, submit = _case(tmp_path)
    experiment = service.submit(submit).experiment.experiment_fingerprint
    expected = query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment)).expected_state
    command = OnlyAdvanceSearchExperimentV1(
        _command_id(),
        OnlySearchMethodV1.SYMBOLIC,
        OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE,
        expected,
    )
    authority.fail_next_receipt = True
    with pytest.raises(OnlySearchProductReceiptCorrupt):
        service.advance(command)

    restarted, restarted_query, _authority2, _commands2, _submit2 = _case(
        tmp_path,
        authority=authority,
        runtime_generations=service._runtime_generations,  # type: ignore[attr-defined]
    )
    repaired = restarted.advance(command)
    assert len(repaired.ledger.plans) == 1
    assert len(restarted_query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment)).plans) == 1


def test_exact_search_experiment_query_fails_closed_for_unknown_identity(tmp_path) -> None:
    _service, query, authority, commands, submit = _case(tmp_path)
    before = (len(authority.admissions), len(authority.receipts), commands.calls)

    with pytest.raises(OnlySearchProductSemanticFactCorrupt):
        query.get_experiment(OnlyGetSearchExperimentV1("f" * 64))

    assert (len(authority.admissions), len(authority.receipts), commands.calls) == before


def test_search_commands_and_queries_use_existing_product_dispatchers(tmp_path) -> None:
    service, query, _authority, _commands, submit = _case(tmp_path)

    class _Ready:
        calls = 0

        def assert_mutation_ready(self) -> None:
            self.calls += 1

    ready = _Ready()
    boundary = only_compose_research_product_boundary(
        admission=ready,
        commands=cast(object, object()),
        queries=cast(object, object()),
        search_commands=service,
        search_queries=query,
    )

    created = boundary.commands.dispatch(submit)
    assert ready.calls == 1
    assert (
        boundary.queries.dispatch(OnlyGetSearchExperimentV1(created.experiment.experiment_fingerprint)).experiment
        == created.experiment
    )


def test_symbolic_submit_receipt_recovery_is_monotonic_after_later_progress(tmp_path) -> None:
    service, query, authority, commands, submit = _case(tmp_path)
    same_intent = replace(submit, command_id=_command_id())
    experiment = service.submit(submit).experiment.experiment_fingerprint
    assert service.submit(same_intent).experiment.experiment_fingerprint == experiment
    initial = query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment))
    advance = OnlyAdvanceSearchExperimentV1(
        _command_id(),
        OnlySearchMethodV1.SYMBOLIC,
        OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE,
        initial.expected_state,
    )
    progressed = service.advance(advance)
    before = (len(progressed.ledger.plans), commands.calls)

    del authority.receipts[submit.command_id]
    repaired = service.submit(submit)
    assert repaired.replayed is False
    assert (len(repaired.ledger.plans), commands.calls) == before
    assert repaired.experiment.experiment_fingerprint == experiment

    commands.state = OnlyResearchRunState.COMPLETED
    while True:
        ledger = query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment))
        enumeration = cast(OnlySymbolicEnumerationResultV1, ledger.enumeration_result)
        open_plan = next(
            (plan for plan, result in zip(ledger.plans, ledger.results, strict=True) if result is None),
            None,
        )
        if open_plan is not None:
            state = cast(OnlySymbolicExpectedStateV1, ledger.expected_state)
            service.advance(
                OnlyAdvanceSearchExperimentV1(
                    _command_id(),
                    OnlySearchMethodV1.SYMBOLIC,
                    OnlySearchBoundedOperationV1.RECONCILE_ONE_SYMBOLIC_OCCURRENCE,
                    _reconcile_expected(state, open_plan.iteration_plan_fingerprint),
                )
            )
            continue
        if len(ledger.plans) == len(enumeration.ordered_proposal_fingerprints):
            break
        service.advance(
            OnlyAdvanceSearchExperimentV1(
                _command_id(),
                OnlySearchMethodV1.SYMBOLIC,
                OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE,
                ledger.expected_state,
            )
        )

    terminal_count = len(query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment)).plans)
    del authority.receipts[same_intent.command_id]
    terminal_repair = service.submit(same_intent)
    assert len(terminal_repair.ledger.plans) == terminal_count
    assert all(item is not None for item in terminal_repair.ledger.results)


def test_symbolic_enumeration_absence_is_only_exact_store_not_found(tmp_path) -> None:
    service, query, authority, _commands, submit = _case(tmp_path)
    created = service.submit(submit)
    experiment = created.experiment.experiment_fingerprint
    initial = cast(OnlySymbolicExpectedStateV1, created.ledger.expected_state)
    assert initial.enumeration_result_fingerprint is None

    target = tmp_path / "research/symbolic-search/enumeration-results/sha256" / experiment[:2] / experiment
    target.mkdir(parents=True)
    (target / "manifest.json").write_text("{}\n", encoding="utf-8")
    advance = OnlyAdvanceSearchExperimentV1(
        _command_id(),
        OnlySearchMethodV1.SYMBOLIC,
        OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE,
        initial,
    )
    with pytest.raises(Exception, match="SEARCH_ENUMERATION_RESULT_CORRUPT"):
        query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment))
    with pytest.raises(Exception, match="SEARCH_ENUMERATION_RESULT_CORRUPT"):
        service.advance(advance)
    assert (
        query._adapters[OnlySearchMethodV1.SYMBOLIC]._provenance.iteration_plans_for_experiment_verified(  # type: ignore[attr-defined]
            experiment
        )
        == ()
    )
    assert advance.command_id not in authority.receipts


def test_contextually_invalid_enumeration_never_becomes_absent_or_is_replaced(tmp_path) -> None:
    service, query, authority, _commands, submit = _case(tmp_path)
    experiment = service.submit(submit).experiment.experiment_fingerprint
    initial = query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment))
    advanced = service.advance(
        OnlyAdvanceSearchExperimentV1(
            _command_id(),
            OnlySearchMethodV1.SYMBOLIC,
            OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE,
            initial.expected_state,
        )
    )
    enumeration = cast(OnlySymbolicEnumerationResultV1, advanced.ledger.enumeration_result)
    invalid = replace(enumeration, algorithm_implementation_fingerprint="b" * 64)
    manifest = (
        tmp_path / "research/symbolic-search/enumeration-results/sha256" / experiment[:2] / experiment / "manifest.json"
    )
    manifest.write_text(only_canonical_json(invalid.to_dict()), encoding="utf-8")
    plan_root = tmp_path / "research/search-provenance/iteration-plans/sha256"
    before_plan_paths = tuple(sorted(plan_root.glob("*/*/manifest.json")))
    command = OnlyAdvanceSearchExperimentV1(
        _command_id(),
        OnlySearchMethodV1.SYMBOLIC,
        OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE,
        advanced.ledger.expected_state,
    )
    with pytest.raises(Exception, match="SEARCH_"):
        query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment))
    with pytest.raises(Exception, match="SEARCH_"):
        service.advance(command)
    assert tuple(sorted(plan_root.glob("*/*/manifest.json"))) == before_plan_paths
    assert command.command_id not in authority.receipts


def test_unsafe_enumeration_path_fails_closed_without_reenumeration(tmp_path) -> None:
    service, query, authority, _commands, submit = _case(tmp_path)
    created = service.submit(submit)
    experiment = created.experiment.experiment_fingerprint
    target = tmp_path / "research/symbolic-search/enumeration-results/sha256" / experiment[:2] / experiment
    target.parent.mkdir(parents=True)
    unsafe = tmp_path / "unsafe-enumeration-target"
    unsafe.mkdir()
    (unsafe / "manifest.json").write_text("{}", encoding="utf-8")
    target.symlink_to(unsafe, target_is_directory=True)
    command = OnlyAdvanceSearchExperimentV1(
        _command_id(),
        OnlySearchMethodV1.SYMBOLIC,
        OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE,
        created.ledger.expected_state,
    )
    with pytest.raises(Exception, match="SEARCH_SYMBOLIC_UNSAFE_PATH"):
        query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment))
    with pytest.raises(Exception, match="SEARCH_SYMBOLIC_UNSAFE_PATH"):
        service.advance(command)
    assert command.command_id not in authority.receipts
    assert not tuple((tmp_path / "research/search-provenance/iteration-plans").glob("**/manifest.json"))


def test_dangling_and_mismatched_research_runs_fail_before_search_result_or_outer_receipt(tmp_path) -> None:
    service, query, authority, commands, submit = _case(tmp_path)
    experiment = service.submit(submit).experiment.experiment_fingerprint
    advanced = service.advance(
        OnlyAdvanceSearchExperimentV1(
            _command_id(),
            OnlySearchMethodV1.SYMBOLIC,
            OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE,
            query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment)).expected_state,
        )
    )
    state = cast(OnlySymbolicExpectedStateV1, advanced.ledger.expected_state)
    plan = advanced.ledger.plans[0]
    inner_id = symbolic_submission_key(plan)
    authority.admit_exact(OnlyProductCommandAdmissionV1(inner_id, authority.research_kind, "9" * 64))
    authority.put_verified_receipt(
        OnlyProductCommandReceipt(
            inner_id,
            authority.research_kind,
            "9" * 64,
            OnlyProductCommandOutcomeRef(OnlyProductCommandOutcomeKind.RESEARCH_RUN, inner_id.value),
            datetime(2026, 9, 8, tzinfo=UTC),
        )
    )
    dangling = OnlyAdvanceSearchExperimentV1(
        _command_id(),
        OnlySearchMethodV1.SYMBOLIC,
        OnlySearchBoundedOperationV1.RECONCILE_ONE_SYMBOLIC_OCCURRENCE,
        _reconcile_expected(state, plan.iteration_plan_fingerprint),
    )
    with pytest.raises(OnlySearchProductSemanticFactCorrupt):
        service.advance(dangling)
    assert dangling.command_id not in authority.receipts
    assert advanced.ledger.results == (None,)

    del authority.receipts[inner_id]
    del authority.admissions[inner_id]
    commands.state = OnlyResearchRunState.QUEUED
    service.advance(
        OnlyAdvanceSearchExperimentV1(
            _command_id(),
            OnlySearchMethodV1.SYMBOLIC,
            OnlySearchBoundedOperationV1.RECONCILE_ONE_SYMBOLIC_OCCURRENCE,
            _reconcile_expected(state, plan.iteration_plan_fingerprint),
        )
    )
    observed = cast(
        OnlySymbolicExpectedStateV1,
        query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment)).expected_state,
    )
    correct = commands.runs[OnlyResearchRunId(inner_id.value)]
    commands.runs[OnlyResearchRunId(inner_id.value)] = replace(
        correct,
        run_id=OnlyResearchRunId("00000000-0000-4000-8000-000000000999"),
    )
    mismatched = OnlyAdvanceSearchExperimentV1(
        _command_id(),
        OnlySearchMethodV1.SYMBOLIC,
        OnlySearchBoundedOperationV1.RECONCILE_ONE_SYMBOLIC_OCCURRENCE,
        _reconcile_expected(observed, plan.iteration_plan_fingerprint),
    )
    with pytest.raises(OnlySearchProductSemanticFactCorrupt):
        service.advance(mismatched)
    assert mismatched.command_id not in authority.receipts
    assert (
        query._adapters[OnlySearchMethodV1.SYMBOLIC]._provenance.terminal_result_for_plan_verified(  # type: ignore[attr-defined]
            plan.iteration_plan_fingerprint
        )
        is None
    )


def test_symbolic_effect_assessment_distinguishes_pre_and_complete(tmp_path) -> None:
    service, query, _authority, _commands, submit = _case(tmp_path)
    experiment = service.submit(submit).experiment.experiment_fingerprint
    adapter = query._adapters[OnlySearchMethodV1.SYMBOLIC]  # type: ignore[attr-defined]
    initial = query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment)).expected_state
    command = OnlyAdvanceSearchExperimentV1(
        _command_id(),
        OnlySearchMethodV1.SYMBOLIC,
        OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE,
        initial,
    )
    assert adapter.assess_advance_effect(command) is OnlySearchProductEffectStateV1.EXACT_PRE_STATE
    service.advance(command)
    assert adapter.assess_advance_effect(command) is OnlySearchProductEffectStateV1.COMPLETE_EXACT_EFFECT
