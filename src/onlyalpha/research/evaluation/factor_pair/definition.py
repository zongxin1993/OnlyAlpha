"""Typed Factor-Pair correlation semantic definition."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from onlyalpha.calculation import ONLY_DECIMAL_EXECUTION_POLICY_V1, OnlyNumericDefinition

from ..definition import (
    OnlyResearchPairingPolicy,
    OnlyResearchRankTieMethod,
    OnlyResearchUniversePolicy,
    OnlyResearchWeighting,
)

RESEARCH_FACTOR_PAIR_DEFINITION_SCHEMA_VERSION = 1


class OnlyResearchFactorPairStatisticsMethod(StrEnum):
    FACTOR_CORRELATION = "FACTOR_CORRELATION"
    FACTOR_RANK_CORRELATION = "FACTOR_RANK_CORRELATION"


class OnlyResearchFactorPairAlignment(StrEnum):
    EXACT_COORDINATE_INTERSECTION = "EXACT_COORDINATE_INTERSECTION"


@dataclass(frozen=True, slots=True)
class OnlyResearchFactorPairStatisticsDefinition:
    method: OnlyResearchFactorPairStatisticsMethod
    minimum_observations: int = 2
    alignment: OnlyResearchFactorPairAlignment = OnlyResearchFactorPairAlignment.EXACT_COORDINATE_INTERSECTION
    pairing_policy: OnlyResearchPairingPolicy = OnlyResearchPairingPolicy.PAIRWISE_COMPLETE
    universe_policy: OnlyResearchUniversePolicy = OnlyResearchUniversePolicy.OBSERVED_PAIRWISE
    rank_tie_method: OnlyResearchRankTieMethod = OnlyResearchRankTieMethod.AVERAGE
    weighting: OnlyResearchWeighting = OnlyResearchWeighting.EQUAL
    numeric: OnlyNumericDefinition = OnlyNumericDefinition(
        representation="DECIMAL",
        precision=38,
        output_quantum=Decimal("0.000000000001"),
        rounding="ROUND_HALF_EVEN",
    )
    decimal_execution_policy: str = "onlyalpha.decimal.execution@1"
    schema_version: int = RESEARCH_FACTOR_PAIR_DEFINITION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RESEARCH_FACTOR_PAIR_DEFINITION_SCHEMA_VERSION:
            raise ValueError(f"unsupported Factor-Pair Definition schema version: {self.schema_version}")
        if not isinstance(self.method, OnlyResearchFactorPairStatisticsMethod):
            raise ValueError("Factor-Pair method is invalid")
        if (
            isinstance(self.minimum_observations, bool)
            or not isinstance(self.minimum_observations, int)
            or self.minimum_observations < 2
        ):
            raise ValueError("minimum_observations must be an integer >= 2")
        if self.alignment is not OnlyResearchFactorPairAlignment.EXACT_COORDINATE_INTERSECTION:
            raise ValueError("Factor-Pair V1 requires EXACT_COORDINATE_INTERSECTION")
        if self.pairing_policy is not OnlyResearchPairingPolicy.PAIRWISE_COMPLETE:
            raise ValueError("Factor-Pair V1 requires PAIRWISE_COMPLETE")
        if self.universe_policy is not OnlyResearchUniversePolicy.OBSERVED_PAIRWISE:
            raise ValueError("Factor-Pair V1 requires OBSERVED_PAIRWISE")
        if self.rank_tie_method is not OnlyResearchRankTieMethod.AVERAGE:
            raise ValueError("Factor-Pair V1 requires AVERAGE rank ties")
        if self.weighting is not OnlyResearchWeighting.EQUAL:
            raise ValueError("Factor-Pair V1 requires EQUAL weighting")
        if (
            self.numeric.representation != "DECIMAL"
            or self.numeric.precision != 38
            or self.numeric.output_quantum != Decimal("0.000000000001")
            or self.numeric.rounding != "ROUND_HALF_EVEN"
        ):
            raise ValueError("Factor-Pair V1 requires Decimal(38), quantum 1e-12, ROUND_HALF_EVEN")
        policy = ONLY_DECIMAL_EXECUTION_POLICY_V1
        if self.decimal_execution_policy != f"{policy.policy_id}@{policy.semantic_version}":
            raise ValueError("Factor-Pair V1 requires the canonical Decimal execution policy")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "method": self.method.value,
            "minimum_observations": self.minimum_observations,
            "alignment": self.alignment.value,
            "pairing_policy": self.pairing_policy.value,
            "universe_policy": self.universe_policy.value,
            "rank_tie_method": self.rank_tie_method.value,
            "weighting": self.weighting.value,
            "numeric": {
                "representation": self.numeric.representation,
                "precision": self.numeric.precision,
                "output_quantum": format(self.numeric.output_quantum, "f"),
                "rounding": self.numeric.rounding,
            },
            "decimal_execution_policy": self.decimal_execution_policy,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchFactorPairStatisticsDefinition:
        expected = {
            "schema_version",
            "method",
            "minimum_observations",
            "alignment",
            "pairing_policy",
            "universe_policy",
            "rank_tie_method",
            "weighting",
            "numeric",
            "decimal_execution_policy",
        }
        if set(payload) != expected:
            raise ValueError("Factor-Pair Definition fields are invalid")
        numeric = _mapping(payload["numeric"], "numeric")
        if set(numeric) != {"representation", "precision", "output_quantum", "rounding"}:
            raise ValueError("Factor-Pair numeric fields are invalid")
        return cls(
            OnlyResearchFactorPairStatisticsMethod(_string(payload, "method")),
            _integer(payload, "minimum_observations"),
            OnlyResearchFactorPairAlignment(_string(payload, "alignment")),
            OnlyResearchPairingPolicy(_string(payload, "pairing_policy")),
            OnlyResearchUniversePolicy(_string(payload, "universe_policy")),
            OnlyResearchRankTieMethod(_string(payload, "rank_tie_method")),
            OnlyResearchWeighting(_string(payload, "weighting")),
            OnlyNumericDefinition(
                _string(numeric, "representation"),
                _integer(numeric, "precision"),
                Decimal(_string(numeric, "output_quantum")),
                _string(numeric, "rounding"),
            ),
            _string(payload, "decimal_execution_policy"),
            _integer(payload, "schema_version"),
        )


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"Factor-Pair {name} must be an object")
    return value


def _string(payload: Mapping[str, object], name: str) -> str:
    value = payload[name]
    if not isinstance(value, str):
        raise ValueError(f"Factor-Pair {name} must be a string")
    return value


def _integer(payload: Mapping[str, object], name: str) -> int:
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Factor-Pair {name} must be an integer")
    return value
