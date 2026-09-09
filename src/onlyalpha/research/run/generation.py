"""Stable port for server-verified authoring execution generations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from onlyalpha.application.search_generation_execution import (
    OnlyHistoricalGenerationExecutionMismatch,
    OnlySearchGenerationExecutionPort,
    OnlySearchGenerationExecutionRequestV1,
    OnlySearchGenerationExecutionResponseV1,
    OnlySearchGenerationOperationV1,
)
from onlyalpha.research.provenance import OnlyResearchAuthoringProvenance
from onlyalpha.research.specification.model import OnlyResearchSpecification
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolution

from .errors import OnlyResearchRunAdmissionError
from .evidence import OnlyResearchAdmissionResolutionEvidence


class OnlyResearchAuthoringGenerationResolver(Protocol):
    """Resolve through the exact generation verified by an external component."""

    def resolve(
        self,
        provenance: OnlyResearchAuthoringProvenance,
        specification: OnlyResearchSpecification,
    ) -> OnlyResearchSpecificationResolution: ...


class OnlyResearchRuntimeGenerationResolver(Protocol):
    """Non-durable admission computation selected by the exact Runtime binding."""

    def resolve(
        self,
        runtime_generation_fingerprint: str,
        specification: OnlyResearchSpecification,
    ) -> OnlyResearchAdmissionResolutionEvidence: ...


class OnlyResearchHostedRuntimeGenerationResolver:
    """Bounded DTO adapter; the execution port proves the hosted generation."""

    def __init__(self, *, execution: OnlySearchGenerationExecutionPort, dataset_store_root: str) -> None:
        if not isinstance(dataset_store_root, str) or not dataset_store_root:
            raise ValueError("Dataset Store root is required")
        self._execution = execution
        self._dataset_store_root = dataset_store_root

    def resolve(
        self,
        runtime_generation_fingerprint: str,
        specification: OnlyResearchSpecification,
    ) -> OnlyResearchAdmissionResolutionEvidence:
        strict = OnlyResearchSpecification.from_dict(specification.to_dict())
        request = OnlySearchGenerationExecutionRequestV1(
            runtime_generation_fingerprint,
            OnlySearchGenerationOperationV1.RESOLVE_RESEARCH_ADMISSION,
            {"specification": strict.to_dict(), "dataset_store_root": self._dataset_store_root},
        )
        response = OnlySearchGenerationExecutionResponseV1.from_dict(self._execution.execute(request).to_dict())
        if (
            response.runtime_generation_fingerprint != runtime_generation_fingerprint
            or response.operation_kind != request.operation_kind
        ):
            raise OnlyHistoricalGenerationExecutionMismatch("Research admission response generation/operation differs")
        payload = response.result_payload
        if set(payload) != {"admission_evidence"} or not isinstance(payload["admission_evidence"], Mapping):
            raise OnlyResearchRunAdmissionError(
                "Research admission response fields differ", code="RESEARCH_ADMISSION_EVIDENCE_INVALID"
            )
        evidence = OnlyResearchAdmissionResolutionEvidence.from_dict(payload["admission_evidence"])
        if evidence.specification_fingerprint != strict.specification_fingerprint:
            raise OnlyResearchRunAdmissionError(
                "Admission evidence does not name the requested Specification",
                code="RESEARCH_ADMISSION_EVIDENCE_SPECIFICATION_MISMATCH",
            )
        return evidence


__all__ = [
    "OnlyResearchAuthoringGenerationResolver",
    "OnlyResearchRuntimeGenerationResolver",
    "OnlyResearchHostedRuntimeGenerationResolver",
]
