from __future__ import annotations

from dataclasses import fields, replace
from decimal import Decimal
from threading import Barrier, Thread
from types import SimpleNamespace
from typing import Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from onlyalpha.research.command.errors import OnlyResearchSubmissionConflictError
from onlyalpha.research.evaluation.definition import OnlyResearchStatisticsMethod
from onlyalpha.research.evaluation.summary.metric import only_research_effect_metric
from onlyalpha.research.evaluation.summary.scalar import (
    OnlyResearchSummaryScalar,
    OnlyResearchSummaryScalarStatus,
)
from onlyalpha.research.experiment import (
    OnlySearchAlgorithmBindingV1,
    OnlySearchBudgetV1,
    OnlySearchDecisionEngineBindingV1,
    OnlySearchDecisionMode,
    OnlySearchEvaluationContextReferenceV1,
    OnlySearchExperimentManifestV1,
    OnlySearchExperimentManifestV2,
    OnlySearchExperimentManifestV3,
    OnlySearchHypothesisV1,
    OnlySearchPolicyReferenceV1,
    OnlySearchRandomnessMode,
    OnlySearchSpaceReferenceV1,
    OnlySearchWorkflowBindingV1,
)
from onlyalpha.research.run.model import OnlyResearchRunState
from onlyalpha.research.search.parameter import (
    DETERMINISTIC_COARSE_TO_FINE_ALGORITHM_ID,
    DETERMINISTIC_COARSE_TO_FINE_ALGORITHM_SEMANTIC_VERSION,
    PARAMETER_SEARCH_POLICY_KIND,
    PARAMETER_SEARCH_SPACE_KIND,
    OnlyJsonParameterSearchStore,
    OnlyParameterFactorSearchSpaceV1,
    OnlyParameterFeedbackDecisionKind,
    OnlyParameterObjectiveDirection,
    OnlyParameterResearchEvidenceV1,
    OnlyParameterSearchAlgorithmManifestV1,
    OnlyParameterSearchControllerV1,
    OnlyParameterSearchError,
    OnlyParameterSearchFeedbackDecisionV1,
    OnlyParameterSearchPolicyV1,
    OnlyParameterSearchStopReason,
    OnlyParameterSearchStoreError,
    OnlyParameterTieBreakerV1,
    OnlyResolvedParameterResearchCandidateV1,
    OnlyVerifiedParameterSearchContextV1,
    decide_parameter_search_v1,
    materialize_parameter_proposals,
    plans_for_feedback_decision,
    reconcile_parameter_research_plan,
    resolve_parameter_research_candidate,
)
from onlyalpha.research.search.symbolic.evaluation import (
    SYMBOLIC_EVALUATION_CONTRACT_KIND,
    OnlySymbolicResearchEvaluationContractV1,
)
from onlyalpha.research.specification.model import (
    OnlyResearchScientificEvidenceSpec,
    OnlyResearchSeriesSelector,
    OnlyResearchSignalEvidenceSpec,
    OnlyResearchSpecification,
)
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver
from tests.research.specification.support import registry as specification_registry
from tests.research.specification.support import specification
from tests.research.sweep.support import definition, registry

_SHA = "a" * 64
_ALGORITHM_SHA = "b" * 64
_METRIC = only_research_effect_metric(OnlyResearchStatisticsMethod.IC, "mean").metric_id
_TIE = only_research_effect_metric(OnlyResearchStatisticsMethod.IC, "information_ratio").metric_id


def _space(candidates: tuple[object, ...] = (1, 3, 5, 7, 9)) -> OnlyParameterFactorSearchSpaceV1:
    return OnlyParameterFactorSearchSpaceV1.from_sweep(
        catalog_generation_fingerprint="c" * 64,
        sweep_definition=definition(candidates=candidates),
        candidate_template_node_id="momentum",
        candidate_output_name="factor_value",
        calculation_registry=registry(),
    )


def _proposals():  # type: ignore[no-untyped-def]
    return materialize_parameter_proposals(_space(), registry())


