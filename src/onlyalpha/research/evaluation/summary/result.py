"""Immutable fixed-shape typed Summary Statistics result contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import datetime, timedelta
from decimal import Decimal, localcontext

from onlyalpha.calculation import OnlyNumericDefinition, only_decimal_context

from ..definition import OnlyResearchStatisticsMethod
from ..factor_pair.definition import OnlyResearchFactorPairStatisticsMethod
from .identity import (
    RESEARCH_SUMMARY_STATISTICS_DOMAIN,
    RESEARCH_SUMMARY_STATISTICS_RESULT_SCHEMA_VERSION,
    only_research_summary_result_fingerprint,
)
from .metric import (
    OnlyResearchSummaryKind,
    only_research_coverage_metric,
    only_research_effect_metric,
    only_research_factor_pair_effect_metric,
    only_research_parameter_neighborhood_metric,
    only_research_stability_metric,
)
from .plan import (
    OnlyResearchCoverageSummaryPlan,
    OnlyResearchEffectSummaryPlan,
    OnlyResearchFactorPairEffectSummaryPlan,
    OnlyResearchParameterNeighborhoodSummaryPlan,
    OnlyResearchTemporalStabilityPlan,
    only_research_summary_plan_from_dict,
)
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
_FACTOR_PAIR_EFFECT_FIELDS = ("mean", "stddev_sample")
_SingleSourceSummaryPlan = (
    OnlyResearchEffectSummaryPlan
    | OnlyResearchCoverageSummaryPlan
    | OnlyResearchTemporalStabilityPlan
    | OnlyResearchFactorPairEffectSummaryPlan
)
_NEIGHBORHOOD_FIELDS = (
    "focal_value",
    "neighbor_count",
    "valid_neighbor_count",
    "neighbor_no_valid_observations_count",
    "neighbor_mean",
    "neighbor_min",
    "neighbor_max",
    "neighbor_stddev_sample",
    "local_range",
    "focal_minus_neighbor_mean",
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


@dataclass(frozen=True, slots=True)
class OnlyResearchFactorPairEffectSummary:
    source_method: OnlyResearchFactorPairStatisticsMethod
    mean: OnlyResearchSummaryScalar
    stddev_sample: OnlyResearchSummaryScalar
    summary_kind: OnlyResearchSummaryKind = OnlyResearchSummaryKind.FACTOR_PAIR_EFFECT_SUMMARY
    schema_version: int = RESEARCH_SUMMARY_STATISTICS_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RESEARCH_SUMMARY_STATISTICS_RESULT_SCHEMA_VERSION:
            raise ValueError("Factor-Pair Effect Summary result schema is unsupported")
        if self.summary_kind is not OnlyResearchSummaryKind.FACTOR_PAIR_EFFECT_SUMMARY:
            raise ValueError("Factor-Pair Effect Summary result kind is invalid")
        if not isinstance(self.source_method, OnlyResearchFactorPairStatisticsMethod):
            raise ValueError("Factor-Pair Effect Summary source method is invalid")
        for name in _FACTOR_PAIR_EFFECT_FIELDS:
            scalar = getattr(self, name)
            if not isinstance(scalar, OnlyResearchSummaryScalar):
                raise ValueError(f"Factor-Pair Effect Summary {name} scalar is invalid")
            descriptor = only_research_factor_pair_effect_metric(self.source_method, name)
            if scalar.metric_id != descriptor.metric_id or scalar.value_kind is not descriptor.value_kind:
                raise ValueError(f"Factor-Pair Effect Summary {name} metric linkage mismatch")
        if self.mean.status not in {
            OnlyResearchSummaryScalarStatus.VALID,
            OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS,
        }:
            raise ValueError("Factor-Pair Effect Summary mean status is invalid")
        if self.stddev_sample.status not in {
            OnlyResearchSummaryScalarStatus.VALID,
            OnlyResearchSummaryScalarStatus.INSUFFICIENT_OBSERVATIONS,
        }:
            raise ValueError("Factor-Pair Effect Summary standard deviation status is invalid")
        if self.mean.status is OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS and (
            self.stddev_sample.status is not OnlyResearchSummaryScalarStatus.INSUFFICIENT_OBSERVATIONS
        ):
            raise ValueError("Factor-Pair Effect Summary statuses are inconsistent")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "summary_kind": self.summary_kind.value,
            "source_method": self.source_method.value,
            "mean": self.mean.to_dict(),
            "stddev_sample": self.stddev_sample.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchFactorPairEffectSummary:
        if set(payload) != {"schema_version", "summary_kind", "source_method", *_FACTOR_PAIR_EFFECT_FIELDS}:
            raise ValueError("Factor-Pair Effect Summary result fields are invalid")
        scalars: dict[str, OnlyResearchSummaryScalar] = {}
        for name in _FACTOR_PAIR_EFFECT_FIELDS:
            value = payload[name]
            if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
                raise ValueError(f"Factor-Pair Effect Summary {name} must be an object")
            scalars[name] = OnlyResearchSummaryScalar.from_dict(value)
        return cls(
            source_method=OnlyResearchFactorPairStatisticsMethod(_string(payload, "source_method")),
            **scalars,
            summary_kind=OnlyResearchSummaryKind(_string(payload, "summary_kind")),
            schema_version=_integer(payload, "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchParameterNeighborhoodSummary:
    source_metric_id: str
    focal_value: OnlyResearchSummaryScalar
    neighbor_count: OnlyResearchSummaryScalar
    valid_neighbor_count: OnlyResearchSummaryScalar
    neighbor_no_valid_observations_count: OnlyResearchSummaryScalar
    neighbor_mean: OnlyResearchSummaryScalar
    neighbor_min: OnlyResearchSummaryScalar
    neighbor_max: OnlyResearchSummaryScalar
    neighbor_stddev_sample: OnlyResearchSummaryScalar
    local_range: OnlyResearchSummaryScalar
    focal_minus_neighbor_mean: OnlyResearchSummaryScalar
    summary_kind: OnlyResearchSummaryKind = OnlyResearchSummaryKind.PARAMETER_NEIGHBORHOOD_SUMMARY
    schema_version: int = RESEARCH_SUMMARY_STATISTICS_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RESEARCH_SUMMARY_STATISTICS_RESULT_SCHEMA_VERSION:
            raise ValueError("Parameter Neighborhood Summary result schema is unsupported")
        if self.summary_kind is not OnlyResearchSummaryKind.PARAMETER_NEIGHBORHOOD_SUMMARY:
            raise ValueError("Parameter Neighborhood Summary result kind is invalid")
        source_method = _neighborhood_source_method(self.source_metric_id)
        for name in _NEIGHBORHOOD_FIELDS:
            scalar = getattr(self, name)
            if not isinstance(scalar, OnlyResearchSummaryScalar):
                raise ValueError(f"Parameter Neighborhood Summary {name} scalar is invalid")
            descriptor = only_research_parameter_neighborhood_metric(source_method, name)
            if scalar.metric_id != descriptor.metric_id or scalar.value_kind is not descriptor.value_kind:
                raise ValueError(f"Parameter Neighborhood Summary {name} metric linkage mismatch")
        self._validate_invariants()

    def _validate_invariants(self) -> None:
        count_fields = (
            "neighbor_count",
            "valid_neighbor_count",
            "neighbor_no_valid_observations_count",
        )
        if any(getattr(self, name).status is not OnlyResearchSummaryScalarStatus.VALID for name in count_fields):
            raise ValueError("Parameter Neighborhood Summary count scalars must be VALID")
        total = _integer_scalar(self.neighbor_count)
        valid_count = _integer_scalar(self.valid_neighbor_count)
        invalid_count = _integer_scalar(self.neighbor_no_valid_observations_count)
        if total != valid_count + invalid_count:
            raise ValueError("Parameter Neighborhood Summary neighbor counts are inconsistent")
        aggregate_status = (
            OnlyResearchSummaryScalarStatus.VALID
            if valid_count
            else OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS
        )
        if any(
            getattr(self, name).status is not aggregate_status
            for name in ("neighbor_mean", "neighbor_min", "neighbor_max", "local_range")
        ):
            raise ValueError("Parameter Neighborhood Summary aggregate statuses are inconsistent")
        stddev_status = (
            OnlyResearchSummaryScalarStatus.VALID
            if valid_count >= 2
            else OnlyResearchSummaryScalarStatus.INSUFFICIENT_OBSERVATIONS
        )
        if self.neighbor_stddev_sample.status is not stddev_status:
            raise ValueError("Parameter Neighborhood Summary standard deviation status is inconsistent")
        if self.focal_value.status not in {
            OnlyResearchSummaryScalarStatus.VALID,
            OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS,
        }:
            raise ValueError("Parameter Neighborhood Summary focal status is invalid")
        difference_status = (
            OnlyResearchSummaryScalarStatus.VALID
            if self.focal_value.status is OnlyResearchSummaryScalarStatus.VALID and valid_count
            else OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS
        )
        if self.focal_minus_neighbor_mean.status is not difference_status:
            raise ValueError("Parameter Neighborhood Summary focal-minus-mean status is inconsistent")
        if valid_count:
            minimum = self.neighbor_min.decimal_value
            maximum = self.neighbor_max.decimal_value
            neighbor_mean = self.neighbor_mean.decimal_value
            local_range = self.local_range.decimal_value
            if minimum is None or maximum is None or neighbor_mean is None or local_range is None or minimum > maximum:
                raise ValueError("Parameter Neighborhood Summary neighbor bounds are inconsistent")
            with localcontext(
                only_decimal_context(OnlyNumericDefinition("DECIMAL", 38, Decimal("0.000000000001"), "ROUND_HALF_EVEN"))
            ):
                expected_range = maximum - minimum
            if local_range != expected_range or local_range < 0:
                raise ValueError("Parameter Neighborhood Summary local range is inconsistent")
            if self.focal_value.decimal_value is not None:
                with localcontext(
                    only_decimal_context(
                        OnlyNumericDefinition("DECIMAL", 38, Decimal("0.000000000001"), "ROUND_HALF_EVEN")
                    )
                ):
                    expected_difference = self.focal_value.decimal_value - neighbor_mean
                if self.focal_minus_neighbor_mean.decimal_value != expected_difference:
                    raise ValueError("Parameter Neighborhood Summary focal-minus-mean value is inconsistent")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "summary_kind": self.summary_kind.value,
            "source_metric_id": self.source_metric_id,
            **{name: getattr(self, name).to_dict() for name in _NEIGHBORHOOD_FIELDS},
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchParameterNeighborhoodSummary:
        if set(payload) != {"schema_version", "summary_kind", "source_metric_id", *_NEIGHBORHOOD_FIELDS}:
            raise ValueError("Parameter Neighborhood Summary result fields are invalid")
        scalars: dict[str, OnlyResearchSummaryScalar] = {}
        for name in _NEIGHBORHOOD_FIELDS:
            value = payload[name]
            if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
                raise ValueError(f"Parameter Neighborhood Summary {name} must be an object")
            scalars[name] = OnlyResearchSummaryScalar.from_dict(value)
        return cls(
            source_metric_id=_string(payload, "source_metric_id"),
            **scalars,
            summary_kind=OnlyResearchSummaryKind(_string(payload, "summary_kind")),
            schema_version=_integer(payload, "schema_version"),
        )


OnlyResearchSummary = (
    OnlyResearchEffectSummary
    | OnlyResearchCoverageSummary
    | OnlyResearchTemporalStabilitySummary
    | OnlyResearchFactorPairEffectSummary
    | OnlyResearchParameterNeighborhoodSummary
)


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
    if kind is OnlyResearchSummaryKind.FACTOR_PAIR_EFFECT_SUMMARY:
        return OnlyResearchFactorPairEffectSummary.from_dict(payload)
    if kind is OnlyResearchSummaryKind.PARAMETER_NEIGHBORHOOD_SUMMARY:
        return OnlyResearchParameterNeighborhoodSummary.from_dict(payload)
    raise ValueError("Summary Statistics payload kind is unsupported")  # pragma: no cover


@dataclass(frozen=True, slots=True)
class OnlyResearchSummaryStatisticsResultManifest:
    statistics_fingerprint: str
    plan: _SingleSourceSummaryPlan
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
            (
                OnlyResearchEffectSummaryPlan,
                OnlyResearchCoverageSummaryPlan,
                OnlyResearchTemporalStabilityPlan,
                OnlyResearchFactorPairEffectSummaryPlan,
            ),
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
        decoded_plan = only_research_summary_plan_from_dict(plan)
        if isinstance(decoded_plan, OnlyResearchParameterNeighborhoodSummaryPlan):
            raise ValueError("single-source Summary manifest cannot contain a Neighborhood Plan")
        return cls(
            statistics_fingerprint=_string(payload, "statistics_fingerprint"),
            plan=decoded_plan,
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
class OnlyResearchSummaryStatisticsDependencyReference:
    statistics_fingerprint: str
    statistics_result_fingerprint: str

    def __post_init__(self) -> None:
        if (
            _SHA256.fullmatch(self.statistics_fingerprint) is None
            or _SHA256.fullmatch(self.statistics_result_fingerprint) is None
        ):
            raise ValueError("Summary Statistics dependency identities must be lower-case SHA256")

    def to_dict(self) -> dict[str, str]:
        return {
            "statistics_fingerprint": self.statistics_fingerprint,
            "statistics_result_fingerprint": self.statistics_result_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchSummaryStatisticsDependencyReference:
        if set(payload) != {"statistics_fingerprint", "statistics_result_fingerprint"}:
            raise ValueError("Summary Statistics dependency reference fields are invalid")
        return cls(
            _string(payload, "statistics_fingerprint"),
            _string(payload, "statistics_result_fingerprint"),
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchParameterNeighborhoodSummaryUpstreamReferences:
    focal: OnlyResearchSummaryStatisticsDependencyReference
    neighbors: tuple[OnlyResearchSummaryStatisticsDependencyReference, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.focal, OnlyResearchSummaryStatisticsDependencyReference):
            raise ValueError("Parameter Neighborhood focal dependency is invalid")
        if not isinstance(self.neighbors, tuple) or any(
            not isinstance(item, OnlyResearchSummaryStatisticsDependencyReference) for item in self.neighbors
        ):
            raise ValueError("Parameter Neighborhood neighbor dependencies are invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "focal": self.focal.to_dict(),
            "neighbors": [item.to_dict() for item in self.neighbors],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchParameterNeighborhoodSummaryUpstreamReferences:
        if set(payload) != {"focal", "neighbors"}:
            raise ValueError("Parameter Neighborhood upstream reference fields are invalid")
        focal = payload["focal"]
        neighbors = payload["neighbors"]
        if not isinstance(focal, Mapping) or any(not isinstance(key, str) for key in focal):
            raise ValueError("Parameter Neighborhood focal dependency must be an object")
        if not isinstance(neighbors, list) or any(
            not isinstance(item, Mapping) or any(not isinstance(key, str) for key in item) for item in neighbors
        ):
            raise ValueError("Parameter Neighborhood neighbor dependencies must be an array")
        return cls(
            OnlyResearchSummaryStatisticsDependencyReference.from_dict(focal),
            tuple(OnlyResearchSummaryStatisticsDependencyReference.from_dict(item) for item in neighbors),
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchParameterNeighborhoodSummaryResultManifest:
    statistics_fingerprint: str
    plan: OnlyResearchParameterNeighborhoodSummaryPlan
    dataset_snapshot_fingerprint: str
    upstream_statistics_references: OnlyResearchParameterNeighborhoodSummaryUpstreamReferences
    result_content_fingerprint: str
    statistics_result_fingerprint: str
    summary_byte_sha256: str
    created_at: datetime
    domain: str = RESEARCH_SUMMARY_STATISTICS_DOMAIN
    schema_version: int = RESEARCH_SUMMARY_STATISTICS_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.domain != RESEARCH_SUMMARY_STATISTICS_DOMAIN:
            raise ValueError("Parameter Neighborhood Summary domain is unsupported")
        if self.schema_version != RESEARCH_SUMMARY_STATISTICS_RESULT_SCHEMA_VERSION:
            raise ValueError("Parameter Neighborhood Summary Result schema is unsupported")
        for name in (
            "statistics_fingerprint",
            "dataset_snapshot_fingerprint",
            "result_content_fingerprint",
            "statistics_result_fingerprint",
            "summary_byte_sha256",
        ):
            if _SHA256.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"Parameter Neighborhood Summary {name} must be a lower-case SHA256")
        if not isinstance(self.plan, OnlyResearchParameterNeighborhoodSummaryPlan):
            raise ValueError("Parameter Neighborhood Summary Plan is invalid")
        if self.statistics_fingerprint != self.plan.statistics_fingerprint:
            raise ValueError("Parameter Neighborhood Summary logical identity mismatch")
        if self.dataset_snapshot_fingerprint != self.plan.dataset_snapshot_fingerprint:
            raise ValueError("Parameter Neighborhood Summary Dataset identity mismatch")
        expected = OnlyResearchParameterNeighborhoodSummaryUpstreamReferences(
            OnlyResearchSummaryStatisticsDependencyReference(
                self.plan.focal.source_statistics_fingerprint,
                self.plan.focal.source_statistics_result_fingerprint,
            ),
            tuple(
                OnlyResearchSummaryStatisticsDependencyReference(
                    item.source_statistics_fingerprint,
                    item.source_statistics_result_fingerprint,
                )
                for item in self.plan.neighbors
            ),
        )
        if self.upstream_statistics_references != expected:
            raise ValueError("Parameter Neighborhood Summary upstream dependencies mismatch")
        if (
            only_research_summary_result_fingerprint(self.statistics_fingerprint, self.result_content_fingerprint)
            != self.statistics_result_fingerprint
        ):
            raise ValueError("Parameter Neighborhood Summary Result identity mismatch")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != timedelta(0):
            raise ValueError("Parameter Neighborhood Summary created_at must be timezone-aware UTC")

    def to_dict(self) -> dict[str, object]:
        return {item.name: _manifest_value(getattr(self, item.name)) for item in fields(self)}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchParameterNeighborhoodSummaryResultManifest:
        expected = {item.name for item in fields(cls)}
        if set(payload) != expected:
            raise ValueError("Parameter Neighborhood Summary manifest fields are invalid")
        plan = payload["plan"]
        upstream = payload["upstream_statistics_references"]
        if not isinstance(plan, Mapping) or any(not isinstance(key, str) for key in plan):
            raise ValueError("Parameter Neighborhood Summary manifest Plan must be an object")
        if not isinstance(upstream, Mapping) or any(not isinstance(key, str) for key in upstream):
            raise ValueError("Parameter Neighborhood Summary upstream references must be an object")
        return cls(
            statistics_fingerprint=_string(payload, "statistics_fingerprint"),
            plan=OnlyResearchParameterNeighborhoodSummaryPlan.from_dict(plan),
            dataset_snapshot_fingerprint=_string(payload, "dataset_snapshot_fingerprint"),
            upstream_statistics_references=OnlyResearchParameterNeighborhoodSummaryUpstreamReferences.from_dict(
                upstream
            ),
            result_content_fingerprint=_string(payload, "result_content_fingerprint"),
            statistics_result_fingerprint=_string(payload, "statistics_result_fingerprint"),
            summary_byte_sha256=_string(payload, "summary_byte_sha256"),
            created_at=_datetime(payload, "created_at"),
            domain=_string(payload, "domain"),
            schema_version=_integer(payload, "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchSummaryStatisticsResult:
    manifest: OnlyResearchSummaryStatisticsResultManifest | OnlyResearchParameterNeighborhoodSummaryResultManifest
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
        if isinstance(self.manifest.plan, OnlyResearchParameterNeighborhoodSummaryPlan) and not isinstance(
            self.summary, OnlyResearchParameterNeighborhoodSummary
        ):
            raise ValueError("Parameter Neighborhood Plan requires a Parameter Neighborhood payload")


def _manifest_value(value: object) -> object:
    from .plan import OnlyResearchCoverageSummaryPlan, OnlyResearchEffectSummaryPlan

    if isinstance(
        value,
        (
            OnlyResearchEffectSummaryPlan,
            OnlyResearchCoverageSummaryPlan,
            OnlyResearchTemporalStabilityPlan,
            OnlyResearchFactorPairEffectSummaryPlan,
            OnlyResearchParameterNeighborhoodSummaryPlan,
        ),
    ):
        return value.to_dict()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, OnlyResearchParameterNeighborhoodSummaryUpstreamReferences):
        return value.to_dict()
    return value


def _neighborhood_source_method(metric_id: str) -> OnlyResearchStatisticsMethod:
    if metric_id == "research.factor.ic.mean@1":
        return OnlyResearchStatisticsMethod.IC
    if metric_id == "research.factor.rank_ic.mean@1":
        return OnlyResearchStatisticsMethod.RANK_IC
    raise ValueError("Parameter Neighborhood source metric is unsupported")


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
    "OnlyResearchFactorPairEffectSummary",
    "OnlyResearchParameterNeighborhoodSummary",
    "OnlyResearchParameterNeighborhoodSummaryResultManifest",
    "OnlyResearchParameterNeighborhoodSummaryUpstreamReferences",
    "OnlyResearchSummary",
    "OnlyResearchSummaryStatisticsResult",
    "OnlyResearchSummaryStatisticsResultManifest",
    "OnlyResearchSummaryStatisticsDependencyReference",
    "OnlyResearchTemporalSliceEvidence",
    "OnlyResearchTemporalSliceValue",
    "OnlyResearchTemporalStabilitySummary",
    "only_research_summary_from_dict",
]
