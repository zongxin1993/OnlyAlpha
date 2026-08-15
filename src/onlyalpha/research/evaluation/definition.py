"""Explicit Statistics semantic contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from onlyalpha.calculation import OnlyNumericDefinition

RESEARCH_STATISTICS_DEFINITION_SCHEMA_VERSION = 1


class OnlyResearchStatisticsMethod(StrEnum):
    IC = "IC"
    RANK_IC = "RANK_IC"


class OnlyResearchPairingPolicy(StrEnum):
    PAIRWISE_COMPLETE = "PAIRWISE_COMPLETE"


class OnlyResearchUniversePolicy(StrEnum):
    OBSERVED_PAIRWISE = "OBSERVED_PAIRWISE"


class OnlyResearchRankTieMethod(StrEnum):
    AVERAGE = "AVERAGE"


class OnlyResearchWeighting(StrEnum):
    EQUAL = "EQUAL"


@dataclass(frozen=True, slots=True)
class OnlyResearchStatisticsDefinition:
    method: OnlyResearchStatisticsMethod
    minimum_observations: int = 2
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
    schema_version: int = RESEARCH_STATISTICS_DEFINITION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RESEARCH_STATISTICS_DEFINITION_SCHEMA_VERSION:
            raise ValueError(f"unsupported Statistics Definition schema version: {self.schema_version}")
        if not isinstance(self.method, OnlyResearchStatisticsMethod):
            raise ValueError("Statistics method is invalid")
        if (
            isinstance(self.minimum_observations, bool)
            or not isinstance(self.minimum_observations, int)
            or self.minimum_observations < 2
        ):
            raise ValueError("minimum_observations must be an integer >= 2")
        if self.pairing_policy is not OnlyResearchPairingPolicy.PAIRWISE_COMPLETE:
            raise ValueError("Statistics V1 requires PAIRWISE_COMPLETE")
        if self.universe_policy is not OnlyResearchUniversePolicy.OBSERVED_PAIRWISE:
            raise ValueError("Statistics V1 requires OBSERVED_PAIRWISE")
        if self.rank_tie_method is not OnlyResearchRankTieMethod.AVERAGE:
            raise ValueError("Statistics V1 requires AVERAGE rank ties")
        if self.weighting is not OnlyResearchWeighting.EQUAL:
            raise ValueError("Statistics V1 requires EQUAL weighting")
        if (
            self.numeric.representation != "DECIMAL"
            or self.numeric.precision != 38
            or self.numeric.output_quantum != Decimal("0.000000000001")
            or self.numeric.rounding != "ROUND_HALF_EVEN"
        ):
            raise ValueError("Statistics V1 requires Decimal(38), quantum 1e-12, ROUND_HALF_EVEN")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "method": self.method.value,
            "minimum_observations": self.minimum_observations,
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
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchStatisticsDefinition:
        expected = {
            "schema_version",
            "method",
            "minimum_observations",
            "pairing_policy",
            "universe_policy",
            "rank_tie_method",
            "weighting",
            "numeric",
        }
        if set(payload) != expected:
            raise ValueError("Statistics Definition fields are invalid")
        numeric = payload["numeric"]
        if not isinstance(numeric, Mapping) or set(numeric) != {
            "representation",
            "precision",
            "output_quantum",
            "rounding",
        }:
            raise ValueError("Statistics numeric fields are invalid")
        return cls(
            OnlyResearchStatisticsMethod(_string(payload, "method")),
            _integer(payload, "minimum_observations"),
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
            _integer(payload, "schema_version"),
        )


def _string(payload: Mapping[str, object], name: str) -> str:
    value = payload[name]
    if not isinstance(value, str):
        raise ValueError(f"Statistics {name} must be a string")
    return value


def _integer(payload: Mapping[str, object], name: str) -> int:
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Statistics {name} must be an integer")
    return value