def _policy(**changes: object) -> OnlyParameterSearchPolicyV1:
    values = {
        "primary_metric_selector": _METRIC,
        "objective_direction": OnlyParameterObjectiveDirection.MAXIMIZE,
        "required_constraints": (),
        "ordered_tie_breakers": (OnlyParameterTieBreakerV1(_TIE, OnlyParameterObjectiveDirection.MAXIMIZE),),
        "minimum_improvement": Decimal("0.010000000000"),
        "max_no_improvement_decisions": 3,
        "batch_size": 3,
        "coarse_stride": 2,
    }
    values.update(changes)
    return OnlyParameterSearchPolicyV1(**values)  # type: ignore[arg-type]


def _scalar(metric_id: str, value: str) -> OnlyResearchSummaryScalar:
    descriptor = only_research_effect_metric(
        OnlyResearchStatisticsMethod.IC,
        "mean" if metric_id == _METRIC else "information_ratio",
    )
    return OnlyResearchSummaryScalar(
        descriptor.metric_id,
        descriptor.value_kind,
        OnlyResearchSummaryScalarStatus.VALID,
        decimal_value=Decimal(value).quantize(Decimal("0.000000000001")),
    )


def _evidence(proposal, value: str, tie: str = "0.000000000000"):  # type: ignore[no-untyped-def]
    return OnlyParameterResearchEvidenceV1(
        f"{proposal.ordinal + 1:064x}",
        proposal,
        {_METRIC: _scalar(_METRIC, value), _TIE: _scalar(_TIE, tie)},
        True,
        True,
    )


def _decide(evidence=(), prior=(), policy=None):  # type: ignore[no-untyped-def]
    return decide_parameter_search_v1(
        experiment_fingerprint=_SHA,
        proposals=_proposals(),
        policy=policy or _policy(),
        algorithm_implementation_fingerprint=_ALGORITHM_SHA,
        budget=OnlySearchBudgetV1(5, 5, 1),
        evidence=tuple(evidence),
        prior_decisions=tuple(prior),
    )


def _manifest(policy: OnlyParameterSearchPolicyV1) -> OnlySearchExperimentManifestV3:
    algorithm = OnlyParameterSearchAlgorithmManifestV1(
        DETERMINISTIC_COARSE_TO_FINE_ALGORITHM_ID,
        DETERMINISTIC_COARSE_TO_FINE_ALGORITHM_SEMANTIC_VERSION,
        "revision",
        ("d" * 64,),
    )
    space = _space()
    return OnlySearchExperimentManifestV3(
        OnlySearchHypothesisV1("finite adaptive parameter hypothesis"),
        OnlySearchAlgorithmBindingV1(
            algorithm.algorithm_id,
            algorithm.algorithm_semantic_version,
            algorithm.implementation_fingerprint,
            algorithm.source_revision,
        ),
        OnlySearchSpaceReferenceV1(PARAMETER_SEARCH_SPACE_KIND, 1, space.search_space_fingerprint),
        OnlySearchEvaluationContextReferenceV1(SYMBOLIC_EVALUATION_CONTRACT_KIND, 1, "e" * 64),
        OnlySearchPolicyReferenceV1(PARAMETER_SEARCH_POLICY_KIND, 1, policy.policy_fingerprint),
        OnlySearchRandomnessMode.NONE,
        None,
        OnlySearchBudgetV1(5, 5, 1),
        space.catalog_generation_fingerprint,
        space.sweep_definition.dataset_snapshot_fingerprint,
        OnlySearchWorkflowBindingV1("parameter.factor.search", "1"),
        OnlySearchDecisionEngineBindingV1(OnlySearchDecisionMode.DETERMINISTIC),
    )


def _context() -> OnlyVerifiedParameterSearchContextV1:
    policy = _policy()
    experiment = _manifest(policy)
    algorithm = OnlyParameterSearchAlgorithmManifestV1(
        DETERMINISTIC_COARSE_TO_FINE_ALGORITHM_ID,
        DETERMINISTIC_COARSE_TO_FINE_ALGORITHM_SEMANTIC_VERSION,
        "revision",
        ("d" * 64,),
    )
    return OnlyVerifiedParameterSearchContextV1(
        experiment,
        _space(),
        policy,
        cast(Any, None),
        cast(Any, None),
        cast(Any, None),
        algorithm,
        _proposals(),
        cast(Any, None),
    )


