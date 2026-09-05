"""Exact immutable plan for one Effect Summary."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from ..reference import OnlyResearchFeatureSeriesReference
from .definition import OnlyResearchEffectSummaryDefinition
from .identity import only_research_effect_summary_fingerprint

RESEARCH_EFFECT_SUMMARY_PLAN_SCHEMA_VERSION = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class OnlyResearchEffectSummaryPlan:
    dataset_snapshot_fingerprint: str
    subject_candidate_fingerprint: str
    subject: OnlyResearchFeatureSeriesReference
    source_statistics_fingerprint: str
    source_statistics_result_fingerprint: str
    definition: OnlyResearchEffectSummaryDefinition
    schema_version: int = RESEARCH_EFFECT_SUMMARY_PLAN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RESEARCH_EFFECT_SUMMARY_PLAN_SCHEMA_VERSION:
            raise ValueError("unsupported Effect Summary Plan schema version")
        for name in (
            "dataset_snapshot_fingerprint",
            "subject_candidate_fingerprint",
            "source_statistics_fingerprint",
            "source_statistics_result_fingerprint",
        ):
            if _SHA256.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"Effect Summary Plan {name} must be a lower-case SHA256")
        if not isinstance(self.subject, OnlyResearchFeatureSeriesReference):
            raise ValueError("Effect Summary Plan subject is invalid")
        if not isinstance(self.definition, OnlyResearchEffectSummaryDefinition):
            raise ValueError("Effect Summary Plan definition is invalid")

    @property
    def statistics_fingerprint(self) -> str:
        return only_research_effect_summary_fingerprint(
            self.dataset_snapshot_fingerprint,
            self.subject_candidate_fingerprint,
            self.subject,
            self.source_statistics_fingerprint,
            self.definition,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "dataset_snapshot_fingerprint": self.dataset_snapshot_fingerprint,
            "subject_candidate_fingerprint": self.subject_candidate_fingerprint,
            "subject": self.subject.to_dict(),
            "source_statistics_fingerprint": self.source_statistics_fingerprint,
            "source_statistics_result_fingerprint": self.source_statistics_result_fingerprint,
            "definition": self.definition.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchEffectSummaryPlan:
        expected = {
            "schema_version",
            "dataset_snapshot_fingerprint",
            "subject_candidate_fingerprint",
            "subject",
            "source_statistics_fingerprint",
            "source_statistics_result_fingerprint",
            "definition",
        }
        if set(payload) != expected:
            raise ValueError("Effect Summary Plan fields are invalid")
        subject = payload["subject"]
        definition = payload["definition"]
        if not isinstance(subject, Mapping) or any(not isinstance(key, str) for key in subject):
            raise ValueError("Effect Summary Plan subject must be an object")
        if not isinstance(definition, Mapping) or any(not isinstance(key, str) for key in definition):
            raise ValueError("Effect Summary Plan definition must be an object")
        return cls(
            _string(payload, "dataset_snapshot_fingerprint"),
            _string(payload, "subject_candidate_fingerprint"),
            OnlyResearchFeatureSeriesReference.from_dict(subject),
            _string(payload, "source_statistics_fingerprint"),
            _string(payload, "source_statistics_result_fingerprint"),
            OnlyResearchEffectSummaryDefinition.from_dict(definition),
            _integer(payload, "schema_version"),
        )


def _string(payload: Mapping[str, object], name: str) -> str:
    value = payload[name]
    if not isinstance(value, str):
        raise ValueError(f"Effect Summary Plan {name} must be a string")
    return value


def _integer(payload: Mapping[str, object], name: str) -> int:
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Effect Summary Plan {name} must be an integer")
    return value


__all__ = ["OnlyResearchEffectSummaryPlan"]
