"""Public DataSource plugin Factory SPI."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
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
from onlyalpha.data.models import OnlyMarketDataConnectionSnapshot, OnlyRealtimeBarPreviewV1
from onlyalpha.data.ports import (
    OnlyHistoricalDataSource,
    OnlyMarketDataGateway,
    OnlyMarketDataUpdateSink,
    OnlyReferenceDataSource,
)
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.enums import OnlyAssetClass
from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.market import OnlyBarType
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.market_data.resolution import OnlyBarCapability
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
    market_data_preview_sink: Callable[[OnlyRealtimeBarPreviewV1], None] | None = None
    market_data_connection_sink: Callable[[OnlyMarketDataConnectionSnapshot], None] | None = None
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
    asset_class: str | None = None
    instrument_types: tuple[str, ...] = ()
    deadline_monotonic: float | None = None
    snapshot: bool = False

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 10001 or len(self.instrument_ids) > self.limit:
            raise ValueError("DATA_SOURCE_INSTRUMENT_CATALOG_REQUEST_INVALID")
        if self.deadline_monotonic is not None and (
            not math.isfinite(self.deadline_monotonic) or self.deadline_monotonic <= 0
        ):
            raise ValueError("DATA_SOURCE_INSTRUMENT_CATALOG_REQUEST_INVALID")
        if bool(self.instrument_ids) and (self.query.strip() or self.snapshot):
            raise ValueError("DATA_SOURCE_INSTRUMENT_CATALOG_REQUEST_AMBIGUOUS")


@dataclass(frozen=True, slots=True)
class OnlyDataSourceMarketIdentityV1:
    """Canonical Market Source identity a DataSource implementation declares.

    `source_id` is the provider-owned canonical identity of the external market-data
    universe the facts belong to. It changes when the semantic universe changes (for
    example a production venue versus that provider's own sandbox venue) and does not
    change for non-semantic runtime settings such as timeouts or reconnect bounds.
    `environment` is the provider-owned environment token behind that identity.
    """

    venue: str
    market: str
    environment: str
    source_id: str

    def __post_init__(self) -> None:
        if not all(item.strip() for item in (self.venue, self.market, self.environment, self.source_id)):
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


@dataclass(frozen=True, slots=True)
class OnlyDataSourceDiscoveryCapabilitiesV1:
    """Provider-declared searchable asset scope; snapshot matching uses literal symbols."""

    asset_classes: tuple[str, ...]
    catalogue_snapshot: bool = False
    quotes: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.catalogue_snapshot) is not bool
            or type(self.quotes) is not bool
            or not isinstance(self.asset_classes, tuple)
            or not self.asset_classes
            or len(set(self.asset_classes)) != len(self.asset_classes)
            or any(item not in {kind.value for kind in OnlyAssetClass} for item in self.asset_classes)
        ):
            raise ValueError("DATA_SOURCE_DISCOVERY_CAPABILITIES_INVALID")


@dataclass(frozen=True, slots=True)
class OnlyDataSourceQuoteRequestV1:
    plugin_config: object
    instrument_ids: tuple[str, ...]
    deadline_monotonic: float

    def __post_init__(self) -> None:
        if (
            not 1 <= len(self.instrument_ids) <= 25
            or len(set(self.instrument_ids)) != len(self.instrument_ids)
            or not math.isfinite(self.deadline_monotonic)
            or self.deadline_monotonic <= 0
        ):
            raise ValueError("DATA_SOURCE_QUOTE_REQUEST_INVALID")


@dataclass(frozen=True, slots=True)
class OnlyDataSourceQuoteV1:
    instrument_id: str
    last_price: str
    change_pct: str | None
    change_basis: str | None
    ts_event_ns: int


@runtime_checkable
class OnlyDataSourceDiscovery(Protocol):
    def discovery_capabilities(self, plugin_config: object) -> OnlyDataSourceDiscoveryCapabilitiesV1: ...


@runtime_checkable
class OnlyDataSourceQuotes(Protocol):
    def quotes(self, request: OnlyDataSourceQuoteRequestV1) -> tuple[OnlyDataSourceQuoteV1, ...]: ...


@runtime_checkable
class OnlyDataSourceTimeBarCalendar(Protocol):
    """Provider-owned session authority for derived intraday Time Bars."""

    def time_bar_calendar(self, plugin_config: object) -> OnlyTradingCalendar: ...


@runtime_checkable
class OnlyDataSourceBarCapabilities(Protocol):
    """Published native bar semantics for an exact source and instrument."""

    def bar_capabilities(
        self, plugin_config: object, instrument_id: OnlyInstrumentId
    ) -> tuple[OnlyBarCapability, ...]: ...


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
