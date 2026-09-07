"""Contextual and occurrence verification for adaptive Feedback Decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.research.experiment import OnlySearchIterationPlanV1, OnlySearchIterationResultV1

from .algorithm import decide_parameter_search_v1
from .context import OnlyVerifiedParameterSearchContextV1, admit_current_parameter_algorithm_runtime
from .errors import OnlyParameterSearchError
from .evidence import OnlyParameterResearchEvidenceReader, OnlyParameterResearchEvidenceV1
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
    experiment = context.experiment
    ordered_plans = tuple(
        sorted(
            provenance.iteration_plans_for_experiment_verified(experiment.experiment_fingerprint),
            key=lambda item: item.iteration_index,
        )
    )
    if tuple(item.iteration_index for item in ordered_plans) != tuple(range(len(ordered_plans))):
        raise OnlyParameterSearchError("PARAMETER_FEEDBACK_OCCURRENCE_MISMATCH", "non-contiguous Plan prefix")
    if any(item.experiment_fingerprint != experiment.experiment_fingerprint for item in ordered_plans):
        raise OnlyParameterSearchError("PARAMETER_FEEDBACK_OCCURRENCE_MISMATCH", "Plan Experiment differs")

    proposals = {item.proposal_fingerprint: item for item in context.proposals}
    evidence = []
    for plan in ordered_plans:
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

    decision_ids: list[str] = []
    for plan in ordered_plans:
        if not decision_ids or decision_ids[-1] != plan.decision_output_fingerprint:
            decision_ids.append(plan.decision_output_fingerprint)
    prior_decisions = tuple(decisions.load_feedback_decision_intrinsic_verified(item) for item in decision_ids)
    for decision in prior_decisions:
        if (
            decision.experiment_fingerprint != experiment.experiment_fingerprint
            or decision.search_policy_fingerprint != context.policy.policy_fingerprint
            or decision.algorithm_implementation_fingerprint != runtime.implementation_fingerprint
        ):
            raise OnlyParameterSearchError(
                "PARAMETER_FEEDBACK_OCCURRENCE_MISMATCH",
                decision.feedback_decision_fingerprint,
            )

    expected = decide_parameter_search_v1(
        experiment_fingerprint=experiment.experiment_fingerprint,
        proposals=context.proposals,
        policy=context.policy,
        algorithm_implementation_fingerprint=runtime.implementation_fingerprint,
        budget=experiment.search_budget,
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
