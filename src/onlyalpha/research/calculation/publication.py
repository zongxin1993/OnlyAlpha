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


RESEARCH_CALCULATION_READINESS_ARTIFACT_PROFILE = "RESEARCH_CALCULATION_V2"


@dataclass(frozen=True, slots=True)
class OnlyResearchCalculationPublicationSelectionV1:
    """Publication membership, distinct from Calculation semantic identity."""

    artifact_profile: str = RESEARCH_CALCULATION_READINESS_ARTIFACT_PROFILE
    calculation_result_schema_version: int = 2
    execution_evidence_schema_version: int = 2
    readiness_contract_version: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.artifact_profile) is not str
            or self.artifact_profile != RESEARCH_CALCULATION_READINESS_ARTIFACT_PROFILE
        ):
            raise ValueError("unsupported Calculation publication artifact profile")
        _ = self.execution_contract

    @property
    def execution_contract(self) -> OnlyResearchCalculationPublicationContract:
        return OnlyResearchCalculationPublicationContract(
            self.calculation_result_schema_version,
            self.execution_evidence_schema_version,
            self.readiness_contract_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_profile": self.artifact_profile,
            "calculation_result_schema_version": self.calculation_result_schema_version,
            "execution_evidence_schema_version": self.execution_evidence_schema_version,
            "readiness_contract_version": self.readiness_contract_version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchCalculationPublicationSelectionV1:
        context = "Calculation publication selection"
        payload = require_mapping(payload, context)
        require_exact_fields(
            payload,
            {
                "artifact_profile",
                "calculation_result_schema_version",
                "execution_evidence_schema_version",
                "readiness_contract_version",
            },
            context,
        )
        profile = payload["artifact_profile"]
        if type(profile) is not str:
            raise ValueError("Calculation publication artifact profile must be a string")
        return cls(
            profile,
            require_int(payload, "calculation_result_schema_version", context),
            require_int(payload, "execution_evidence_schema_version", context),
            require_int(payload, "readiness_contract_version", context),
        )
