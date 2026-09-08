from __future__ import annotations

from typing import cast
from uuid import uuid4

import pytest

from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.application.search_product import (
    OnlyAdvanceSearchExperimentV1,
    OnlyParameterExpectedStateV1,
    OnlySearchBoundedOperationV1,
    OnlySearchMethodV1,
    OnlySearchProductExpectedStateMismatch,
    OnlySubmitParameterSearchExperimentV1,
)
from onlyalpha.research.experiment import (
    OnlySearchBudgetV1,
    OnlySearchDecisionEngineBindingV1,
    OnlySearchDecisionMode,
    OnlySearchHypothesisV1,
    OnlySearchWorkflowBindingV1,
)
from onlyalpha.research.search.parameter import (
    OnlyJsonParameterSearchStore,
    OnlyParameterSearchProductAdapterV1,
    commit_feedback_plan_batch,
    materialize_parameter_proposals,
    only_deterministic_coarse_to_fine_implementation,
)
from onlyalpha.research.search.parameter.context import OnlyVerifiedParameterSearchContextV1
from onlyalpha.research.search.symbolic import (
    OnlyJsonSymbolicSearchStore,
    OnlySymbolicResearchEvaluationContractV1,
)
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver
from tests.research.search.symbolic.test_research_and_provenance_integration import _scientific_template
from tests.research.specification.support import registry as specification_registry

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

    def submit_research_run(self, submission_key, specification, provenance=None):  # type: ignore[no-untyped-def]
        del submission_key, specification, provenance
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
):
    context = context or _context()
    durable = provenance or _DurableProvenance(context.experiment)
    parameter_store = store or OnlyJsonParameterSearchStore(tmp_path)
    evidence_reader = _EvidenceReader(evidence)
    commands = _ResearchCommands()
    adapter = OnlyParameterSearchProductAdapterV1(
        parameter_store=parameter_store,
        evaluation_store=cast(object, evaluation_store),
        provenance=cast(object, durable),
        contexts=cast(object, _Contexts(context)),
        calculation_registry=specification_registry(),
        evidence_reader=cast(object, evidence_reader),
        resolver=OnlyResearchSpecificationResolver(specification_registry()),
        research_commands=cast(object, commands),
    )
    return context, durable, parameter_store, commands, adapter


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
    submit = OnlySubmitParameterSearchExperimentV1(
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
    same_intent = OnlySubmitParameterSearchExperimentV1(
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
    assert same_intent.command_fingerprint == submit.command_fingerprint


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
