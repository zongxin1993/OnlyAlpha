"""Immutable transport-neutral Research Query read models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition

from .request import only_research_query_sha256

RESEARCH_QUERY_SCHEMA_VERSION = 1


def _positive_schema(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class OnlyResearchArtifactSummary:
    research_result_plan_fingerprint: str
    research_result_content_fingerprint: str
    research_result_fingerprint: str
    dataset_snapshot_fingerprint: str
    artifact_content_fingerprint: str
    research_result_schema_version: int
    artifact_profile: str
    artifact_schema_version: int
    statistics_count: int
    row_count: int
    created_at: datetime
    candidate_count: int = 0
    published_series_count: int = 0
    signal_series_count: int = 0
    market_row_count: int = 0
    schema_version: int = RESEARCH_QUERY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "research_result_plan_fingerprint",
            "research_result_content_fingerprint",
            "research_result_fingerprint",
            "dataset_snapshot_fingerprint",
            "artifact_content_fingerprint",
        ):
            only_research_query_sha256(getattr(self, name), name)
        if self.schema_version != RESEARCH_QUERY_SCHEMA_VERSION:
            raise ValueError("Research Query schema version is unsupported")
        _positive_schema(self.research_result_schema_version, "research_result_schema_version")
        _positive_schema(self.artifact_schema_version, "artifact_schema_version")
        if not self.artifact_profile:
            raise ValueError("artifact_profile is required")
        for name in ("statistics_count", "row_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if (
            not isinstance(self.created_at, datetime)
            or self.created_at.tzinfo is None
            or self.created_at.utcoffset() != timedelta(0)
        ):
            raise ValueError("created_at must be timezone-aware UTC")


@dataclass(frozen=True, slots=True)
class OnlyResearchSeriesReference:
    calculation_fingerprint: str
    node_fingerprint: str
    output_name: str

    def __post_init__(self) -> None:
        only_research_query_sha256(self.calculation_fingerprint, "calculation_fingerprint")
        only_research_query_sha256(self.node_fingerprint, "node_fingerprint")
        if not self.output_name or any(char.isspace() for char in self.output_name):
            raise ValueError("output_name is invalid")


@dataclass(frozen=True, slots=True)
class OnlyResearchNumericDescriptor:
    representation: str
    precision: int
    output_quantum: Decimal
    rounding: str

    def __post_init__(self) -> None:
        if not self.representation or not self.rounding:
            raise ValueError("numeric representation and rounding are required")
        if isinstance(self.precision, bool) or not isinstance(self.precision, int) or self.precision <= 0:
            raise ValueError("numeric precision must be positive")
        if not isinstance(self.output_quantum, Decimal) or not self.output_quantum.is_finite():
            raise ValueError("numeric output_quantum must be a finite Decimal")


@dataclass(frozen=True, slots=True)
class OnlyResearchStatisticsDefinitionDescriptor:
    method: str
    minimum_observations: int
    pairing_policy: str
    universe_policy: str
    rank_tie_method: str
    weighting: str
    numeric: OnlyResearchNumericDescriptor

    def __post_init__(self) -> None:
        if any(
            not value
            for value in (self.method, self.pairing_policy, self.universe_policy, self.rank_tie_method, self.weighting)
        ):
            raise ValueError("Statistics definition values are required")
        if (
            isinstance(self.minimum_observations, bool)
            or not isinstance(self.minimum_observations, int)
            or self.minimum_observations < 2
        ):
            raise ValueError("minimum_observations must be an integer >= 2")
        if not isinstance(self.numeric, OnlyResearchNumericDescriptor):
            raise ValueError("numeric descriptor is invalid")


@dataclass(frozen=True, slots=True, order=True)
class OnlyResearchStatisticsDescriptor:
    statistics_fingerprint: str
    statistics_result_fingerprint: str
    result_content_fingerprint: str
    statistics_result_schema_version: int
    row_count: int
    feature: OnlyResearchSeriesReference
    target: OnlyResearchSeriesReference
    definition: OnlyResearchStatisticsDefinitionDescriptor

    def __post_init__(self) -> None:
        for name in ("statistics_fingerprint", "statistics_result_fingerprint", "result_content_fingerprint"):
            only_research_query_sha256(getattr(self, name), name)
        _positive_schema(self.statistics_result_schema_version, "statistics_result_schema_version")
        if isinstance(self.row_count, bool) or not isinstance(self.row_count, int) or self.row_count < 0:
            raise ValueError("row_count must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class OnlyResearchStatisticsCatalog:
    research_result_fingerprint: str
    statistics: tuple[OnlyResearchStatisticsDescriptor, ...]
    schema_version: int = RESEARCH_QUERY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        only_research_query_sha256(self.research_result_fingerprint, "research_result_fingerprint")
        if self.schema_version != RESEARCH_QUERY_SCHEMA_VERSION:
            raise ValueError("Research Query schema version is unsupported")
        if (
            not isinstance(self.statistics, tuple)
            or any(not isinstance(item, OnlyResearchStatisticsDescriptor) for item in self.statistics)
            or self.statistics != tuple(sorted(self.statistics))
            or len({item.statistics_fingerprint for item in self.statistics}) != len(self.statistics)
        ):
            raise ValueError("Statistics catalog must be a canonical tuple")


@dataclass(frozen=True, slots=True)
class OnlyResearchStatisticPoint:
    ts_event_ns: int
    statistic_value: Decimal | None
    sample_count: int
    status: str

    def __post_init__(self) -> None:
        if isinstance(self.ts_event_ns, bool) or not isinstance(self.ts_event_ns, int):
            raise ValueError("ts_event_ns must be an integer")
        if self.statistic_value is not None and (
            not isinstance(self.statistic_value, Decimal) or not self.statistic_value.is_finite()
        ):
            raise ValueError("statistic_value must be a finite Decimal or null")
        if isinstance(self.sample_count, bool) or not isinstance(self.sample_count, int) or self.sample_count < 0:
            raise ValueError("sample_count must be a non-negative integer")
        if not self.status:
            raise ValueError("status is required")


@dataclass(frozen=True, slots=True)
class OnlyResearchStatisticSeriesPage:
    research_result_fingerprint: str
    statistics_fingerprint: str
    points: tuple[OnlyResearchStatisticPoint, ...]
    has_more: bool
    next_after_ts_event_ns: int | None
    schema_version: int = RESEARCH_QUERY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        only_research_query_sha256(self.research_result_fingerprint, "research_result_fingerprint")
        only_research_query_sha256(self.statistics_fingerprint, "statistics_fingerprint")
        if self.schema_version != RESEARCH_QUERY_SCHEMA_VERSION:
            raise ValueError("Research Query schema version is unsupported")
        if (
            not isinstance(self.points, tuple)
            or any(not isinstance(item, OnlyResearchStatisticPoint) for item in self.points)
            or self.points != tuple(sorted(self.points, key=lambda item: item.ts_event_ns))
            or len({item.ts_event_ns for item in self.points}) != len(self.points)
        ):
            raise ValueError("points must be a canonical tuple")
        if not isinstance(self.has_more, bool):
            raise ValueError("has_more must be a boolean")
        expected_cursor = self.points[-1].ts_event_ns if self.has_more and self.points else None
        if self.next_after_ts_event_ns != expected_cursor:
            raise ValueError("next cursor does not match page state")


@dataclass(frozen=True, slots=True, order=True)
class OnlyResearchCandidateDescriptor:
    candidate_fingerprint: str
    candidate_calculation_id: str
    assignment: tuple[tuple[str, object], ...]
    calculation_fingerprint: str
    graph_fingerprint: str
    statistics_fingerprints: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OnlyResearchCandidateCatalog:
    research_result_fingerprint: str
    candidates: tuple[OnlyResearchCandidateDescriptor, ...]
    schema_version: int = RESEARCH_QUERY_SCHEMA_VERSION


@dataclass(frozen=True, slots=True, order=True)
class OnlyResearchPublishedSeriesDescriptor:
    candidate_fingerprint: str | None
    calculation_fingerprint: str
    node_fingerprint: str
    output_name: str
    value_kind: str


@dataclass(frozen=True, slots=True)
class OnlyResearchPublishedSeriesCatalog:
    research_result_fingerprint: str
    series: tuple[OnlyResearchPublishedSeriesDescriptor, ...]
    schema_version: int = RESEARCH_QUERY_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class OnlyResearchMarketPoint:
    instrument_id: str
    ts_event_ns: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True, slots=True)
class OnlyResearchVariablePoint:
    instrument_id: str
    ts_event_ns: int
    value_kind: str
    decimal_value: str | None
    integer_value: str | None
    boolean_value: bool | None
    string_value: str | None


@dataclass(frozen=True, slots=True)
class OnlyResearchSignalPoint:
    instrument_id: str
    ts_event_ns: int
    value: bool | None


@dataclass(frozen=True, slots=True)
class OnlyResearchScientificSeriesPage:
    research_result_fingerprint: str
    points: tuple[OnlyResearchMarketPoint | OnlyResearchVariablePoint | OnlyResearchSignalPoint, ...]
    has_more: bool
    next_after_ts_event_ns: int | None
    schema_version: int = RESEARCH_QUERY_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class OnlyResearchCandidateGraph:
    research_result_fingerprint: str
    candidate_fingerprint: str
    calculation_fingerprint: str
    graph: OnlyCalculationGraphDefinition
    schema_version: int = RESEARCH_QUERY_SCHEMA_VERSION
