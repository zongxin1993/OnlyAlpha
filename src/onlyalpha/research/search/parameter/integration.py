"""Normal Research resolution and recoverable B3.1 occurrence integration."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.research.command.errors import OnlyResearchSubmissionConflictError
from onlyalpha.research.command.model import OnlyResearchSubmitOutcome
from onlyalpha.research.experiment import (
    OnlySearchFailureCode,
    OnlySearchIterationDisposition,
    OnlySearchIterationPlanV1,
    OnlySearchIterationResultV1,
    OnlySearchResearchResultReferenceV1,
)
from onlyalpha.research.run.errors import OnlyResearchRunIntegrityError
from onlyalpha.research.run.model import OnlyResearchRunState
from onlyalpha.research.search.symbolic.materialization import research_specification_from_candidate_graph
from onlyalpha.research.specification.model import OnlyResearchSpecification
from onlyalpha.research.specification.resolver import (
    OnlyResearchCandidateLineage,
    OnlyResearchSpecificationResolution,
    OnlyResearchSpecificationResolver,
)

from .context import OnlyVerifiedParameterSearchContextV1
from .errors import OnlyParameterSearchError
from .model import (
    PARAMETER_PROPOSAL_KIND,
    PARAMETER_PROPOSAL_SCHEMA_VERSION,
    OnlyParameterGraphProposalV1,
    OnlyParameterSearchFeedbackDecisionV1,
)


class OnlyParameterProvenanceWriter(Protocol):
    def commit_iteration_plan(self, value: OnlySearchIterationPlanV1) -> object: ...

    def commit_iteration_result(self, value: OnlySearchIterationResultV1) -> object: ...

    def terminal_result_for_plan_verified(self, plan_fingerprint: str) -> OnlySearchIterationResultV1 | None: ...


class OnlyParameterResearchCommandService(Protocol):
    def submit_research_run(
        self,
        submission_key: OnlyProductCommandId,
        specification: object,
        provenance: object | None = None,
    ) -> OnlyResearchSubmitOutcome: ...


class OnlyParameterRunReader(Protocol):
    def load(self, run_id: object) -> object: ...


@dataclass(frozen=True, slots=True)
class OnlyResolvedParameterResearchCandidateV1:
    proposal: OnlyParameterGraphProposalV1
    specification: OnlyResearchSpecification
    resolution: OnlyResearchSpecificationResolution
    candidate: OnlyResearchCandidateLineage


def resolve_parameter_research_candidate(
    context: OnlyVerifiedParameterSearchContextV1,
    proposal: OnlyParameterGraphProposalV1,
    resolver: OnlyResearchSpecificationResolver,
) -> OnlyResolvedParameterResearchCandidateV1:
    """Create Candidate identity exclusively through the normal Research Resolver."""

    try:
        materialized = research_specification_from_candidate_graph(
            context.evaluation_contract,
            proposal.graph,
            proposal.candidate_node_fingerprint,
            proposal.candidate_output_name,
        )
        resolution = resolver.resolve(materialized.specification)
        candidates = tuple(
            item
            for item in resolution.candidates
            if item.calculation_id == context.evaluation_contract.candidate_calculation_id
            and item.candidate_fingerprint is not None
        )
        if len(candidates) != 1 or candidates[0].graph_fingerprint != proposal.graph_fingerprint:
            raise ValueError("normal Resolver did not produce the exact Candidate")
        return OnlyResolvedParameterResearchCandidateV1(proposal, materialized.specification, resolution, candidates[0])
    except Exception as exc:
        raise OnlyParameterSearchError("CANDIDATE_BINDING_FAILED", proposal.proposal_fingerprint) from exc


def plans_for_feedback_decision(
    decision: OnlyParameterSearchFeedbackDecisionV1,
    proposals: tuple[OnlyParameterGraphProposalV1, ...],
) -> tuple[OnlySearchIterationPlanV1, ...]:
    by_fingerprint = {item.proposal_fingerprint: item for item in proposals}
    parent = decision.selected_anchor_iteration_result_fingerprint
    plans = []
    for position, fingerprint in enumerate(decision.ordered_next_proposal_fingerprints):
        if fingerprint not in by_fingerprint:
            raise OnlyParameterSearchError("SEARCH_INVALID_PROPOSAL", fingerprint)
        plans.append(
            OnlySearchIterationPlanV1(
                decision.experiment_fingerprint,
                decision.start_iteration_index + position,
                PARAMETER_PROPOSAL_KIND,
                PARAMETER_PROPOSAL_SCHEMA_VERSION,
                fingerprint,
                decision.ordered_input_iteration_result_fingerprints,
                (),
                decision.feedback_decision_fingerprint,
                parent,
            )
        )
    return tuple(plans)


def commit_feedback_plan_batch(
    decision: OnlyParameterSearchFeedbackDecisionV1,
    proposals: tuple[OnlyParameterGraphProposalV1, ...],
    provenance: OnlyParameterProvenanceWriter,
) -> tuple[OnlySearchIterationPlanV1, ...]:
    """Idempotently finish a decision's exact Plan batch after any partial crash."""

    plans = plans_for_feedback_decision(decision, proposals)
    for plan in plans:
        provenance.commit_iteration_plan(plan)
    return plans


