"""Runtime-independent semantic contracts for normalized historical data."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.domain.enums import OnlyAdjustmentType
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBar, OnlyBarType, OnlyTradeTick

type OnlyJsonValue = str | int | bool | None | list[OnlyJsonValue] | dict[str, OnlyJsonValue]


class OnlyDataQualitySeverity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class OnlyHistoricalDataRequest:
    instrument_id: OnlyInstrumentId
    bar_type: OnlyBarType
    time_range: OnlyTimeRange
    price_adjustment: OnlyAdjustmentType = OnlyAdjustmentType.RAW
    adjustment_reference: str | None = None
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
    resolved_ranges: tuple[OnlyTimeRange, ...]
    observed_ranges: tuple[OnlyTimeRange, ...]
    quality_report: OnlyDataQualityReport
    source_metadata: Mapping[str, OnlyJsonValue]


@dataclass(frozen=True, slots=True)
class OnlyHistoricalTradeDataRequest:
    instrument_id: OnlyInstrumentId
    time_range: OnlyTimeRange
    metadata: Mapping[str, OnlyJsonValue] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.metadata is None:
            object.__setattr__(self, "metadata", {})


@dataclass(frozen=True, slots=True)
class OnlyHistoricalTradeFetchResult:
    records: tuple[OnlyTradeTick, ...]
    resolved_ranges: tuple[OnlyTimeRange, ...]
    observed_ranges: tuple[OnlyTimeRange, ...]
    quality_report: OnlyDataQualityReport
    source_metadata: Mapping[str, OnlyJsonValue]
