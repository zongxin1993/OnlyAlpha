"""Public DataSource plugin Factory SPI."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from logging import Logger
from pathlib import Path
from typing import Protocol, runtime_checkable

from onlyalpha.cache.historical.service import OnlyHistoricalCacheService
from onlyalpha.config.models import OnlyDataSourceCoverageConfig, OnlyUniverseConfig
from onlyalpha.core.clock import OnlyClock
from onlyalpha.data.evidence import OnlyProviderEvidenceSink
from onlyalpha.data.historical.models import OnlyHistoricalFactRequest
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
    runtime_state_root: Path | None = None
    provider_evidence_sink: OnlyProviderEvidenceSink | None = None
    durable_recording_required: bool = False
    kernel_economic_requests: tuple[OnlyHistoricalFactRequest, ...] = ()


@dataclass(frozen=True, slots=True)
class OnlyDataSourceInstrumentCatalogRequestV1:
    """Provider reference lookup by exact canonical instrument or by symbol query."""

    plugin_config: object
    instrument_ids: tuple[str, ...] = ()
    query: str = ""
    limit: int = 25

    def __post_init__(self) -> None:
        if self.limit <= 0 or len(self.instrument_ids) > self.limit:
            raise ValueError("DATA_SOURCE_INSTRUMENT_CATALOG_REQUEST_INVALID")
        if bool(self.instrument_ids) and self.query.strip():
            raise ValueError("DATA_SOURCE_INSTRUMENT_CATALOG_REQUEST_AMBIGUOUS")


@dataclass(frozen=True, slots=True)
class OnlyDataSourceMarketIdentityV1:
    """Canonical venue/market identity a DataSource implementation records."""

    venue: str
    market: str

    def __post_init__(self) -> None:
        if not self.venue.strip() or not self.market.strip():
            raise ValueError("DATA_SOURCE_MARKET_IDENTITY_INVALID")


@dataclass(frozen=True, slots=True)
class OnlyDataSourceInstrumentV1:
    """Canonical instrument projection published by one DataSource implementation."""

    instrument: OnlyInstrument
    display_symbol: str
    venue: str
    market: str
    market_data_capabilities: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.display_symbol.strip() or not self.venue.strip() or not self.market.strip():
            raise ValueError("DATA_SOURCE_INSTRUMENT_PROJECTION_INVALID")


@runtime_checkable
class OnlyDataSourceInstrumentCatalog(Protocol):
    """Optional public SPI for provider reference instrument projection."""

    def market_identity(self, plugin_config: object) -> OnlyDataSourceMarketIdentityV1: ...

    def list_instruments(
        self, request: OnlyDataSourceInstrumentCatalogRequestV1
    ) -> tuple[OnlyDataSourceInstrumentV1, ...]: ...


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


@runtime_checkable
class OnlyDataSourceIntegrationRuntimeAdapter(Protocol):
    def parse_runtime_integration_config(
        self,
        public_configuration: Mapping[str, object],
        resolved_secrets: Mapping[str, str],
    ) -> object: ...
