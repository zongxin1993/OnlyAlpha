"""Canonical Statistics evaluation plan."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .definition import OnlyResearchStatisticsDefinition
from .reference import OnlyResearchFeatureSeriesReference, OnlyResearchTargetSeriesReference
from .result_identity import only_research_statistics_fingerprint

RESEARCH_STATISTICS_PLAN_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class OnlyResearchStatisticsPlan:
    feature: OnlyResearchFeatureSeriesReference
    target: OnlyResearchTargetSeriesReference
    definition: OnlyResearchStatisticsDefinition
    schema_version: int = RESEARCH_STATISTICS_PLAN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RESEARCH_STATISTICS_PLAN_SCHEMA_VERSION:
            raise ValueError(f"unsupported Statistics Plan schema version: {self.schema_version}")
        if not isinstance(self.feature, OnlyResearchFeatureSeriesReference):
            raise ValueError("Statistics Plan feature reference is invalid")
        if not isinstance(self.target, OnlyResearchTargetSeriesReference):
            raise ValueError("Statistics Plan target reference is invalid")
        if not isinstance(self.definition, OnlyResearchStatisticsDefinition):
            raise ValueError("Statistics Plan definition is invalid")

    @property
    def statistics_fingerprint(self) -> str:
        return only_research_statistics_fingerprint(self.feature, self.target, self.definition)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "feature": self.feature.to_dict(),
            "target": self.target.to_dict(),
            "definition": self.definition.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchStatisticsPlan:
        if set(payload) != {"schema_version", "feature", "target", "definition"}:
            raise ValueError("Statistics Plan fields are invalid")
        version = payload["schema_version"]
        if isinstance(version, bool) or not isinstance(version, int):
            raise ValueError("Statistics Plan schema_version must be an integer")
        feature = _mapping(payload["feature"], "feature")
        target = _mapping(payload["target"], "target")
        definition = _mapping(payload["definition"], "definition")
        return cls(
            OnlyResearchFeatureSeriesReference.from_dict(feature),
            OnlyResearchTargetSeriesReference.from_dict(target),
            OnlyResearchStatisticsDefinition.from_dict(definition),
            version,
        )


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"Statistics Plan {name} must be an object")
    return value
