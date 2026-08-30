"""Public models for the reusable historical Bar cache."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.data.historical import models as historical_models
from onlyalpha.domain.enums import OnlyAdjustmentType
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBar, OnlyBarType, OnlyTradeTick

type OnlyJsonValue = str | int | bool | None | list[OnlyJsonValue] | dict[str, OnlyJsonValue]


class OnlyCachePolicy(StrEnum):
    CACHE_ONLY = "cache_only"
    PREFER_CACHE = "prefer_cache"
    FORCE_REFRESH = "force_refresh"


class OnlyBarTimestampSemantics(StrEnum):
    BAR_OPEN = "bar_open"
    BAR_CLOSE = "bar_close"


@dataclass(frozen=True, slots=True)
class OnlyHistoricalBarCacheKey:
    source_id: str
    dataset_type: str
    instrument_id: OnlyInstrumentId
    bar_type: OnlyBarType
    price_adjustment: OnlyAdjustmentType
    adjustment_reference: str | None = None
    schema_version: int = 1
    time_semantics_version: int = 1
    data_version: str | None = None
    compatibility_profile_id: str | None = None
    timestamp_semantics: OnlyBarTimestampSemantics = OnlyBarTimestampSemantics.BAR_CLOSE


OnlyHistoricalCacheKey = OnlyHistoricalBarCacheKey


@dataclass(frozen=True, slots=True)
class OnlyHistoricalTradeCacheKey:
    source_id: str
    dataset_type: str
    instrument_id: OnlyInstrumentId
    data_version: str
    schema_version: int = 1
    time_semantics_version: int = 1
    compatibility_profile_id: str | None = None

    def __post_init__(self) -> None:
        if not self.data_version.strip():
            raise ValueError("historical Trade cache key requires data_version")


type OnlyTypedHistoricalCacheKey = OnlyHistoricalBarCacheKey | OnlyHistoricalTradeCacheKey


@dataclass(frozen=True, slots=True)
class OnlyCacheManifest:
    key: OnlyTypedHistoricalCacheKey
    resolved_ranges: tuple[OnlyTimeRange, ...]
    observed_ranges: tuple[OnlyTimeRange, ...]
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
    key: OnlyTypedHistoricalCacheKey
    resolved_ranges: tuple[OnlyTimeRange, ...]
    observed_ranges: tuple[OnlyTimeRange, ...]
    missing_ranges: tuple[OnlyTimeRange, ...]
    manifest: OnlyCacheManifest | None
    issues: tuple[historical_models.OnlyDataQualityIssue, ...] = ()


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
    quality_report: historical_models.OnlyDataQualityReport
    statistics: OnlyCacheStatistics


@dataclass(frozen=True, slots=True)
class OnlyHistoricalTradeDataResult:
    records: tuple[OnlyTradeTick, ...]
    manifest: OnlyCacheManifest
    quality_report: historical_models.OnlyDataQualityReport
    statistics: OnlyCacheStatistics


@dataclass(frozen=True, slots=True)
class OnlyCacheWriteResult:
    manifest: OnlyCacheManifest
    partitions_written: int
