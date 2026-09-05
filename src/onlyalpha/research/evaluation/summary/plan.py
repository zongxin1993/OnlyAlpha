"""Exact immutable plans for typed Summary Statistics."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from ..reference import OnlyResearchFeatureSeriesReference
from .definition import (
    OnlyResearchCoverageSummaryDefinition,
    OnlyResearchEffectSummaryDefinition,
    OnlyResearchTemporalStabilityDefinition,
)
from .identity import (
    only_research_coverage_summary_fingerprint,
    only_research_effect_summary_fingerprint,
    only_research_temporal_stability_fingerprint,
)
from .metric import OnlyResearchSummaryKind
from .temporal import OnlyResearchTemporalSlice

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


@dataclass(frozen=True, slots=True)
class OnlyResearchCoverageSummaryPlan:
    dataset_snapshot_fingerprint: str
    subject_candidate_fingerprint: str
    subject: OnlyResearchFeatureSeriesReference
    source_statistics_fingerprint: str
    source_statistics_result_fingerprint: str
    definition: OnlyResearchCoverageSummaryDefinition
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported Coverage Summary Plan schema version")
        for name in (
            "dataset_snapshot_fingerprint",
            "subject_candidate_fingerprint",
            "source_statistics_fingerprint",
            "source_statistics_result_fingerprint",
        ):
            if _SHA256.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"Coverage Summary Plan {name} must be a lower-case SHA256")
        if not isinstance(self.subject, OnlyResearchFeatureSeriesReference):
            raise ValueError("Coverage Summary Plan subject is invalid")
        if not isinstance(self.definition, OnlyResearchCoverageSummaryDefinition):
            raise ValueError("Coverage Summary Plan definition is invalid")

    @property
    def statistics_fingerprint(self) -> str:
        return only_research_coverage_summary_fingerprint(
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
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchCoverageSummaryPlan:
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
            raise ValueError("Coverage Summary Plan fields are invalid")
        subject = payload["subject"]
        definition = payload["definition"]
        if not isinstance(subject, Mapping) or any(not isinstance(key, str) for key in subject):
            raise ValueError("Coverage Summary Plan subject must be an object")
        if not isinstance(definition, Mapping) or any(not isinstance(key, str) for key in definition):
            raise ValueError("Coverage Summary Plan definition must be an object")
        return cls(
            _string(payload, "dataset_snapshot_fingerprint"),
            _string(payload, "subject_candidate_fingerprint"),
            OnlyResearchFeatureSeriesReference.from_dict(subject),
            _string(payload, "source_statistics_fingerprint"),
            _string(payload, "source_statistics_result_fingerprint"),
            OnlyResearchCoverageSummaryDefinition.from_dict(definition),
            _integer(payload, "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchTemporalStabilityPlan:
    dataset_snapshot_fingerprint: str
    subject_candidate_fingerprint: str
    subject: OnlyResearchFeatureSeriesReference
    source_statistics_fingerprint: str
    source_statistics_result_fingerprint: str
    definition: OnlyResearchTemporalStabilityDefinition
    intervals: tuple[OnlyResearchTemporalSlice, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported Temporal Stability Plan schema version")
        for name in (
            "dataset_snapshot_fingerprint",
            "subject_candidate_fingerprint",
            "source_statistics_fingerprint",
            "source_statistics_result_fingerprint",
        ):
            if _SHA256.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"Temporal Stability Plan {name} must be a lower-case SHA256")
        if not isinstance(self.subject, OnlyResearchFeatureSeriesReference):
            raise ValueError("Temporal Stability Plan subject is invalid")
        if not isinstance(self.definition, OnlyResearchTemporalStabilityDefinition):
            raise ValueError("Temporal Stability Plan definition is invalid")
        if not isinstance(self.intervals, tuple) or not self.intervals:
            raise ValueError("Temporal Stability Plan intervals must be a non-empty tuple")
        if any(not isinstance(interval, OnlyResearchTemporalSlice) for interval in self.intervals):
            raise ValueError("Temporal Stability Plan interval is invalid")
        for previous, current in zip(self.intervals, self.intervals[1:], strict=False):
            if current.start_ts_event_ns < previous.end_ts_event_ns:
                raise ValueError("Temporal Stability Plan intervals must be ordered and non-overlapping")

    @property
    def statistics_fingerprint(self) -> str:
        return only_research_temporal_stability_fingerprint(
            self.dataset_snapshot_fingerprint,
            self.subject_candidate_fingerprint,
            self.subject,
            self.source_statistics_fingerprint,
            self.definition,
            self.intervals,
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
            "intervals": [interval.to_dict() for interval in self.intervals],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchTemporalStabilityPlan:
        expected = {
            "schema_version",
            "dataset_snapshot_fingerprint",
            "subject_candidate_fingerprint",
            "subject",
            "source_statistics_fingerprint",
            "source_statistics_result_fingerprint",
            "definition",
            "intervals",
        }
        if set(payload) != expected:
            raise ValueError("Temporal Stability Plan fields are invalid")
        subject = payload["subject"]
        definition = payload["definition"]
        intervals = payload["intervals"]
        if not isinstance(subject, Mapping) or any(not isinstance(key, str) for key in subject):
            raise ValueError("Temporal Stability Plan subject must be an object")
        if not isinstance(definition, Mapping) or any(not isinstance(key, str) for key in definition):
            raise ValueError("Temporal Stability Plan definition must be an object")
        if not isinstance(intervals, list) or any(
            not isinstance(item, Mapping) or any(not isinstance(key, str) for key in item) for item in intervals
        ):
            raise ValueError("Temporal Stability Plan intervals must be an array of objects")
        return cls(
            _string(payload, "dataset_snapshot_fingerprint"),
            _string(payload, "subject_candidate_fingerprint"),
            OnlyResearchFeatureSeriesReference.from_dict(subject),
            _string(payload, "source_statistics_fingerprint"),
            _string(payload, "source_statistics_result_fingerprint"),
            OnlyResearchTemporalStabilityDefinition.from_dict(definition),
            tuple(OnlyResearchTemporalSlice.from_dict(item) for item in intervals),
            _integer(payload, "schema_version"),
        )


OnlyResearchSummaryPlan = (
    OnlyResearchEffectSummaryPlan | OnlyResearchCoverageSummaryPlan | OnlyResearchTemporalStabilityPlan
)


def only_research_summary_plan_from_dict(payload: Mapping[str, object]) -> OnlyResearchSummaryPlan:
    definition = payload.get("definition")
    if not isinstance(definition, Mapping) or any(not isinstance(key, str) for key in definition):
        raise ValueError("Summary Statistics Plan definition must be an object")
    raw_kind = definition.get("summary_kind")
    if not isinstance(raw_kind, str):
        raise ValueError("Summary Statistics Plan kind must be a string")
    try:
        kind = OnlyResearchSummaryKind(raw_kind)
    except ValueError as exc:
        raise ValueError("Summary Statistics Plan kind is unsupported") from exc
    if kind is OnlyResearchSummaryKind.EFFECT_SUMMARY:
        return OnlyResearchEffectSummaryPlan.from_dict(payload)
    if kind is OnlyResearchSummaryKind.COVERAGE_SUMMARY:
        return OnlyResearchCoverageSummaryPlan.from_dict(payload)
    if kind is OnlyResearchSummaryKind.TEMPORAL_STABILITY:
        return OnlyResearchTemporalStabilityPlan.from_dict(payload)
    raise ValueError("Summary Statistics Plan kind is unsupported")  # pragma: no cover


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


__all__ = [
    "OnlyResearchCoverageSummaryPlan",
    "OnlyResearchEffectSummaryPlan",
    "OnlyResearchSummaryPlan",
    "OnlyResearchTemporalStabilityPlan",
    "only_research_summary_plan_from_dict",
]
