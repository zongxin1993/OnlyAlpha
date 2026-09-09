from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest

from onlyalpha.application.product_boundary import only_compose_research_product_boundary
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
    OnlyGetSearchIterationLedgerV1,
    OnlyParameterExpectedStateV1,
    OnlySearchBoundedOperationV1,
    OnlySearchMethodV1,
    OnlySearchProductCommandServiceV1,
    OnlySearchProductEffectStateV1,
    OnlySearchProductExpectedStateMismatch,
    OnlySearchProductQueryServiceV1,
    OnlySearchProductSemanticFactCorrupt,
    OnlySubmitParameterSearchExperimentV1,
    OnlySubmitParameterSearchExperimentV2,
)
from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.command.model import OnlyResearchSubmitDisposition, OnlyResearchSubmitOutcome
from onlyalpha.research.experiment import (
    OnlySearchBudgetV1,
    OnlySearchDecisionEngineBindingV1,
    OnlySearchDecisionMode,
    OnlySearchHypothesisV1,
    OnlySearchWorkflowBindingV1,
)
from onlyalpha.research.run.model import (
    OnlyResearchRun,
    OnlyResearchRunFailure,
    OnlyResearchRunFailurePhase,
    OnlyResearchRunId,
    OnlyResearchRunState,
)
from onlyalpha.research.search.parameter import (
    OnlyJsonParameterSearchStore,
    OnlyParameterResearchEvidenceV1,
    OnlyParameterSearchProductAdapterV1,
    commit_feedback_plan_batch,
    materialize_parameter_proposals,
    only_deterministic_coarse_to_fine_implementation,
    parameter_submission_key,
)
from onlyalpha.research.search.parameter.context import OnlyVerifiedParameterSearchContextV1
from onlyalpha.research.search.symbolic import (
    OnlyJsonSymbolicSearchStore,
    OnlySymbolicResearchEvaluationContractV1,
)
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver
from tests.research.search.symbolic.test_research_and_provenance_integration import _scientific_template
from tests.research.search.symbolic.test_search_product_adapter import _ProductAuthority
from tests.research.specification.support import registry as specification_registry
from tests.runtime_generation_support import OnlyTestRuntimeGenerationAuthority

from .test_adaptive_parameter_search_v1 import (
    _completed_initial_round,
    _context,
    _decision_for_context,
    _EvidenceReader,
    _policy,
    _Provenance,
    _space,
    _verified,
)


class _Contexts:
    def __init__(self, context):  # type: ignore[no-untyped-def]
        self.context = context

    def resolve_verified_context(self, experiment):  # type: ignore[no-untyped-def]
        if experiment != self.context.experiment:
            raise ValueError("Experiment differs")
        return self.context


class _DurableProvenance(_Provenance):
    def __init__(self, experiment) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.experiment = experiment

    def load_experiment_verified(self, fingerprint):  # type: ignore[no-untyped-def]
        if fingerprint != self.experiment.experiment_fingerprint:
            raise KeyError(fingerprint)
        return self.experiment

    def commit_experiment(self, value):  # type: ignore[no-untyped-def]
        assert value == self.experiment