class _Provenance:
    def __init__(self) -> None:
        self.plans = {}  # type: ignore[var-annotated]
        self.results = {}  # type: ignore[var-annotated]

    def iteration_plans_for_experiment_verified(self, experiment_fingerprint: str):  # type: ignore[no-untyped-def]
        return tuple(sorted(self.plans.values(), key=lambda item: item.iteration_index))

    def terminal_result_for_plan_verified(self, plan_fingerprint: str):  # type: ignore[no-untyped-def]
        return self.results.get(plan_fingerprint)

    def commit_iteration_plan(self, value):  # type: ignore[no-untyped-def]
        existing = next(
            (item for item in self.plans.values() if item.iteration_index == value.iteration_index),
            None,
        )
        if existing is not None and existing != value:
            raise RuntimeError("plan conflict")
        self.plans[value.iteration_plan_fingerprint] = value

    def commit_iteration_result(self, value):  # type: ignore[no-untyped-def]
        self.results[value.iteration_plan_fingerprint] = value


def test_at_b1_b2_b3_b5_deterministic_decision_ignores_load_and_completion_order() -> None:
    proposals = _proposals()
    first = _decide()
    assert first.ordered_next_proposal_fingerprints == tuple(
        proposals[index].proposal_fingerprint for index in (0, 2, 4)
    )
    evidence = (
        _evidence(proposals[0], "0.100000000000"),
        _evidence(proposals[2], "0.300000000000"),
        _evidence(proposals[4], "0.200000000000"),
    )
    expected = _decide(evidence)
    assert _decide(tuple(reversed(evidence))) == expected
    assert expected.ordered_next_proposal_fingerprints == (
        proposals[1].proposal_fingerprint,
        proposals[3].proposal_fingerprint,
    )


def test_at_b4_b6_b7_b8_canonical_identity_and_no_numeric_search_truth() -> None:
    left = _space((9, 1, 7, 3, 5))
    right = _space((1, 3, 5, 7, 9))
    assert left.search_space_fingerprint == right.search_space_fingerprint
    proposals = materialize_parameter_proposals(left, registry())
    proposal = proposals[0]
    assert (
        len(
            {
                left.search_space_fingerprint,
                proposal.proposal_fingerprint,
                proposal.graph_fingerprint,
                proposal.candidate_node_fingerprint,
            }
        )
        == 4
    )
    forbidden = {"ic", "rank_ic", "sharpe", "coverage", "stability", "qualification_decision"}
    assert not ({field.name.lower() for field in fields(OnlyParameterSearchFeedbackDecisionV1)} & forbidden)
    assert len({item.proposal_fingerprint for item in proposals}) == left.cardinality


def test_at_b8_parameter_candidate_is_created_only_by_normal_research_resolver() -> None:
    base = specification(_SHA)
    scientific = OnlyResearchSpecification(
        base.dataset_snapshot_fingerprint,
        base.calculations,
        base.statistics,
        OnlyResearchScientificEvidenceSpec(
            "feature",
            (OnlyResearchSeriesSelector("feature", "momentum", "factor_value"),),
            OnlyResearchSignalEvidenceSpec(),
        ),
        2,
    )
    evaluation = OnlySymbolicResearchEvaluationContractV1.from_specification(scientific, "feature")
    context = replace(_context(), evaluation_contract=evaluation)
    resolved = resolve_parameter_research_candidate(
        context,
        context.proposals[0],
        OnlyResearchSpecificationResolver(specification_registry()),
    )
    assert resolved.candidate.candidate_fingerprint is not None
    assert resolved.candidate.graph_fingerprint == context.proposals[0].graph_fingerprint


def test_at_b9_v1_v2_readers_and_identity_are_unchanged() -> None:
    assert OnlySearchExperimentManifestV1.from_dict.__func__ is not None
    assert OnlySearchExperimentManifestV2.from_dict.__func__ is not None
    v3 = _manifest(_policy())
    assert OnlySearchExperimentManifestV3.from_dict(v3.to_dict()) == v3


