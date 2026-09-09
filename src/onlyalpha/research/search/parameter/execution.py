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
    OnlySearchGenerationExecutionResponseV1,
    OnlySearchGenerationOperationV1,
)
from onlyalpha.research.experiment.store import OnlyHostedSearchAdmission, _hosted_search_admission
from onlyalpha.research.search.symbolic.execution import OnlyHostedResolvedResearchV1, decode_hosted_research

from .context import OnlyHistoricalParameterSearchFactsV1, OnlyVerifiedParameterSearchContextV1
from .evidence import OnlyParameterResearchEvidenceV1
from .model import OnlyParameterGraphProposalV1, OnlyParameterSearchFeedbackDecisionV1


@dataclass(frozen=True, slots=True)
class OnlyHostedParameterGenerationExecutionV1:
    execution: OnlySearchGenerationExecutionPort
    dataset_store_root: Path

    def admit_experiment(
        self,
        runtime_generation_fingerprint: str,
        context: OnlyHistoricalParameterSearchFactsV1,
    ) -> tuple[
        OnlyHostedSearchAdmission, OnlyParameterSearchFeedbackDecisionV1, tuple[OnlyParameterGraphProposalV1, ...]
    ]:
        decision, proposals = self.derive_decision(runtime_generation_fingerprint, context, (), ())
        return (
            _hosted_search_admission(context.experiment.experiment_fingerprint, runtime_generation_fingerprint),
            decision,
            proposals,
        )

    def derive_verified_decision(
        self,
        runtime_generation_fingerprint: str,
        context: OnlyVerifiedParameterSearchContextV1 | OnlyHistoricalParameterSearchFactsV1,
        evidence: tuple[OnlyParameterResearchEvidenceV1, ...],
        prior_decisions: tuple[OnlyParameterSearchFeedbackDecisionV1, ...],
    ) -> tuple[
        OnlyParameterSearchFeedbackDecisionV1, tuple[OnlyParameterGraphProposalV1, ...], OnlyHostedSearchAdmission
    ]:
        decision, proposals = self.derive_decision(runtime_generation_fingerprint, context, evidence, prior_decisions)
        return (
            decision,
            proposals,
            _hosted_search_admission(
                context.experiment.experiment_fingerprint,
                runtime_generation_fingerprint,
                decision.feedback_decision_fingerprint,
            ),
        )

    def derive_decision(
        self,
        runtime_generation_fingerprint: str,
        context: OnlyVerifiedParameterSearchContextV1 | OnlyHistoricalParameterSearchFactsV1,
        evidence: tuple[OnlyParameterResearchEvidenceV1, ...],
        prior_decisions: tuple[OnlyParameterSearchFeedbackDecisionV1, ...],
    ) -> tuple[OnlyParameterSearchFeedbackDecisionV1, tuple[OnlyParameterGraphProposalV1, ...]]:
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
        response = OnlySearchGenerationExecutionResponseV1.from_dict(response.to_dict())
        payload = response.result_payload
        if (
            response.runtime_generation_fingerprint != runtime_generation_fingerprint
            or response.operation_kind is not OnlySearchGenerationOperationV1.DERIVE_PARAMETER_DECISION
        ):
            raise OnlyHistoricalGenerationExecutionMismatch("Parameter response generation/operation differs")
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
        ):
            raise OnlyHistoricalGenerationExecutionMismatch("Parameter execution identity differs")
        decision = OnlyParameterSearchFeedbackDecisionV1.from_dict(cast(Mapping[str, object], raw_decision))
        proposals = tuple(
            OnlyParameterGraphProposalV1.from_dict(cast(Mapping[str, object], item))
            for item in raw_proposals
            if isinstance(item, Mapping)
        )
        if (
            len(proposals) != len(raw_proposals)
            or tuple(item.ordinal for item in proposals) != tuple(range(len(proposals)))
            or len({item.proposal_fingerprint for item in proposals}) != len(proposals)
            or any(item.search_space_fingerprint != context.search_space.search_space_fingerprint for item in proposals)
            or any(item not in proposals for item in context.proposals)
        ):
            raise OnlyHistoricalGenerationExecutionMismatch("Parameter Proposal identities differ")
        if decision.experiment_fingerprint != context.experiment.experiment_fingerprint:
            raise OnlyHistoricalGenerationExecutionMismatch("Parameter Experiment identity differs")
        return decision, proposals

    def resolve_research(
        self,
        runtime_generation_fingerprint: str,
        context: OnlyVerifiedParameterSearchContextV1 | OnlyHistoricalParameterSearchFactsV1,
        proposal: OnlyParameterGraphProposalV1,
    ) -> OnlyHostedResolvedResearchV1:
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
        response = OnlySearchGenerationExecutionResponseV1.from_dict(response.to_dict())
        if (
            response.runtime_generation_fingerprint != runtime_generation_fingerprint
            or response.operation_kind is not OnlySearchGenerationOperationV1.RESOLVE_PARAMETER_RESEARCH
        ):
            raise OnlyHistoricalGenerationExecutionMismatch("Parameter Research response generation/operation differs")
        return decode_hosted_research(response.result_payload, context.evaluation_contract, proposal)


def _evidence_payload(value: OnlyParameterResearchEvidenceV1) -> dict[str, object]:
    return {
        "iteration_result_fingerprint": value.iteration_result_fingerprint,
        "proposal_fingerprint": value.proposal.proposal_fingerprint,
        "metric_scalars": {key: scalar.to_dict() for key, scalar in sorted(value.metric_scalars.items())},
        "research_attempted": value.research_attempted,
        "available": value.available,
    }


__all__ = ["OnlyHostedParameterGenerationExecutionV1"]
