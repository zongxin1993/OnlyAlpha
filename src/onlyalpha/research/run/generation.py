"""Stable port for server-verified authoring execution generations."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, cast

from onlyalpha.application.search_generation_execution import (
    OnlyHistoricalGenerationExecutionMismatch,
    OnlySearchGenerationExecutionPort,
    OnlySearchGenerationExecutionRequestV1,
    OnlySearchGenerationExecutionResponseV1,
    OnlySearchGenerationOperationV1,
)
from onlyalpha.calculation.definition import (
    only_calculation_scalar_from_dict,
    only_calculation_scalar_to_dict,
)
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition
from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.definition.model import OnlyResearchDefinition
from onlyalpha.research.provenance import OnlyResearchAuthoringProvenance
from onlyalpha.research.result.plan import OnlyResearchResultPlan
from onlyalpha.research.specification.identity import only_research_candidate_fingerprint
from onlyalpha.research.specification.model import OnlyResearchSpecification
from onlyalpha.research.specification.resolver import (
    OnlyResearchCandidateLineage,
    OnlyResearchSignalLineage,
    OnlyResearchSpecificationResolution,
)
from onlyalpha.strategy.admission import OnlyRuntimeStrategyTradingResolutionV1
from onlyalpha.strategy.revision import OnlyStrategyMarketInputContract, OnlyStrategySignalSemantics

from .errors import OnlyResearchRunAdmissionError
from .evidence import OnlyResearchAdmissionResolutionEvidence


class OnlyResearchAuthoringGenerationResolver(Protocol):
    """Resolve through the exact generation verified by an external component."""

    def load_verified(self, authoring_generation_fingerprint: str) -> OnlyResearchAuthoringProvenance: ...

    def resolve(
        self,
        authoring_generation_fingerprint: str,
        specification: OnlyResearchSpecification,
    ) -> OnlyResearchSpecificationResolution: ...


class OnlyResearchRuntimeGenerationResolver(Protocol):
    """Non-durable admission computation selected by the exact Runtime binding."""

    def resolve(
        self,
        runtime_generation_fingerprint: str,
        specification: OnlyResearchSpecification,
    ) -> OnlyResearchAdmissionResolutionEvidence: ...


@dataclass(frozen=True, slots=True)
class OnlyResearchDefinitionRuntimeResolutionV1:
    """Strict DTO returned by the exact generation Definition resolver."""

    research_definition_fingerprint: str
    specification: OnlyResearchSpecification
    specification_fingerprint: str
    admission_evidence: OnlyResearchAdmissionResolutionEvidence
    private_factor_bindings: tuple[Mapping[str, object], ...]
    candidates: tuple[OnlyResearchCandidateLineage, ...]
    signals: tuple[OnlyResearchSignalLineage, ...]
    result_plan: OnlyResearchResultPlan

    def __post_init__(self) -> None:
        _sha(self.research_definition_fingerprint)
        _sha(self.specification_fingerprint)
        if self.specification.specification_fingerprint != self.specification_fingerprint:
            raise ValueError("RESEARCH_DEFINITION_RUNTIME_RESOLUTION_MISMATCH")
        if self.admission_evidence.specification_fingerprint != self.specification_fingerprint:
            raise ValueError("RESEARCH_DEFINITION_RUNTIME_RESOLUTION_MISMATCH")
        bindings = tuple(_private_factor_binding(item) for item in self.private_factor_bindings)
        canonical = tuple(sorted(bindings, key=only_canonical_json))
        if canonical != bindings or len({only_canonical_json(item) for item in canonical}) != len(canonical):
            raise ValueError("RESEARCH_DEFINITION_RUNTIME_RESOLUTION_MISMATCH")
        object.__setattr__(self, "private_factor_bindings", canonical)
        if not isinstance(self.result_plan, OnlyResearchResultPlan):
            raise ValueError("RESEARCH_DEFINITION_RUNTIME_RESOLUTION_MISMATCH")
        if any(not isinstance(item, OnlyResearchCandidateLineage) for item in self.candidates):
            raise ValueError("RESEARCH_DEFINITION_RUNTIME_RESOLUTION_MISMATCH")
        if any(not isinstance(item, OnlyResearchSignalLineage) for item in self.signals):
            raise ValueError("RESEARCH_DEFINITION_RUNTIME_RESOLUTION_MISMATCH")
        if len({item.calculation_fingerprint for item in self.candidates}) != len(self.candidates):
            raise ValueError("RESEARCH_DEFINITION_RUNTIME_RESOLUTION_MISMATCH")
        canonical_candidates = tuple(
            type(candidate)(
                candidate.calculation_id,
                candidate.assignment,
                OnlyCalculationGraphDefinition(tuple(candidate.graph.ordered_nodes)),
                candidate.graph_fingerprint,
                candidate.calculation_fingerprint,
                candidate.node_fingerprints,
                candidate.candidate_fingerprint,
            )
            for candidate in self.candidates
        )
        object.__setattr__(self, "candidates", canonical_candidates)
        for candidate in canonical_candidates:
            if candidate.graph_fingerprint != candidate.graph.fingerprint:
                raise ValueError("RESEARCH_DEFINITION_RUNTIME_RESOLUTION_MISMATCH")
            if candidate.candidate_fingerprint is not None and candidate.candidate_fingerprint != (
                only_research_candidate_fingerprint(
                    self.specification_fingerprint,
                    candidate.calculation_id,
                    candidate.assignment,
                    candidate.calculation_fingerprint,
                )
            ):
                raise ValueError("RESEARCH_DEFINITION_RUNTIME_RESOLUTION_MISMATCH")
        if self.signals != tuple(sorted(set(self.signals))):
            raise ValueError("RESEARCH_DEFINITION_RUNTIME_RESOLUTION_MISMATCH")

    def to_dict(self) -> dict[str, object]:
        return {
            "research_definition_fingerprint": self.research_definition_fingerprint,
            "specification": self.specification.to_dict(),
            "specification_fingerprint": self.specification_fingerprint,
            "admission_evidence": self.admission_evidence.to_dict(),
            "private_factor_bindings": [dict(item) for item in self.private_factor_bindings],
            "candidates": [_candidate_to_dict(item) for item in self.candidates],
            "signals": [_signal_to_dict(item) for item in self.signals],
            "result_plan": self.result_plan.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchDefinitionRuntimeResolutionV1:
        if set(payload) != {
            "research_definition_fingerprint",
            "specification",
            "specification_fingerprint",
            "admission_evidence",
            "private_factor_bindings",
            "candidates",
            "signals",
            "result_plan",
        }:
            raise ValueError("RESEARCH_DEFINITION_RUNTIME_RESOLUTION_INVALID")
        bindings = payload["private_factor_bindings"]
        if not isinstance(bindings, list) or any(not isinstance(item, Mapping) for item in bindings):
            raise ValueError("RESEARCH_DEFINITION_RUNTIME_RESOLUTION_INVALID")
        candidates = payload["candidates"]
        signals = payload["signals"]
        if not isinstance(candidates, list) or any(not isinstance(item, Mapping) for item in candidates):
            raise ValueError("RESEARCH_DEFINITION_RUNTIME_RESOLUTION_INVALID")
        if not isinstance(signals, list) or any(not isinstance(item, Mapping) for item in signals):
            raise ValueError("RESEARCH_DEFINITION_RUNTIME_RESOLUTION_INVALID")
        return cls(
            _sha(payload["research_definition_fingerprint"]),
            OnlyResearchSpecification.from_dict(_mapping(payload["specification"])),
            _sha(payload["specification_fingerprint"]),
            OnlyResearchAdmissionResolutionEvidence.from_dict(_mapping(payload["admission_evidence"])),
            tuple(_private_factor_binding(item) for item in bindings),
            tuple(_candidate_from_dict(item) for item in candidates),
            tuple(_signal_from_dict(item) for item in signals),
            OnlyResearchResultPlan.from_dict(_mapping(payload["result_plan"])),
        )


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

    def resolve_definition(
        self,
        runtime_generation_fingerprint: str,
        definition: OnlyResearchDefinition,
    ) -> OnlyResearchDefinitionRuntimeResolutionV1:
        request = OnlySearchGenerationExecutionRequestV1(
            runtime_generation_fingerprint,
            OnlySearchGenerationOperationV1.RESOLVE_RESEARCH_DEFINITION,
            {"definition": definition.to_dict(), "dataset_store_root": self._dataset_store_root},
        )
        response = OnlySearchGenerationExecutionResponseV1.from_dict(self._execution.execute(request).to_dict())
        if (
            response.runtime_generation_fingerprint != runtime_generation_fingerprint
            or response.operation_kind is not request.operation_kind
        ):
            raise OnlyHistoricalGenerationExecutionMismatch("Research definition response generation/operation differs")
        try:
            result = OnlyResearchDefinitionRuntimeResolutionV1.from_dict(response.result_payload)
            if result.research_definition_fingerprint != definition.definition_fingerprint:
                raise ValueError("RESEARCH_DEFINITION_RUNTIME_RESOLUTION_MISMATCH")
            return result
        except (TypeError, ValueError, KeyError) as exc:
            raise OnlyResearchRunAdmissionError(
                "Research definition response fields differ", code="RESEARCH_DEFINITION_RESOLUTION_INVALID"
            ) from exc

    def resolve_strategy_trading_admission(
        self,
        runtime_generation_fingerprint: str,
        graph: OnlyCalculationGraphDefinition,
        signals: OnlyStrategySignalSemantics,
        market_input_contract: OnlyStrategyMarketInputContract,
        research_implementation_bindings: tuple[Mapping[str, object], ...],
    ) -> OnlyRuntimeStrategyTradingResolutionV1:
        request = OnlySearchGenerationExecutionRequestV1(
            runtime_generation_fingerprint,
            OnlySearchGenerationOperationV1.RESOLVE_STRATEGY_TRADING_ADMISSION,
            {
                "graph": graph.to_dict(),
                "signals": signals.to_dict(),
                "market_input_contract": market_input_contract.to_dict(),
                "research_implementation_bindings": [dict(item) for item in research_implementation_bindings],
            },
        )
        response = OnlySearchGenerationExecutionResponseV1.from_dict(self._execution.execute(request).to_dict())
        if (
            response.runtime_generation_fingerprint != runtime_generation_fingerprint
            or response.operation_kind is not request.operation_kind
        ):
            raise OnlyHistoricalGenerationExecutionMismatch("Strategy Trading response generation/operation differs")
        try:
            resolution = OnlyRuntimeStrategyTradingResolutionV1.from_dict(response.result_payload)
        except (TypeError, ValueError, KeyError) as exc:
            raise OnlyHistoricalGenerationExecutionMismatch("Strategy Trading response fields differ") from exc
        if resolution.runtime_generation_fingerprint != runtime_generation_fingerprint:
            raise OnlyHistoricalGenerationExecutionMismatch("Strategy Trading response generation differs")
        return resolution


def _sha(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("RESEARCH_DEFINITION_RUNTIME_RESOLUTION_INVALID")
    return value


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError("RESEARCH_DEFINITION_RUNTIME_RESOLUTION_INVALID")
    return cast(Mapping[str, object], value)


def _private_factor_binding(value: Mapping[str, object]) -> Mapping[str, object]:
    if set(value) != {"provider_snapshot_fingerprint", "runtime_artifact_fingerprint", "entry"}:
        raise ValueError("RESEARCH_DEFINITION_RUNTIME_RESOLUTION_INVALID")
    entry = _mapping(value["entry"])
    entry_fields = {
        "factor_id",
        "semantic_version",
        "revision_fingerprint",
        "source_sha256",
        "source_artifact_fingerprint",
        "factor_api_version",
        "factor_api_contract_fingerprint",
        "research_adapter_fingerprint",
        "trading_adapter_fingerprint",
        "research_implementation_fingerprint",
        "trading_implementation_fingerprint",
        "equivalence_evidence_fingerprint",
    }
    if set(entry) != entry_fields or isinstance(entry["factor_api_version"], bool):
        raise ValueError("RESEARCH_DEFINITION_RUNTIME_RESOLUTION_INVALID")
    if not isinstance(entry["factor_api_version"], int):
        raise ValueError("RESEARCH_DEFINITION_RUNTIME_RESOLUTION_INVALID")
    for key in (
        "provider_snapshot_fingerprint",
        "runtime_artifact_fingerprint",
        "revision_fingerprint",
        "source_sha256",
        "source_artifact_fingerprint",
        "factor_api_contract_fingerprint",
        "research_adapter_fingerprint",
        "trading_adapter_fingerprint",
        "research_implementation_fingerprint",
        "trading_implementation_fingerprint",
        "equivalence_evidence_fingerprint",
    ):
        _sha(value[key] if key in value else entry[key])
    for key in ("factor_id", "semantic_version"):
        _string(entry[key])
    return {
        "provider_snapshot_fingerprint": value["provider_snapshot_fingerprint"],
        "runtime_artifact_fingerprint": value["runtime_artifact_fingerprint"],
        "entry": dict(entry),
    }


def _candidate_to_dict(candidate: OnlyResearchCandidateLineage) -> dict[str, object]:
    return {
        "calculation_id": candidate.calculation_id,
        "assignment": {key: only_calculation_scalar_to_dict(value) for key, value in candidate.assignment.items()},
        "graph": dict(candidate.graph.to_dict()),
        "graph_fingerprint": candidate.graph_fingerprint,
        "calculation_fingerprint": candidate.calculation_fingerprint,
        "node_fingerprints": dict(candidate.node_fingerprints),
        "candidate_fingerprint": candidate.candidate_fingerprint,
    }


def _candidate_from_dict(payload: Mapping[str, object]) -> OnlyResearchCandidateLineage:
    if set(payload) != {
        "calculation_id",
        "assignment",
        "graph",
        "graph_fingerprint",
        "calculation_fingerprint",
        "node_fingerprints",
        "candidate_fingerprint",
    }:
        raise ValueError("RESEARCH_DEFINITION_RUNTIME_RESOLUTION_INVALID")
    assignment = _mapping(payload["assignment"])
    node_fingerprints = _mapping(payload["node_fingerprints"])
    if any(not isinstance(value, str) for value in node_fingerprints.values()):
        raise ValueError("RESEARCH_DEFINITION_RUNTIME_RESOLUTION_INVALID")
    candidate = payload["candidate_fingerprint"]
    if candidate is not None:
        candidate = _sha(candidate)
    return OnlyResearchCandidateLineage(
        _string(payload["calculation_id"]),
        {key: only_calculation_scalar_from_dict(value) for key, value in assignment.items()},
        OnlyCalculationGraphDefinition.from_dict(_mapping(payload["graph"])),
        _sha(payload["graph_fingerprint"]),
        _sha(payload["calculation_fingerprint"]),
        cast(dict[str, str], dict(node_fingerprints)),
        candidate,
    )


def _signal_to_dict(signal: OnlyResearchSignalLineage) -> dict[str, str]:
    return {
        "role": signal.role,
        "candidate_fingerprint": signal.candidate_fingerprint,
        "calculation_fingerprint": signal.calculation_fingerprint,
        "node_fingerprint": signal.node_fingerprint,
        "output_name": signal.output_name,
    }


def _signal_from_dict(payload: Mapping[str, object]) -> OnlyResearchSignalLineage:
    if set(payload) != {
        "role",
        "candidate_fingerprint",
        "calculation_fingerprint",
        "node_fingerprint",
        "output_name",
    }:
        raise ValueError("RESEARCH_DEFINITION_RUNTIME_RESOLUTION_INVALID")
    return OnlyResearchSignalLineage(
        _string(payload["role"]),
        _sha(payload["candidate_fingerprint"]),
        _sha(payload["calculation_fingerprint"]),
        _sha(payload["node_fingerprint"]),
        _string(payload["output_name"]),
    )


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("RESEARCH_DEFINITION_RUNTIME_RESOLUTION_INVALID")
    return value


__all__ = [
    "OnlyResearchDefinitionRuntimeResolutionV1",
    "OnlyResearchAuthoringGenerationResolver",
    "OnlyResearchRuntimeGenerationResolver",
    "OnlyResearchHostedRuntimeGenerationResolver",
]
