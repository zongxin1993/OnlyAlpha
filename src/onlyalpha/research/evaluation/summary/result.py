"""Immutable fixed-shape Effect Summary result contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import datetime, timedelta

from ..definition import OnlyResearchStatisticsMethod
from .identity import (
    RESEARCH_SUMMARY_STATISTICS_DOMAIN,
    RESEARCH_SUMMARY_STATISTICS_RESULT_SCHEMA_VERSION,
    only_research_summary_result_fingerprint,
)
from .metric import OnlyResearchSummaryKind, only_research_effect_metric
from .plan import OnlyResearchEffectSummaryPlan
from .scalar import OnlyResearchSummaryScalar, OnlyResearchSummaryScalarStatus

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EFFECT_FIELDS = (
    "total_count",
    "valid_count",
    "insufficient_observations_count",
    "zero_variance_feature_count",
    "zero_variance_target_count",
    "mean",
    "stddev_sample",
    "information_ratio",
    "positive_count",
    "negative_count",
    "zero_count",
    "positive_ratio",
    "negative_ratio",
    "zero_ratio",
)


@dataclass(frozen=True, slots=True)
class OnlyResearchEffectSummary:
    source_method: OnlyResearchStatisticsMethod
    total_count: OnlyResearchSummaryScalar
    valid_count: OnlyResearchSummaryScalar
    insufficient_observations_count: OnlyResearchSummaryScalar
    zero_variance_feature_count: OnlyResearchSummaryScalar
    zero_variance_target_count: OnlyResearchSummaryScalar
    mean: OnlyResearchSummaryScalar
    stddev_sample: OnlyResearchSummaryScalar
    information_ratio: OnlyResearchSummaryScalar
    positive_count: OnlyResearchSummaryScalar
    negative_count: OnlyResearchSummaryScalar
    zero_count: OnlyResearchSummaryScalar
    positive_ratio: OnlyResearchSummaryScalar
    negative_ratio: OnlyResearchSummaryScalar
    zero_ratio: OnlyResearchSummaryScalar
    summary_kind: OnlyResearchSummaryKind = OnlyResearchSummaryKind.EFFECT_SUMMARY
    schema_version: int = RESEARCH_SUMMARY_STATISTICS_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RESEARCH_SUMMARY_STATISTICS_RESULT_SCHEMA_VERSION:
            raise ValueError("Effect Summary result schema is unsupported")
        if self.summary_kind is not OnlyResearchSummaryKind.EFFECT_SUMMARY:
            raise ValueError("Effect Summary result kind is invalid")
        if not isinstance(self.source_method, OnlyResearchStatisticsMethod) or self.source_method not in {
            OnlyResearchStatisticsMethod.IC,
            OnlyResearchStatisticsMethod.RANK_IC,
        }:
            raise ValueError("Effect Summary result source method is invalid")
        for name in _EFFECT_FIELDS:
            scalar = getattr(self, name)
            if not isinstance(scalar, OnlyResearchSummaryScalar):
                raise ValueError(f"Effect Summary {name} scalar is invalid")
            descriptor = only_research_effect_metric(self.source_method, name)
            if scalar.metric_id != descriptor.metric_id or scalar.value_kind is not descriptor.value_kind:
                raise ValueError(f"Effect Summary {name} metric linkage mismatch")
        self._validate_effect_invariants()

    def _validate_effect_invariants(self) -> None:
        count_fields = (
            "total_count",
            "valid_count",
            "insufficient_observations_count",
            "zero_variance_feature_count",
            "zero_variance_target_count",
            "positive_count",
            "negative_count",
            "zero_count",
        )
        if any(getattr(self, name).status is not OnlyResearchSummaryScalarStatus.VALID for name in count_fields):
            raise ValueError("Effect Summary count scalars must be VALID")
        counts = {name: getattr(self, name).integer_value for name in count_fields}
        if any(value is None for value in counts.values()):  # pragma: no cover - scalar invariant
            raise ValueError("Effect Summary count scalar is absent")
        total = _required_count(counts, "total_count")
        valid = _required_count(counts, "valid_count")
        if total != valid + sum(
            _required_count(counts, name)
            for name in (
                "insufficient_observations_count",
                "zero_variance_feature_count",
                "zero_variance_target_count",
            )
        ):
            raise ValueError("Effect Summary source status counts are inconsistent")
        if valid != sum(_required_count(counts, name) for name in ("positive_count", "negative_count", "zero_count")):
            raise ValueError("Effect Summary sign counts are inconsistent")
        expected_value_status = (
            OnlyResearchSummaryScalarStatus.VALID if valid else OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS
        )
        if any(
            getattr(self, name).status is not expected_value_status
            for name in ("mean", "positive_ratio", "negative_ratio", "zero_ratio")
        ):
            raise ValueError("Effect Summary mean/ratio statuses are inconsistent")
        if valid < 2:
            if self.stddev_sample.status is not OnlyResearchSummaryScalarStatus.INSUFFICIENT_OBSERVATIONS:
                raise ValueError("Effect Summary standard deviation status is inconsistent")
            if self.information_ratio.status is not OnlyResearchSummaryScalarStatus.INSUFFICIENT_OBSERVATIONS:
                raise ValueError("Effect Summary information ratio status is inconsistent")
        else:
            if self.stddev_sample.status is not OnlyResearchSummaryScalarStatus.VALID:
                raise ValueError("Effect Summary standard deviation must be VALID")
            if self.information_ratio.status not in {
                OnlyResearchSummaryScalarStatus.VALID,
                OnlyResearchSummaryScalarStatus.ZERO_VARIANCE,
            }:
                raise ValueError("Effect Summary information ratio status is inconsistent")
            if (
                self.information_ratio.status is OnlyResearchSummaryScalarStatus.ZERO_VARIANCE
                and self.stddev_sample.decimal_value != 0
            ):
                raise ValueError("Effect Summary ZERO_VARIANCE requires published zero standard deviation")
            if (
                self.stddev_sample.decimal_value != 0
                and self.information_ratio.status is not OnlyResearchSummaryScalarStatus.VALID
            ):
                raise ValueError("Effect Summary nonzero standard deviation requires VALID information ratio")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "summary_kind": self.summary_kind.value,
            "source_method": self.source_method.value,
            **{name: getattr(self, name).to_dict() for name in _EFFECT_FIELDS},
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchEffectSummary:
        if set(payload) != {"schema_version", "summary_kind", "source_method", *_EFFECT_FIELDS}:
            raise ValueError("Effect Summary result fields are invalid")
        scalars: dict[str, OnlyResearchSummaryScalar] = {}
        for name in _EFFECT_FIELDS:
            value = payload[name]
            if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
                raise ValueError(f"Effect Summary {name} must be an object")
            scalars[name] = OnlyResearchSummaryScalar.from_dict(value)
        return cls(
            source_method=OnlyResearchStatisticsMethod(_string(payload, "source_method")),
            **scalars,
            summary_kind=OnlyResearchSummaryKind(_string(payload, "summary_kind")),
            schema_version=_integer(payload, "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchSummaryStatisticsResultManifest:
    statistics_fingerprint: str
    plan: OnlyResearchEffectSummaryPlan
    source_statistics_fingerprint: str
    source_statistics_result_fingerprint: str
    dataset_snapshot_fingerprint: str
    result_content_fingerprint: str
    statistics_result_fingerprint: str
    summary_byte_sha256: str
    created_at: datetime
    domain: str = RESEARCH_SUMMARY_STATISTICS_DOMAIN
    schema_version: int = RESEARCH_SUMMARY_STATISTICS_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.domain != RESEARCH_SUMMARY_STATISTICS_DOMAIN:
            raise ValueError("Summary Statistics domain is unsupported")
        if self.schema_version != RESEARCH_SUMMARY_STATISTICS_RESULT_SCHEMA_VERSION:
            raise ValueError("Summary Statistics Result schema is unsupported")
        for name in (
            "statistics_fingerprint",
            "source_statistics_fingerprint",
            "source_statistics_result_fingerprint",
            "dataset_snapshot_fingerprint",
            "result_content_fingerprint",
            "statistics_result_fingerprint",
            "summary_byte_sha256",
        ):
            if _SHA256.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"Summary Statistics {name} must be a lower-case SHA256")
        if not isinstance(self.plan, OnlyResearchEffectSummaryPlan):
            raise ValueError("Summary Statistics Plan is invalid")
        if self.statistics_fingerprint != self.plan.statistics_fingerprint:
            raise ValueError("Summary Statistics logical identity mismatch")
        if self.source_statistics_fingerprint != self.plan.source_statistics_fingerprint:
            raise ValueError("Summary Statistics source logical identity mismatch")
        if self.source_statistics_result_fingerprint != self.plan.source_statistics_result_fingerprint:
            raise ValueError("Summary Statistics source result identity mismatch")
        if self.dataset_snapshot_fingerprint != self.plan.dataset_snapshot_fingerprint:
            raise ValueError("Summary Statistics Dataset identity mismatch")
        if (
            only_research_summary_result_fingerprint(self.statistics_fingerprint, self.result_content_fingerprint)
            != self.statistics_result_fingerprint
        ):
            raise ValueError("Summary Statistics Result identity mismatch")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != timedelta(0):
            raise ValueError("Summary Statistics created_at must be timezone-aware UTC")

    def to_dict(self) -> dict[str, object]:
        return {item.name: _manifest_value(getattr(self, item.name)) for item in fields(self)}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchSummaryStatisticsResultManifest:
        expected = {item.name for item in fields(cls)}
        if set(payload) != expected:
            raise ValueError("Summary Statistics manifest fields are invalid")
        plan = payload["plan"]
        if not isinstance(plan, Mapping) or any(not isinstance(key, str) for key in plan):
            raise ValueError("Summary Statistics manifest plan must be an object")
        return cls(
            statistics_fingerprint=_string(payload, "statistics_fingerprint"),
            plan=OnlyResearchEffectSummaryPlan.from_dict(plan),
            source_statistics_fingerprint=_string(payload, "source_statistics_fingerprint"),
            source_statistics_result_fingerprint=_string(payload, "source_statistics_result_fingerprint"),
            dataset_snapshot_fingerprint=_string(payload, "dataset_snapshot_fingerprint"),
            result_content_fingerprint=_string(payload, "result_content_fingerprint"),
            statistics_result_fingerprint=_string(payload, "statistics_result_fingerprint"),
            summary_byte_sha256=_string(payload, "summary_byte_sha256"),
            created_at=_datetime(payload, "created_at"),
            domain=_string(payload, "domain"),
            schema_version=_integer(payload, "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchSummaryStatisticsResult:
    manifest: OnlyResearchSummaryStatisticsResultManifest
    summary: OnlyResearchEffectSummary


def _manifest_value(value: object) -> object:
    if isinstance(value, OnlyResearchEffectSummaryPlan):
        return value.to_dict()
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _required_count(counts: Mapping[str, int | None], name: str) -> int:
    value = counts[name]
    if value is None:  # pragma: no cover - scalar invariant
        raise ValueError("Effect Summary count scalar is absent")
    return value


def _string(payload: Mapping[str, object], name: str) -> str:
    value = payload[name]
    if not isinstance(value, str):
        raise ValueError(f"Summary Statistics {name} must be a string")
    return value


def _integer(payload: Mapping[str, object], name: str) -> int:
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Summary Statistics {name} must be an integer")
    return value


def _datetime(payload: Mapping[str, object], name: str) -> datetime:
    try:
        value = datetime.fromisoformat(_string(payload, name).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Summary Statistics {name} must be an ISO datetime") from exc
    return value


__all__ = [
    "OnlyResearchEffectSummary",
    "OnlyResearchSummaryStatisticsResult",
    "OnlyResearchSummaryStatisticsResultManifest",
]
