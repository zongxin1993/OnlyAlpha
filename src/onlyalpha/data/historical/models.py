"""Runtime-independent semantic contracts for normalized historical data."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataVersion
from onlyalpha.domain.enums import OnlyAdjustmentType
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBar, OnlyBarType, OnlyFundingRateFact, OnlyReferencePriceFact, OnlyTradeTick
from onlyalpha.domain.trading import OnlyReferencePriceKind

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


type OnlyHistoricalCanonicalFact = OnlyBar | OnlyTradeTick | OnlyReferencePriceFact | OnlyFundingRateFact


@dataclass(frozen=True, slots=True)
class OnlyHistoricalFactRequest:
    instrument_id: OnlyInstrumentId
    fact_family: OnlyMarketDataType
    time_range: OnlyTimeRange
    data_version: OnlyDataVersion
    reference_price_kind: OnlyReferencePriceKind | None = None
    batch_size: int = 1024
    metadata: Mapping[str, OnlyJsonValue] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        supported = {
            OnlyMarketDataType.BAR,
            OnlyMarketDataType.TRADE,
            OnlyMarketDataType.REFERENCE_PRICE,
            OnlyMarketDataType.FUNDING_RATE,
            OnlyMarketDataType.SETTLEMENT,
        }
        if self.fact_family not in supported:
            raise ValueError("HISTORICAL_FACT_FAMILY_UNSUPPORTED")
        if self.fact_family is OnlyMarketDataType.REFERENCE_PRICE and self.reference_price_kind is None:
            raise ValueError("REFERENCE_PRICE_KIND_REQUIRED")
        if self.fact_family is OnlyMarketDataType.SETTLEMENT:
            object.__setattr__(self, "reference_price_kind", OnlyReferencePriceKind.SETTLEMENT)
        if self.fact_family not in {OnlyMarketDataType.REFERENCE_PRICE, OnlyMarketDataType.SETTLEMENT}:
            if self.reference_price_kind is not None:
                raise ValueError("REFERENCE_PRICE_KIND_NOT_APPLICABLE")
        if self.batch_size <= 0:
            raise ValueError("HISTORICAL_FACT_BATCH_SIZE_INVALID")
        if self.metadata is None:
            object.__setattr__(self, "metadata", {})


@dataclass(frozen=True, slots=True)
class OnlyHistoricalFactFetchResult:
    records: tuple[OnlyHistoricalCanonicalFact, ...]
    resolved_ranges: tuple[OnlyTimeRange, ...]
    observed_ranges: tuple[OnlyTimeRange, ...]
    quality_report: OnlyDataQualityReport
    source_metadata: Mapping[str, OnlyJsonValue]
