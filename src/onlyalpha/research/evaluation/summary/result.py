"""Immutable fixed-shape typed Summary Statistics result contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import datetime, timedelta
from decimal import Decimal

from ..definition import OnlyResearchStatisticsMethod
from .identity import (
    RESEARCH_SUMMARY_STATISTICS_DOMAIN,
    RESEARCH_SUMMARY_STATISTICS_RESULT_SCHEMA_VERSION,
    only_research_summary_result_fingerprint,
)
from .metric import (
    OnlyResearchSummaryKind,
    only_research_coverage_metric,
    only_research_effect_metric,
    only_research_stability_metric,
)
from .plan import OnlyResearchSummaryPlan, OnlyResearchTemporalStabilityPlan, only_research_summary_plan_from_dict
from .scalar import OnlyResearchSummaryScalar, OnlyResearchSummaryScalarStatus
from .temporal import OnlyResearchTemporalSlice

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
_COVERAGE_FIELDS = (
    "total_timestamp_count",
    "valid_timestamp_count",
    "valid_timestamp_ratio",
    "insufficient_timestamp_count",
    "zero_variance_feature_count",
    "zero_variance_target_count",
    "pair_count_total",
    "pair_count_mean",
    "pair_count_min",
    "pair_count_max",
)
_STABILITY_FIELDS = (
    "slice_count",
    "valid_slice_count",
    "positive_mean_slice_count",
    "negative_mean_slice_count",
    "zero_mean_slice_count",
    "positive_mean_slice_ratio",
    "negative_mean_slice_ratio",
    "zero_mean_slice_ratio",
    "min_slice_mean",
    "max_slice_mean",
    "stddev_of_slice_means",
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
class OnlyResearchCoverageSummary:
    source_method: OnlyResearchStatisticsMethod
    total_timestamp_count: OnlyResearchSummaryScalar
    valid_timestamp_count: OnlyResearchSummaryScalar
    valid_timestamp_ratio: OnlyResearchSummaryScalar
    insufficient_timestamp_count: OnlyResearchSummaryScalar
    zero_variance_feature_count: OnlyResearchSummaryScalar
    zero_variance_target_count: OnlyResearchSummaryScalar
    pair_count_total: OnlyResearchSummaryScalar
    pair_count_mean: OnlyResearchSummaryScalar
    pair_count_min: OnlyResearchSummaryScalar
    pair_count_max: OnlyResearchSummaryScalar
    summary_kind: OnlyResearchSummaryKind = OnlyResearchSummaryKind.COVERAGE_SUMMARY
    schema_version: int = RESEARCH_SUMMARY_STATISTICS_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RESEARCH_SUMMARY_STATISTICS_RESULT_SCHEMA_VERSION:
            raise ValueError("Coverage Summary result schema is unsupported")
        if self.summary_kind is not OnlyResearchSummaryKind.COVERAGE_SUMMARY:
            raise ValueError("Coverage Summary result kind is invalid")
        if not isinstance(self.source_method, OnlyResearchStatisticsMethod) or self.source_method not in {
            OnlyResearchStatisticsMethod.IC,
            OnlyResearchStatisticsMethod.RANK_IC,
        }:
            raise ValueError("Coverage Summary result source method is invalid")
        for name in _COVERAGE_FIELDS:
            scalar = getattr(self, name)
            if not isinstance(scalar, OnlyResearchSummaryScalar):
                raise ValueError(f"Coverage Summary {name} scalar is invalid")
            descriptor = only_research_coverage_metric(self.source_method, name)
            if scalar.metric_id != descriptor.metric_id or scalar.value_kind is not descriptor.value_kind:
                raise ValueError(f"Coverage Summary {name} metric linkage mismatch")
        self._validate_coverage_invariants()

    def _validate_coverage_invariants(self) -> None:
        count_fields = (
            "total_timestamp_count",
            "valid_timestamp_count",
            "insufficient_timestamp_count",
            "zero_variance_feature_count",
            "zero_variance_target_count",
            "pair_count_total",
        )
        if any(getattr(self, name).status is not OnlyResearchSummaryScalarStatus.VALID for name in count_fields):
            raise ValueError("Coverage Summary count scalars must be VALID")
        total = _integer_scalar(self.total_timestamp_count)
        valid = _integer_scalar(self.valid_timestamp_count)
        if total != valid + sum(
            _integer_scalar(getattr(self, name))
            for name in (
                "insufficient_timestamp_count",
                "zero_variance_feature_count",
                "zero_variance_target_count",
            )
        ):
            raise ValueError("Coverage Summary source status counts are inconsistent")
        observed_fields = ("valid_timestamp_ratio", "pair_count_mean", "pair_count_min", "pair_count_max")
        expected = (
            OnlyResearchSummaryScalarStatus.VALID
            if total > 0
            else OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS
        )
        if any(getattr(self, name).status is not expected for name in observed_fields):
            raise ValueError("Coverage Summary observed metric statuses are inconsistent")
        if total > 0:
            ratio = self.valid_timestamp_ratio.decimal_value
            if ratio is None or not Decimal(0) <= ratio <= Decimal(1):
                raise ValueError("Coverage Summary valid timestamp ratio is invalid")
            if _integer_scalar(self.pair_count_min) > _integer_scalar(self.pair_count_max):
                raise ValueError("Coverage Summary pair count bounds are inconsistent")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "summary_kind": self.summary_kind.value,
            "source_method": self.source_method.value,
            **{name: getattr(self, name).to_dict() for name in _COVERAGE_FIELDS},
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchCoverageSummary:
        if set(payload) != {"schema_version", "summary_kind", "source_method", *_COVERAGE_FIELDS}:
            raise ValueError("Coverage Summary result fields are invalid")
        scalars: dict[str, OnlyResearchSummaryScalar] = {}
        for name in _COVERAGE_FIELDS:
            value = payload[name]
            if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
                raise ValueError(f"Coverage Summary {name} must be an object")
            scalars[name] = OnlyResearchSummaryScalar.from_dict(value)
        return cls(
            source_method=OnlyResearchStatisticsMethod(_string(payload, "source_method")),
            **scalars,
            summary_kind=OnlyResearchSummaryKind(_string(payload, "summary_kind")),
            schema_version=_integer(payload, "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchTemporalSliceValue:
    status: OnlyResearchSummaryScalarStatus
    decimal_value: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, OnlyResearchSummaryScalarStatus):
            raise ValueError("Temporal Slice value status is invalid")
        if self.status is OnlyResearchSummaryScalarStatus.VALID:
            if not isinstance(self.decimal_value, Decimal) or not self.decimal_value.is_finite():
                raise ValueError("VALID Temporal Slice value requires a finite Decimal")
            if self.decimal_value.as_tuple().exponent != -12:
                raise ValueError("Temporal Slice Decimal must use canonical quantum 1e-12")
            if self.decimal_value.is_zero() and self.decimal_value.is_signed():
                raise ValueError("Temporal Slice zero must use the canonical positive representation")
        elif self.decimal_value is not None:
            raise ValueError("non-VALID Temporal Slice value requires an absent Decimal")

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "decimal_value": None if self.decimal_value is None else format(self.decimal_value, "f"),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchTemporalSliceValue:
        if set(payload) != {"status", "decimal_value"}:
            raise ValueError("Temporal Slice value fields are invalid")
        raw = payload["decimal_value"]
        if raw is not None and not isinstance(raw, str):
            raise ValueError("Temporal Slice decimal_value is invalid")
        return cls(
            OnlyResearchSummaryScalarStatus(_string(payload, "status")),
            None if raw is None else Decimal(raw),
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchTemporalSliceEvidence:
    start_ts_event_ns: int
    end_ts_event_ns: int
    total_timestamp_count: int
    valid_timestamp_count: int
    mean: OnlyResearchTemporalSliceValue
    stddev_sample: OnlyResearchTemporalSliceValue
    information_ratio: OnlyResearchTemporalSliceValue
    valid_timestamp_ratio: OnlyResearchTemporalSliceValue

    def __post_init__(self) -> None:
        OnlyResearchTemporalSlice(self.start_ts_event_ns, self.end_ts_event_ns)
        for name in ("total_timestamp_count", "valid_timestamp_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"Temporal Slice {name} must be a non-negative integer")
        if self.valid_timestamp_count > self.total_timestamp_count:
            raise ValueError("Temporal Slice valid timestamp count exceeds total")
        for name in ("mean", "stddev_sample", "information_ratio", "valid_timestamp_ratio"):
            if not isinstance(getattr(self, name), OnlyResearchTemporalSliceValue):
                raise ValueError(f"Temporal Slice {name} is invalid")
        valid_count = self.valid_timestamp_count
        mean_status = (
            OnlyResearchSummaryScalarStatus.VALID
            if valid_count
            else OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS
        )
        if self.mean.status is not mean_status:
            raise ValueError("Temporal Slice mean status is inconsistent")
        if valid_count < 2:
            if self.stddev_sample.status is not OnlyResearchSummaryScalarStatus.INSUFFICIENT_OBSERVATIONS:
                raise ValueError("Temporal Slice standard deviation status is inconsistent")
            if self.information_ratio.status is not OnlyResearchSummaryScalarStatus.INSUFFICIENT_OBSERVATIONS:
                raise ValueError("Temporal Slice information ratio status is inconsistent")
        else:
            if self.stddev_sample.status is not OnlyResearchSummaryScalarStatus.VALID:
                raise ValueError("Temporal Slice standard deviation must be VALID")
            if self.information_ratio.status not in {
                OnlyResearchSummaryScalarStatus.VALID,
                OnlyResearchSummaryScalarStatus.ZERO_VARIANCE,
            }:
                raise ValueError("Temporal Slice information ratio status is inconsistent")
            if self.information_ratio.status is OnlyResearchSummaryScalarStatus.ZERO_VARIANCE:
                if self.stddev_sample.decimal_value != 0:
                    raise ValueError("Temporal Slice ZERO_VARIANCE requires published zero standard deviation")
        ratio_status = (
            OnlyResearchSummaryScalarStatus.VALID
            if self.total_timestamp_count
            else OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS
        )
        if self.valid_timestamp_ratio.status is not ratio_status:
            raise ValueError("Temporal Slice valid timestamp ratio status is inconsistent")
        ratio = self.valid_timestamp_ratio.decimal_value
        if ratio is not None and not Decimal(0) <= ratio <= Decimal(1):
            raise ValueError("Temporal Slice valid timestamp ratio is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "start_ts_event_ns": self.start_ts_event_ns,
            "end_ts_event_ns": self.end_ts_event_ns,
            "total_timestamp_count": self.total_timestamp_count,
            "valid_timestamp_count": self.valid_timestamp_count,
            "mean": self.mean.to_dict(),
            "stddev_sample": self.stddev_sample.to_dict(),
            "information_ratio": self.information_ratio.to_dict(),
            "valid_timestamp_ratio": self.valid_timestamp_ratio.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchTemporalSliceEvidence:
        expected = {
            "start_ts_event_ns",
            "end_ts_event_ns",
            "total_timestamp_count",
            "valid_timestamp_count",
            "mean",
            "stddev_sample",
            "information_ratio",
            "valid_timestamp_ratio",
        }
        if set(payload) != expected:
            raise ValueError("Temporal Slice evidence fields are invalid")
        values: dict[str, OnlyResearchTemporalSliceValue] = {}
        for name in ("mean", "stddev_sample", "information_ratio", "valid_timestamp_ratio"):
            value = payload[name]
            if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
                raise ValueError(f"Temporal Slice {name} must be an object")
            values[name] = OnlyResearchTemporalSliceValue.from_dict(value)
        return cls(
            _integer(payload, "start_ts_event_ns"),
            _integer(payload, "end_ts_event_ns"),
            _integer(payload, "total_timestamp_count"),
            _integer(payload, "valid_timestamp_count"),
            **values,
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchTemporalStabilitySummary:
    source_method: OnlyResearchStatisticsMethod
    slices: tuple[OnlyResearchTemporalSliceEvidence, ...]
    slice_count: OnlyResearchSummaryScalar
    valid_slice_count: OnlyResearchSummaryScalar
    positive_mean_slice_count: OnlyResearchSummaryScalar
    negative_mean_slice_count: OnlyResearchSummaryScalar
    zero_mean_slice_count: OnlyResearchSummaryScalar
    positive_mean_slice_ratio: OnlyResearchSummaryScalar
    negative_mean_slice_ratio: OnlyResearchSummaryScalar
    zero_mean_slice_ratio: OnlyResearchSummaryScalar
    min_slice_mean: OnlyResearchSummaryScalar
    max_slice_mean: OnlyResearchSummaryScalar
    stddev_of_slice_means: OnlyResearchSummaryScalar
    summary_kind: OnlyResearchSummaryKind = OnlyResearchSummaryKind.TEMPORAL_STABILITY
    schema_version: int = RESEARCH_SUMMARY_STATISTICS_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RESEARCH_SUMMARY_STATISTICS_RESULT_SCHEMA_VERSION:
            raise ValueError("Temporal Stability result schema is unsupported")
        if self.summary_kind is not OnlyResearchSummaryKind.TEMPORAL_STABILITY:
            raise ValueError("Temporal Stability result kind is invalid")
        if not isinstance(self.source_method, OnlyResearchStatisticsMethod) or self.source_method not in {
            OnlyResearchStatisticsMethod.IC,
            OnlyResearchStatisticsMethod.RANK_IC,
        }:
            raise ValueError("Temporal Stability result source method is invalid")
        if not isinstance(self.slices, tuple) or any(
            not isinstance(item, OnlyResearchTemporalSliceEvidence) for item in self.slices
        ):
            raise ValueError("Temporal Stability slices are invalid")
        for previous, current in zip(self.slices, self.slices[1:], strict=False):
            if current.start_ts_event_ns < previous.end_ts_event_ns:
                raise ValueError("Temporal Stability slices must be ordered and non-overlapping")
        for name in _STABILITY_FIELDS:
            scalar = getattr(self, name)
            if not isinstance(scalar, OnlyResearchSummaryScalar):
                raise ValueError(f"Temporal Stability {name} scalar is invalid")
            descriptor = only_research_stability_metric(self.source_method, name)
            if scalar.metric_id != descriptor.metric_id or scalar.value_kind is not descriptor.value_kind:
                raise ValueError(f"Temporal Stability {name} metric linkage mismatch")
        self._validate_stability_invariants()

    def _validate_stability_invariants(self) -> None:
        count_fields = (
            "slice_count",
            "valid_slice_count",
            "positive_mean_slice_count",
            "negative_mean_slice_count",
            "zero_mean_slice_count",
        )
        if any(getattr(self, name).status is not OnlyResearchSummaryScalarStatus.VALID for name in count_fields):
            raise ValueError("Temporal Stability count scalars must be VALID")
        slice_count = _integer_scalar(self.slice_count)
        valid_count = _integer_scalar(self.valid_slice_count)
        if slice_count != len(self.slices):
            raise ValueError("Temporal Stability slice count is inconsistent")
        if valid_count != sum(item.mean.status is OnlyResearchSummaryScalarStatus.VALID for item in self.slices):
            raise ValueError("Temporal Stability valid slice count is inconsistent")
        if valid_count != sum(
            _integer_scalar(getattr(self, name))
            for name in ("positive_mean_slice_count", "negative_mean_slice_count", "zero_mean_slice_count")
        ):
            raise ValueError("Temporal Stability sign counts are inconsistent")
        aggregate_fields = (
            "positive_mean_slice_ratio",
            "negative_mean_slice_ratio",
            "zero_mean_slice_ratio",
            "min_slice_mean",
            "max_slice_mean",
        )
        aggregate_status = (
            OnlyResearchSummaryScalarStatus.VALID
            if valid_count
            else OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS
        )
        if any(getattr(self, name).status is not aggregate_status for name in aggregate_fields):
            raise ValueError("Temporal Stability aggregate statuses are inconsistent")
        stddev_status = (
            OnlyResearchSummaryScalarStatus.VALID
            if valid_count >= 2
            else OnlyResearchSummaryScalarStatus.INSUFFICIENT_OBSERVATIONS
        )
        if self.stddev_of_slice_means.status is not stddev_status:
            raise ValueError("Temporal Stability cross-slice standard deviation status is inconsistent")
        if valid_count:
            minimum = self.min_slice_mean.decimal_value
            maximum = self.max_slice_mean.decimal_value
            if minimum is None or maximum is None or minimum > maximum:
                raise ValueError("Temporal Stability slice mean bounds are inconsistent")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "summary_kind": self.summary_kind.value,
            "source_method": self.source_method.value,
            "slices": [item.to_dict() for item in self.slices],
            **{name: getattr(self, name).to_dict() for name in _STABILITY_FIELDS},
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchTemporalStabilitySummary:
        if set(payload) != {"schema_version", "summary_kind", "source_method", "slices", *_STABILITY_FIELDS}:
            raise ValueError("Temporal Stability result fields are invalid")
        slices = payload["slices"]
        if not isinstance(slices, list) or any(
            not isinstance(item, Mapping) or any(not isinstance(key, str) for key in item) for item in slices
        ):
            raise ValueError("Temporal Stability slices must be an array of objects")
        scalars: dict[str, OnlyResearchSummaryScalar] = {}
        for name in _STABILITY_FIELDS:
            value = payload[name]
            if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
                raise ValueError(f"Temporal Stability {name} must be an object")
            scalars[name] = OnlyResearchSummaryScalar.from_dict(value)
        return cls(
            source_method=OnlyResearchStatisticsMethod(_string(payload, "source_method")),
            slices=tuple(OnlyResearchTemporalSliceEvidence.from_dict(item) for item in slices),
            **scalars,
            summary_kind=OnlyResearchSummaryKind(_string(payload, "summary_kind")),
            schema_version=_integer(payload, "schema_version"),
        )


OnlyResearchSummary = OnlyResearchEffectSummary | OnlyResearchCoverageSummary | OnlyResearchTemporalStabilitySummary


def only_research_summary_from_dict(payload: Mapping[str, object]) -> OnlyResearchSummary:
    raw_kind = payload.get("summary_kind")
    if not isinstance(raw_kind, str):
        raise ValueError("Summary Statistics payload kind must be a string")
    try:
        kind = OnlyResearchSummaryKind(raw_kind)
    except ValueError as exc:
        raise ValueError("Summary Statistics payload kind is unsupported") from exc
    if kind is OnlyResearchSummaryKind.EFFECT_SUMMARY:
        return OnlyResearchEffectSummary.from_dict(payload)
    if kind is OnlyResearchSummaryKind.COVERAGE_SUMMARY:
        return OnlyResearchCoverageSummary.from_dict(payload)
    if kind is OnlyResearchSummaryKind.TEMPORAL_STABILITY:
        return OnlyResearchTemporalStabilitySummary.from_dict(payload)
    raise ValueError("Summary Statistics payload kind is unsupported")  # pragma: no cover


@dataclass(frozen=True, slots=True)
class OnlyResearchSummaryStatisticsResultManifest:
    statistics_fingerprint: str
    plan: OnlyResearchSummaryPlan
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
        from .plan import OnlyResearchCoverageSummaryPlan, OnlyResearchEffectSummaryPlan

        if not isinstance(
            self.plan,
            (OnlyResearchEffectSummaryPlan, OnlyResearchCoverageSummaryPlan, OnlyResearchTemporalStabilityPlan),
        ):
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
            plan=only_research_summary_plan_from_dict(plan),
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
    summary: OnlyResearchSummary

    def __post_init__(self) -> None:
        if self.manifest.plan.definition.summary_kind is not self.summary.summary_kind:
            raise ValueError("Summary Statistics Plan/payload kind mismatch")
        if isinstance(self.manifest.plan, OnlyResearchTemporalStabilityPlan):
            if not isinstance(self.summary, OnlyResearchTemporalStabilitySummary):
                raise ValueError("Temporal Stability Plan requires a Temporal Stability payload")
            actual = tuple(
                OnlyResearchTemporalSlice(item.start_ts_event_ns, item.end_ts_event_ns) for item in self.summary.slices
            )
            if actual != self.manifest.plan.intervals:
                raise ValueError("Temporal Stability Result intervals do not match Plan")


def _manifest_value(value: object) -> object:
    from .plan import OnlyResearchCoverageSummaryPlan, OnlyResearchEffectSummaryPlan

    if isinstance(
        value, (OnlyResearchEffectSummaryPlan, OnlyResearchCoverageSummaryPlan, OnlyResearchTemporalStabilityPlan)
    ):
        return value.to_dict()
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _required_count(counts: Mapping[str, int | None], name: str) -> int:
    value = counts[name]
    if value is None:  # pragma: no cover - scalar invariant
        raise ValueError("Effect Summary count scalar is absent")
    return value


def _integer_scalar(scalar: OnlyResearchSummaryScalar) -> int:
    if scalar.integer_value is None:  # pragma: no cover - scalar invariant
        raise ValueError("Summary count scalar is absent")
    return scalar.integer_value


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
    "OnlyResearchCoverageSummary",
    "OnlyResearchEffectSummary",
    "OnlyResearchSummary",
    "OnlyResearchSummaryStatisticsResult",
    "OnlyResearchSummaryStatisticsResultManifest",
    "OnlyResearchTemporalSliceEvidence",
    "OnlyResearchTemporalSliceValue",
    "OnlyResearchTemporalStabilitySummary",
    "only_research_summary_from_dict",
]
