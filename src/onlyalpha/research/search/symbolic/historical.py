"""Historical symbolic proof paths that never execute deterministic enumeration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.research.experiment import OnlySearchExperimentManifestV2, OnlySearchIterationPlanV1

from .enumeration_result import OnlySymbolicEnumerationResultV1
from .errors import OnlySymbolicSearchError, OnlySymbolicSearchStoreError
from .model import OnlySymbolicGraphProposalV1
from .verification import (
    OnlyVerifiedSymbolicProposalV1,
    verify_symbolic_iteration_historical_binding,
    verify_symbolic_proposal_reconstruction,
)


class OnlySymbolicHistoricalStore(Protocol):
    def load_proposal_intrinsic_verified(self, fingerprint: str) -> OnlySymbolicGraphProposalV1: ...

    def load_enumeration_result_verified(self, experiment_fingerprint: str) -> OnlySymbolicEnumerationResultV1: ...

    def commit_enumeration_result(
        self,
        value: OnlySymbolicEnumerationResultV1,
        *,
        context: object,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class OnlyVerifiedSymbolicEnumerationResultV1:
    result: OnlySymbolicEnumerationResultV1
    proposals: tuple[OnlyVerifiedSymbolicProposalV1 | OnlySymbolicGraphProposalV1, ...]


def verify_symbolic_enumeration_result(
    result: OnlySymbolicEnumerationResultV1,
    context: object,
    store: OnlySymbolicHistoricalStore,
) -> OnlyVerifiedSymbolicEnumerationResultV1:
    """Close a durable ordered stream against exact historical Authorities."""

    experiment = getattr(context, "experiment", None)
    from .context import OnlyHistoricalSymbolicSearchFactsV1

    facts_only = isinstance(context, OnlyHistoricalSymbolicSearchFactsV1)
    verified_space = getattr(context, "verified_search_space", None)
    space = (
        context.search_space
        if isinstance(context, OnlyHistoricalSymbolicSearchFactsV1)
        else getattr(verified_space, "search_space", None)
    )
    historical_algorithm = getattr(context, "historical_algorithm_manifest", None)
    if not isinstance(experiment, OnlySearchExperimentManifestV2) or space is None or historical_algorithm is None:
        raise OnlySymbolicSearchError("SEARCH_CONTEXT_INVALID", "Verified historical Search Context is required")
    if result.experiment_fingerprint != experiment.experiment_fingerprint:
        raise OnlySymbolicSearchError("SEARCH_ENUMERATION_EXPERIMENT_MISMATCH", result.enumeration_result_fingerprint)
    if result.algorithm_implementation_fingerprint != historical_algorithm.implementation_fingerprint:
        raise OnlySymbolicSearchError("SEARCH_ENUMERATION_ALGORITHM_MISMATCH", result.enumeration_result_fingerprint)
    if result.search_space_fingerprint != space.search_space_fingerprint:
        raise OnlySymbolicSearchError("SEARCH_ENUMERATION_SEARCH_SPACE_MISMATCH", result.enumeration_result_fingerprint)
    if result.proposal_limit != experiment.search_budget.proposal_limit:
        raise OnlySymbolicSearchError("SEARCH_ENUMERATION_BUDGET_MISMATCH", result.enumeration_result_fingerprint)
    proposals: list[OnlyVerifiedSymbolicProposalV1 | OnlySymbolicGraphProposalV1] = []
    for fingerprint in result.ordered_proposal_fingerprints:
        try:
            proposal = store.load_proposal_intrinsic_verified(fingerprint)
            if proposal.proposal_fingerprint != fingerprint:
                raise ValueError("Proposal reader returned a different identity")
            if facts_only:
                if proposal.search_space_fingerprint != space.search_space_fingerprint:
                    raise OnlySymbolicSearchError("SEARCH_ENUMERATION_PROPOSAL_INVALID", fingerprint)
                proposals.append(proposal)
            else:
                proposals.append(verify_symbolic_proposal_reconstruction(proposal, context))
        except OnlySymbolicSearchStoreError as exc:
            raise OnlySymbolicSearchError("SEARCH_ENUMERATION_PROPOSAL_INVALID", fingerprint) from exc
        except OnlySymbolicSearchError:
            raise
        except Exception as exc:
            raise OnlySymbolicSearchError("SEARCH_ENUMERATION_PROPOSAL_INVALID", fingerprint) from exc
    return OnlyVerifiedSymbolicEnumerationResultV1(result, tuple(proposals))


def load_symbolic_enumeration_result_historical_verified(
    experiment: OnlySearchExperimentManifestV2,
    context: object,
    store: OnlySymbolicHistoricalStore,
) -> OnlyVerifiedSymbolicEnumerationResultV1:
    try:
        result = store.load_enumeration_result_verified(experiment.experiment_fingerprint)
    except Exception as exc:
        raise OnlySymbolicSearchError(
            "SEARCH_ENUMERATION_RESULT_REFERENCE_INVALID", experiment.experiment_fingerprint
        ) from exc
    return verify_symbolic_enumeration_result(result, context, store)


def load_optional_symbolic_enumeration_result_historical_verified(
    experiment: OnlySearchExperimentManifestV2,
    context: object,
    store: OnlySymbolicHistoricalStore,
) -> OnlyVerifiedSymbolicEnumerationResultV1 | None:
    """Return absence only for exact NOT_FOUND from the owning Symbolic Store."""

    try:
        result = store.load_enumeration_result_verified(experiment.experiment_fingerprint)
    except OnlySymbolicSearchStoreError as exc:
        if exc.code == "SEARCH_ENUMERATION_RESULT_NOT_FOUND":
            return None
        raise
    return verify_symbolic_enumeration_result(result, context, store)


def commit_symbolic_enumeration_result_verified(
    result: OnlySymbolicEnumerationResultV1,
    context: object,
    store: OnlySymbolicHistoricalStore,
) -> object:
    return store.commit_enumeration_result(result, context=context)


def verify_symbolic_historical_iteration_occurrence(
    experiment: OnlySearchExperimentManifestV2,
    plan: OnlySearchIterationPlanV1,
    context: object,
    store: OnlySymbolicHistoricalStore,
) -> OnlyVerifiedSymbolicProposalV1 | OnlySymbolicGraphProposalV1:
    """Prove ordinal occurrence solely from the stored Enumeration Result."""

    try:
        proposal = store.load_proposal_intrinsic_verified(plan.proposal_fingerprint)
    except Exception as exc:
        raise OnlySymbolicSearchError("SEARCH_ENUMERATION_PROPOSAL_INVALID", plan.proposal_fingerprint) from exc
    from .context import OnlyHistoricalSymbolicSearchFactsV1
    from .verification import verify_symbolic_iteration_proposal_binding

    verified: OnlyVerifiedSymbolicProposalV1 | OnlySymbolicGraphProposalV1
    if isinstance(context, OnlyHistoricalSymbolicSearchFactsV1):
        verify_symbolic_iteration_proposal_binding(
            plan, proposal, expected_search_space_fingerprint=context.search_space.search_space_fingerprint
        )
        if (
            plan.experiment_fingerprint != experiment.experiment_fingerprint
            or plan.parent_iteration_result_fingerprint is not None
            or plan.decision_input_context_fingerprints
            or plan.decision_tool_result_fingerprints
            or plan.decision_output_fingerprint != plan.proposal_fingerprint
            or plan.iteration_index >= experiment.search_budget.proposal_limit
        ):
            raise OnlySymbolicSearchError("SEARCH_INVALID_PROPOSAL", plan.iteration_plan_fingerprint)
        verified = proposal
    else:
        verified = verify_symbolic_iteration_historical_binding(experiment, plan, proposal, context)
    enumeration = load_symbolic_enumeration_result_historical_verified(experiment, context, store)
    ordered = enumeration.result.ordered_proposal_fingerprints
    if plan.iteration_index >= len(ordered):
        raise OnlySymbolicSearchError("SEARCH_OCCURRENCE_ORDINAL_INVALID", plan.iteration_plan_fingerprint)
    if ordered[plan.iteration_index] != plan.proposal_fingerprint:
        raise OnlySymbolicSearchError("SEARCH_OCCURRENCE_PROPOSAL_MISMATCH", plan.iteration_plan_fingerprint)
    return verified


__all__ = [name for name in globals() if name.startswith(("Only", "commit_", "load_", "verify_"))]
