"""Minimal normal Research/Qualification/B3.1 integration for B3.2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.research.experiment import (
    OnlySearchFailureCode,
    OnlySearchIterationDisposition,
    OnlySearchIterationPlanV1,
    OnlySearchIterationResultV1,
    OnlySearchResearchResultReferenceV1,
)
from onlyalpha.research.specification.resolver import (
    OnlyResearchCandidateLineage,
    OnlyResearchSpecificationResolution,
    OnlyResearchSpecificationResolver,
)

from .context import OnlyVerifiedSymbolicSearchContextV1, admit_current_symbolic_algorithm_runtime
from .enumeration import OnlySymbolicEnumerationResultV1, enumerate_symbolic_factor_proposals
from .errors import OnlySymbolicSearchError
from .materialization import materialize_symbolic_research_specification
from .model import SYMBOLIC_PROPOSAL_KIND, SYMBOLIC_PROPOSAL_SCHEMA_VERSION
from .store import OnlyJsonSymbolicSearchStore
from .verification import (
    OnlyVerifiedSymbolicProposalV1,
    verify_symbolic_proposal_reconstruction,
)


class OnlySymbolicProvenanceWriter(Protocol):
    def commit_iteration_plan(self, value: OnlySearchIterationPlanV1) -> object: ...

    def commit_iteration_result(self, value: OnlySearchIterationResultV1) -> object: ...


class OnlySymbolicResearchExecutor(Protocol):
    def execute(
        self,
        resolution: OnlyResearchSpecificationResolution,
        candidate: OnlyResearchCandidateLineage,
    ) -> OnlySearchResearchResultReferenceV1: ...


class OnlySymbolicQualificationExecutor(Protocol):
    def evaluate(
        self,
        candidate: OnlyResearchCandidateLineage,
        research_result: OnlySearchResearchResultReferenceV1,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class OnlySymbolicResolvedResearchCandidateV1:
    proposal: OnlyVerifiedSymbolicProposalV1
    resolution: OnlyResearchSpecificationResolution
    candidate: OnlyResearchCandidateLineage


@dataclass(frozen=True, slots=True)
class OnlySymbolicWorkflowResultV1:
    enumeration: OnlySymbolicEnumerationResultV1
    iteration_plans: tuple[OnlySearchIterationPlanV1, ...]
    iteration_results: tuple[OnlySearchIterationResultV1, ...]


def resolve_symbolic_research_candidate(
    proposal: OnlyVerifiedSymbolicProposalV1,
    resolver: OnlyResearchSpecificationResolver,
) -> OnlySymbolicResolvedResearchCandidateV1:
    """Use the sole existing Research resolver and Candidate constructor."""

    context = proposal.context
    evaluation = getattr(context, "evaluation_contract", None)
    if evaluation is None:
        raise OnlySymbolicSearchError("SEARCH_CONTEXT_INVALID", "Evaluation Contract is unavailable")
    materialized = materialize_symbolic_research_specification(evaluation, proposal)
    resolution = resolver.resolve(materialized.specification)
    candidates = tuple(
        item
        for item in resolution.candidates
        if item.calculation_id == evaluation.candidate_calculation_id and item.candidate_fingerprint is not None
    )
    if len(candidates) != 1:
        raise OnlySymbolicSearchError("CANDIDATE_BINDING_FAILED", "normal Resolver did not produce one Candidate")
    candidate = candidates[0]
    if candidate.graph_fingerprint != proposal.proposal.graph_fingerprint:
        raise OnlySymbolicSearchError("CANDIDATE_BINDING_FAILED", "normal Resolver graph identity differs")
    return OnlySymbolicResolvedResearchCandidateV1(proposal, resolution, candidate)


def run_symbolic_search_workflow(
    *,
    context: OnlyVerifiedSymbolicSearchContextV1,
    symbolic_store: OnlyJsonSymbolicSearchStore,
    provenance: OnlySymbolicProvenanceWriter,
    resolver: OnlyResearchSpecificationResolver,
    research_executor: OnlySymbolicResearchExecutor | None = None,
    qualification_executor: OnlySymbolicQualificationExecutor | None = None,
) -> OnlySymbolicWorkflowResultV1:
    """Run a bounded non-adaptive stream; evaluators can never affect enumeration."""

    experiment = context.experiment
    admit_current_symbolic_algorithm_runtime(context)
    verified_space = context.verified_search_space
    symbolic_store.commit_search_space(verified_space.search_space)
    symbolic_store.commit_evaluation_contract(context.evaluation_contract)
    enumeration = enumerate_symbolic_factor_proposals(
        verified_space,
        proposal_limit=experiment.search_budget.proposal_limit,
    )
    plans: list[OnlySearchIterationPlanV1] = []
    results: list[OnlySearchIterationResultV1] = []
    research_count = 0
    qualification_count = 0

    # Enumeration is complete before the first downstream execution. This is the structural non-adaptive barrier.
    for index, proposal in enumerate(enumeration.proposals):
        symbolic_store.commit_proposal(proposal)
        verified_proposal = verify_symbolic_proposal_reconstruction(proposal, context)
        plan = OnlySearchIterationPlanV1(
            experiment.experiment_fingerprint,
            index,
            SYMBOLIC_PROPOSAL_KIND,
            SYMBOLIC_PROPOSAL_SCHEMA_VERSION,
            proposal.proposal_fingerprint,
            (),
            (),
            proposal.proposal_fingerprint,
        )
        provenance.commit_iteration_plan(plan)
        plans.append(plan)
        try:
            resolved = resolve_symbolic_research_candidate(verified_proposal, resolver)
        except Exception:
            result = OnlySearchIterationResultV1(
                plan.iteration_plan_fingerprint,
                None,
                False,
                None,
                False,
                None,
                OnlySearchIterationDisposition.FAILED,
                OnlySearchFailureCode.CANDIDATE_BINDING_FAILED,
            )
            provenance.commit_iteration_result(result)
            results.append(result)
            continue
        candidate_fingerprint = resolved.candidate.candidate_fingerprint
        assert candidate_fingerprint is not None
        if research_executor is None or research_count >= experiment.search_budget.research_evaluation_limit:
            result = OnlySearchIterationResultV1(
                plan.iteration_plan_fingerprint,
                candidate_fingerprint,
                False,
                None,
                False,
                None,
                OnlySearchIterationDisposition.CANDIDATE_BOUND,
                None,
            )
            provenance.commit_iteration_result(result)
            results.append(result)
            continue
        research_count += 1
        try:
            research_reference = research_executor.execute(resolved.resolution, resolved.candidate)
        except Exception:
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
            provenance.commit_iteration_result(result)
            results.append(result)
            continue
        if (
            qualification_executor is None
            or qualification_count >= experiment.search_budget.qualification_attempt_limit
        ):
            result = OnlySearchIterationResultV1(
                plan.iteration_plan_fingerprint,
                candidate_fingerprint,
                True,
                research_reference,
                False,
                None,
                OnlySearchIterationDisposition.RESEARCH_EVIDENCE_RECORDED,
                None,
            )
            provenance.commit_iteration_result(result)
            results.append(result)
            continue
        qualification_count += 1
        try:
            decision_fingerprint = qualification_executor.evaluate(resolved.candidate, research_reference)
        except Exception:
            result = OnlySearchIterationResultV1(
                plan.iteration_plan_fingerprint,
                candidate_fingerprint,
                True,
                research_reference,
                True,
                None,
                OnlySearchIterationDisposition.FAILED,
                OnlySearchFailureCode.QUALIFICATION_EXECUTION_FAILED,
            )
        else:
            result = OnlySearchIterationResultV1(
                plan.iteration_plan_fingerprint,
                candidate_fingerprint,
                True,
                research_reference,
                True,
                decision_fingerprint,
                OnlySearchIterationDisposition.QUALIFICATION_DECISION_RECORDED,
                None,
            )
        provenance.commit_iteration_result(result)
        results.append(result)
    return OnlySymbolicWorkflowResultV1(enumeration, tuple(plans), tuple(results))


__all__ = [name for name in globals() if name.startswith(("OnlySymbolic", "resolve_symbolic", "run_symbolic"))]
