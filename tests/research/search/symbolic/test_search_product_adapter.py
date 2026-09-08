from __future__ import annotations

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
    OnlySearchBoundedOperationV1,
    OnlySearchMethodV1,
    OnlySearchProductCapabilityUnsupported,
    OnlySearchProductCommandConflict,
    OnlySearchProductCommandServiceV1,
    OnlySearchProductExpectedStateMismatch,
    OnlySearchProductQueryServiceV1,
    OnlySearchProductReceiptCorrupt,
    OnlySearchProductSemanticFactCorrupt,
    OnlySubmitSymbolicSearchExperimentV1,
    OnlySymbolicExpectedStateV1,
)
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
from onlyalpha.research.run.model import OnlyResearchRunState
from onlyalpha.research.search.parameter import parameter_submission_key
from onlyalpha.research.search.symbolic import (
    OnlyJsonSymbolicSearchStore,
    OnlySymbolicResearchEvaluationContractV1,
    OnlySymbolicSearchContextResolver,
    OnlySymbolicSearchProductAdapterV1,
    only_deterministic_enumeration_implementation,
    symbolic_submission_key,
)
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver
from tests.research.specification.support import registry as specification_registry

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

    def submit_symbolic_research(self, *, plan, resolved):  # type: ignore[no-untyped-def]
        del resolved
        from onlyalpha.research.search.symbolic import symbolic_submission_key

        self.calls += 1
        command_id = symbolic_submission_key(plan)
        run_id = OnlyProductCommandId("12345678-1234-4234-8234-123456789abc")
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
        run = SimpleNamespace(
            run_id=run_id,
            state=self.state,
            research_result_fingerprint="8" * 64 if self.state is OnlyResearchRunState.COMPLETED else None,
        )
        return SimpleNamespace(disposition=OnlyResearchSubmitDisposition.REUSED, run=run)

    def research_result_reference(self, *, outcome, resolved):  # type: ignore[no-untyped-def]
        del outcome
        candidate = resolved.candidate.candidate_fingerprint
        assert candidate is not None
        reference = OnlySearchResearchResultReferenceV1("7" * 64, "8" * 64)
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


def _case(tmp_path, *, authority=None):  # type: ignore[no-untyped-def]
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
    commands = _Commands(authority, results)
    adapter = OnlySymbolicSearchProductAdapterV1(
        symbolic_store=symbolic,
        provenance=cast(object, provenance),
        contexts=contexts,
        resolver=OnlyResearchSpecificationResolver(specification_registry()),
        research_commands=commands,
        product_receipts=authority,
    )
    service = OnlySearchProductCommandServiceV1(
        command_admissions=authority,
        command_receipts=authority,
        adapters=(adapter,),
        now_utc=lambda: datetime(2026, 9, 8, tzinfo=UTC),
    )
    query = OnlySearchProductQueryServiceV1((adapter,))
    evaluation = OnlySymbolicResearchEvaluationContractV1.from_specification(_scientific_template(dataset), "feature")
    submit = OnlySubmitSymbolicSearchExperimentV1(
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
    same_intent = OnlySubmitSymbolicSearchExperimentV1(
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
    conflict = OnlySubmitSymbolicSearchExperimentV1(
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
    )
    with pytest.raises(OnlySearchProductCommandConflict):
        service.submit(conflict)


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
