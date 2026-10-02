"""Exact non-semantic request for readiness-bearing Research publication."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from onlyalpha.research.dataset.strict import require_exact_fields, require_int, require_mapping

RESEARCH_CALCULATION_PUBLICATION_CONTRACT_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class OnlyResearchCalculationPublicationContract:
    calculation_result_schema_version: int = 2
    execution_evidence_schema_version: int = 2
    readiness_contract_version: int = 1
    schema_version: int = RESEARCH_CALCULATION_PUBLICATION_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        payload = self.to_dict()
        for name, expected in (
            ("schema_version", RESEARCH_CALCULATION_PUBLICATION_CONTRACT_SCHEMA_VERSION),
            ("calculation_result_schema_version", 2),
            ("execution_evidence_schema_version", 2),
            ("readiness_contract_version", 1),
        ):
            if require_int(payload, name, "Research Calculation publication") != expected:
                raise ValueError(f"unsupported Research Calculation publication {name}: {payload[name]}")

    def to_dict(self) -> dict[str, int]:
        return {
            "schema_version": self.schema_version,
            "calculation_result_schema_version": self.calculation_result_schema_version,
            "execution_evidence_schema_version": self.execution_evidence_schema_version,
            "readiness_contract_version": self.readiness_contract_version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchCalculationPublicationContract:
        context = "Research Calculation publication"
        payload = require_mapping(payload, context)
        require_exact_fields(
            payload,
            {
                "schema_version",
                "calculation_result_schema_version",
                "execution_evidence_schema_version",
                "readiness_contract_version",
            },
            context,
        )
        return cls(
            calculation_result_schema_version=require_int(payload, "calculation_result_schema_version", context),
            execution_evidence_schema_version=require_int(payload, "execution_evidence_schema_version", context),
            readiness_contract_version=require_int(payload, "readiness_contract_version", context),
            schema_version=require_int(payload, "schema_version", context),
        )
