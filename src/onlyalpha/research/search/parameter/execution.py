"""Exact-generation adapter for bounded Parameter decision derivation."""

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

from .context import OnlyVerifiedParameterSearchContextV1
from .evidence import OnlyParameterResearchEvidenceV1
from .model import OnlyParameterGraphProposalV1, OnlyParameterSearchFeedbackDecisionV1


@dataclass(frozen=True, slots=True)
class OnlyHostedParameterGenerationExecutionV1:
    execution: OnlySearchGenerationExecutionPort
    dataset_store_root: Path

    def derive_decision(
        self,
        runtime_generation_fingerprint: str,
        context: OnlyVerifiedParameterSearchContextV1,
        evidence: tuple[OnlyParameterResearchEvidenceV1, ...],
        prior_decisions: tuple[OnlyParameterSearchFeedbackDecisionV1, ...],
    ) -> OnlyParameterSearchFeedbackDecisionV1:
        response = self.execution.execute(
            OnlySearchGenerationExecutionRequestV1(
                runtime_generation_fingerprint,
                OnlySearchGenerationOperationV1.DERIVE_PARAMETER_DECISION,
                {
                    "experiment": context.experiment.to_dict(),
                    "search_space": context.search_space.to_dict(),
                    "evaluation_contract": context.evaluation_contract.to_dict(),
                    "search_policy": context.policy.to_dict(),
                    "algorithm_manifest": context.historical_algorithm_manifest.to_dict(),
                    "dataset_store_root": str(self.dataset_store_root.resolve()),
                    "evidence": [_evidence_payload(item) for item in evidence],
                    "prior_decisions": [item.to_dict() for item in prior_decisions],
                },
            )
        )
        payload = response.result_payload
        if set(payload) != {
            "algorithm_implementation_fingerprint",
            "catalog_generation_fingerprint",
            "decision",
            "proposals",
        }:
            raise OnlyHistoricalGenerationExecutionMismatch("Parameter result fields differ")
        raw_decision = payload["decision"]
        raw_proposals = payload["proposals"]
        if not isinstance(raw_decision, Mapping) or not isinstance(raw_proposals, list):
            raise OnlyHistoricalGenerationExecutionMismatch("Parameter result shape differs")
        if (
            payload["algorithm_implementation_fingerprint"]
            != context.historical_algorithm_manifest.implementation_fingerprint
            or payload["catalog_generation_fingerprint"] != context.experiment.catalog_generation_fingerprint
            or raw_proposals != [item.to_dict() for item in context.proposals]
        ):
            raise OnlyHistoricalGenerationExecutionMismatch("Parameter execution identity differs")
        decision = OnlyParameterSearchFeedbackDecisionV1.from_dict(cast(Mapping[str, object], raw_decision))
        if decision.experiment_fingerprint != context.experiment.experiment_fingerprint:
            raise OnlyHistoricalGenerationExecutionMismatch("Parameter Experiment identity differs")
        return decision

    def verify_resolved_research(
        self,
        runtime_generation_fingerprint: str,
        context: OnlyVerifiedParameterSearchContextV1,
        proposal: OnlyParameterGraphProposalV1,
        resolved: object,
    ) -> None:
        response = self.execution.execute(
            OnlySearchGenerationExecutionRequestV1(
                runtime_generation_fingerprint,
                OnlySearchGenerationOperationV1.RESOLVE_PARAMETER_RESEARCH,
                {
                    "evaluation_contract": context.evaluation_contract.to_dict(),
                    "proposal": proposal.to_dict(),
                },
            )
        )
        payload = response.result_payload
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


def _evidence_payload(value: OnlyParameterResearchEvidenceV1) -> dict[str, object]:
    return {
        "iteration_result_fingerprint": value.iteration_result_fingerprint,
        "proposal_fingerprint": value.proposal.proposal_fingerprint,
        "metric_scalars": {key: scalar.to_dict() for key, scalar in sorted(value.metric_scalars.items())},
        "research_attempted": value.research_attempted,
        "available": value.available,
    }


__all__ = ["OnlyHostedParameterGenerationExecutionV1"]