class _ResearchCommands:
    calls = 0

    def submit_research_run(  # type: ignore[no-untyped-def]
        self, submission_key, specification, provenance=None, *, parent_runtime_work_id=None
    ):
        del submission_key, specification, provenance, parent_runtime_work_id
        self.calls += 1
        raise AssertionError("Parameter candidate binding must fail before the fake Research gateway")

    def finalize_parameter_evidence(self, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        raise AssertionError("no completed Research exists")


def _adapter(  # type: ignore[no-untyped-def]
    tmp_path,
    *,
    context=None,
    provenance=None,
    store=None,
    evidence=(),
    evaluation_store=None,
    product_receipts=None,
    research_runs=None,
    research_commands=None,
):
    context = context or _context()
    durable = provenance or _DurableProvenance(context.experiment)
    parameter_store = store or OnlyJsonParameterSearchStore(tmp_path)
    evidence_reader = _EvidenceReader(evidence)
    commands = research_commands or _ResearchCommands()
    adapter = OnlyParameterSearchProductAdapterV1(
        parameter_store=parameter_store,
        evaluation_store=cast(object, evaluation_store),
        provenance=cast(object, durable),
        contexts=cast(object, _Contexts(context)),
        calculation_registry=specification_registry(),
        evidence_reader=cast(object, evidence_reader),
        resolver=OnlyResearchSpecificationResolver(specification_registry()),
        research_commands=cast(object, commands),
        product_receipts=cast(object, product_receipts),
        research_runs=cast(object, research_runs),
    )
    return context, durable, parameter_store, commands, adapter


class _Runs:
    def __init__(self) -> None:
        self.values: dict[OnlyResearchRunId, OnlyResearchRun] = {}

    def get_run(self, run_id: OnlyResearchRunId) -> OnlyResearchRun:
        return self.values[run_id]


class _ProductResearchCommands:
    def __init__(self, authority: _ProductAuthority, runs: _Runs) -> None:
        self.authority = authority
        self.runs = runs
        self.calls = 0

    def submit_research_run(  # type: ignore[no-untyped-def]
        self, submission_key, specification, provenance=None, *, parent_runtime_work_id=None
    ):
        del provenance, parent_runtime_work_id
        self.calls += 1
        admission = OnlyProductCommandAdmissionV1(
            submission_key,
            self.authority.research_kind,
            "9" * 64,
        )
        self.authority.admit_exact(admission)
        self.authority.put_verified_receipt(
            OnlyProductCommandReceipt(
                submission_key,
                self.authority.research_kind,
                "9" * 64,
                OnlyProductCommandOutcomeRef(
                    OnlyProductCommandOutcomeKind.RESEARCH_RUN,
                    submission_key.value,
                ),
                datetime(2026, 9, 8, tzinfo=UTC),
            )
        )
        run = OnlyResearchRun.queued(
            run_id=OnlyResearchRunId(submission_key.value),
            specification=specification,
            canonical_specification_payload=only_canonical_json(specification.to_dict()),
            admission_resolution_fingerprint="6" * 64,
            queued_at=datetime(2026, 9, 8, tzinfo=UTC),
        ).transition(OnlyResearchRunState.RUNNING, at=datetime(2026, 9, 8, 0, 0, 1, tzinfo=UTC))
        run = run.transition(
            OnlyResearchRunState.FAILED,
            at=datetime(2026, 9, 8, 0, 0, 2, tzinfo=UTC),
            failure=OnlyResearchRunFailure(
                OnlyResearchRunFailurePhase.EXECUTION,
                "TEST_RESEARCH_FAILED",
                "deterministic terminal failure",
            ),
        )
        self.runs.values[run.run_id] = run
        return OnlyResearchSubmitOutcome(OnlyResearchSubmitDisposition.REUSED, run)

    def finalize_parameter_evidence(self, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        raise AssertionError("failed Research has no Evidence")


def _product_case(tmp_path):  # type: ignore[no-untyped-def]
    search_space = _space()
    policy = _policy()
    algorithm = only_deterministic_coarse_to_fine_implementation()
    dataset = search_space.sweep_definition.dataset_snapshot_fingerprint
    evaluation = OnlySymbolicResearchEvaluationContractV1.from_specification(
        _scientific_template(dataset),
        "feature",
    )
    runtime_generations = OnlyTestRuntimeGenerationAuthority(
        generation_fingerprint="f" * 64,
        catalog_generation_fingerprint=search_space.catalog_generation_fingerprint,
    )
    submit = OnlySubmitParameterSearchExperimentV2(
        OnlyProductCommandId(str(uuid4())),
        OnlySearchHypothesisV1("bounded Product parameter recovery"),
        search_space,
        evaluation,
        policy,
        OnlySearchBudgetV1(5, 5, 1),
        algorithm,
        OnlySearchWorkflowBindingV1("parameter.factor.search", "1"),
        OnlySearchDecisionEngineBindingV1(OnlySearchDecisionMode.DETERMINISTIC),
        search_space.catalog_generation_fingerprint,
        dataset,
        runtime_generation_fingerprint=runtime_generations.generation_fingerprint,
    )
    _context0, _provenance0, _store0, _commands0, deriver = _adapter(tmp_path)
    experiment = deriver.derive_submit_experiment(submit)
    context = OnlyVerifiedParameterSearchContextV1(
        experiment,
        search_space,
        policy,
        evaluation,
        cast(object, None),
        cast(object, None),
        algorithm,
        materialize_parameter_proposals(search_space, specification_registry()),
        specification_registry(),
    )
    provenance = _DurableProvenance(experiment)
    store = OnlyJsonParameterSearchStore(tmp_path)
    evaluations = OnlyJsonSymbolicSearchStore(tmp_path)
    authority = _ProductAuthority()
    runs = _Runs()
    research_commands = _ProductResearchCommands(authority, runs)
    _context1, _provenance1, _store1, commands, adapter = _adapter(
        tmp_path,
        context=context,
        provenance=provenance,
        store=store,
        evaluation_store=evaluations,
        product_receipts=authority,
        research_runs=runs,
        research_commands=research_commands,
    )
    service = OnlySearchProductCommandServiceV1(
        command_admissions=authority,
        command_receipts=authority,
        runtime_generations=runtime_generations,
        adapters=(adapter,),
        now_utc=lambda: datetime(2026, 9, 8, tzinfo=UTC),
    )
    return service, OnlySearchProductQueryServiceV1((adapter,)), authority, runs, commands, submit, adapter


def _command(expected: OnlyParameterExpectedStateV1, operation: OnlySearchBoundedOperationV1):
    return OnlyAdvanceSearchExperimentV1(
        OnlyProductCommandId(str(uuid4())),
        OnlySearchMethodV1.PARAMETER,
        operation,
        expected,
    )


def test_parameter_advance_is_one_decision_batch_and_reconcile_creates_no_decision(tmp_path) -> None:
    context, provenance, store, commands, adapter = _adapter(tmp_path)
    initial = adapter.expected_state(context.experiment.experiment_fingerprint)
    adapter.apply_advance(_command(initial, OnlySearchBoundedOperationV1.ADVANCE_ONE_PARAMETER_DECISION))
    advanced = adapter.expected_state(context.experiment.experiment_fingerprint)
    assert len(advanced.ordered_feedback_decision_fingerprints) == 1
    assert len(provenance.plans) == len(advanced.frontier_plan_states) > 0
    assert commands.calls == 0

    with pytest.raises(
        OnlySearchProductExpectedStateMismatch,
        match="open Parameter batch requires reconciliation",
    ):
        adapter.apply_advance(_command(advanced, OnlySearchBoundedOperationV1.ADVANCE_ONE_PARAMETER_DECISION))
    frontier = advanced.frontier_fingerprint
    adapter.apply_advance(_command(advanced, OnlySearchBoundedOperationV1.RECONCILE_OPEN_PARAMETER_BATCH))
    reconciled = adapter.expected_state(context.experiment.experiment_fingerprint)
    assert reconciled.frontier_fingerprint == frontier
    assert len(reconciled.ordered_feedback_decision_fingerprints) == 1
    assert all(item.result_fingerprint is not None for item in reconciled.frontier_plan_states)
    assert commands.calls == 0


def test_parameter_submit_is_exact_experiment_only_and_identity_excludes_command_id(tmp_path) -> None:
    search_space = _space()
    policy = _policy()
    algorithm = only_deterministic_coarse_to_fine_implementation()
    dataset = search_space.sweep_definition.dataset_snapshot_fingerprint
    evaluation = OnlySymbolicResearchEvaluationContractV1.from_specification(
        _scientific_template(dataset),
        "feature",
    )
    submit = OnlySubmitParameterSearchExperimentV2(
        OnlyProductCommandId(str(uuid4())),
        OnlySearchHypothesisV1("bounded Product parameter hypothesis"),
        search_space,
        evaluation,
        policy,
        OnlySearchBudgetV1(5, 5, 1),
        algorithm,
        OnlySearchWorkflowBindingV1("parameter.factor.search", "1"),
        OnlySearchDecisionEngineBindingV1(OnlySearchDecisionMode.DETERMINISTIC),
        search_space.catalog_generation_fingerprint,
        dataset,
        runtime_generation_fingerprint="f" * 64,
    )
    _context0, _provenance0, _store0, _commands0, deriver = _adapter(tmp_path)
    experiment = deriver.derive_submit_experiment(submit)
    context = OnlyVerifiedParameterSearchContextV1(
        experiment,
        search_space,
        policy,
        evaluation,
        cast(object, None),
        cast(object, None),
        algorithm,
        materialize_parameter_proposals(search_space, specification_registry()),
        specification_registry(),
    )
    provenance = _DurableProvenance(experiment)
    store = OnlyJsonParameterSearchStore(tmp_path)
    evaluations = OnlyJsonSymbolicSearchStore(tmp_path)
    _context1, _provenance1, _store1, commands, adapter = _adapter(
        tmp_path,
        context=context,
        provenance=provenance,
        store=store,
        evaluation_store=evaluations,
    )

    exact = adapter.commit_submit(submit, experiment)
    assert exact == experiment
    assert provenance.plans == {}
    assert store.load_frontier_fingerprint(experiment.experiment_fingerprint) is None
    assert commands.calls == 0
    same_intent = OnlySubmitParameterSearchExperimentV2(
        OnlyProductCommandId(str(uuid4())),
        submit.hypothesis,
        submit.search_space,
        submit.evaluation_contract,
        submit.search_policy,
        submit.search_budget,
        submit.algorithm_manifest,
        submit.workflow_binding,
        submit.decision_engine_binding,
        submit.catalog_generation_fingerprint,
        submit.dataset_snapshot_fingerprint,
        runtime_generation_fingerprint=submit.runtime_generation_fingerprint,
    )
    assert same_intent.command_fingerprint == submit.command_fingerprint


def test_parameter_v1_historical_replay_uses_canonical_product_boundary(tmp_path) -> None:
    service, query, authority, _runs, _commands, submit, _adapter = _product_case(tmp_path)

    class _Ready:
        def assert_mutation_ready(self) -> None:
            pass

    boundary = only_compose_research_product_boundary(
        admission=_Ready(),
        commands=cast(object, object()),
        queries=cast(object, object()),
        search_commands=service,
        search_queries=query,
    )
    created = boundary.commands.dispatch(submit)
    historical = OnlySubmitParameterSearchExperimentV1(
        OnlyProductCommandId(str(uuid4())),
        submit.hypothesis,
        submit.search_space,
        submit.evaluation_contract,
        submit.search_policy,
        submit.search_budget,
        submit.algorithm_manifest,
        submit.workflow_binding,
        submit.decision_engine_binding,
        submit.catalog_generation_fingerprint,
        submit.dataset_snapshot_fingerprint,
    )
    authority.admit_exact(
        OnlyProductCommandAdmissionV1(
            historical.command_id,
            OnlyProductCommandKind.CREATE_PARAMETER_SEARCH_EXPERIMENT,
            historical.command_fingerprint,
        )
    )

    replay = boundary.commands.dispatch(historical)

    assert replay.experiment == created.experiment
    fresh = replace(historical, command_id=OnlyProductCommandId(str(uuid4())))
    before = len(authority.receipts)
    with pytest.raises(Exception, match="Search Submit V1 cannot admit new executable work"):
        boundary.commands.dispatch(fresh)
    assert len(authority.receipts) == before


def test_parameter_partial_effect_retry_completes_same_decision_in_fresh_adapter(tmp_path) -> None:
    context, provenance, store, _commands, adapter = _adapter(tmp_path)
    expected = adapter.expected_state(context.experiment.experiment_fingerprint)
    decision = _decision_for_context(context)
    store.commit_feedback_decision(_verified(decision, context=context))
    exact_plans = commit_feedback_plan_batch(decision, context.proposals, provenance)
    # Deterministically simulate a crash after only the first Plan by rebuilding the durable projection.
    provenance.plans = {exact_plans[0].iteration_plan_fingerprint: exact_plans[0]}

    _context2, _provenance2, _store2, commands2, restarted = _adapter(
        tmp_path,
        provenance=provenance,
        store=store,
    )
    restarted.apply_advance(_command(expected, OnlySearchBoundedOperationV1.ADVANCE_ONE_PARAMETER_DECISION))
    assert len(provenance.plans) == len(exact_plans)
    assert restarted.expected_state(context.experiment.experiment_fingerprint).frontier_fingerprint == (
        decision.feedback_decision_fingerprint
    )
    assert commands2.calls == 0


def test_parameter_expected_state_has_no_generic_mutable_search_version(tmp_path) -> None:
    context, _provenance, _store, _commands, adapter = _adapter(tmp_path)
    state = adapter.expected_state(context.experiment.experiment_fingerprint)
    assert "search_version" not in state.to_dict()
    assert state.frontier_fingerprint is None


def test_stale_open_batch_advance_cannot_claim_a_later_decision(tmp_path) -> None:
    context = _context()
    decision, plans, results, evidence = _completed_initial_round(context)
    provenance = _DurableProvenance(context.experiment)
    store = OnlyJsonParameterSearchStore(tmp_path)
    store.commit_feedback_decision(_verified(decision, context=context))
    for plan in plans:
        provenance.commit_iteration_plan(plan)
    _context2, _provenance, _store, _commands, adapter = _adapter(
        tmp_path,
        context=context,
        provenance=provenance,
        store=store,
        evidence=evidence,
    )
    open_batch = adapter.expected_state(context.experiment.experiment_fingerprint)
    stale_illegal = _command(open_batch, OnlySearchBoundedOperationV1.ADVANCE_ONE_PARAMETER_DECISION)

    for result in results:
        provenance.commit_iteration_result(result)
    completed = adapter.expected_state(context.experiment.experiment_fingerprint)
    adapter.apply_advance(_command(completed, OnlySearchBoundedOperationV1.ADVANCE_ONE_PARAMETER_DECISION))
    after_later_advance = adapter.expected_state(context.experiment.experiment_fingerprint)

    with pytest.raises(OnlySearchProductExpectedStateMismatch):
        adapter.apply_advance(stale_illegal)
    assert adapter.expected_state(context.experiment.experiment_fingerprint) == after_later_advance


def test_parameter_old_advance_effect_remains_exactly_provable_after_later_frontier(tmp_path) -> None:
    context = _context()
    decision, plans, results, evidence = _completed_initial_round(context)
    provenance = _DurableProvenance(context.experiment)
    store = OnlyJsonParameterSearchStore(tmp_path)
    _context2, _provenance, _store, _commands, adapter = _adapter(
        tmp_path,
        context=context,
        provenance=provenance,
        store=store,
        evidence=evidence,
    )
    initial = adapter.expected_state(context.experiment.experiment_fingerprint)
    first_advance = _command(initial, OnlySearchBoundedOperationV1.ADVANCE_ONE_PARAMETER_DECISION)
    store.commit_feedback_decision(_verified(decision, context=context))
    for plan in plans:
        provenance.commit_iteration_plan(plan)
    for result in results:
        provenance.commit_iteration_result(result)
    completed = adapter.expected_state(context.experiment.experiment_fingerprint)
    adapter.apply_advance(_command(completed, OnlySearchBoundedOperationV1.ADVANCE_ONE_PARAMETER_DECISION))

    adapter.verify_advance_effect(first_advance)


def test_parameter_submit_and_old_advance_recovery_survive_later_frontier(tmp_path) -> None:
    service, query, authority, _runs, commands, submit, adapter = _product_case(tmp_path)
    same_intent = replace(submit, command_id=OnlyProductCommandId(str(uuid4())))
    experiment = service.submit(submit).experiment.experiment_fingerprint
    assert service.submit(same_intent).experiment.experiment_fingerprint == experiment
    initial = query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment))
    first_advance = _command(
        cast(OnlyParameterExpectedStateV1, initial.expected_state),
        OnlySearchBoundedOperationV1.ADVANCE_ONE_PARAMETER_DECISION,
    )
    first = service.advance(first_advance)
    first_frontier = cast(OnlyParameterExpectedStateV1, first.ledger.expected_state).frontier_fingerprint

    del authority.receipts[submit.command_id]
    repaired_submit = service.submit(submit)
    assert (
        cast(OnlyParameterExpectedStateV1, repaired_submit.ledger.expected_state).frontier_fingerprint == first_frontier
    )
    assert commands.calls == 0

    open_state = cast(OnlyParameterExpectedStateV1, first.ledger.expected_state)
    service.advance(_command(open_state, OnlySearchBoundedOperationV1.RECONCILE_OPEN_PARAMETER_BATCH))
    completed = cast(
        OnlyParameterExpectedStateV1,
        query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment)).expected_state,
    )
    proposals = {
        item.proposal_fingerprint: item
        for item in adapter._contexts.context.proposals  # type: ignore[attr-defined]
    }
    for plan in adapter.ledger(experiment).plans:
        result = adapter._provenance.terminal_result_for_plan_verified(  # type: ignore[attr-defined]
            plan.iteration_plan_fingerprint
        )
        assert result is not None
        evidence = OnlyParameterResearchEvidenceV1(
            result.iteration_result_fingerprint,
            proposals[plan.proposal_fingerprint],
            {},
            True,
            False,
        )
        adapter._evidence_reader.values[evidence.iteration_result_fingerprint] = evidence  # type: ignore[attr-defined]
    service.advance(_command(completed, OnlySearchBoundedOperationV1.ADVANCE_ONE_PARAMETER_DECISION))
    later = cast(
        OnlyParameterExpectedStateV1,
        query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment)).expected_state,
    )
    assert later.frontier_fingerprint != first_frontier

    del authority.receipts[first_advance.command_id]
    before = (later.frontier_fingerprint, len(adapter.ledger(experiment).plans), commands.calls)
    repaired = service.advance(first_advance)
    after = cast(OnlyParameterExpectedStateV1, repaired.ledger.expected_state)
    assert (after.frontier_fingerprint, len(repaired.ledger.plans), commands.calls) == before

    del authority.receipts[same_intent.command_id]
    same_repair = service.submit(same_intent)
    assert cast(OnlyParameterExpectedStateV1, same_repair.ledger.expected_state).frontier_fingerprint == (
        later.frontier_fingerprint
    )