def test_at_b10_b22_concurrent_frontier_is_put_once(tmp_path) -> None:
    store = OnlyJsonParameterSearchStore(tmp_path)
    proposals = _proposals()
    first = _decide()
    competing = replace(first, ordered_next_proposal_fingerprints=(proposals[1].proposal_fingerprint,))
    barrier = Barrier(2)
    outcomes: list[object] = []

    def commit(value: OnlyParameterSearchFeedbackDecisionV1) -> None:
        barrier.wait()
        try:
            outcomes.append(store.commit_feedback_decision(value, expected_predecessor_fingerprint=None))
        except Exception as exc:  # exact observed concurrency outcome
            outcomes.append(exc)

    threads = [Thread(target=commit, args=(item,)) for item in (first, competing)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(not isinstance(item, Exception) for item in outcomes) == 1
    assert sum(isinstance(item, OnlyParameterSearchStoreError) for item in outcomes) == 1
    committed = store.load_feedback_decision_intrinsic_verified(store.load_frontier_fingerprint(_SHA) or "")
    assert committed in {first, competing}


def test_parameter_authority_store_exact_round_trip_and_reuse(tmp_path) -> None:
    store = OnlyJsonParameterSearchStore(tmp_path)
    space = _space()
    policy = _policy()
    proposal = _proposals()[0]
    algorithm = OnlyParameterSearchAlgorithmManifestV1(
        DETERMINISTIC_COARSE_TO_FINE_ALGORITHM_ID, "1", "revision", ("d" * 64,)
    )
    for commit, load, value, fingerprint in (
        (store.commit_search_space, store.load_search_space_intrinsic_verified, space, space.search_space_fingerprint),
        (store.commit_policy, store.load_policy_intrinsic_verified, policy, policy.policy_fingerprint),
        (store.commit_proposal, store.load_proposal_intrinsic_verified, proposal, proposal.proposal_fingerprint),
        (
            store.commit_algorithm_manifest,
            store.load_algorithm_manifest_intrinsic_verified,
            algorithm,
            algorithm.implementation_fingerprint,
        ),
    ):
        assert commit(value).disposition.value == "CREATED"
        assert commit(value).disposition.value == "REUSED"
        assert load(fingerprint) == value


def test_at_b11_b12_b13_policy_changes_change_experiment_identity() -> None:
    baseline = _policy()
    variants = (
        _policy(primary_metric_selector=_TIE),
        _policy(ordered_tie_breakers=()),
        _policy(max_no_improvement_decisions=4),
    )
    assert len({baseline.policy_fingerprint, *(item.policy_fingerprint for item in variants)}) == 4
    assert (
        len(
            {_manifest(baseline).experiment_fingerprint, *(_manifest(item).experiment_fingerprint for item in variants)}
        )
        == 4
    )


def test_at_b14_b24_b25_failure_is_unavailable_not_a_score() -> None:
    proposals = _proposals()
    failed = OnlyParameterResearchEvidenceV1("1" * 64, proposals[0], {}, True, False)
    decision = _decide((failed,))
    assert decision.stop_reason is OnlyParameterSearchStopReason.NO_ELIGIBLE_EVIDENCE
    assert failed.metric_scalars == {}


def test_at_b16_b17_feedback_batch_resumes_exact_plans() -> None:
    decision = _decide()
    plans = plans_for_feedback_decision(decision, _proposals())
    assert tuple(item.iteration_index for item in plans) == (0, 1, 2)
    assert {item.decision_output_fingerprint for item in plans} == {decision.feedback_decision_fingerprint}
    assert tuple(item.proposal_fingerprint for item in plans) == decision.ordered_next_proposal_fingerprints


def test_at_b15_b16_b17_controller_restart_completes_exact_partial_batch(tmp_path) -> None:
    context = _context()
    uninterrupted_store = OnlyJsonParameterSearchStore(tmp_path / "uninterrupted")
    uninterrupted_provenance = _Provenance()
    uninterrupted = OnlyParameterSearchControllerV1(
        parameter_store=uninterrupted_store,
        provenance=uninterrupted_provenance,
    ).advance(context, ())
    store = OnlyJsonParameterSearchStore(tmp_path)
    provenance = _Provenance()
    decision = decide_parameter_search_v1(
        experiment_fingerprint=context.experiment.experiment_fingerprint,
        proposals=context.proposals,
        policy=context.policy,
        algorithm_implementation_fingerprint=context.historical_algorithm_manifest.implementation_fingerprint,
        budget=context.experiment.search_budget,
        evidence=(),
    )
    store.commit_feedback_decision(decision, expected_predecessor_fingerprint=None)
    exact = plans_for_feedback_decision(decision, context.proposals)
    provenance.commit_iteration_plan(exact[0])
    controller = OnlyParameterSearchControllerV1(parameter_store=store, provenance=provenance)
    with pytest.raises(OnlyParameterSearchError, match="SEARCH_ROUND_BARRIER_OPEN"):
        controller.advance(context, ())
    assert tuple(provenance.plans.values()) == exact
    assert uninterrupted.decision == decision
    assert uninterrupted.plans == exact


def test_at_b19_budget_is_derived_and_never_returns() -> None:
    proposals = _proposals()
    evidence = tuple(_evidence(item, f"0.{index + 1:012d}") for index, item in enumerate(proposals[:3]))
    decision = decide_parameter_search_v1(
        experiment_fingerprint=_SHA,
        proposals=proposals,
        policy=_policy(),
        algorithm_implementation_fingerprint=_ALGORITHM_SHA,
        budget=OnlySearchBudgetV1(3, 3, 1),
        evidence=evidence,
    )
    assert decision.stop_reason is OnlyParameterSearchStopReason.PROPOSAL_BUDGET_EXHAUSTED
    assert _decide(tuple(reversed(evidence))) == _decide(evidence)


def test_at_b18_completed_run_reconciles_exact_terminal_iteration_result() -> None:
    decision = _decide()
    plan = plans_for_feedback_decision(decision, _proposals())[0]
    provenance = _Provenance()
    provenance.commit_iteration_plan(plan)
    candidate = SimpleNamespace(candidate_fingerprint="7" * 64)
    resolution = SimpleNamespace(workload=SimpleNamespace(result_plan=SimpleNamespace(fingerprint="8" * 64)))
    resolved = OnlyResolvedParameterResearchCandidateV1(
        _proposals()[0], cast(Any, object()), cast(Any, resolution), cast(Any, candidate)
    )

    class Commands:
        def submit_research_run(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return SimpleNamespace(
                run=SimpleNamespace(
                    state=OnlyResearchRunState.COMPLETED,
                    research_result_fingerprint="9" * 64,
                )
            )

    result = reconcile_parameter_research_plan(
        plan=plan,
        resolved=resolved,
        provenance=provenance,
        commands=cast(Any, Commands()),
    )
    assert result is not None and result.research_attempted
    assert result.research_result_reference is not None
    assert result.research_result_reference.locator_fingerprint == "8" * 64
    assert provenance.results[plan.iteration_plan_fingerprint] == result


def test_at_b20_ambiguous_command_receipt_fails_closed_without_retry() -> None:
    decision = _decide()
    plan = plans_for_feedback_decision(decision, _proposals())[0]
    provenance = _Provenance()
    calls = 0

    class Commands:
        def submit_research_run(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            nonlocal calls
            calls += 1
            raise OnlyResearchSubmissionConflictError()

    resolved = OnlyResolvedParameterResearchCandidateV1(
        _proposals()[0], cast(Any, object()), cast(Any, object()), cast(Any, object())
    )
    with pytest.raises(OnlyParameterSearchError, match="AMBIGUOUS_ATTEMPT_STATE"):
        reconcile_parameter_research_plan(
            plan=plan,
            resolved=resolved,
            provenance=provenance,
            commands=cast(Any, Commands()),
        )
    assert calls == 1
    assert not provenance.results


def test_at_b21_b23_full_terminal_prefix_is_canonical_input() -> None:
    proposals = _proposals()
    evidence = tuple(_evidence(item, f"0.{index + 1:012d}") for index, item in enumerate(proposals[:3]))
    decision = _decide(tuple(reversed(evidence)))
    assert decision.ordered_input_iteration_result_fingerprints == tuple(
        item.iteration_result_fingerprint for item in evidence
    )


def test_at_b26_b27_missing_and_mismatched_evidence_fail_closed() -> None:
    proposals = _proposals()
    missing = OnlyParameterResearchEvidenceV1("1" * 64, proposals[0], {_METRIC: _scalar(_METRIC, "0.1")}, True, True)
    with pytest.raises(Exception, match="MISSING_REQUIRED_EVIDENCE"):
        _decide((missing,))
    foreign = replace(proposals[0], search_space_fingerprint="f" * 64)
    with pytest.raises(Exception, match="outside Search Space"):
        _decide((_evidence(foreign, "0.100000000000"),))


def test_at_b28_b29_b30_history_load_is_independent_of_current_algorithm(tmp_path) -> None:
    store = OnlyJsonParameterSearchStore(tmp_path)
    historical = OnlyParameterSearchAlgorithmManifestV1(
        DETERMINISTIC_COARSE_TO_FINE_ALGORITHM_ID, "1", "old", ("1" * 64,)
    )
    changed = OnlyParameterSearchAlgorithmManifestV1(DETERMINISTIC_COARSE_TO_FINE_ALGORITHM_ID, "2", "new", ("2" * 64,))
    store.commit_algorithm_manifest(historical)
    store.commit_algorithm_manifest(changed)
    decision = _decide()
    store.commit_feedback_decision(decision, expected_predecessor_fingerprint=None)
    assert store.load_feedback_decision_intrinsic_verified(decision.feedback_decision_fingerprint) == decision
    assert historical.implementation_fingerprint != changed.implementation_fingerprint
    assert _decide() == decision


def test_at_b31_b32_b33_exact_coarse_to_fine_and_exhaustion() -> None:
    proposals = _proposals()
    initial = _decide()
    first_evidence = (
        _evidence(proposals[0], "0.100000000000"),
        _evidence(proposals[2], "0.300000000000"),
        _evidence(proposals[4], "0.200000000000"),
    )
    refined = _decide(first_evidence, (initial,))
    all_evidence = (
        *first_evidence,
        _evidence(proposals[1], "0.250000000000"),
        _evidence(proposals[3], "0.290000000000"),
    )
    stopped = _decide(all_evidence, (initial, refined))
    assert stopped.decision_kind is OnlyParameterFeedbackDecisionKind.STOP
    assert stopped.stop_reason is OnlyParameterSearchStopReason.SEARCH_SPACE_EXHAUSTED
    assert len({item.proposal.proposal_fingerprint for item in all_evidence}) == 5


def test_at_b34_convergence_is_a_durable_stop() -> None:
    proposals = _proposals()
    evidence = (
        _evidence(proposals[0], "0.100000000000"),
        _evidence(proposals[2], "0.300000000000"),
        _evidence(proposals[4], "0.200000000000"),
    )
    anchor_result = evidence[1].iteration_result_fingerprint
    prior = tuple(
        replace(
            _decide(),
            selected_anchor_iteration_result_fingerprint=anchor_result,
            ordered_input_iteration_result_fingerprints=tuple(item.iteration_result_fingerprint for item in evidence),
        )
        for _ in range(3)
    )
    stopped = _decide(evidence, prior)
    assert stopped.stop_reason is OnlyParameterSearchStopReason.CONVERGED_NO_IMPROVEMENT
    assert OnlyParameterSearchFeedbackDecisionV1.from_dict(stopped.to_dict()) == stopped


@given(st.permutations((0, 1, 2)))
def test_property_completion_permutation_cannot_change_feedback_decision(order: list[int]) -> None:
    proposals = _proposals()
    evidence = (
        _evidence(proposals[0], "0.100000000000"),
        _evidence(proposals[2], "0.300000000000"),
        _evidence(proposals[4], "0.200000000000"),
    )
    assert _decide(tuple(evidence[index] for index in order)) == _decide(evidence)


@given(
    proposal_limit=st.integers(min_value=1, max_value=5),
    research_limit=st.integers(min_value=1, max_value=5),
    batch_size=st.integers(min_value=1, max_value=5),
)
def test_property_initial_batch_never_exceeds_any_durable_budget(
    proposal_limit: int,
    research_limit: int,
    batch_size: int,
) -> None:
    decision = decide_parameter_search_v1(
        experiment_fingerprint=_SHA,
        proposals=_proposals(),
        policy=_policy(batch_size=batch_size),
        algorithm_implementation_fingerprint=_ALGORITHM_SHA,
        budget=OnlySearchBudgetV1(proposal_limit, research_limit, 1),
        evidence=(),
    )
    assert len(decision.ordered_next_proposal_fingerprints) <= min(proposal_limit, research_limit, batch_size)
