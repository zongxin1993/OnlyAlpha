"""Narrow provider SPI for historical acquisition outside Trading Runtime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.instrument import OnlyInstrument

from .models import (
    OnlyHistoricalDataRequest,
    OnlyHistoricalFactFetchResult,
    OnlyHistoricalFactRequest,
    OnlyHistoricalFetchResult,
)


@dataclass(frozen=True, slots=True)
class OnlyHistoricalDataProviderCreateRequest:
    source_id: OnlyMarketDataSourceId
    plugin_config: object
    instrument: OnlyInstrument
    calendar: OnlyTradingCalendar
    data_version: OnlyDataVersion
    batch_size: int
    config_directory: Path

    def __post_init__(self) -> None:
        if self.batch_size <= 0:
            raise ValueError("historical provider batch_size must be positive")


class OnlyHistoricalDataProvider(Protocol):
    def fetch(self, request: OnlyHistoricalDataRequest, time_range: OnlyTimeRange) -> OnlyHistoricalFetchResult: ...


class OnlyHistoricalFactProvider(Protocol):
    def fetch_facts(
        self, request: OnlyHistoricalFactRequest, time_range: OnlyTimeRange
    ) -> OnlyHistoricalFactFetchResult: ...


class OnlyHistoricalDataProviderFactory(Protocol):
    def create_historical_provider(
        self, request: OnlyHistoricalDataProviderCreateRequest
    ) -> OnlyHistoricalDataProvider: ...
