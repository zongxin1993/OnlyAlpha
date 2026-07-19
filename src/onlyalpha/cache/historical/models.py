"""Public models for the reusable historical Bar cache."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBar, OnlyBarType

type OnlyJsonValue = str | int | bool | None | list[OnlyJsonValue] | dict[str, OnlyJsonValue]


class OnlyCachePolicy(StrEnum):
    CACHE_ONLY = "cache_only"
    PREFER_CACHE = "prefer_cache"
    FORCE_REFRESH = "force_refresh"


class OnlyBarTimestampSemantics(StrEnum):
    BAR_OPEN = "bar_open"
    BAR_CLOSE = "bar_close"


class OnlyDataQualitySeverity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class OnlyHistoricalCacheKey:
    source_id: str
    dataset_type: str
    instrument_id: OnlyInstrumentId
    bar_type: OnlyBarType
    adjustment: str
    schema_version: int = 1
    time_semantics_version: int = 1


@dataclass(frozen=True, slots=True)
class OnlyHistoricalDataRequest:
    instrument_id: OnlyInstrumentId
    bar_type: OnlyBarType
    time_range: OnlyTimeRange
    adjustment: str = "raw"
    metadata: Mapping[str, OnlyJsonValue] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.instrument_id != self.bar_type.instrument_id:
            raise ValueError("request instrument and Bar type must match")
        if self.metadata is None:
            object.__setattr__(self, "metadata", {})


@dataclass(frozen=True, slots=True)
class OnlyDataQualityIssue:
    code: str
    severity: OnlyDataQualitySeverity
    message: str
    instrument_id: OnlyInstrumentId | None = None
    timestamp: datetime | None = None
    metadata: Mapping[str, OnlyJsonValue] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.metadata is None:
            object.__setattr__(self, "metadata", {})


@dataclass(frozen=True, slots=True)
class OnlyDataQualityReport:
    valid: bool
    issues: tuple[OnlyDataQualityIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class OnlyHistoricalFetchResult:
    records: tuple[OnlyBar, ...]
    actual_coverage: tuple[OnlyTimeRange, ...]
    quality_report: OnlyDataQualityReport
    source_metadata: Mapping[str, OnlyJsonValue]


@dataclass(frozen=True, slots=True)
class OnlyCacheManifest:
    key: OnlyHistoricalCacheKey
    coverage: tuple[OnlyTimeRange, ...]
    row_count: int
    partition_hashes: Mapping[str, str]
    content_fingerprint: str
    schema_version: int
    time_semantics_version: int
    created_at: datetime
    updated_at: datetime
    metadata: Mapping[str, OnlyJsonValue]


@dataclass(frozen=True, slots=True)
class OnlyCacheInspection:
    exists: bool
    valid: bool
    key: OnlyHistoricalCacheKey
    coverage: tuple[OnlyTimeRange, ...]
    missing_ranges: tuple[OnlyTimeRange, ...]
    manifest: OnlyCacheManifest | None
    issues: tuple[OnlyDataQualityIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class OnlyCacheStatistics:
    cache_hit: bool
    partitions_read: int
    partitions_written: int
    rows_read: int
    rows_fetched: int
    missing_ranges: tuple[OnlyTimeRange, ...]
    content_fingerprint: str


@dataclass(frozen=True, slots=True)
class OnlyHistoricalDataResult:
    records: tuple[OnlyBar, ...]
    manifest: OnlyCacheManifest
    quality_report: OnlyDataQualityReport
    statistics: OnlyCacheStatistics


@dataclass(frozen=True, slots=True)
class OnlyCacheWriteResult:
    manifest: OnlyCacheManifest
    partitions_written: int
