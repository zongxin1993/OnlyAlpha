"""Immutable symbolic-search Research Evaluation Contract V1."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.specification.model import (
    RESEARCH_SPECIFICATION_SCIENTIFIC_SCHEMA_VERSION,
    OnlyResearchCalculationSpec,
    OnlyResearchScientificEvidenceSpec,
    OnlyResearchSpecification,
    OnlyResearchStatisticsSpec,
)

SYMBOLIC_EVALUATION_CONTRACT_KIND = "ONLY_SYMBOLIC_RESEARCH_EVALUATION_CONTRACT"
SYMBOLIC_EVALUATION_CONTRACT_SCHEMA_VERSION = 1
SYMBOLIC_CANDIDATE_BINDING_POLICY_V1 = "REPLACE_CANDIDATE_FEATURE_SELECTORS_V1"


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{context} must be an object")
    return cast(Mapping[str, object], value)


def _integer(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{context} must be an integer")
    return value


@dataclass(frozen=True, slots=True)
class OnlySymbolicResearchEvaluationContractV1:
    dataset_snapshot_fingerprint: str
    candidate_calculation_id: str
    fixed_calculations: tuple[OnlyResearchCalculationSpec, ...]
    statistics: tuple[OnlyResearchStatisticsSpec, ...]
    evidence: OnlyResearchScientificEvidenceSpec
    candidate_binding_policy: str = SYMBOLIC_CANDIDATE_BINDING_POLICY_V1
    research_specification_schema_version: int = RESEARCH_SPECIFICATION_SCIENTIFIC_SCHEMA_VERSION
    schema_version: int = SYMBOLIC_EVALUATION_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SYMBOLIC_EVALUATION_CONTRACT_SCHEMA_VERSION:
            raise ValueError("SEARCH_EVALUATION_SCHEMA_UNSUPPORTED")
        if self.research_specification_schema_version != RESEARCH_SPECIFICATION_SCIENTIFIC_SCHEMA_VERSION:
            raise ValueError("SEARCH_EVALUATION_SPECIFICATION_SCHEMA_INVALID")
        if len(self.dataset_snapshot_fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in self.dataset_snapshot_fingerprint
        ):
            raise ValueError("SEARCH_EVALUATION_DATASET_INVALID")
        if not self.candidate_calculation_id or any(character.isspace() for character in self.candidate_calculation_id):
            raise ValueError("SEARCH_EVALUATION_CANDIDATE_SLOT_INVALID")
        if self.candidate_binding_policy != SYMBOLIC_CANDIDATE_BINDING_POLICY_V1:
            raise ValueError("SEARCH_EVALUATION_BINDING_POLICY_INVALID")
        if not self.fixed_calculations or any(
            not isinstance(item, OnlyResearchCalculationSpec) for item in self.fixed_calculations
        ):
            raise ValueError("SEARCH_EVALUATION_FIXED_CALCULATIONS_INVALID")
        if any(item.calculation_id == self.candidate_calculation_id for item in self.fixed_calculations):
            raise ValueError("SEARCH_EVALUATION_CANDIDATE_SLOT_DUPLICATED")
        if len({item.calculation_id for item in self.fixed_calculations}) != len(self.fixed_calculations):
            raise ValueError("SEARCH_EVALUATION_FIXED_CALCULATIONS_INVALID")
        if not self.statistics or any(not isinstance(item, OnlyResearchStatisticsSpec) for item in self.statistics):
            raise ValueError("SEARCH_EVALUATION_STATISTICS_INVALID")
        if any(item.target.calculation_id == self.candidate_calculation_id for item in self.statistics):
            raise ValueError("SEARCH_EVALUATION_CANDIDATE_CANNOT_BE_TARGET")
        if not any(item.feature.calculation_id == self.candidate_calculation_id for item in self.statistics):
            raise ValueError("SEARCH_EVALUATION_CANDIDATE_FEATURE_REQUIRED")
        if not isinstance(self.evidence, OnlyResearchScientificEvidenceSpec):
            raise ValueError("SEARCH_EVALUATION_EVIDENCE_INVALID")
        if self.evidence.candidate_calculation_id != self.candidate_calculation_id:
            raise ValueError("SEARCH_EVALUATION_EVIDENCE_CANDIDATE_MISMATCH")
        calculation_ids = {self.candidate_calculation_id, *(item.calculation_id for item in self.fixed_calculations)}
        selectors = [selector for item in self.statistics for selector in (item.feature, item.target)]
        selectors.extend(self.evidence.published_series)
        selectors.extend(
            selector
            for selector in (
                self.evidence.signals.eligibility,
                self.evidence.signals.entry,
                self.evidence.signals.exit,
            )
            if selector is not None
        )
        if any(selector.calculation_id not in calculation_ids for selector in selectors):
            raise ValueError("SEARCH_EVALUATION_SELECTOR_INVALID")
        object.__setattr__(
            self, "fixed_calculations", tuple(sorted(self.fixed_calculations, key=lambda x: x.calculation_id))
        )
        object.__setattr__(self, "statistics", tuple(sorted(self.statistics, key=lambda x: str(dict(x.to_dict())))))

    @property
    def evaluation_contract_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.research.symbolic-evaluation-contract", **self.to_dict(include_fingerprint=False)}
        )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "research_specification_schema_version": self.research_specification_schema_version,
            "dataset_snapshot_fingerprint": self.dataset_snapshot_fingerprint,
            "candidate_calculation_id": self.candidate_calculation_id,
            "fixed_calculations": [dict(item.to_dict()) for item in self.fixed_calculations],
            "statistics": [dict(item.to_dict()) for item in self.statistics],
            "evidence": dict(self.evidence.to_dict()),
            "candidate_binding_policy": self.candidate_binding_policy,
        }
        if include_fingerprint:
            payload["evaluation_contract_fingerprint"] = self.evaluation_contract_fingerprint
        return payload

    @classmethod
    def from_specification(
        cls,
        specification: OnlyResearchSpecification,
        candidate_calculation_id: str,
    ) -> OnlySymbolicResearchEvaluationContractV1:
        if specification.schema_version != RESEARCH_SPECIFICATION_SCIENTIFIC_SCHEMA_VERSION:
            raise ValueError("SEARCH_EVALUATION_SPECIFICATION_SCHEMA_INVALID")
        matches = tuple(item for item in specification.calculations if item.calculation_id == candidate_calculation_id)
        if len(matches) != 1 or specification.evidence is None:
            raise ValueError("SEARCH_EVALUATION_CANDIDATE_SLOT_INVALID")
        return cls(
            specification.dataset_snapshot_fingerprint,
            candidate_calculation_id,
            tuple(item for item in specification.calculations if item.calculation_id != candidate_calculation_id),
            specification.statistics,
            specification.evidence,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySymbolicResearchEvaluationContractV1:
        expected = {
            "schema_version",
            "research_specification_schema_version",
            "dataset_snapshot_fingerprint",
            "candidate_calculation_id",
            "fixed_calculations",
            "statistics",
            "evidence",
            "candidate_binding_policy",
            "evaluation_contract_fingerprint",
        }
        if set(payload) != expected:
            raise ValueError("SEARCH_EVALUATION_FIELDS_INVALID")
        fixed = payload["fixed_calculations"]
        statistics = payload["statistics"]
        if not isinstance(fixed, list) or not isinstance(statistics, list):
            raise ValueError("SEARCH_EVALUATION_FIELDS_INVALID")
        value = cls(
            str(payload["dataset_snapshot_fingerprint"]),
            str(payload["candidate_calculation_id"]),
            tuple(OnlyResearchCalculationSpec.from_dict(_mapping(item, "fixed calculation")) for item in fixed),
            tuple(OnlyResearchStatisticsSpec.from_dict(_mapping(item, "statistics")) for item in statistics),
            OnlyResearchScientificEvidenceSpec.from_dict(_mapping(payload["evidence"], "evidence")),
            str(payload["candidate_binding_policy"]),
            _integer(payload["research_specification_schema_version"], "research_specification_schema_version"),
            _integer(payload["schema_version"], "schema_version"),
        )
        if payload["evaluation_contract_fingerprint"] != value.evaluation_contract_fingerprint:
            raise ValueError("SEARCH_EVALUATION_IDENTITY_DIFFERS")
        return value


__all__ = [name for name in globals() if name.startswith(("OnlySymbolic", "SYMBOLIC_"))]
