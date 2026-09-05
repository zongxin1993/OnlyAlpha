"""Canonical symmetric Factor-Pair Statistics Plan."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from .definition import OnlyResearchFactorPairStatisticsDefinition
from .identity import only_research_factor_pair_statistics_fingerprint
from .reference import OnlyResearchFactorPairOperand

RESEARCH_FACTOR_PAIR_PLAN_SCHEMA_VERSION = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class OnlyResearchFactorPairStatisticsPlan:
    dataset_snapshot_fingerprint: str
    first_operand: OnlyResearchFactorPairOperand
    second_operand: OnlyResearchFactorPairOperand
    definition: OnlyResearchFactorPairStatisticsDefinition
    schema_version: int = RESEARCH_FACTOR_PAIR_PLAN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RESEARCH_FACTOR_PAIR_PLAN_SCHEMA_VERSION:
            raise ValueError(f"unsupported Factor-Pair Plan schema version: {self.schema_version}")
        if _SHA256.fullmatch(self.dataset_snapshot_fingerprint) is None:
            raise ValueError("Factor-Pair Dataset fingerprint must be lower-case SHA256")
        if not isinstance(self.first_operand, OnlyResearchFactorPairOperand) or not isinstance(
            self.second_operand, OnlyResearchFactorPairOperand
        ):
            raise ValueError("Factor-Pair operands are invalid")
        if not isinstance(self.definition, OnlyResearchFactorPairStatisticsDefinition):
            raise ValueError("Factor-Pair definition is invalid")
        first, second = sorted((self.first_operand, self.second_operand), key=lambda item: item.canonical_key)
        object.__setattr__(self, "first_operand", first)
        object.__setattr__(self, "second_operand", second)

    @property
    def statistics_fingerprint(self) -> str:
        return only_research_factor_pair_statistics_fingerprint(
            self.dataset_snapshot_fingerprint,
            self.first_operand,
            self.second_operand,
            self.definition,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "dataset_snapshot_fingerprint": self.dataset_snapshot_fingerprint,
            "first_operand": self.first_operand.to_dict(),
            "second_operand": self.second_operand.to_dict(),
            "definition": self.definition.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchFactorPairStatisticsPlan:
        expected = {
            "schema_version",
            "dataset_snapshot_fingerprint",
            "first_operand",
            "second_operand",
            "definition",
        }
        if set(payload) != expected:
            raise ValueError("Factor-Pair Plan fields are invalid")
        return cls(
            _string(payload, "dataset_snapshot_fingerprint"),
            OnlyResearchFactorPairOperand.from_dict(_mapping(payload["first_operand"], "first_operand")),
            OnlyResearchFactorPairOperand.from_dict(_mapping(payload["second_operand"], "second_operand")),
            OnlyResearchFactorPairStatisticsDefinition.from_dict(_mapping(payload["definition"], "definition")),
            _integer(payload, "schema_version"),
        )


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"Factor-Pair Plan {name} must be an object")
    return value


def _string(payload: Mapping[str, object], name: str) -> str:
    value = payload[name]
    if not isinstance(value, str):
        raise ValueError(f"Factor-Pair Plan {name} must be a string")
    return value


def _integer(payload: Mapping[str, object], name: str) -> int:
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Factor-Pair Plan {name} must be an integer")
    return value
