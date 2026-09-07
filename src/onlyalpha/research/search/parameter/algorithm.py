"""Deterministic coarse-to-fine adaptive parameter search V1."""

from __future__ import annotations

import hashlib
import subprocess
from decimal import Decimal
from functools import cmp_to_key
from pathlib import Path

from onlyalpha.calculation.definition import only_calculation_scalar_sort_key
from onlyalpha.research.experiment import OnlySearchBudgetV1

from .errors import OnlyParameterSearchError
from .evidence import OnlyParameterResearchEvidenceV1
from .model import (
    OnlyParameterConstraintOperator,
    OnlyParameterFeedbackDecisionKind,
    OnlyParameterGraphProposalV1,
    OnlyParameterObjectiveDirection,
    OnlyParameterSearchAlgorithmManifestV1,
    OnlyParameterSearchFeedbackDecisionV1,
    OnlyParameterSearchPolicyV1,
    OnlyParameterSearchStopReason,
)


def only_deterministic_coarse_to_fine_implementation() -> OnlyParameterSearchAlgorithmManifestV1:
    """Bind the exact executable resource closure of algorithm semantic version 1."""

    package_root = Path(__file__).resolve().parents[3]
    repository_root = package_root.parents[1]
    resources = (
        "research/search/parameter/algorithm.py",
        "research/search/parameter/model.py",
        "research/search/parameter/evidence.py",
        "research/search/parameter/integration.py",
        "research/search/parameter/controller.py",
        "research/sweep/planning.py",
        "research/sweep/materialization.py",
        "calculation/definition.py",
        "calculation/graph.py",
    )
    identities = []
    for relative_path in resources:
        path = package_root / relative_path
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"PARAMETER_ALGORITHM_RESOURCE_INVALID: {relative_path}")
        identities.append(hashlib.sha256(relative_path.encode() + b"\0" + path.read_bytes()).hexdigest())
    try:
        revision = subprocess.run(
            ("git", "-C", str(repository_root), "rev-parse", "HEAD"),
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise ValueError("PARAMETER_ALGORITHM_SOURCE_REVISION_UNAVAILABLE") from exc
    return OnlyParameterSearchAlgorithmManifestV1("DETERMINISTIC_COARSE_TO_FINE", "1", revision, tuple(identities))


def decide_parameter_search_v1(
    *,
    experiment_fingerprint: str,
    proposals: tuple[OnlyParameterGraphProposalV1, ...],
    policy: OnlyParameterSearchPolicyV1,
    algorithm_implementation_fingerprint: str,
    budget: OnlySearchBudgetV1,
    evidence: tuple[OnlyParameterResearchEvidenceV1, ...],
    prior_decisions: tuple[OnlyParameterSearchFeedbackDecisionV1, ...] = (),
) -> OnlyParameterSearchFeedbackDecisionV1:
    """Return the sole next durable decision from exact immutable inputs."""

    ordered_proposals = tuple(sorted(proposals, key=lambda item: (item.ordinal, item.proposal_fingerprint)))
    if len({item.proposal_fingerprint for item in ordered_proposals}) != len(ordered_proposals):
        raise OnlyParameterSearchError("IDENTITY_MISMATCH", "duplicate Proposal identity")
    by_fingerprint = {item.proposal_fingerprint: item for item in ordered_proposals}
    ordered_evidence = tuple(
        sorted(evidence, key=lambda item: (item.proposal.ordinal, item.proposal.proposal_fingerprint))
    )
    if len({item.proposal.proposal_fingerprint for item in ordered_evidence}) != len(ordered_evidence):
        raise OnlyParameterSearchError("IDENTITY_MISMATCH", "duplicate terminal Proposal evidence")
    if any(item.proposal.proposal_fingerprint not in by_fingerprint for item in ordered_evidence):
        raise OnlyParameterSearchError("IDENTITY_MISMATCH", "Evidence Proposal is outside Search Space")
    for item in ordered_evidence:
        if item.available and set(policy.required_metric_ids) - set(item.metric_scalars):
            raise OnlyParameterSearchError("MISSING_REQUIRED_EVIDENCE", item.iteration_result_fingerprint)
    tested = {item.proposal.proposal_fingerprint for item in ordered_evidence}
    research_attempts = sum(int(item.research_attempted) for item in ordered_evidence)
    if len(tested) > budget.proposal_limit or research_attempts > budget.research_evaluation_limit:
        raise OnlyParameterSearchError("SEARCH_BUDGET_HISTORY_INVALID", experiment_fingerprint)
    start = len(tested)
    inputs = tuple(item.iteration_result_fingerprint for item in ordered_evidence)

    if not ordered_evidence:
        coarse = tuple(
            item
            for position, item in enumerate(ordered_proposals)
            if position % policy.coarse_stride == 0 or position == len(ordered_proposals) - 1
        )
        return _continue_or_budget_stop(
            experiment_fingerprint, inputs, None, coarse, start, policy, algorithm_implementation_fingerprint, budget, 0
        )

    eligible = tuple(item for item in ordered_evidence if item.available and _constraints_pass(item, policy))
    if not eligible:
        return _stop(
            experiment_fingerprint,
            inputs,
            None,
            start,
            policy,
            algorithm_implementation_fingerprint,
            OnlyParameterSearchStopReason.NO_ELIGIBLE_EVIDENCE,
        )

    def comparison(left: OnlyParameterResearchEvidenceV1, right: OnlyParameterResearchEvidenceV1) -> int:
        return _compare(left, right, policy)

    anchor = sorted(eligible, key=cmp_to_key(comparison))[0]
    if _converged(anchor, ordered_evidence, prior_decisions, policy):
        return _stop(
            experiment_fingerprint,
            inputs,
            anchor.iteration_result_fingerprint,
            start,
            policy,
            algorithm_implementation_fingerprint,
            OnlyParameterSearchStopReason.CONVERGED_NO_IMPROVEMENT,
        )
    if len(tested) == len(ordered_proposals):
        return _stop(
            experiment_fingerprint,
            inputs,
            anchor.iteration_result_fingerprint,
            start,
            policy,
            algorithm_implementation_fingerprint,
            OnlyParameterSearchStopReason.SEARCH_SPACE_EXHAUSTED,
        )
    neighbors = tuple(
        item
        for item in ordered_proposals
        if item.proposal_fingerprint not in tested and _is_neighbor(anchor.proposal, item, ordered_proposals)
    )
    if not neighbors:
        return _stop(
            experiment_fingerprint,
            inputs,
            anchor.iteration_result_fingerprint,
            start,
            policy,
            algorithm_implementation_fingerprint,
            OnlyParameterSearchStopReason.NEIGHBORHOOD_EXHAUSTED,
        )
    return _continue_or_budget_stop(
        experiment_fingerprint,
        inputs,
        anchor.iteration_result_fingerprint,
        neighbors,
        start,
        policy,
        algorithm_implementation_fingerprint,
        budget,
        research_attempts,
    )


def _continue_or_budget_stop(
    experiment: str,
    inputs: tuple[str, ...],
    anchor: str | None,
    candidates: tuple[OnlyParameterGraphProposalV1, ...],
    start: int,
    policy: OnlyParameterSearchPolicyV1,
    algorithm: str,
    budget: OnlySearchBudgetV1,
    research_attempts: int,
) -> OnlyParameterSearchFeedbackDecisionV1:
    proposal_remaining = budget.proposal_limit - start
    research_remaining = budget.research_evaluation_limit - research_attempts
    if proposal_remaining <= 0:
        return _stop(
            experiment,
            inputs,
            anchor,
            start,
            policy,
            algorithm,
            OnlyParameterSearchStopReason.PROPOSAL_BUDGET_EXHAUSTED,
        )
    if research_remaining <= 0:
        return _stop(
            experiment,
            inputs,
            anchor,
            start,
            policy,
            algorithm,
            OnlyParameterSearchStopReason.RESEARCH_BUDGET_EXHAUSTED,
        )
    count = min(policy.batch_size, proposal_remaining, research_remaining, len(candidates))
    if count <= 0:
        return _stop(
            experiment, inputs, anchor, start, policy, algorithm, OnlyParameterSearchStopReason.SEARCH_SPACE_EXHAUSTED
        )
    return OnlyParameterSearchFeedbackDecisionV1(
        experiment,
        inputs,
        anchor,
        tuple(item.proposal_fingerprint for item in candidates[:count]),
        start,
        OnlyParameterFeedbackDecisionKind.CONTINUE,
        None,
        policy.policy_fingerprint,
        algorithm,
    )


def _stop(
    experiment: str,
    inputs: tuple[str, ...],
    anchor: str | None,
    start: int,
    policy: OnlyParameterSearchPolicyV1,
    algorithm: str,
    reason: OnlyParameterSearchStopReason,
) -> OnlyParameterSearchFeedbackDecisionV1:
    return OnlyParameterSearchFeedbackDecisionV1(
        experiment,
        inputs,
        anchor,
        (),
        start,
        OnlyParameterFeedbackDecisionKind.STOP,
        reason,
        policy.policy_fingerprint,
        algorithm,
    )


def _number(evidence: OnlyParameterResearchEvidenceV1, metric_id: str) -> Decimal:
    scalar = evidence.metric_scalars.get(metric_id)
    if scalar is None:
        raise OnlyParameterSearchError("MISSING_REQUIRED_EVIDENCE", metric_id)
    value = scalar.decimal_value if scalar.decimal_value is not None else scalar.integer_value
    if value is None:
        raise OnlyParameterSearchError("MISSING_REQUIRED_EVIDENCE", metric_id)
    return value if isinstance(value, Decimal) else Decimal(value)


def _constraints_pass(evidence: OnlyParameterResearchEvidenceV1, policy: OnlyParameterSearchPolicyV1) -> bool:
    for item in policy.required_constraints:
        value = _number(evidence, item.metric_id)
        if item.operator is OnlyParameterConstraintOperator.GE and not value >= item.threshold:
            return False
        if item.operator is OnlyParameterConstraintOperator.LE and not value <= item.threshold:
            return False
        if item.operator is OnlyParameterConstraintOperator.GT and not value > item.threshold:
            return False
        if item.operator is OnlyParameterConstraintOperator.LT and not value < item.threshold:
            return False
    return True


def _compare(
    left: OnlyParameterResearchEvidenceV1,
    right: OnlyParameterResearchEvidenceV1,
    policy: OnlyParameterSearchPolicyV1,
) -> int:
    selectors = ((policy.primary_metric_selector, policy.objective_direction),) + tuple(
        (item.metric_id, item.direction) for item in policy.ordered_tie_breakers
    )
    for metric_id, direction in selectors:
        left_value, right_value = _number(left, metric_id), _number(right, metric_id)
        if left_value != right_value:
            result = -1 if left_value < right_value else 1
            return -result if direction is OnlyParameterObjectiveDirection.MAXIMIZE else result
    return (
        -1
        if left.proposal.proposal_fingerprint < right.proposal.proposal_fingerprint
        else 1
        if left.proposal.proposal_fingerprint > right.proposal.proposal_fingerprint
        else 0
    )


def _is_neighbor(
    anchor: OnlyParameterGraphProposalV1,
    candidate: OnlyParameterGraphProposalV1,
    proposals: tuple[OnlyParameterGraphProposalV1, ...],
) -> bool:
    left = anchor.assignment_by_key
    right = candidate.assignment_by_key
    if set(left) != set(right):
        raise OnlyParameterSearchError("IDENTITY_MISMATCH", "Proposal dimensions differ")
    differing = tuple(key for key in left if left[key] != right[key])
    if len(differing) != 1:
        return False
    key = differing[0]
    ordered_values = tuple(
        sorted(
            {item.assignment_by_key[key] for item in proposals},
            key=only_calculation_scalar_sort_key,
        )
    )
    return abs(ordered_values.index(left[key]) - ordered_values.index(right[key])) == 1


def _converged(
    anchor: OnlyParameterResearchEvidenceV1,
    evidence: tuple[OnlyParameterResearchEvidenceV1, ...],
    decisions: tuple[OnlyParameterSearchFeedbackDecisionV1, ...],
    policy: OnlyParameterSearchPolicyV1,
) -> bool:
    anchors = [
        item.selected_anchor_iteration_result_fingerprint
        for item in decisions
        if item.selected_anchor_iteration_result_fingerprint
    ]
    if len(anchors) < policy.max_no_improvement_decisions:
        return False
    by_result = {item.iteration_result_fingerprint: item for item in evidence}
    recent = anchors[-policy.max_no_improvement_decisions :]
    if any(item not in by_result for item in recent):
        raise OnlyParameterSearchError("CORRUPT_REFERENCE", "historical anchor Evidence missing")
    current = _number(anchor, policy.primary_metric_selector)
    direction = policy.objective_direction
    return all(
        (current - _number(by_result[item], policy.primary_metric_selector) <= policy.minimum_improvement)
        if direction is OnlyParameterObjectiveDirection.MAXIMIZE
        else (_number(by_result[item], policy.primary_metric_selector) - current <= policy.minimum_improvement)
        for item in recent
    )


__all__ = ["decide_parameter_search_v1", "only_deterministic_coarse_to_fine_implementation"]
