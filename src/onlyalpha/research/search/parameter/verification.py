"""Contextual and occurrence verification for adaptive Feedback Decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.research.experiment import OnlySearchIterationPlanV1, OnlySearchIterationResultV1

from .algorithm import decide_parameter_search_v1
from .context import OnlyVerifiedParameterSearchContextV1, admit_current_parameter_algorithm_runtime
from .errors import OnlyParameterSearchError
from .evidence import OnlyParameterResearchEvidenceReader, OnlyParameterResearchEvidenceV1
from .integration import plans_for_feedback_decision
from .model import OnlyParameterSearchFeedbackDecisionV1

_VERIFIED_FEEDBACK_DECISION_SEAL = object()


class _ParameterDecisionReader(Protocol):
    def load_feedback_decision_intrinsic_verified(self, fingerprint: str) -> OnlyParameterSearchFeedbackDecisionV1: ...


class _ParameterOccurrenceProvenance(Protocol):
    def iteration_plans_for_experiment_verified(
        self, experiment_fingerprint: str
    ) -> tuple[OnlySearchIterationPlanV1, ...]: ...

    def terminal_result_for_plan_verified(self, plan_fingerprint: str) -> OnlySearchIterationResultV1 | None: ...


@dataclass(frozen=True, slots=True)
class OnlyVerifiedParameterSearchFeedbackDecisionV1:
    """Ephemeral proof capability; it is not a persisted authority."""

    decision: OnlyParameterSearchFeedbackDecisionV1
    predecessor_fingerprint: str | None
    _seal: object


def verify_parameter_feedback_decision_occurrence(
    *,
    context: OnlyVerifiedParameterSearchContextV1,
    provenance: _ParameterOccurrenceProvenance,
    evidence_reader: OnlyParameterResearchEvidenceReader,
    decisions: _ParameterDecisionReader,
    candidate_decision: OnlyParameterSearchFeedbackDecisionV1,
) -> OnlyVerifiedParameterSearchFeedbackDecisionV1:
    """Prove that a candidate is exactly F(the complete authoritative prefix)."""

    runtime = admit_current_parameter_algorithm_runtime(context)
    ordered_plans = _ordered_plans(context, provenance)
    prior_decisions = _verify_referenced_decision_chain(
        context=context,
        provenance=provenance,
        evidence_reader=evidence_reader,
        decisions=decisions,
        ordered_plans=ordered_plans,
        runtime_fingerprint=runtime.implementation_fingerprint,
    )
    evidence = _evidence_for_plans(context, provenance, evidence_reader, ordered_plans)

    expected = decide_parameter_search_v1(
        experiment_fingerprint=context.experiment.experiment_fingerprint,
        proposals=context.proposals,
        policy=context.policy,
        algorithm_implementation_fingerprint=runtime.implementation_fingerprint,
        budget=context.experiment.search_budget,
        evidence=tuple(evidence),
        prior_decisions=prior_decisions,
    )
    if expected.start_iteration_index != len(ordered_plans) or candidate_decision != expected:
        raise OnlyParameterSearchError(
            "PARAMETER_FEEDBACK_OCCURRENCE_MISMATCH",
            candidate_decision.feedback_decision_fingerprint,
        )
    predecessor = prior_decisions[-1].feedback_decision_fingerprint if prior_decisions else None
    return OnlyVerifiedParameterSearchFeedbackDecisionV1(
        candidate_decision,
        predecessor,
        _VERIFIED_FEEDBACK_DECISION_SEAL,
    )


def verify_parameter_feedback_frontier_for_execution(
    *,
    context: OnlyVerifiedParameterSearchContextV1,
    provenance: _ParameterOccurrenceProvenance,
    evidence_reader: OnlyParameterResearchEvidenceReader,
    decisions: _ParameterDecisionReader,
    frontier_fingerprint: str,
) -> OnlyParameterSearchFeedbackDecisionV1:
    """Rebuild the complete historical proof before a frontier can authorize work."""

    runtime = admit_current_parameter_algorithm_runtime(context)
    ordered_plans = _ordered_plans(context, provenance)
    decision_ids: list[str] = []
    for plan in ordered_plans:
        if not decision_ids or decision_ids[-1] != plan.decision_output_fingerprint:
            decision_ids.append(plan.decision_output_fingerprint)
    if not decision_ids or decision_ids[-1] != frontier_fingerprint:
        decision_ids.append(frontier_fingerprint)

    verified: list[OnlyParameterSearchFeedbackDecisionV1] = []
    for fingerprint in decision_ids:
        decision = decisions.load_feedback_decision_intrinsic_verified(fingerprint)
        _verify_historical_decision(
            context=context,
            provenance=provenance,
            evidence_reader=evidence_reader,
            decision=decision,
            prior_decisions=tuple(verified),
            ordered_plans=ordered_plans,
            runtime_fingerprint=runtime.implementation_fingerprint,
        )
        _verify_plan_prefix(
            context=context,
            decision=decision,
            ordered_plans=ordered_plans,
            require_complete=fingerprint != frontier_fingerprint,
        )
        verified.append(decision)
    frontier = verified[-1]
    if frontier.feedback_decision_fingerprint != frontier_fingerprint:
        raise OnlyParameterSearchError("PARAMETER_FEEDBACK_HISTORY_UNVERIFIED", frontier_fingerprint)
    return frontier


def _ordered_plans(
    context: OnlyVerifiedParameterSearchContextV1,
    provenance: _ParameterOccurrenceProvenance,
) -> tuple[OnlySearchIterationPlanV1, ...]:
    plans = tuple(
        sorted(
            provenance.iteration_plans_for_experiment_verified(context.experiment.experiment_fingerprint),
            key=lambda item: item.iteration_index,
        )
    )
    if tuple(item.iteration_index for item in plans) != tuple(range(len(plans))):
        raise OnlyParameterSearchError("SEARCH_ITERATION_PREFIX_CORRUPT", "non-contiguous Plan prefix")
    if any(item.experiment_fingerprint != context.experiment.experiment_fingerprint for item in plans):
        raise OnlyParameterSearchError("SEARCH_ITERATION_PREFIX_CORRUPT", "Plan Experiment differs")
    return plans


def _evidence_for_plans(
    context: OnlyVerifiedParameterSearchContextV1,
    provenance: _ParameterOccurrenceProvenance,
    evidence_reader: OnlyParameterResearchEvidenceReader,
    plans: tuple[OnlySearchIterationPlanV1, ...],
) -> tuple[OnlyParameterResearchEvidenceV1, ...]:
    proposals = {item.proposal_fingerprint: item for item in context.proposals}
    evidence = []
    for plan in plans:
        proposal = proposals.get(plan.proposal_fingerprint)
        result = provenance.terminal_result_for_plan_verified(plan.iteration_plan_fingerprint)
        if proposal is None or result is None:
            raise OnlyParameterSearchError("PARAMETER_FEEDBACK_OCCURRENCE_MISMATCH", plan.iteration_plan_fingerprint)
        item = evidence_reader.load_required(
            iteration_result_fingerprint=result.iteration_result_fingerprint,
            proposal=proposal,
            policy=context.policy,
        )
        if not isinstance(item, OnlyParameterResearchEvidenceV1) or item.proposal != proposal:
            raise OnlyParameterSearchError("PARAMETER_FEEDBACK_OCCURRENCE_MISMATCH", plan.iteration_plan_fingerprint)
        evidence.append(item)
    return tuple(evidence)


def _verify_referenced_decision_chain(
    *,
    context: OnlyVerifiedParameterSearchContextV1,
    provenance: _ParameterOccurrenceProvenance,
    evidence_reader: OnlyParameterResearchEvidenceReader,
    decisions: _ParameterDecisionReader,
    ordered_plans: tuple[OnlySearchIterationPlanV1, ...],
    runtime_fingerprint: str,
) -> tuple[OnlyParameterSearchFeedbackDecisionV1, ...]:
    decision_ids: list[str] = []
    for plan in ordered_plans:
        if not decision_ids or decision_ids[-1] != plan.decision_output_fingerprint:
            decision_ids.append(plan.decision_output_fingerprint)
    verified: list[OnlyParameterSearchFeedbackDecisionV1] = []
    for fingerprint in decision_ids:
        decision = decisions.load_feedback_decision_intrinsic_verified(fingerprint)
        _verify_historical_decision(
            context=context,
            provenance=provenance,
            evidence_reader=evidence_reader,
            decision=decision,
            prior_decisions=tuple(verified),
            ordered_plans=ordered_plans,
            runtime_fingerprint=runtime_fingerprint,
        )
        _verify_plan_prefix(
            context=context,
            decision=decision,
            ordered_plans=ordered_plans,
            require_complete=True,
        )
        verified.append(decision)
    return tuple(verified)


def _verify_historical_decision(
    *,
    context: OnlyVerifiedParameterSearchContextV1,
    provenance: _ParameterOccurrenceProvenance,
    evidence_reader: OnlyParameterResearchEvidenceReader,
    decision: OnlyParameterSearchFeedbackDecisionV1,
    prior_decisions: tuple[OnlyParameterSearchFeedbackDecisionV1, ...],
    ordered_plans: tuple[OnlySearchIterationPlanV1, ...],
    runtime_fingerprint: str,
) -> None:
    if decision.start_iteration_index > len(ordered_plans):
        raise OnlyParameterSearchError("PARAMETER_FEEDBACK_HISTORY_UNVERIFIED", decision.feedback_decision_fingerprint)
    prefix = ordered_plans[: decision.start_iteration_index]
    evidence = _evidence_for_plans(context, provenance, evidence_reader, prefix)
    expected = decide_parameter_search_v1(
        experiment_fingerprint=context.experiment.experiment_fingerprint,
        proposals=context.proposals,
        policy=context.policy,
        algorithm_implementation_fingerprint=runtime_fingerprint,
        budget=context.experiment.search_budget,
        evidence=evidence,
        prior_decisions=prior_decisions,
    )
    if expected != decision:
        raise OnlyParameterSearchError("PARAMETER_FEEDBACK_HISTORY_UNVERIFIED", decision.feedback_decision_fingerprint)


def _verify_plan_prefix(
    *,
    context: OnlyVerifiedParameterSearchContextV1,
    decision: OnlyParameterSearchFeedbackDecisionV1,
    ordered_plans: tuple[OnlySearchIterationPlanV1, ...],
    require_complete: bool,
) -> None:
    expected = plans_for_feedback_decision(decision, context.proposals)
    end = decision.start_iteration_index + len(expected)
    window = tuple(item for item in ordered_plans if decision.start_iteration_index <= item.iteration_index < end)
    belonging = tuple(
        item for item in ordered_plans if item.decision_output_fingerprint == decision.feedback_decision_fingerprint
    )
    if window != belonging or belonging != expected[: len(belonging)] or len(belonging) > len(expected):
        raise OnlyParameterSearchError("SEARCH_ITERATION_PREFIX_CORRUPT", decision.feedback_decision_fingerprint)
    if require_complete and belonging != expected:
        raise OnlyParameterSearchError("SEARCH_ITERATION_PREFIX_CORRUPT", decision.feedback_decision_fingerprint)
    if not require_complete and any(item.iteration_index >= end for item in ordered_plans):
        raise OnlyParameterSearchError("SEARCH_ITERATION_PREFIX_CORRUPT", decision.feedback_decision_fingerprint)


def require_verified_parameter_feedback_decision(
    value: OnlyVerifiedParameterSearchFeedbackDecisionV1,
) -> tuple[OnlyParameterSearchFeedbackDecisionV1, str | None]:
    if (
        not isinstance(value, OnlyVerifiedParameterSearchFeedbackDecisionV1)
        or value._seal is not _VERIFIED_FEEDBACK_DECISION_SEAL
    ):
        raise OnlyParameterSearchError("PARAMETER_FEEDBACK_DECISION_UNVERIFIED")
    return value.decision, value.predecessor_fingerprint


__all__ = [name for name in globals() if name.startswith(("OnlyVerified", "verify_parameter_"))]