def parameter_submission_key(plan: OnlySearchIterationPlanV1) -> OnlyProductCommandId:
    """Stable UUID4 derived only from the immutable Plan occurrence identity."""

    raw = bytes.fromhex(plan.iteration_plan_fingerprint[:32])
    return OnlyProductCommandId(str(uuid.UUID(bytes=raw, version=4)))


def reconcile_parameter_research_plan(
    *,
    plan: OnlySearchIterationPlanV1,
    resolved: OnlyResolvedParameterResearchCandidateV1,
    provenance: OnlyParameterProvenanceWriter,
    commands: OnlyParameterResearchCommandService,
) -> OnlySearchIterationResultV1 | None:
    """Reconcile exact Product Command/Run facts; active states remain behind the barrier."""

    existing = provenance.terminal_result_for_plan_verified(plan.iteration_plan_fingerprint)
    if existing is not None:
        return existing
    try:
        outcome = commands.submit_research_run(parameter_submission_key(plan), resolved.specification)
    except (OnlyResearchSubmissionConflictError, OnlyResearchRunIntegrityError) as exc:
        raise OnlyParameterSearchError("AMBIGUOUS_ATTEMPT_STATE", plan.iteration_plan_fingerprint) from exc
    except Exception:
        raise
    run = outcome.run
    candidate_fingerprint = resolved.candidate.candidate_fingerprint
    if candidate_fingerprint is None:
        raise OnlyParameterSearchError("CANDIDATE_BINDING_FAILED", plan.proposal_fingerprint)
    if run.state in {OnlyResearchRunState.QUEUED, OnlyResearchRunState.RUNNING, OnlyResearchRunState.CANCEL_REQUESTED}:
        return None
    if run.state is OnlyResearchRunState.COMPLETED:
        if run.research_result_fingerprint is None:
            raise OnlyParameterSearchError("AMBIGUOUS_ATTEMPT_STATE", plan.iteration_plan_fingerprint)
        result = OnlySearchIterationResultV1(
            plan.iteration_plan_fingerprint,
            candidate_fingerprint,
            True,
            OnlySearchResearchResultReferenceV1(
                resolved.resolution.workload.result_plan.fingerprint,
                run.research_result_fingerprint,
            ),
            False,
            None,
            OnlySearchIterationDisposition.RESEARCH_EVIDENCE_RECORDED,
            None,
        )
    elif run.state in {OnlyResearchRunState.FAILED, OnlyResearchRunState.CANCELLED}:
        result = OnlySearchIterationResultV1(
            plan.iteration_plan_fingerprint,
            candidate_fingerprint,
            True,
            None,
            False,
            None,
            OnlySearchIterationDisposition.FAILED,
            OnlySearchFailureCode.RESEARCH_EXECUTION_FAILED,
        )
    else:  # pragma: no cover - enum exhaustiveness guard
        raise OnlyParameterSearchError("AMBIGUOUS_ATTEMPT_STATE", plan.iteration_plan_fingerprint)
    provenance.commit_iteration_result(result)
    return result


__all__ = [
    name for name in globals() if name.startswith(("Only", "commit_", "parameter_", "plans_", "reconcile_", "resolve_"))
]
