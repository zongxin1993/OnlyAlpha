"""Public DataSource plugin Factory SPI."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from logging import Logger
from pathlib import Path
from typing import Protocol

from onlyalpha.cache.historical.service import OnlyHistoricalCacheService
from onlyalpha.config.models import OnlyDataSourceCoverageConfig, OnlyUniverseConfig
from onlyalpha.core.clock import OnlyClock
from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.data.ports import (
    OnlyHistoricalDataSource,
    OnlyMarketDataGateway,
    OnlyMarketDataUpdateSink,
    OnlyReferenceDataSource,
)
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.market import OnlyBarType
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.plugin.capabilities import OnlyDataSourceCapabilities, OnlyPluginValidationIssue
from onlyalpha.plugin.descriptor import OnlyPluginDescriptor
from onlyalpha.plugin.lifecycle import OnlyPluginResource


@dataclass(frozen=True, slots=True)
class OnlyDataSourceCreateRequest:
    source_id: OnlyMarketDataSourceId
    plugin_config: object
    runtime_type: str
    requested_capabilities: OnlyDataSourceCapabilities
    clock: OnlyClock
    event_bus: OnlyEventBus
    instruments: Mapping[OnlyInstrumentId, OnlyInstrument]
    bar_types: Mapping[OnlyInstrumentId, OnlyBarType]
    calendars: Mapping[OnlyCalendarId, OnlyTradingCalendar]
    universes: tuple[OnlyUniverseConfig, ...]
    coverage: OnlyDataSourceCoverageConfig
    runtime_id: OnlyRuntimeId
    data_version: OnlyDataVersion
    batch_size: int
    config_directory: Path
    logger: Logger
    market_data_sink: OnlyMarketDataUpdateSink | None = None
    historical_cache_service: OnlyHistoricalCacheService | None = None


class OnlyDataSource(
    OnlyHistoricalDataSource,
    OnlyMarketDataGateway,
    OnlyReferenceDataSource,
    OnlyPluginResource,
    Protocol,
):
    pass


class OnlyDataSourceFactory(Protocol):
    @property
    def descriptor(self) -> OnlyPluginDescriptor: ...

    def parse_config(self, extensions: Mapping[str, object]) -> object: ...

    def validate_request(self, request: OnlyDataSourceCreateRequest) -> Sequence[OnlyPluginValidationIssue]: ...

    def create(self, request: OnlyDataSourceCreateRequest) -> OnlyDataSource: ...
