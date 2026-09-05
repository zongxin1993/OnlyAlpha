"""Versioned Effect Summary mathematical definition."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from onlyalpha.calculation import ONLY_DECIMAL_EXECUTION_POLICY_V1, OnlyNumericDefinition

from ..definition import OnlyResearchStatisticsMethod
from .metric import OnlyResearchSummaryKind

RESEARCH_EFFECT_SUMMARY_DEFINITION_SCHEMA_VERSION = 1


class OnlyResearchSummarySourceStatusPolicy(StrEnum):
    VALID_ONLY = "VALID_ONLY"


class OnlyResearchSummaryStandardDeviation(StrEnum):
    SAMPLE = "SAMPLE"


class OnlyResearchSummaryInformationRatio(StrEnum):
    NON_ANNUALIZED = "NON_ANNUALIZED"


class OnlyResearchSummarySignRule(StrEnum):
    STRICT = "STRICT"


@dataclass(frozen=True, slots=True)
class OnlyResearchEffectSummaryDefinition:
    source_method: OnlyResearchStatisticsMethod
    summary_kind: OnlyResearchSummaryKind = OnlyResearchSummaryKind.EFFECT_SUMMARY
    source_status_policy: OnlyResearchSummarySourceStatusPolicy = OnlyResearchSummarySourceStatusPolicy.VALID_ONLY
    standard_deviation: OnlyResearchSummaryStandardDeviation = OnlyResearchSummaryStandardDeviation.SAMPLE
    information_ratio: OnlyResearchSummaryInformationRatio = OnlyResearchSummaryInformationRatio.NON_ANNUALIZED
    sign_rule: OnlyResearchSummarySignRule = OnlyResearchSummarySignRule.STRICT
    numeric: OnlyNumericDefinition = OnlyNumericDefinition("DECIMAL", 38, Decimal("0.000000000001"), "ROUND_HALF_EVEN")
    decimal_execution_policy: str = "onlyalpha.decimal.execution@1"
    schema_version: int = RESEARCH_EFFECT_SUMMARY_DEFINITION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RESEARCH_EFFECT_SUMMARY_DEFINITION_SCHEMA_VERSION:
            raise ValueError("unsupported Effect Summary Definition schema version")
        if not isinstance(self.source_method, OnlyResearchStatisticsMethod) or self.source_method not in {
            OnlyResearchStatisticsMethod.IC,
            OnlyResearchStatisticsMethod.RANK_IC,
        }:
            raise ValueError("Effect Summary source method is unsupported")
        if self.summary_kind is not OnlyResearchSummaryKind.EFFECT_SUMMARY:
            raise ValueError("Effect Summary kind is invalid")
        if self.source_status_policy is not OnlyResearchSummarySourceStatusPolicy.VALID_ONLY:
            raise ValueError("Effect Summary requires VALID_ONLY source policy")
        if self.standard_deviation is not OnlyResearchSummaryStandardDeviation.SAMPLE:
            raise ValueError("Effect Summary requires sample standard deviation")
        if self.information_ratio is not OnlyResearchSummaryInformationRatio.NON_ANNUALIZED:
            raise ValueError("Effect Summary requires non-annualized information ratio")
        if self.sign_rule is not OnlyResearchSummarySignRule.STRICT:
            raise ValueError("Effect Summary requires strict sign classification")
        if self.numeric != OnlyNumericDefinition("DECIMAL", 38, Decimal("0.000000000001"), "ROUND_HALF_EVEN"):
            raise ValueError("Effect Summary requires Decimal(38), quantum 1e-12, ROUND_HALF_EVEN")
        policy = ONLY_DECIMAL_EXECUTION_POLICY_V1
        if self.decimal_execution_policy != f"{policy.policy_id}@{policy.semantic_version}":
            raise ValueError("Effect Summary Decimal execution policy is unsupported")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "summary_kind": self.summary_kind.value,
            "source_method": self.source_method.value,
            "source_status_policy": self.source_status_policy.value,
            "standard_deviation": self.standard_deviation.value,
            "information_ratio": self.information_ratio.value,
            "sign_rule": self.sign_rule.value,
            "numeric": {
                "representation": self.numeric.representation,
                "precision": self.numeric.precision,
                "output_quantum": format(self.numeric.output_quantum, "f"),
                "rounding": self.numeric.rounding,
            },
            "decimal_execution_policy": self.decimal_execution_policy,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchEffectSummaryDefinition:
        expected = {
            "schema_version",
            "summary_kind",
            "source_method",
            "source_status_policy",
            "standard_deviation",
            "information_ratio",
            "sign_rule",
            "numeric",
            "decimal_execution_policy",
        }
        if set(payload) != expected:
            raise ValueError("Effect Summary Definition fields are invalid")
        numeric = payload["numeric"]
        if not isinstance(numeric, Mapping) or set(numeric) != {
            "representation",
            "precision",
            "output_quantum",
            "rounding",
        }:
            raise ValueError("Effect Summary numeric fields are invalid")
        return cls(
            source_method=OnlyResearchStatisticsMethod(_string(payload, "source_method")),
            summary_kind=OnlyResearchSummaryKind(_string(payload, "summary_kind")),
            source_status_policy=OnlyResearchSummarySourceStatusPolicy(_string(payload, "source_status_policy")),
            standard_deviation=OnlyResearchSummaryStandardDeviation(_string(payload, "standard_deviation")),
            information_ratio=OnlyResearchSummaryInformationRatio(_string(payload, "information_ratio")),
            sign_rule=OnlyResearchSummarySignRule(_string(payload, "sign_rule")),
            numeric=OnlyNumericDefinition(
                _string(numeric, "representation"),
                _integer(numeric, "precision"),
                Decimal(_string(numeric, "output_quantum")),
                _string(numeric, "rounding"),
            ),
            decimal_execution_policy=_string(payload, "decimal_execution_policy"),
            schema_version=_integer(payload, "schema_version"),
        )


def _string(payload: Mapping[str, object], name: str) -> str:
    value = payload[name]
    if not isinstance(value, str):
        raise ValueError(f"Effect Summary {name} must be a string")
    return value


def _integer(payload: Mapping[str, object], name: str) -> int:
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Effect Summary {name} must be an integer")
    return value


__all__ = [
    "OnlyResearchEffectSummaryDefinition",
    "OnlyResearchSummaryInformationRatio",
    "OnlyResearchSummarySignRule",
    "OnlyResearchSummarySourceStatusPolicy",
    "OnlyResearchSummaryStandardDeviation",
]