def test_parameter_research_receipt_must_exact_resolve_owning_run(tmp_path) -> None:
    service, query, authority, runs, _commands, submit, adapter = _product_case(tmp_path)
    experiment = service.submit(submit).experiment.experiment_fingerprint
    initial = query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment))
    advanced = service.advance(
        _command(
            cast(OnlyParameterExpectedStateV1, initial.expected_state),
            OnlySearchBoundedOperationV1.ADVANCE_ONE_PARAMETER_DECISION,
        )
    )
    open_state = cast(OnlyParameterExpectedStateV1, advanced.ledger.expected_state)
    plan = advanced.ledger.plans[0]
    inner_id = parameter_submission_key(plan)
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
    dangling = _command(open_state, OnlySearchBoundedOperationV1.RECONCILE_OPEN_PARAMETER_BATCH)
    with pytest.raises(OnlySearchProductSemanticFactCorrupt):
        service.advance(dangling)
    assert dangling.command_id not in authority.receipts
    assert adapter._provenance.terminal_result_for_plan_verified(plan.iteration_plan_fingerprint) is None  # type: ignore[attr-defined]

    proposal = next(
        item for item in adapter._contexts.context.proposals if item.proposal_fingerprint == plan.proposal_fingerprint
    )  # type: ignore[attr-defined]
    from onlyalpha.research.search.parameter.integration import resolve_parameter_research_candidate

    resolved = resolve_parameter_research_candidate(adapter._contexts.context, proposal, adapter._resolver)  # type: ignore[attr-defined]
    wrong_id = OnlyResearchRunId("00000000-0000-4000-8000-000000000998")
    runs.values[OnlyResearchRunId(inner_id.value)] = OnlyResearchRun.queued(
        run_id=wrong_id,
        specification=resolved.specification,
        canonical_specification_payload=only_canonical_json(resolved.specification.to_dict()),
        admission_resolution_fingerprint="6" * 64,
        queued_at=datetime(2026, 9, 8, tzinfo=UTC),
    )
    mismatched = _command(open_state, OnlySearchBoundedOperationV1.RECONCILE_OPEN_PARAMETER_BATCH)
    with pytest.raises(OnlySearchProductSemanticFactCorrupt):
        service.advance(mismatched)
    assert mismatched.command_id not in authority.receipts


