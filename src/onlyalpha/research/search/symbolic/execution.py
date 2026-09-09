"""Current-runtime enumeration and reproduction certification boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from onlyalpha.application.search_generation_execution import (
    OnlyHistoricalGenerationExecutionMismatch,
    OnlySearchGenerationExecutionPort,
    OnlySearchGenerationExecutionRequestV1,
    OnlySearchGenerationOperationV1,
)
from onlyalpha.research.experiment import OnlySearchExperimentManifestV2

from .context import (
    OnlyExecutableSymbolicSearchContextV1,
    OnlyVerifiedSymbolicSearchContextV1,
    admit_current_symbolic_algorithm_runtime,
)
from .enumeration import OnlySymbolicEnumerationExecutionV1, enumerate_symbolic_factor_proposals
from .enumeration_result import OnlySymbolicEnumerationResultV1
from .errors import OnlySymbolicSearchError
from .historical import (
    OnlySymbolicHistoricalStore,
    load_symbolic_enumeration_result_historical_verified,
)
from .model import OnlySymbolicGraphProposalV1


@dataclass(frozen=True, slots=True)
class OnlyHostedSymbolicGenerationExecutionV1:
    execution: OnlySearchGenerationExecutionPort
    dataset_store_root: Path

    def derive_enumeration(
        self,
        runtime_generation_fingerprint: str,
        context: OnlyVerifiedSymbolicSearchContextV1,
    ) -> tuple[OnlySymbolicEnumerationExecutionV1, OnlySymbolicEnumerationResultV1]:
        request = OnlySearchGenerationExecutionRequestV1(
            runtime_generation_fingerprint,
            OnlySearchGenerationOperationV1.DERIVE_SYMBOLIC_ENUMERATION,
            {
                "experiment": context.experiment.to_dict(),
                "search_space": context.verified_search_space.search_space.to_dict(),
                "evaluation_contract": context.evaluation_contract.to_dict(),
                "algorithm_manifest": context.historical_algorithm_manifest.to_dict(),
                "dataset_store_root": str(self.dataset_store_root.resolve()),
            },
        )
        response = self.execution.execute(request)
        payload = response.result_payload
        expected = {
            "algorithm_implementation_fingerprint",
            "catalog_generation_fingerprint",
            "enumeration_result",
            "proposals",
        }
        if set(payload) != expected:
            raise OnlyHistoricalGenerationExecutionMismatch("Symbolic result fields differ")
        proposals_raw = payload["proposals"]
        enumeration_raw = payload["enumeration_result"]
        if not isinstance(proposals_raw, list) or not isinstance(enumeration_raw, Mapping):
            raise OnlyHistoricalGenerationExecutionMismatch("Symbolic result shape differs")
        proposals = tuple(
            OnlySymbolicGraphProposalV1.from_dict(cast(Mapping[str, object], item))
            for item in proposals_raw
            if isinstance(item, Mapping)
        )
        if len(proposals) != len(proposals_raw):
            raise OnlyHistoricalGenerationExecutionMismatch("Symbolic Proposal shape differs")
        result = OnlySymbolicEnumerationResultV1.from_dict(cast(Mapping[str, object], enumeration_raw))
        if (
            payload["algorithm_implementation_fingerprint"]
            != context.historical_algorithm_manifest.implementation_fingerprint
            or payload["catalog_generation_fingerprint"] != context.experiment.catalog_generation_fingerprint
            or result.experiment_fingerprint != context.experiment.experiment_fingerprint
            or result.ordered_proposal_fingerprints != tuple(item.proposal_fingerprint for item in proposals)
        ):
            raise OnlyHistoricalGenerationExecutionMismatch("Symbolic execution identity differs")
        return (
            OnlySymbolicEnumerationExecutionV1(
                proposals=proposals,
                search_space_exhausted=result.search_space_exhausted,
                proposal_limit_reached=result.proposal_limit_reached,
            ),
            result,
        )

    def verify_resolved_research(
        self,
        runtime_generation_fingerprint: str,
        context: OnlyVerifiedSymbolicSearchContextV1,
        proposal: OnlySymbolicGraphProposalV1,
        resolved: object,
    ) -> None:
        response = self.execution.execute(
            OnlySearchGenerationExecutionRequestV1(
                runtime_generation_fingerprint,
                OnlySearchGenerationOperationV1.RESOLVE_SYMBOLIC_RESEARCH,
                {
                    "evaluation_contract": context.evaluation_contract.to_dict(),
                    "proposal": proposal.to_dict(),
                },
            )
        )
        _verify_resolved_payload(response.result_payload, proposal, resolved)


def _verify_resolved_payload(
    payload: Mapping[str, object],
    proposal: OnlySymbolicGraphProposalV1,
    resolved: object,
) -> None:
    if set(payload) != {
        "proposal_fingerprint",
        "specification",
        "candidate_fingerprint",
        "calculation_fingerprint",
    }:
        raise OnlyHistoricalGenerationExecutionMismatch("Research resolution fields differ")
    specification = getattr(resolved, "specification", None)
    candidate = getattr(resolved, "candidate", None)
    if (
        payload["proposal_fingerprint"] != proposal.proposal_fingerprint
        or not isinstance(payload["specification"], Mapping)
        or specification is None
        or payload["specification"] != specification.to_dict()
        or payload["candidate_fingerprint"] != getattr(candidate, "candidate_fingerprint", None)
        or payload["calculation_fingerprint"] != getattr(candidate, "calculation_fingerprint", None)
    ):
        raise OnlyHistoricalGenerationExecutionMismatch("Research resolution identity differs")


def build_symbolic_enumeration_result(
    experiment: OnlySearchExperimentManifestV2,
    execution: OnlySymbolicEnumerationExecutionV1,
) -> OnlySymbolicEnumerationResultV1:
    return OnlySymbolicEnumerationResultV1(
        experiment.experiment_fingerprint,
        experiment.search_algorithm_binding.implementation_fingerprint,
        experiment.search_space_reference.search_space_fingerprint,
        experiment.search_budget.proposal_limit,
        tuple(item.proposal_fingerprint for item in execution.proposals),
        execution.proposal_limit_reached,
        execution.search_space_exhausted,
    )


def enumerate_symbolic_executable_context(
    executable: OnlyExecutableSymbolicSearchContextV1,
) -> tuple[OnlySymbolicEnumerationExecutionV1, OnlySymbolicEnumerationResultV1]:
    context = executable.historical_context
    execution = enumerate_symbolic_factor_proposals(
        context.verified_search_space,
        proposal_limit=context.experiment.search_budget.proposal_limit,
    )
    return execution, build_symbolic_enumeration_result(context.experiment, execution)


def certify_symbolic_enumeration_reproduction(
    context: OnlyVerifiedSymbolicSearchContextV1,
    store: OnlySymbolicHistoricalStore,
) -> OnlySymbolicEnumerationResultV1:
    """Admit current code, re-enumerate, and require equality with durable history."""

    executable = admit_current_symbolic_algorithm_runtime(context)
    _execution, reproduced = enumerate_symbolic_executable_context(executable)
    stored = load_symbolic_enumeration_result_historical_verified(context.experiment, context, store).result
    if reproduced != stored:
        raise OnlySymbolicSearchError("SEARCH_ENUMERATION_REPRODUCTION_MISMATCH", stored.enumeration_result_fingerprint)
    return reproduced


__all__ = [name for name in globals() if name.startswith(("Only", "build_", "certify_", "enumerate_"))]
