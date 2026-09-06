"""Additive typed rich Research Evidence read projections."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from .model import (
    RESEARCH_QUERY_SCHEMA_VERSION,
    OnlyResearchSeriesReference,
    OnlyResearchStatisticsDefinitionDescriptor,
)
from .request import only_research_query_sha256


class OnlyResearchTypedStatisticsShape(StrEnum):
    SERIES = "SERIES"
    SUMMARY = "SUMMARY"


class OnlyResearchTypedStatisticsFamily(StrEnum):
    FEATURE_TARGET_CORRELATION_SERIES_V1 = "FEATURE_TARGET_CORRELATION_SERIES_V1"
    FACTOR_PAIR_CORRELATION_SERIES_V1 = "FACTOR_PAIR_CORRELATION_SERIES_V1"
    SUMMARY_STATISTICS_V1 = "SUMMARY_STATISTICS_V1"


class OnlyResearchTypedSummaryKind(StrEnum):
    EFFECT_SUMMARY = "EFFECT_SUMMARY"
    COVERAGE_SUMMARY = "COVERAGE_SUMMARY"
    TEMPORAL_STABILITY = "TEMPORAL_STABILITY"
    FACTOR_PAIR_EFFECT_SUMMARY = "FACTOR_PAIR_EFFECT_SUMMARY"
    PARAMETER_NEIGHBORHOOD_SUMMARY = "PARAMETER_NEIGHBORHOOD_SUMMARY"


class OnlyResearchTypedScalarValueKind(StrEnum):
    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL"


class OnlyResearchTypedScalarStatus(StrEnum):
    VALID = "VALID"
    NO_VALID_OBSERVATIONS = "NO_VALID_OBSERVATIONS"
    INSUFFICIENT_OBSERVATIONS = "INSUFFICIENT_OBSERVATIONS"
    ZERO_VARIANCE = "ZERO_VARIANCE"
    INSUFFICIENT_COVERAGE = "INSUFFICIENT_COVERAGE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True, slots=True)
class OnlyResearchTypedScalar:
    metric_id: str
    value_kind: OnlyResearchTypedScalarValueKind
    status: OnlyResearchTypedScalarStatus
    integer_value: int | None = None
    decimal_value: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.metric_id or not isinstance(self.value_kind, OnlyResearchTypedScalarValueKind):
            raise ValueError("typed scalar identity is invalid")
        if not isinstance(self.status, OnlyResearchTypedScalarStatus):
            raise ValueError("typed scalar status is invalid")
        if self.status is OnlyResearchTypedScalarStatus.VALID:
            if self.value_kind is OnlyResearchTypedScalarValueKind.INTEGER:
                if isinstance(self.integer_value, bool) or not isinstance(self.integer_value, int):
                    raise ValueError("VALID INTEGER scalar requires an exact integer")
                if self.decimal_value is not None:
                    raise ValueError("VALID INTEGER scalar cannot carry a Decimal")
            elif (
                not isinstance(self.decimal_value, Decimal)
                or not self.decimal_value.is_finite()
                or self.integer_value is not None
            ):
                raise ValueError("VALID DECIMAL scalar requires an exact finite Decimal")
        elif self.integer_value is not None or self.decimal_value is not None:
            raise ValueError("non-VALID scalar must not carry a numeric value")


@dataclass(frozen=True, slots=True)
class OnlyResearchTypedStatisticsDependency:
    statistics_fingerprint: str
    statistics_result_fingerprint: str

    def __post_init__(self) -> None:
        only_research_query_sha256(self.statistics_fingerprint, "statistics_fingerprint")
        only_research_query_sha256(self.statistics_result_fingerprint, "statistics_result_fingerprint")


@dataclass(frozen=True, slots=True)
class OnlyResearchTypedFactorOperand:
    candidate_fingerprint: str
    calculation_fingerprint: str
    node_fingerprint: str
    output_name: str

    def __post_init__(self) -> None:
        only_research_query_sha256(self.candidate_fingerprint, "candidate_fingerprint")
        OnlyResearchSeriesReference(self.calculation_fingerprint, self.node_fingerprint, self.output_name)


@dataclass(frozen=True, slots=True)
class OnlyResearchTypedCandidateBinding:
    candidate_fingerprint: str
    assignment: tuple[tuple[str, object], ...]
    source: OnlyResearchTypedStatisticsDependency

    def __post_init__(self) -> None:
        only_research_query_sha256(self.candidate_fingerprint, "candidate_fingerprint")
        if (
            not isinstance(self.assignment, tuple)
            or self.assignment != tuple(sorted(self.assignment))
            or len(dict(self.assignment)) != len(self.assignment)
        ):
            raise ValueError("typed Candidate assignment must be canonical")
        if not isinstance(self.source, OnlyResearchTypedStatisticsDependency):
            raise ValueError("typed Candidate source dependency is invalid")


@dataclass(frozen=True, slots=True)
class OnlyResearchTypedLegacySeriesDescriptor:
    statistics_fingerprint: str
    statistics_result_fingerprint: str
    result_content_fingerprint: str
    dataset_snapshot_fingerprint: str
    statistics_result_schema_version: int
    row_count: int
    feature: OnlyResearchSeriesReference
    target: OnlyResearchSeriesReference
    definition: OnlyResearchStatisticsDefinitionDescriptor
    family: OnlyResearchTypedStatisticsFamily = OnlyResearchTypedStatisticsFamily.FEATURE_TARGET_CORRELATION_SERIES_V1
    shape: OnlyResearchTypedStatisticsShape = OnlyResearchTypedStatisticsShape.SERIES

    def __post_init__(self) -> None:
        _descriptor_common(self)
        _non_negative(self.row_count, "row_count")
        if (
            self.family is not OnlyResearchTypedStatisticsFamily.FEATURE_TARGET_CORRELATION_SERIES_V1
            or self.shape is not OnlyResearchTypedStatisticsShape.SERIES
            or not isinstance(self.definition, OnlyResearchStatisticsDefinitionDescriptor)
        ):
            raise ValueError("legacy Series discriminant or definition is invalid")


@dataclass(frozen=True, slots=True)
class OnlyResearchTypedFactorPairSeriesDescriptor:
    statistics_fingerprint: str
    statistics_result_fingerprint: str
    result_content_fingerprint: str
    dataset_snapshot_fingerprint: str
    statistics_result_schema_version: int
    method: str
    row_count: int
    first_operand: OnlyResearchTypedFactorOperand
    second_operand: OnlyResearchTypedFactorOperand
    family: OnlyResearchTypedStatisticsFamily = OnlyResearchTypedStatisticsFamily.FACTOR_PAIR_CORRELATION_SERIES_V1
    shape: OnlyResearchTypedStatisticsShape = OnlyResearchTypedStatisticsShape.SERIES

    def __post_init__(self) -> None:
        _descriptor_common(self)
        _non_negative(self.row_count, "row_count")
        if (
            not self.method
            or not isinstance(self.first_operand, OnlyResearchTypedFactorOperand)
            or not isinstance(self.second_operand, OnlyResearchTypedFactorOperand)
        ):
            raise ValueError("Factor-Pair descriptor is invalid")
        if (
            self.family is not OnlyResearchTypedStatisticsFamily.FACTOR_PAIR_CORRELATION_SERIES_V1
            or self.shape is not OnlyResearchTypedStatisticsShape.SERIES
        ):
            raise ValueError("Factor-Pair Series discriminant is invalid")


@dataclass(frozen=True, slots=True)
class OnlyResearchTypedCandidateSummaryDescriptor:
    statistics_fingerprint: str
    statistics_result_fingerprint: str
    result_content_fingerprint: str
    dataset_snapshot_fingerprint: str
    statistics_result_schema_version: int
    summary_kind: OnlyResearchTypedSummaryKind
    subject_candidate_fingerprint: str
    subject: OnlyResearchSeriesReference
    source: OnlyResearchTypedStatisticsDependency
    family: OnlyResearchTypedStatisticsFamily = OnlyResearchTypedStatisticsFamily.SUMMARY_STATISTICS_V1
    shape: OnlyResearchTypedStatisticsShape = OnlyResearchTypedStatisticsShape.SUMMARY

    def __post_init__(self) -> None:
        _descriptor_common(self)
        if self.summary_kind not in {
            OnlyResearchTypedSummaryKind.EFFECT_SUMMARY,
            OnlyResearchTypedSummaryKind.COVERAGE_SUMMARY,
            OnlyResearchTypedSummaryKind.TEMPORAL_STABILITY,
        }:
            raise ValueError("Candidate Summary kind is invalid")
        only_research_query_sha256(self.subject_candidate_fingerprint, "subject_candidate_fingerprint")
        if (
            self.family is not OnlyResearchTypedStatisticsFamily.SUMMARY_STATISTICS_V1
            or self.shape is not OnlyResearchTypedStatisticsShape.SUMMARY
        ):
            raise ValueError("Candidate Summary discriminant is invalid")


@dataclass(frozen=True, slots=True)
class OnlyResearchTypedFactorPairSummaryDescriptor:
    statistics_fingerprint: str
    statistics_result_fingerprint: str
    result_content_fingerprint: str
    dataset_snapshot_fingerprint: str
    statistics_result_schema_version: int
    summary_kind: OnlyResearchTypedSummaryKind
    first_operand: OnlyResearchTypedFactorOperand
    second_operand: OnlyResearchTypedFactorOperand
    source: OnlyResearchTypedStatisticsDependency
    family: OnlyResearchTypedStatisticsFamily = OnlyResearchTypedStatisticsFamily.SUMMARY_STATISTICS_V1
    shape: OnlyResearchTypedStatisticsShape = OnlyResearchTypedStatisticsShape.SUMMARY

    def __post_init__(self) -> None:
        _descriptor_common(self)
        if self.summary_kind is not OnlyResearchTypedSummaryKind.FACTOR_PAIR_EFFECT_SUMMARY:
            raise ValueError("Factor-Pair Summary kind is invalid")
        if (
            self.family is not OnlyResearchTypedStatisticsFamily.SUMMARY_STATISTICS_V1
            or self.shape is not OnlyResearchTypedStatisticsShape.SUMMARY
        ):
            raise ValueError("Factor-Pair Summary discriminant is invalid")


@dataclass(frozen=True, slots=True)
class OnlyResearchTypedNeighborhoodSummaryDescriptor:
    statistics_fingerprint: str
    statistics_result_fingerprint: str
    result_content_fingerprint: str
    dataset_snapshot_fingerprint: str
    statistics_result_schema_version: int
    summary_kind: OnlyResearchTypedSummaryKind
    source_metric_id: str
    focal: OnlyResearchTypedCandidateBinding
    neighbors: tuple[OnlyResearchTypedCandidateBinding, ...]
    family: OnlyResearchTypedStatisticsFamily = OnlyResearchTypedStatisticsFamily.SUMMARY_STATISTICS_V1
    shape: OnlyResearchTypedStatisticsShape = OnlyResearchTypedStatisticsShape.SUMMARY

    def __post_init__(self) -> None:
        _descriptor_common(self)
        if self.summary_kind is not OnlyResearchTypedSummaryKind.PARAMETER_NEIGHBORHOOD_SUMMARY:
            raise ValueError("Neighborhood Summary kind is invalid")
        if not self.source_metric_id or not isinstance(self.neighbors, tuple):
            raise ValueError("Neighborhood metadata is invalid")
        if (
            self.family is not OnlyResearchTypedStatisticsFamily.SUMMARY_STATISTICS_V1
            or self.shape is not OnlyResearchTypedStatisticsShape.SUMMARY
        ):
            raise ValueError("Neighborhood Summary discriminant is invalid")


type OnlyResearchTypedStatisticsDescriptor = (
    OnlyResearchTypedLegacySeriesDescriptor
    | OnlyResearchTypedFactorPairSeriesDescriptor
    | OnlyResearchTypedCandidateSummaryDescriptor
    | OnlyResearchTypedFactorPairSummaryDescriptor
    | OnlyResearchTypedNeighborhoodSummaryDescriptor
)


@dataclass(frozen=True, slots=True)
class OnlyResearchTypedStatisticsCatalog:
    research_result_fingerprint: str
    statistics: tuple[OnlyResearchTypedStatisticsDescriptor, ...]
    schema_version: int = RESEARCH_QUERY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        only_research_query_sha256(self.research_result_fingerprint, "research_result_fingerprint")
        if not isinstance(self.statistics, tuple) or any(
            not isinstance(
                item,
                (
                    OnlyResearchTypedLegacySeriesDescriptor,
                    OnlyResearchTypedFactorPairSeriesDescriptor,
                    OnlyResearchTypedCandidateSummaryDescriptor,
                    OnlyResearchTypedFactorPairSummaryDescriptor,
                    OnlyResearchTypedNeighborhoodSummaryDescriptor,
                ),
            )
            for item in self.statistics
        ):
            raise ValueError("typed Statistics catalog entries are invalid")
        identities = tuple(item.statistics_fingerprint for item in self.statistics)
        if self.schema_version != RESEARCH_QUERY_SCHEMA_VERSION or identities != tuple(sorted(identities)):
            raise ValueError("typed Statistics catalog must be canonical")
        if len(identities) != len(set(identities)):
            raise ValueError("typed Statistics catalog must be duplicate-free")


@dataclass(frozen=True, slots=True)
class OnlyResearchTypedStatisticPoint:
    ts_event_ns: int
    statistic_value: Decimal | None
    sample_count: int
    status: str

    def __post_init__(self) -> None:
        if isinstance(self.ts_event_ns, bool) or not isinstance(self.ts_event_ns, int):
            raise ValueError("typed point timestamp must be an integer")
        if self.statistic_value is not None and (
            not isinstance(self.statistic_value, Decimal) or not self.statistic_value.is_finite()
        ):
            raise ValueError("typed point value must be an exact finite Decimal or absent")
        _non_negative(self.sample_count, "sample_count")
        if not self.status:
            raise ValueError("typed point status is required")


@dataclass(frozen=True, slots=True)
class OnlyResearchTypedStatisticSeriesPage:
    research_result_fingerprint: str
    statistics_fingerprint: str
    statistics_family: OnlyResearchTypedStatisticsFamily
    points: tuple[OnlyResearchTypedStatisticPoint, ...]
    has_more: bool
    next_after_ts_event_ns: int | None
    schema_version: int = RESEARCH_QUERY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        only_research_query_sha256(self.research_result_fingerprint, "research_result_fingerprint")
        only_research_query_sha256(self.statistics_fingerprint, "statistics_fingerprint")
        if not isinstance(self.statistics_family, OnlyResearchTypedStatisticsFamily) or self.statistics_family not in {
            OnlyResearchTypedStatisticsFamily.FEATURE_TARGET_CORRELATION_SERIES_V1,
            OnlyResearchTypedStatisticsFamily.FACTOR_PAIR_CORRELATION_SERIES_V1,
        }:
            raise ValueError("typed Series family is invalid")
        if not isinstance(self.points, tuple) or any(
            not isinstance(item, OnlyResearchTypedStatisticPoint) for item in self.points
        ):
            raise ValueError("typed Series points are invalid")
        timestamps = tuple(item.ts_event_ns for item in self.points)
        if timestamps != tuple(sorted(timestamps)) or len(timestamps) != len(set(timestamps)):
            raise ValueError("typed Series points must be canonical")
        if not isinstance(self.has_more, bool):
            raise ValueError("typed Series has_more must be a boolean")
        expected = self.points[-1].ts_event_ns if self.has_more and self.points else None
        if self.schema_version != RESEARCH_QUERY_SCHEMA_VERSION or self.next_after_ts_event_ns != expected:
            raise ValueError("typed Series page state is invalid")


@dataclass(frozen=True, slots=True)
class OnlyResearchTemporalSliceValueProjection:
    status: OnlyResearchTypedScalarStatus
    decimal_value: Decimal | None

    def __post_init__(self) -> None:
        if not isinstance(self.status, OnlyResearchTypedScalarStatus):
            raise ValueError("Temporal slice status is invalid")
        if self.status is OnlyResearchTypedScalarStatus.VALID:
            if not isinstance(self.decimal_value, Decimal) or not self.decimal_value.is_finite():
                raise ValueError("VALID Temporal slice value requires an exact finite Decimal")
        elif self.decimal_value is not None:
            raise ValueError("non-VALID Temporal slice value must be absent")


@dataclass(frozen=True, slots=True)
class OnlyResearchTemporalSliceProjection:
    start_ts_event_ns: int
    end_ts_event_ns: int
    total_timestamp_count: int
    valid_timestamp_count: int
    mean: OnlyResearchTemporalSliceValueProjection
    stddev_sample: OnlyResearchTemporalSliceValueProjection
    information_ratio: OnlyResearchTemporalSliceValueProjection
    valid_timestamp_ratio: OnlyResearchTemporalSliceValueProjection

    def __post_init__(self) -> None:
        if (
            isinstance(self.start_ts_event_ns, bool)
            or not isinstance(self.start_ts_event_ns, int)
            or isinstance(self.end_ts_event_ns, bool)
            or not isinstance(self.end_ts_event_ns, int)
            or self.start_ts_event_ns >= self.end_ts_event_ns
        ):
            raise ValueError("Temporal slice interval is invalid")
        _non_negative(self.total_timestamp_count, "total_timestamp_count")
        _non_negative(self.valid_timestamp_count, "valid_timestamp_count")
        if self.valid_timestamp_count > self.total_timestamp_count:
            raise ValueError("Temporal slice valid count exceeds total count")


@dataclass(frozen=True, slots=True)
class OnlyResearchEffectSummaryProjection:
    research_result_fingerprint: str
    statistics_fingerprint: str
    subject_candidate_fingerprint: str
    subject: OnlyResearchSeriesReference
    source: OnlyResearchTypedStatisticsDependency
    source_method: str
    total_count: OnlyResearchTypedScalar
    valid_count: OnlyResearchTypedScalar
    insufficient_observations_count: OnlyResearchTypedScalar
    zero_variance_feature_count: OnlyResearchTypedScalar
    zero_variance_target_count: OnlyResearchTypedScalar
    mean: OnlyResearchTypedScalar
    stddev_sample: OnlyResearchTypedScalar
    information_ratio: OnlyResearchTypedScalar
    positive_count: OnlyResearchTypedScalar
    negative_count: OnlyResearchTypedScalar
    zero_count: OnlyResearchTypedScalar
    positive_ratio: OnlyResearchTypedScalar
    negative_ratio: OnlyResearchTypedScalar
    zero_ratio: OnlyResearchTypedScalar
    summary_kind: OnlyResearchTypedSummaryKind = OnlyResearchTypedSummaryKind.EFFECT_SUMMARY


@dataclass(frozen=True, slots=True)
class OnlyResearchCoverageSummaryProjection:
    research_result_fingerprint: str
    statistics_fingerprint: str
    subject_candidate_fingerprint: str
    subject: OnlyResearchSeriesReference
    source: OnlyResearchTypedStatisticsDependency
    source_method: str
    total_timestamp_count: OnlyResearchTypedScalar
    valid_timestamp_count: OnlyResearchTypedScalar
    valid_timestamp_ratio: OnlyResearchTypedScalar
    insufficient_timestamp_count: OnlyResearchTypedScalar
    zero_variance_feature_count: OnlyResearchTypedScalar
    zero_variance_target_count: OnlyResearchTypedScalar
    pair_count_total: OnlyResearchTypedScalar
    pair_count_mean: OnlyResearchTypedScalar
    pair_count_min: OnlyResearchTypedScalar
    pair_count_max: OnlyResearchTypedScalar
    summary_kind: OnlyResearchTypedSummaryKind = OnlyResearchTypedSummaryKind.COVERAGE_SUMMARY


@dataclass(frozen=True, slots=True)
class OnlyResearchTemporalStabilitySummaryProjection:
    research_result_fingerprint: str
    statistics_fingerprint: str
    subject_candidate_fingerprint: str
    subject: OnlyResearchSeriesReference
    source: OnlyResearchTypedStatisticsDependency
    source_method: str
    slices: tuple[OnlyResearchTemporalSliceProjection, ...]
    slice_count: OnlyResearchTypedScalar
    valid_slice_count: OnlyResearchTypedScalar
    positive_mean_slice_count: OnlyResearchTypedScalar
    negative_mean_slice_count: OnlyResearchTypedScalar
    zero_mean_slice_count: OnlyResearchTypedScalar
    positive_mean_slice_ratio: OnlyResearchTypedScalar
    negative_mean_slice_ratio: OnlyResearchTypedScalar
    zero_mean_slice_ratio: OnlyResearchTypedScalar
    min_slice_mean: OnlyResearchTypedScalar
    max_slice_mean: OnlyResearchTypedScalar
    stddev_of_slice_means: OnlyResearchTypedScalar
    summary_kind: OnlyResearchTypedSummaryKind = OnlyResearchTypedSummaryKind.TEMPORAL_STABILITY


@dataclass(frozen=True, slots=True)
class OnlyResearchFactorPairEffectSummaryProjection:
    research_result_fingerprint: str
    statistics_fingerprint: str
    first_operand: OnlyResearchTypedFactorOperand
    second_operand: OnlyResearchTypedFactorOperand
    source: OnlyResearchTypedStatisticsDependency
    source_method: str
    mean: OnlyResearchTypedScalar
    stddev_sample: OnlyResearchTypedScalar
    summary_kind: OnlyResearchTypedSummaryKind = OnlyResearchTypedSummaryKind.FACTOR_PAIR_EFFECT_SUMMARY


@dataclass(frozen=True, slots=True)
class OnlyResearchParameterNeighborhoodSummaryProjection:
    research_result_fingerprint: str
    statistics_fingerprint: str
    source_metric_id: str
    focal: OnlyResearchTypedCandidateBinding
    neighbors: tuple[OnlyResearchTypedCandidateBinding, ...]
    focal_value: OnlyResearchTypedScalar
    neighbor_count: OnlyResearchTypedScalar
    valid_neighbor_count: OnlyResearchTypedScalar
    neighbor_no_valid_observations_count: OnlyResearchTypedScalar
    neighbor_mean: OnlyResearchTypedScalar
    neighbor_min: OnlyResearchTypedScalar
    neighbor_max: OnlyResearchTypedScalar
    neighbor_stddev_sample: OnlyResearchTypedScalar
    local_range: OnlyResearchTypedScalar
    focal_minus_neighbor_mean: OnlyResearchTypedScalar
    summary_kind: OnlyResearchTypedSummaryKind = OnlyResearchTypedSummaryKind.PARAMETER_NEIGHBORHOOD_SUMMARY


type OnlyResearchTypedStatisticSummary = (
    OnlyResearchEffectSummaryProjection
    | OnlyResearchCoverageSummaryProjection
    | OnlyResearchTemporalStabilitySummaryProjection
    | OnlyResearchFactorPairEffectSummaryProjection
    | OnlyResearchParameterNeighborhoodSummaryProjection
)


def _descriptor_common(value: OnlyResearchTypedStatisticsDescriptor) -> None:
    for name in (
        "statistics_fingerprint",
        "statistics_result_fingerprint",
        "result_content_fingerprint",
        "dataset_snapshot_fingerprint",
    ):
        only_research_query_sha256(getattr(value, name), name)
    version = value.statistics_result_schema_version
    if isinstance(version, bool) or not isinstance(version, int) or version <= 0:
        raise ValueError("Statistics result schema version must be positive")


def _non_negative(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


__all__ = [name for name in globals() if name.startswith("OnlyResearch")]