def test_parameter_effect_assessment_distinguishes_pre_partial_complete(tmp_path) -> None:
    service, _query, authority, _runs, _commands, _submit, adapter = _product_case(tmp_path)
    experiment = adapter.load_experiment_verified(adapter._contexts.context.experiment.experiment_fingerprint)  # type: ignore[attr-defined]
    service._runtime_generations.bind_work_exact(  # type: ignore[attr-defined]
        f"search-experiment:{experiment.experiment_fingerprint}",
        "f" * 64,
    )
    expected = adapter.expected_state(experiment.experiment_fingerprint)
    command = _command(expected, OnlySearchBoundedOperationV1.ADVANCE_ONE_PARAMETER_DECISION)
    assert adapter.assess_advance_effect(command) is OnlySearchProductEffectStateV1.EXACT_PRE_STATE
    decision = _decision_for_context(adapter._contexts.context)  # type: ignore[attr-defined]
    adapter._store.commit_feedback_decision(_verified(decision, context=adapter._contexts.context))  # type: ignore[attr-defined]
    exact = commit_feedback_plan_batch(decision, adapter._contexts.context.proposals, adapter._provenance)  # type: ignore[attr-defined]
    adapter._provenance.plans = {exact[0].iteration_plan_fingerprint: exact[0]}  # type: ignore[attr-defined]
    assert adapter.assess_advance_effect(command) is OnlySearchProductEffectStateV1.PARTIAL_EXACT_EFFECT
    service.advance(command)
    assert command.command_id in authority.receipts
    assert adapter.assess_advance_effect(command) is OnlySearchProductEffectStateV1.COMPLETE_EXACT_EFFECT
