"""Canonical append-only metric vocabulary for typed Research summaries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from ..definition import OnlyResearchStatisticsMethod


class OnlyResearchSummaryKind(StrEnum):
    EFFECT_SUMMARY = "EFFECT_SUMMARY"
    COVERAGE_SUMMARY = "COVERAGE_SUMMARY"
    TEMPORAL_STABILITY = "TEMPORAL_STABILITY"


class OnlyResearchSummaryValueKind(StrEnum):
    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL"


@dataclass(frozen=True, slots=True)
class OnlyResearchSummaryMetricDescriptor:
    metric_id: str
    semantic_version: int
    summary_kind: OnlyResearchSummaryKind
    source_method: OnlyResearchStatisticsMethod
    field_name: str
    value_kind: OnlyResearchSummaryValueKind

    def __post_init__(self) -> None:
        if not self.metric_id.endswith(f"@{self.semantic_version}"):
            raise ValueError("Summary metric semantic version is invalid")
        if not isinstance(self.summary_kind, OnlyResearchSummaryKind):
            raise ValueError("Summary metric result discriminant is invalid")
        if not isinstance(self.source_method, OnlyResearchStatisticsMethod):
            raise ValueError("Summary metric source method is invalid")
        if not self.field_name or any(char.isspace() for char in self.field_name):
            raise ValueError("Summary metric field name is invalid")
        if not isinstance(self.value_kind, OnlyResearchSummaryValueKind):
            raise ValueError("Summary metric value kind is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "metric_id": self.metric_id,
            "semantic_version": self.semantic_version,
            "summary_kind": self.summary_kind.value,
            "source_method": self.source_method.value,
            "field_name": self.field_name,
            "value_kind": self.value_kind.value,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchSummaryMetricDescriptor:
        expected = {
            "metric_id",
            "semantic_version",
            "summary_kind",
            "source_method",
            "field_name",
            "value_kind",
        }
        if set(payload) != expected:
            raise ValueError("Summary metric descriptor fields are invalid")
        version = payload["semantic_version"]
        if isinstance(version, bool) or not isinstance(version, int):
            raise ValueError("Summary metric semantic_version must be an integer")
        return cls(
            _string(payload, "metric_id"),
            version,
            OnlyResearchSummaryKind(_string(payload, "summary_kind")),
            OnlyResearchStatisticsMethod(_string(payload, "source_method")),
            _string(payload, "field_name"),
            OnlyResearchSummaryValueKind(_string(payload, "value_kind")),
        )


_EFFECT_INTEGER_FIELDS = (
    "total_count",
    "valid_count",
    "insufficient_observations_count",
    "zero_variance_feature_count",
    "zero_variance_target_count",
    "positive_count",
    "negative_count",
    "zero_count",
)
_EFFECT_DECIMAL_FIELDS = (
    "mean",
    "stddev_sample",
    "information_ratio",
    "positive_ratio",
    "negative_ratio",
    "zero_ratio",
)
_METRIC_SUFFIX = MappingProxyType({"information_ratio": "ir"})
_COVERAGE_INTEGER_FIELDS = (
    "total_timestamp_count",
    "valid_timestamp_count",
    "insufficient_timestamp_count",
    "zero_variance_feature_count",
    "zero_variance_target_count",
    "pair_count_total",
    "pair_count_min",
    "pair_count_max",
)
_COVERAGE_DECIMAL_FIELDS = ("valid_timestamp_ratio", "pair_count_mean")
_STABILITY_INTEGER_FIELDS = (
    "slice_count",
    "valid_slice_count",
    "positive_mean_slice_count",
    "negative_mean_slice_count",
    "zero_mean_slice_count",
)
_STABILITY_DECIMAL_FIELDS = (
    "positive_mean_slice_ratio",
    "negative_mean_slice_ratio",
    "zero_mean_slice_ratio",
    "min_slice_mean",
    "max_slice_mean",
    "stddev_of_slice_means",
)


def _descriptors() -> tuple[OnlyResearchSummaryMetricDescriptor, ...]:
    result: list[OnlyResearchSummaryMetricDescriptor] = []
    for method, prefix in (
        (OnlyResearchStatisticsMethod.IC, "research.factor.ic"),
        (OnlyResearchStatisticsMethod.RANK_IC, "research.factor.rank_ic"),
    ):
        for field_name, value_kind in (
            *((name, OnlyResearchSummaryValueKind.INTEGER) for name in _EFFECT_INTEGER_FIELDS),
            *((name, OnlyResearchSummaryValueKind.DECIMAL) for name in _EFFECT_DECIMAL_FIELDS),
        ):
            suffix = _METRIC_SUFFIX.get(field_name, field_name)
            result.append(
                OnlyResearchSummaryMetricDescriptor(
                    f"{prefix}.{suffix}@1",
                    1,
                    OnlyResearchSummaryKind.EFFECT_SUMMARY,
                    method,
                    field_name,
                    value_kind,
                )
            )
        for field_name, value_kind in (
            *((name, OnlyResearchSummaryValueKind.INTEGER) for name in _STABILITY_INTEGER_FIELDS),
            *((name, OnlyResearchSummaryValueKind.DECIMAL) for name in _STABILITY_DECIMAL_FIELDS),
        ):
            result.append(
                OnlyResearchSummaryMetricDescriptor(
                    f"{prefix}.stability.{field_name}@1",
                    1,
                    OnlyResearchSummaryKind.TEMPORAL_STABILITY,
                    method,
                    field_name,
                    value_kind,
                )
            )
        for field_name, value_kind in (
            *((name, OnlyResearchSummaryValueKind.INTEGER) for name in _COVERAGE_INTEGER_FIELDS),
            *((name, OnlyResearchSummaryValueKind.DECIMAL) for name in _COVERAGE_DECIMAL_FIELDS),
        ):
            result.append(
                OnlyResearchSummaryMetricDescriptor(
                    f"{prefix}.coverage.{field_name}@1",
                    1,
                    OnlyResearchSummaryKind.COVERAGE_SUMMARY,
                    method,
                    field_name,
                    value_kind,
                )
            )
    return tuple(sorted(result, key=lambda descriptor: descriptor.metric_id))


ONLY_RESEARCH_SUMMARY_METRICS = _descriptors()
_REGISTRY = MappingProxyType({descriptor.metric_id: descriptor for descriptor in ONLY_RESEARCH_SUMMARY_METRICS})
if len(_REGISTRY) != len(ONLY_RESEARCH_SUMMARY_METRICS):  # pragma: no cover - import-time invariant
    raise RuntimeError("duplicate Research Summary metric id")


def only_research_summary_metric(metric_id: str) -> OnlyResearchSummaryMetricDescriptor:
    try:
        return _REGISTRY[metric_id]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"unsupported Research Summary metric: {metric_id!r}") from exc


def only_research_effect_metric(
    source_method: OnlyResearchStatisticsMethod,
    field_name: str,
) -> OnlyResearchSummaryMetricDescriptor:
    matches = tuple(
        descriptor
        for descriptor in ONLY_RESEARCH_SUMMARY_METRICS
        if descriptor.summary_kind is OnlyResearchSummaryKind.EFFECT_SUMMARY
        and descriptor.source_method is source_method
        and descriptor.field_name == field_name
    )
    if len(matches) != 1:
        raise ValueError("unsupported Effect Summary metric field")
    return matches[0]


def only_research_coverage_metric(
    source_method: OnlyResearchStatisticsMethod,
    field_name: str,
) -> OnlyResearchSummaryMetricDescriptor:
    matches = tuple(
        descriptor
        for descriptor in ONLY_RESEARCH_SUMMARY_METRICS
        if descriptor.summary_kind is OnlyResearchSummaryKind.COVERAGE_SUMMARY
        and descriptor.source_method is source_method
        and descriptor.field_name == field_name
    )
    if len(matches) != 1:
        raise ValueError("unsupported Coverage Summary metric field")
    return matches[0]


def only_research_stability_metric(
    source_method: OnlyResearchStatisticsMethod,
    field_name: str,
) -> OnlyResearchSummaryMetricDescriptor:
    matches = tuple(
        descriptor
        for descriptor in ONLY_RESEARCH_SUMMARY_METRICS
        if descriptor.summary_kind is OnlyResearchSummaryKind.TEMPORAL_STABILITY
        and descriptor.source_method is source_method
        and descriptor.field_name == field_name
    )
    if len(matches) != 1:
        raise ValueError("unsupported Temporal Stability metric field")
    return matches[0]


def _string(payload: Mapping[str, object], name: str) -> str:
    value = payload[name]
    if not isinstance(value, str):
        raise ValueError(f"Summary metric {name} must be a string")
    return value


__all__ = [
    "ONLY_RESEARCH_SUMMARY_METRICS",
    "OnlyResearchSummaryKind",
    "OnlyResearchSummaryMetricDescriptor",
    "OnlyResearchSummaryValueKind",
    "only_research_coverage_metric",
    "only_research_effect_metric",
    "only_research_stability_metric",
    "only_research_summary_metric",
]
