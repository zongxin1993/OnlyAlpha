"""Canonical Research Result composition plan."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from .identity import RESEARCH_RESULT_PLAN_SCHEMA_VERSION, only_research_result_plan_fingerprint

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class OnlyResearchResultPlan:
    statistics_fingerprints: tuple[str, ...]
    schema_version: int = RESEARCH_RESULT_PLAN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RESEARCH_RESULT_PLAN_SCHEMA_VERSION:
            raise ValueError(f"unsupported Research Result Plan schema version: {self.schema_version}")
        if not isinstance(self.statistics_fingerprints, tuple) or not self.statistics_fingerprints:
            raise ValueError("Research Result Plan requires at least one Statistics identity")
        if any(
            not isinstance(value, str) or _SHA256.fullmatch(value) is None for value in self.statistics_fingerprints
        ):
            raise ValueError("Research Result Plan Statistics identity must be a lower-case SHA256")
        if len(set(self.statistics_fingerprints)) != len(self.statistics_fingerprints):
            raise ValueError("Research Result Plan contains duplicate Statistics identity")
        object.__setattr__(self, "statistics_fingerprints", tuple(sorted(self.statistics_fingerprints)))

    @property
    def fingerprint(self) -> str:
        return only_research_result_plan_fingerprint(self.statistics_fingerprints)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "statistics_fingerprints": list(self.statistics_fingerprints),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchResultPlan:
        if set(payload) != {"schema_version", "statistics_fingerprints"}:
            raise ValueError("Research Result Plan fields are invalid")
        version = payload["schema_version"]
        if isinstance(version, bool) or not isinstance(version, int):
            raise ValueError("Research Result Plan schema_version must be an integer")
        raw = payload["statistics_fingerprints"]
        if not isinstance(raw, list) or any(not isinstance(value, str) for value in raw):
            raise ValueError("Research Result Plan Statistics identities must be an array of strings")
        return cls(tuple(raw), version)
