from __future__ import annotations

from dataclasses import fields, replace
from datetime import UTC, datetime
from decimal import Decimal
from inspect import signature
from pathlib import Path
from threading import Barrier, Thread
from types import SimpleNamespace
from typing import Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

import onlyalpha.research.search.parameter.algorithm as parameter_algorithm
from onlyalpha.canonical import only_canonical_json
from onlyalpha.research import (
    OnlyJsonResearchResultStore,
    OnlyJsonResearchSummaryStatisticsResultStore,
    OnlyResearchEffectSummaryExecutor,
    OnlyResearchResultAssembler,
    OnlyResearchResultCalculationPlan,
    OnlyResearchResultCandidatePlan,
    OnlyResearchResultPlan,
    OnlyResearchStatisticsDefinition,
    OnlyResearchStatisticsPlan,
    OnlyResearchStatisticsResultReader,
)
from onlyalpha.research.command.errors import OnlyResearchSubmissionConflictError
from onlyalpha.research.evaluation.definition import OnlyResearchStatisticsMethod
from onlyalpha.research.evaluation.summary.metric import only_research_coverage_metric, only_research_effect_metric
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
    OnlySearchIterationDisposition,
    OnlySearchIterationResultV1,
    OnlySearchPolicyReferenceV1,
    OnlySearchRandomnessMode,
    OnlySearchResearchResultReferenceV1,
    OnlySearchSpaceReferenceV1,
    OnlySearchWorkflowBindingV1,
)
from onlyalpha.research.run.model import OnlyResearchRunState
from onlyalpha.research.search.parameter import (
    DETERMINISTIC_COARSE_TO_FINE_ALGORITHM_ID,
    PARAMETER_SEARCH_POLICY_KIND,
    PARAMETER_SEARCH_SPACE_KIND,
    OnlyJsonParameterSearchStore,
    OnlyParameterFactorSearchSpaceV1,
    OnlyParameterFeedbackDecisionKind,
    OnlyParameterObjectiveDirection,
    OnlyParameterResearchEvidenceFinalizerV1,
    OnlyParameterResearchEvidenceReader,
    OnlyParameterResearchEvidenceV1,
    OnlyParameterSearchAlgorithmManifestV1,
    OnlyParameterSearchControllerV1,
    OnlyParameterSearchError,
    OnlyParameterSearchFeedbackDecisionV1,
    OnlyParameterSearchPolicyV1,
    OnlyParameterSearchStopReason,
    OnlyParameterTieBreakerV1,
    OnlyResolvedParameterResearchCandidateV1,
    OnlyVerifiedParameterSearchContextV1,
    decide_parameter_search_v1,
    materialize_parameter_proposals,
    only_deterministic_coarse_to_fine_implementation,
    plans_for_feedback_decision,
    reconcile_parameter_research_plan,
    resolve_parameter_research_candidate,
    verify_parameter_feedback_decision_occurrence,
    verify_parameter_feedback_frontier_for_execution,
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
from tests.research.evaluation.support import statistics_case, summary_case
from tests.research.specification.support import registry as specification_registry
from tests.research.specification.support import specification
from tests.research.sweep.support import definition, registry

pytestmark = pytest.mark.usefixtures("source_checkout_parameter_build_provenance_stub")

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
    algorithm = only_deterministic_coarse_to_fine_implementation()
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


def _context(policy: OnlyParameterSearchPolicyV1 | None = None) -> OnlyVerifiedParameterSearchContextV1:
    policy = policy or _policy()
    experiment = _manifest(policy)
    algorithm = only_deterministic_coarse_to_fine_implementation()
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


def _decision_for_context(context: OnlyVerifiedParameterSearchContextV1 | None = None):  # type: ignore[no-untyped-def]
    current = context or _context()
    return decide_parameter_search_v1(
        experiment_fingerprint=current.experiment.experiment_fingerprint,
        proposals=current.proposals,
        policy=current.policy,
        algorithm_implementation_fingerprint=current.historical_algorithm_manifest.implementation_fingerprint,
        budget=current.experiment.search_budget,
        evidence=(),
    )


def _completed_initial_round(context: OnlyVerifiedParameterSearchContextV1):  # type: ignore[no-untyped-def]
    initial = _decision_for_context(context)
    plans = plans_for_feedback_decision(initial, context.proposals)
    proposal_by_fingerprint = {item.proposal_fingerprint: item for item in context.proposals}
    results = []
    evidence = []
    for index, plan in enumerate(plans):
        result = OnlySearchIterationResultV1(
            plan.iteration_plan_fingerprint,
            f"{index + 10:064x}",
            True,
            OnlySearchResearchResultReferenceV1(f"{index + 20:064x}", f"{index + 30:064x}"),
            False,
            None,
            OnlySearchIterationDisposition.RESEARCH_EVIDENCE_RECORDED,
            None,
        )
        proposal = proposal_by_fingerprint[plan.proposal_fingerprint]
        results.append(result)
        evidence.append(
            OnlyParameterResearchEvidenceV1(
                result.iteration_result_fingerprint,
                proposal,
                {
                    _METRIC: _scalar(_METRIC, f"0.{index + 1:012d}"),
                    _TIE: _scalar(_TIE, f"0.{index + 1:012d}"),
                },
                True,
                True,
            )
        )
    return initial, plans, tuple(results), tuple(evidence)


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


class _EvidenceReader:
    def __init__(self, values=()):  # type: ignore[no-untyped-def]
        self.values = {item.iteration_result_fingerprint: item for item in values}

    def load_required(self, *, iteration_result_fingerprint, proposal, policy):  # type: ignore[no-untyped-def]
        del policy
        value = self.values[iteration_result_fingerprint]
        assert value.proposal == proposal
        return value


class _DecisionReader:
    def __init__(self, values=()):  # type: ignore[no-untyped-def]
        self.values = {item.feedback_decision_fingerprint: item for item in values}

    def load_feedback_decision_intrinsic_verified(self, fingerprint):  # type: ignore[no-untyped-def]
        return self.values[fingerprint]


class _ExactValues:
    def __init__(self, values):  # type: ignore[no-untyped-def]
        self._values = values

    def load_iteration_result_verified(self, fingerprint):  # type: ignore[no-untyped-def]
        return self._values[fingerprint]

    def load_iteration_plan_verified(self, fingerprint):  # type: ignore[no-untyped-def]
        return self._values[fingerprint]

    def load_verified(self, fingerprint):  # type: ignore[no-untyped-def]
        return self._values[fingerprint]


def _persist_legacy_frontier(
    root,
    decision: OnlyParameterSearchFeedbackDecisionV1,
) -> OnlyJsonParameterSearchStore:  # type: ignore[no-untyped-def]
    """Frozen test-only layout for data written before verified commit capability."""

    decision_path = (
        root
        / "research/parameter-search/feedback-decisions/sha256"
        / decision.feedback_decision_fingerprint[:2]
        / decision.feedback_decision_fingerprint
    )
    decision_path.mkdir(parents=True)
    (decision_path / "manifest.json").write_text(
        only_canonical_json(decision.to_dict()),
        encoding="utf-8",
    )
    frontier = (
        root
        / "research/parameter-search/frontiers/sha256"
        / decision.experiment_fingerprint[:2]
        / decision.experiment_fingerprint
    )
    frontier.parent.mkdir(parents=True)
    frontier.write_text(decision.feedback_decision_fingerprint + "\n", encoding="ascii")
    return OnlyJsonParameterSearchStore(root)


def _verified(
    decision: OnlyParameterSearchFeedbackDecisionV1,
    *,
    context: OnlyVerifiedParameterSearchContextV1 | None = None,
    plans=(),  # type: ignore[no-untyped-def]
    results=(),  # type: ignore[no-untyped-def]
    evidence=(),  # type: ignore[no-untyped-def]
    prior=(),  # type: ignore[no-untyped-def]
):  # type: ignore[no-untyped-def]
    current = context or _context()
    provenance = _Provenance()
    for plan in plans:
        provenance.commit_iteration_plan(plan)
    for result in results:
        provenance.commit_iteration_result(result)
    return verify_parameter_feedback_decision_occurrence(
        context=current,
        provenance=cast(Any, provenance),
        evidence_reader=cast(Any, _EvidenceReader(evidence)),
        decisions=cast(Any, _DecisionReader(prior)),
        candidate_decision=decision,
    )


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


def test_at_16_17_identical_verified_decisions_converge_to_created_and_reused(tmp_path) -> None:
    store = OnlyJsonParameterSearchStore(tmp_path)
    first = _decision_for_context()
    verified = _verified(first)
    barrier = Barrier(2)
    outcomes: list[object] = []

    def commit() -> None:
        barrier.wait()
        try:
            outcomes.append(store.commit_feedback_decision(verified))
        except Exception as exc:  # exact observed concurrency outcome
            outcomes.append(exc)

    threads = [Thread(target=commit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not any(isinstance(item, Exception) for item in outcomes)
    assert {item.disposition.value for item in outcomes} == {"CREATED", "REUSED"}  # type: ignore[attr-defined]
    committed = store.load_feedback_decision_intrinsic_verified(
        store.load_frontier_fingerprint(first.experiment_fingerprint) or ""
    )
    assert committed == first


def test_at_01_formal_controller_has_no_metric_bearing_argument() -> None:
    assert tuple(signature(OnlyParameterSearchControllerV1.advance).parameters) == ("self", "context")
    assert tuple(signature(OnlyParameterSearchControllerV1.__init__).parameters) == (
        "self",
        "parameter_store",
        "provenance",
        "evidence_reader",
        "generation_execution",
    )
    verifier_parameters = signature(verify_parameter_feedback_decision_occurrence).parameters
    assert not {"current_algorithm", "committed_plans", "terminal_results", "evidence", "prior_decisions"} & set(
        verifier_parameters
    )


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value, proposals, results: replace(
            value,
            ordered_next_proposal_fingerprints=(proposals[-1].proposal_fingerprint,),
        ),
        lambda value, proposals, results: replace(
            value,
            selected_anchor_iteration_result_fingerprint=results[0].iteration_result_fingerprint,
        ),
        lambda value, proposals, results: replace(
            value,
            ordered_input_iteration_result_fingerprints=tuple(
                reversed(value.ordered_input_iteration_result_fingerprints)
            ),
        ),
        lambda value, proposals, results: replace(value, start_iteration_index=value.start_iteration_index + 1),
    ),
)
def test_at_12_15_semantically_fabricated_feedback_decision_is_rejected(mutation) -> None:  # type: ignore[no-untyped-def]
    context = _context()
    initial, plans, results, evidence = _completed_initial_round(context)
    exact = decide_parameter_search_v1(
        experiment_fingerprint=context.experiment.experiment_fingerprint,
        proposals=context.proposals,
        policy=context.policy,
        algorithm_implementation_fingerprint=context.historical_algorithm_manifest.implementation_fingerprint,
        budget=context.experiment.search_budget,
        evidence=evidence,
        prior_decisions=(initial,),
    )
    fabricated = mutation(exact, context.proposals, results)
    assert fabricated != exact
    with pytest.raises(OnlyParameterSearchError, match="PARAMETER_FEEDBACK_OCCURRENCE_MISMATCH"):
        _verified(
            fabricated,
            context=context,
            plans=plans,
            results=results,
            evidence=evidence,
            prior=(initial,),
        )


def test_at_11_exact_algorithm_decision_is_occurrence_verified() -> None:
    context = _context()
    decision = _decision_for_context(context)
    assert _verified(decision, context=context).decision == decision


def test_at_02_formal_controller_derives_metrics_from_its_authority_reader(tmp_path) -> None:
    context = _context()
    initial, plans, results, evidence = _completed_initial_round(context)
    store = OnlyJsonParameterSearchStore(tmp_path)
    store.commit_feedback_decision(_verified(initial, context=context))
    provenance = _Provenance()
    for plan in plans:
        provenance.commit_iteration_plan(plan)
    for result in results:
        provenance.commit_iteration_result(result)
    outcome = OnlyParameterSearchControllerV1(
        parameter_store=store,
        provenance=provenance,
        evidence_reader=cast(Any, _EvidenceReader(evidence)),
    ).advance(context)
    expected = decide_parameter_search_v1(
        experiment_fingerprint=context.experiment.experiment_fingerprint,
        proposals=context.proposals,
        policy=context.policy,
        algorithm_implementation_fingerprint=context.historical_algorithm_manifest.implementation_fingerprint,
        budget=context.experiment.search_budget,
        evidence=evidence,
        prior_decisions=(initial,),
    )
    assert outcome.decision == expected


def test_unverified_structurally_valid_decision_cannot_enter_store(tmp_path) -> None:
    decision = _decision_for_context()
    with pytest.raises(OnlyParameterSearchError, match="PARAMETER_FEEDBACK_DECISION_UNVERIFIED"):
        OnlyJsonParameterSearchStore(tmp_path).commit_feedback_decision(cast(Any, decision))


def test_at_07_10_current_runtime_mismatch_blocks_execution_not_historical_load(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    context = _context()
    decision, plans, results, evidence = _completed_initial_round(context)
    store = OnlyJsonParameterSearchStore(tmp_path)
    store.commit_feedback_decision(_verified(decision, context=context))
    changed = replace(
        context.historical_algorithm_manifest,
        ordered_resource_sha256=("f" * 64,),
    )
    monkeypatch.setattr(parameter_algorithm, "only_deterministic_coarse_to_fine_implementation", lambda: changed)
    provenance = _Provenance()
    for plan in plans:
        provenance.commit_iteration_plan(plan)
    for result in results:
        provenance.commit_iteration_result(result)
    controller = OnlyParameterSearchControllerV1(
        parameter_store=store,
        provenance=provenance,
        evidence_reader=cast(Any, _EvidenceReader(evidence)),
    )
    assert store.load_feedback_decision_intrinsic_verified(decision.feedback_decision_fingerprint) == decision
    with pytest.raises(OnlyParameterSearchError, match="PARAMETER_ALGORITHM_RUNTIME_MISMATCH"):
        controller.advance(context)
    assert (
        store.load_frontier_fingerprint(context.experiment.experiment_fingerprint)
        == decision.feedback_decision_fingerprint
    )
    with pytest.raises(OnlyParameterSearchError, match="PARAMETER_ALGORITHM_RUNTIME_MISMATCH"):
        controller.certify_historical_reproduction(context, decision, ())


def test_at_h1_h2_runtime_admission_precedes_partial_plan_recovery(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    context = _context()
    decision = _decision_for_context(context)
    store = _persist_legacy_frontier(tmp_path, decision)
    provenance = _Provenance()
    exact = plans_for_feedback_decision(decision, context.proposals)
    provenance.commit_iteration_plan(exact[0])
    changed = replace(context.historical_algorithm_manifest, ordered_resource_sha256=("f" * 64,))
    monkeypatch.setattr(parameter_algorithm, "only_deterministic_coarse_to_fine_implementation", lambda: changed)
    controller = OnlyParameterSearchControllerV1(
        parameter_store=store,
        provenance=provenance,
        evidence_reader=cast(Any, _EvidenceReader()),
    )
    assert store.load_feedback_decision_intrinsic_verified(decision.feedback_decision_fingerprint) == decision
    with pytest.raises(OnlyParameterSearchError, match="PARAMETER_ALGORITHM_RUNTIME_MISMATCH"):
        controller.advance(context)
    assert tuple(provenance.plans.values()) == exact[:1]
    with pytest.raises(OnlyParameterSearchError, match="PARAMETER_ALGORITHM_RUNTIME_MISMATCH"):
        controller.reconcile_open_plans(
            context,
            resolver=cast(Any, object()),
            commands=cast(Any, object()),
        )
    assert tuple(provenance.plans.values()) == exact[:1]


def test_at_h3_fabricated_legacy_frontier_exact_loads_but_cannot_authorize_work(tmp_path) -> None:
    context = _context()
    exact = _decision_for_context(context)
    fabricated = replace(
        exact,
        ordered_next_proposal_fingerprints=tuple(reversed(exact.ordered_next_proposal_fingerprints)),
    )
    store = _persist_legacy_frontier(tmp_path, fabricated)
    provenance = _Provenance()
    controller = OnlyParameterSearchControllerV1(
        parameter_store=store,
        provenance=provenance,
        evidence_reader=cast(Any, _EvidenceReader()),
    )
    assert store.load_feedback_decision_intrinsic_verified(fabricated.feedback_decision_fingerprint) == fabricated
    with pytest.raises(OnlyParameterSearchError, match="PARAMETER_FEEDBACK_HISTORY_UNVERIFIED"):
        controller.advance(context)
    assert not provenance.plans and not provenance.results


def test_at_h4_p1_p2_p3_legitimate_legacy_frontier_recovers_only_missing_suffix(tmp_path) -> None:
    context = _context()
    decision = _decision_for_context(context)
    store = _persist_legacy_frontier(tmp_path, decision)
    provenance = _Provenance()
    exact = plans_for_feedback_decision(decision, context.proposals)
    provenance.commit_iteration_plan(exact[0])
    controller = OnlyParameterSearchControllerV1(
        parameter_store=store,
        provenance=provenance,
        evidence_reader=cast(Any, _EvidenceReader()),
    )
    with pytest.raises(OnlyParameterSearchError, match="SEARCH_ROUND_BARRIER_OPEN"):
        controller.advance(context)
    assert tuple(provenance.plans.values()) == exact
    with pytest.raises(OnlyParameterSearchError, match="SEARCH_ROUND_BARRIER_OPEN"):
        controller.advance(context)
    assert tuple(provenance.plans.values()) == exact


@pytest.mark.parametrize("existing_indices", ((1,), (0, 2)))
def test_at_p4_gapped_or_non_prefix_plan_batch_fails_closed(tmp_path, existing_indices) -> None:  # type: ignore[no-untyped-def]
    context = _context()
    decision = _decision_for_context(context)
    store = _persist_legacy_frontier(tmp_path, decision)
    exact = plans_for_feedback_decision(decision, context.proposals)
    provenance = _Provenance()
    for index in existing_indices:
        provenance.plans[exact[index].iteration_plan_fingerprint] = exact[index]
    before = dict(provenance.plans)
    with pytest.raises(OnlyParameterSearchError, match="SEARCH_ITERATION_PREFIX_CORRUPT"):
        verify_parameter_feedback_frontier_for_execution(
            context=context,
            provenance=cast(Any, provenance),
            evidence_reader=cast(Any, _EvidenceReader()),
            decisions=store,
            frontier_fingerprint=decision.feedback_decision_fingerprint,
        )
    assert provenance.plans == before


def test_at_d6_fabricated_prior_decision_cannot_influence_next_decision() -> None:
    context = _context()
    initial, _plans, _results, _evidence_values = _completed_initial_round(context)
    fabricated = replace(
        initial,
        ordered_next_proposal_fingerprints=tuple(reversed(initial.ordered_next_proposal_fingerprints)),
    )
    plans = plans_for_feedback_decision(fabricated, context.proposals)
    by_proposal = {item.proposal_fingerprint: item for item in context.proposals}
    results = tuple(
        OnlySearchIterationResultV1(
            plan.iteration_plan_fingerprint,
            f"{index + 10:064x}",
            True,
            OnlySearchResearchResultReferenceV1(f"{index + 20:064x}", f"{index + 30:064x}"),
            False,
            None,
            OnlySearchIterationDisposition.RESEARCH_EVIDENCE_RECORDED,
            None,
        )
        for index, plan in enumerate(plans)
    )
    evidence = tuple(
        OnlyParameterResearchEvidenceV1(
            result.iteration_result_fingerprint,
            by_proposal[plan.proposal_fingerprint],
            {_METRIC: _scalar(_METRIC, f"0.{index + 1:012d}"), _TIE: _scalar(_TIE, "0")},
            True,
            True,
        )
        for index, (plan, result) in enumerate(zip(plans, results, strict=True))
    )
    candidate = decide_parameter_search_v1(
        experiment_fingerprint=context.experiment.experiment_fingerprint,
        proposals=context.proposals,
        policy=context.policy,
        algorithm_implementation_fingerprint=context.historical_algorithm_manifest.implementation_fingerprint,
        budget=context.experiment.search_budget,
        evidence=evidence,
        prior_decisions=(fabricated,),
    )
    with pytest.raises(OnlyParameterSearchError, match="PARAMETER_FEEDBACK_HISTORY_UNVERIFIED"):
        _verified(
            candidate,
            context=context,
            plans=plans,
            results=results,
            evidence=evidence,
            prior=(fabricated,),
        )


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


def test_parameter_runtime_identity_is_offline_and_does_not_require_git(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "")
    first = only_deterministic_coarse_to_fine_implementation()
    second = only_deterministic_coarse_to_fine_implementation()
    assert first == second
    assert first.source_revision == "1" * 40


def test_missing_packaged_build_provenance_fails_before_new_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context()
    provenance = _Provenance()
    store = OnlyJsonParameterSearchStore(tmp_path)

    def unavailable() -> object:
        raise ValueError("ONLYALPHA_BUILD_PROVENANCE_UNAVAILABLE")

    monkeypatch.setattr(parameter_algorithm, "only_packaged_build_provenance", unavailable)
    controller = OnlyParameterSearchControllerV1(
        parameter_store=store,
        provenance=provenance,
        evidence_reader=cast(Any, _EvidenceReader()),
    )
    with pytest.raises(ValueError, match="PARAMETER_ALGORITHM_SOURCE_REVISION_UNAVAILABLE"):
        controller.advance(context)
    assert provenance.plans == {}
    assert store.load_frontier_fingerprint(context.experiment.experiment_fingerprint) is None


def test_tampered_packaged_revision_blocks_new_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context()
    provenance = _Provenance()
    store = OnlyJsonParameterSearchStore(tmp_path)
    monkeypatch.setattr(
        parameter_algorithm,
        "only_packaged_build_provenance",
        lambda: SimpleNamespace(source_revision="f" * 40),
    )
    controller = OnlyParameterSearchControllerV1(
        parameter_store=store,
        provenance=provenance,
        evidence_reader=cast(Any, _EvidenceReader()),
    )
    with pytest.raises(OnlyParameterSearchError, match="PARAMETER_ALGORITHM_RUNTIME_MISMATCH"):
        controller.advance(context)
    assert provenance.plans == {}
    assert store.load_frontier_fingerprint(context.experiment.experiment_fingerprint) is None


def test_tampered_algorithm_resource_blocks_new_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context()
    provenance = _Provenance()
    store = OnlyJsonParameterSearchStore(tmp_path)
    original_read_bytes = Path.read_bytes

    def tampered_read_bytes(path: Path) -> bytes:
        content = original_read_bytes(path)
        return content + b"\n# tampered\n" if path.name == "algorithm.py" else content

    monkeypatch.setattr(Path, "read_bytes", tampered_read_bytes)
    controller = OnlyParameterSearchControllerV1(
        parameter_store=store,
        provenance=provenance,
        evidence_reader=cast(Any, _EvidenceReader()),
    )
    with pytest.raises(OnlyParameterSearchError, match="PARAMETER_ALGORITHM_RUNTIME_MISMATCH"):
        controller.advance(context)
    assert provenance.plans == {}
    assert store.load_frontier_fingerprint(context.experiment.experiment_fingerprint) is None


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


def _real_research_evidence_case(root, *, result_identity: str | None = None):  # type: ignore[no-untyped-def]
    case = summary_case(root)
    summary_plan, summary_store, summary_executor = case[11], case[12], case[13]
    summary_executor.execute(summary_plan)
    summary = summary_store.load_verified(summary_plan.statistics_fingerprint)
    source = summary_plan.source_statistics_fingerprint
    calculation = case[2].load_verified(summary_plan.subject.calculation_fingerprint).manifest
    member = OnlyResearchResultCalculationPlan(
        calculation.calculation_fingerprint,
        calculation.calculation_graph_fingerprint,
    )
    candidate = OnlyResearchResultCandidatePlan(
        summary_plan.subject_candidate_fingerprint,
        "feature",
        (),
        member.calculation_fingerprint,
        member.graph_fingerprint,
        (summary_plan.statistics_fingerprint,),
    )
    result_plan = OnlyResearchResultPlan(
        (source, summary_plan.statistics_fingerprint),
        2,
        summary_plan.dataset_snapshot_fingerprint,
        (member,),
        (candidate,),
    )
    statistics = OnlyResearchStatisticsResultReader(root / "statistics-results", case[8], summary_store)
    assembled = OnlyResearchResultAssembler(
        statistics,
        calculation_result_store=case[2],
        audit_time=lambda: datetime(2026, 9, 7, tzinfo=UTC),
    ).assemble(result_plan)
    results = OnlyJsonResearchResultStore(root / "research-results", statistics, case[2])
    results.commit(assembled)
    context = _context()
    decision = _decision_for_context(context)
    plan = plans_for_feedback_decision(decision, context.proposals)[0]
    iteration = OnlySearchIterationResultV1(
        plan.iteration_plan_fingerprint,
        candidate.candidate_fingerprint,
        True,
        OnlySearchResearchResultReferenceV1(
            result_plan.fingerprint,
            result_identity or assembled.manifest.research_result_fingerprint,
        ),
        False,
        None,
        OnlySearchIterationDisposition.RESEARCH_EVIDENCE_RECORDED,
        None,
    )
    reader = OnlyParameterResearchEvidenceReader(
        iteration_results=cast(Any, _ExactValues({iteration.iteration_result_fingerprint: iteration})),
        iteration_plans=cast(Any, _ExactValues({plan.iteration_plan_fingerprint: plan})),
        research_results=results,
        statistics_results=statistics,
    )
    return context, plan, iteration, reader, summary


def test_at_02_06_evidence_reader_uses_exact_research_and_statistics_authorities(tmp_path) -> None:
    context, plan, iteration, reader, _summary = _real_research_evidence_case(tmp_path)
    proposal = next(item for item in context.proposals if item.proposal_fingerprint == plan.proposal_fingerprint)
    evidence = reader.load_required(
        iteration_result_fingerprint=iteration.iteration_result_fingerprint,
        proposal=proposal,
        policy=_policy(ordered_tie_breakers=()),
    )
    assert evidence.available
    assert evidence.metric_scalars[_METRIC].metric_id == _METRIC
    assert evidence.metric_scalars[_TIE].metric_id == _TIE


def test_at_03_tampered_research_result_reference_fails_closed(tmp_path) -> None:
    context, plan, iteration, reader, _summary = _real_research_evidence_case(
        tmp_path,
        result_identity="f" * 64,
    )
    proposal = next(item for item in context.proposals if item.proposal_fingerprint == plan.proposal_fingerprint)
    with pytest.raises(OnlyParameterSearchError, match="CORRUPT_REFERENCE"):
        reader.load_required(
            iteration_result_fingerprint=iteration.iteration_result_fingerprint,
            proposal=proposal,
            policy=context.policy,
        )


def test_at_04_tampered_statistics_identity_fails_closed(tmp_path) -> None:
    context, plan, iteration, _reader, summary = _real_research_evidence_case(tmp_path)
    proposal = next(item for item in context.proposals if item.proposal_fingerprint == plan.proposal_fingerprint)
    statistics = _ExactValues({"f" * 64: replace(summary)})
    research = SimpleNamespace(
        manifest=SimpleNamespace(
            research_result_plan_fingerprint=iteration.research_result_reference.locator_fingerprint,
            research_result_fingerprint=iteration.research_result_reference.result_fingerprint,
            statistics_results=(
                SimpleNamespace(
                    statistics_fingerprint="f" * 64,
                    statistics_result_fingerprint=summary.manifest.statistics_result_fingerprint,
                ),
            ),
        )
    )
    reader = OnlyParameterResearchEvidenceReader(
        iteration_results=cast(Any, _ExactValues({iteration.iteration_result_fingerprint: iteration})),
        iteration_plans=cast(Any, _ExactValues({plan.iteration_plan_fingerprint: plan})),
        research_results=cast(Any, _ExactValues({iteration.research_result_reference.locator_fingerprint: research})),
        statistics_results=cast(Any, statistics),
    )
    with pytest.raises(OnlyParameterSearchError, match="CORRUPT_REFERENCE"):
        reader.load_required(
            iteration_result_fingerprint=iteration.iteration_result_fingerprint,
            proposal=proposal,
            policy=context.policy,
        )


def test_at_b16_b17_feedback_batch_resumes_exact_plans() -> None:
    decision = _decision_for_context()
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
        evidence_reader=cast(Any, _EvidenceReader()),
    ).advance(context)
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
    store.commit_feedback_decision(_verified(decision, context=context))
    exact = plans_for_feedback_decision(decision, context.proposals)
    provenance.commit_iteration_plan(exact[0])
    controller = OnlyParameterSearchControllerV1(
        parameter_store=store,
        provenance=provenance,
        evidence_reader=cast(Any, _EvidenceReader()),
    )
    with pytest.raises(OnlyParameterSearchError, match="SEARCH_ROUND_BARRIER_OPEN"):
        controller.advance(context)
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

        def finalize_parameter_evidence(self, **_kwargs):  # type: ignore[no-untyped-def]
            return OnlySearchResearchResultReferenceV1("8" * 64, "9" * 64)

    result = reconcile_parameter_research_plan(
        plan=plan,
        resolved=resolved,
        provenance=provenance,
        commands=cast(Any, Commands()),
        policy=_policy(),
    )
    assert result is not None and result.research_attempted
    assert result.research_result_reference is not None
    assert result.research_result_reference.locator_fingerprint == "8" * 64
    assert provenance.results[plan.iteration_plan_fingerprint] == result


def test_completed_run_composes_registered_mixed_parameter_evidence_sources_once(tmp_path) -> None:
    mixed_policy = replace(
        _policy(),
        ordered_tie_breakers=(
            OnlyParameterTieBreakerV1(
                only_research_effect_metric(
                    OnlyResearchStatisticsMethod.RANK_IC,
                    "mean",
                ).metric_id,
                OnlyParameterObjectiveDirection.MAXIMIZE,
            ),
        ),
    )
    case = statistics_case(tmp_path)
    ic_plan = case[6]
    source_store = case[8]
    source_executor = case[9]
    rank_plan = OnlyResearchStatisticsPlan(
        ic_plan.feature,
        ic_plan.target,
        OnlyResearchStatisticsDefinition(OnlyResearchStatisticsMethod.RANK_IC),
    )
    source_executor.execute(rank_plan)
    summary_store = OnlyJsonResearchSummaryStatisticsResultStore(
        tmp_path / "statistics-results",
        source_store,
        audit_time=lambda: datetime(2026, 9, 8, tzinfo=UTC),
    )
    summary_executor = OnlyResearchEffectSummaryExecutor(source_store, summary_store)
    statistics = OnlyResearchStatisticsResultReader(tmp_path / "statistics-results", source_store, summary_store)
    result_assembler = OnlyResearchResultAssembler(
        statistics,
        calculation_result_store=case[2],
        audit_time=lambda: datetime(2026, 9, 8, tzinfo=UTC),
    )
    calculation = case[2].load_verified(ic_plan.feature.calculation_fingerprint).manifest
    member = OnlyResearchResultCalculationPlan(
        calculation.calculation_fingerprint,
        calculation.calculation_graph_fingerprint,
    )
    candidate = OnlyResearchResultCandidatePlan(
        "c" * 64,
        "feature",
        (),
        member.calculation_fingerprint,
        member.graph_fingerprint,
        tuple(sorted((ic_plan.statistics_fingerprint, rank_plan.statistics_fingerprint))),
    )
    base_plan = OnlyResearchResultPlan(
        tuple(sorted((ic_plan.statistics_fingerprint, rank_plan.statistics_fingerprint))),
        2,
        case[0].snapshot_fingerprint,
        (member,),
        (candidate,),
    )
    base_result = result_assembler.assemble(base_plan)
    results = OnlyJsonResearchResultStore(tmp_path / "research-results", statistics, case[2])
    results.commit(base_result)
    finalizer = OnlyParameterResearchEvidenceFinalizerV1(
        research_results=results,
        summary_executor=summary_executor,
        result_assembler=result_assembler,
    )
    run = SimpleNamespace(
        state=OnlyResearchRunState.COMPLETED,
        research_result_fingerprint=base_result.manifest.research_result_fingerprint,
        run_id=SimpleNamespace(value="run-1"),
    )
    resolved = SimpleNamespace(
        proposal=_proposals()[0],
        candidate=SimpleNamespace(
            candidate_fingerprint=candidate.candidate_fingerprint,
            calculation_fingerprint=candidate.calculation_fingerprint,
        ),
        resolution=SimpleNamespace(
            workload=SimpleNamespace(
                result_plan=base_plan,
                statistics_plans=(ic_plan, rank_plan),
            )
        ),
    )

    reference = finalizer.finalize(run=cast(Any, run), resolved=cast(Any, resolved), policy=mixed_policy)
    repeated = finalizer.finalize(run=cast(Any, run), resolved=cast(Any, resolved), policy=mixed_policy)
    assert repeated == reference
    from onlyalpha.research.search.symbolic.execution import OnlyHostedResolvedResearchV1

    hosted = OnlyHostedResolvedResearchV1(
        specification=cast(Any, None),
        proposal_fingerprint=_proposals()[0].proposal_fingerprint,
        candidate_fingerprint=candidate.candidate_fingerprint,
        calculation_fingerprint=candidate.calculation_fingerprint,
        result_plan=base_plan,
        statistics_plans=(ic_plan, rank_plan),
    )
    assert finalizer.finalize(run=cast(Any, run), resolved=hosted, policy=mixed_policy) == reference
    composition = results.load_verified(reference.locator_fingerprint)
    source_fingerprints = {ic_plan.statistics_fingerprint, rank_plan.statistics_fingerprint}
    summary_fingerprints = {
        item.statistics_fingerprint
        for item in composition.manifest.statistics_results
        if item.statistics_fingerprint not in source_fingerprints
    }
    assert len(summary_fingerprints) == 2
    assert {
        summary_store.load_verified(fingerprint).manifest.plan.definition.source_method
        for fingerprint in summary_fingerprints
    } == {OnlyResearchStatisticsMethod.IC, OnlyResearchStatisticsMethod.RANK_IC}

    decision = _decision_for_context(_context(mixed_policy))
    plan = plans_for_feedback_decision(decision, _proposals())[0]
    iteration = OnlySearchIterationResultV1(
        plan.iteration_plan_fingerprint,
        candidate.candidate_fingerprint,
        True,
        reference,
        False,
        None,
        OnlySearchIterationDisposition.RESEARCH_EVIDENCE_RECORDED,
        None,
    )
    reader = OnlyParameterResearchEvidenceReader(
        iteration_results=cast(Any, _ExactValues({iteration.iteration_result_fingerprint: iteration})),
        iteration_plans=cast(Any, _ExactValues({plan.iteration_plan_fingerprint: plan})),
        research_results=results,
        statistics_results=statistics,
    )
    evidence = reader.load_required(
        iteration_result_fingerprint=iteration.iteration_result_fingerprint,
        proposal=_proposals()[0],
        policy=mixed_policy,
    )
    assert evidence.available
    assert set(mixed_policy.required_metric_ids) <= set(evidence.metric_scalars)


def test_completed_run_rejects_unsupported_summary_family_before_composition() -> None:
    unsupported_policy = replace(
        _policy(),
        primary_metric_selector=only_research_coverage_metric(
            OnlyResearchStatisticsMethod.IC,
            "valid_timestamp_ratio",
        ).metric_id,
        ordered_tie_breakers=(),
    )
    finalizer = OnlyParameterResearchEvidenceFinalizerV1(
        research_results=cast(Any, object()),
        summary_executor=cast(Any, object()),
        result_assembler=cast(Any, object()),
    )
    run = SimpleNamespace(
        state=OnlyResearchRunState.COMPLETED,
        research_result_fingerprint="a" * 64,
        run_id=SimpleNamespace(value="run-1"),
    )
    with pytest.raises(OnlyParameterSearchError, match="PARAMETER_EVIDENCE_METRIC_SET_UNSUPPORTED"):
        finalizer.finalize(
            run=cast(Any, run),
            resolved=cast(Any, object()),
            policy=unsupported_policy,
        )


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
            policy=_policy(),
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
    with pytest.raises(OnlyParameterSearchError, match="MISSING_REQUIRED_EVIDENCE"):
        _decide((missing,))
    foreign = replace(proposals[0], search_space_fingerprint="f" * 64)
    with pytest.raises(OnlyParameterSearchError, match="outside Search Space"):
        _decide((_evidence(foreign, "0.100000000000"),))


def test_at_b28_b29_b30_history_load_is_independent_of_current_algorithm(tmp_path) -> None:
    store = OnlyJsonParameterSearchStore(tmp_path)
    historical = OnlyParameterSearchAlgorithmManifestV1(
        DETERMINISTIC_COARSE_TO_FINE_ALGORITHM_ID, "1", "old", ("1" * 64,)
    )
    changed = OnlyParameterSearchAlgorithmManifestV1(DETERMINISTIC_COARSE_TO_FINE_ALGORITHM_ID, "2", "new", ("2" * 64,))
    store.commit_algorithm_manifest(historical)
    store.commit_algorithm_manifest(changed)
    decision = _decision_for_context()
    store.commit_feedback_decision(_verified(decision))
    assert store.load_feedback_decision_intrinsic_verified(decision.feedback_decision_fingerprint) == decision
    assert historical.implementation_fingerprint != changed.implementation_fingerprint
    assert store.load_feedback_decision_intrinsic_verified(decision.feedback_decision_fingerprint) == decision


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
