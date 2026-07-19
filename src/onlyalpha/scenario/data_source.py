"""Exact, deterministic Scenario bars exposed through the public DataSource SPI."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import cast

from onlyalpha.data.enums import OnlyMarketDataCapability, OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataSequence, OnlyMarketDataUpdateId
from onlyalpha.data.models import OnlyBarUpdate, OnlyMarketDataInboundUpdate
from onlyalpha.data.ports import OnlyMarketDataCapabilities
from onlyalpha.data.sources import OnlyInMemoryHistoricalDataSource
from onlyalpha.domain.enums import OnlyAdjustmentType, OnlySessionType
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBar
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.plugin.capabilities import OnlyDataSourceCapabilities, OnlyPluginValidationIssue
from onlyalpha.plugin.data_source import OnlyDataSource, OnlyDataSourceCreateRequest
from onlyalpha.plugin.descriptor import OnlyPluginDescriptor, OnlyPluginType
from onlyalpha.plugin.lifecycle import OnlyPluginHealth, OnlyPluginHealthStatus, OnlyPluginLifecycleState
from onlyalpha.plugin.version import ONLYALPHA_PLUGIN_API_VERSION

ONLY_SCENARIO_DATA_PLUGIN = OnlyPluginDescriptor(
    "scenario-exact",
    OnlyPluginType.DATA_SOURCE,
    "1.0.0",
    ONLYALPHA_PLUGIN_API_VERSION,
    "OnlyAlpha Exact Scenario Data",
    "OnlyAlpha",
    OnlyDataSourceCapabilities(historical_bars=True),
)


@dataclass(frozen=True, slots=True)
class OnlyScenarioDataSourceConfig:
    bars: tuple[Mapping[str, object], ...]


class OnlyScenarioHistoricalDataSource(OnlyInMemoryHistoricalDataSource):
    def __init__(self, request: OnlyDataSourceCreateRequest, updates: tuple[OnlyMarketDataInboundUpdate, ...]) -> None:
        super().__init__(request.source_id, updates)
        self._state = OnlyPluginLifecycleState.CREATED

    @property
    def plugin_descriptor(self) -> OnlyPluginDescriptor:
        return ONLY_SCENARIO_DATA_PLUGIN

    @property
    def plugin_resource_id(self) -> str:
        return str(self.source_id)

    @property
    def state(self) -> OnlyPluginLifecycleState:
        return self._state

    def initialize(self) -> None:
        if self._state is OnlyPluginLifecycleState.CREATED:
            self._state = OnlyPluginLifecycleState.INITIALIZED

    def connect(self) -> None:
        self.initialize()
        self._state = OnlyPluginLifecycleState.CONNECTED

    def start(self) -> None:
        self.connect()
        self._state = OnlyPluginLifecycleState.RUNNING

    def stop(self) -> None:
        self._state = OnlyPluginLifecycleState.STOPPED

    def close(self) -> None:
        self.stop()

    def health(self) -> OnlyPluginHealth:
        status = (
            OnlyPluginHealthStatus.HEALTHY
            if self._state is OnlyPluginLifecycleState.RUNNING
            else OnlyPluginHealthStatus.STOPPED
            if self._state is OnlyPluginLifecycleState.STOPPED
            else OnlyPluginHealthStatus.UNKNOWN
        )
        return OnlyPluginHealth(status)

    @property
    def capabilities(self) -> OnlyMarketDataCapabilities:
        return frozenset({OnlyMarketDataCapability.QUERY_HISTORICAL_BAR})


class OnlyScenarioDataSourceFactory:
    @property
    def descriptor(self) -> OnlyPluginDescriptor:
        return ONLY_SCENARIO_DATA_PLUGIN

    def parse_config(self, extensions: Mapping[str, object]) -> OnlyScenarioDataSourceConfig:
        raw = extensions.get("bars")
        if not isinstance(raw, list) or any(not isinstance(item, Mapping) for item in raw):
            raise ValueError("scenario-exact requires extensions.bars")
        return OnlyScenarioDataSourceConfig(tuple(cast(Mapping[str, object], item) for item in raw))

    def validate_request(self, request: OnlyDataSourceCreateRequest) -> Sequence[OnlyPluginValidationIssue]:
        return (
            ()
            if isinstance(request.plugin_config, OnlyScenarioDataSourceConfig)
            else (OnlyPluginValidationIssue("PLUGIN_CONFIG_INVALID", "invalid exact Scenario data config"),)
        )

    def create(self, request: OnlyDataSourceCreateRequest) -> OnlyDataSource:
        config = request.plugin_config
        if not isinstance(config, OnlyScenarioDataSourceConfig):
            raise TypeError("Scenario DataSource requires OnlyScenarioDataSourceConfig")
        updates = tuple(self._update(request, item) for item in config.bars)
        return cast(OnlyDataSource, OnlyScenarioHistoricalDataSource(request, updates))

    @staticmethod
    def _update(request: OnlyDataSourceCreateRequest, raw: Mapping[str, object]) -> OnlyMarketDataInboundUpdate:
        instrument_id = OnlyInstrumentId.parse(str(raw["instrument_id"]))
        instrument = request.instruments[instrument_id]
        bar_type = request.bar_types[instrument_id]
        ts_event = OnlyTimestamp.from_unix_nanos(int(str(raw["ts_event_ns"])))
        ts_init = OnlyTimestamp.from_unix_nanos(int(str(raw["ts_init_ns"])))
        sequence = int(str(raw["sequence"]))
        event = ts_event.to_datetime()
        bar = OnlyBar(
            bar_type=bar_type,
            open=OnlyPrice(Decimal(str(raw["open"])), instrument.price_precision),
            high=OnlyPrice(Decimal(str(raw["high"])), instrument.price_precision),
            low=OnlyPrice(Decimal(str(raw["low"])), instrument.price_precision),
            close=OnlyPrice(Decimal(str(raw["close"])), instrument.price_precision),
            volume=OnlyQuantity(Decimal(str(raw["volume"])), instrument.quantity_precision),
            quote_volume=None,
            turnover=None,
            trade_count=None,
            open_interest=None,
            bar_start=event - timedelta(minutes=bar_type.specification.step),
            bar_end=event,
            ts_event=event,
            ts_init=ts_init.to_datetime(),
            is_closed=True,
            revision=0,
            adjustment_type=OnlyAdjustmentType.RAW,
            trading_day=event.date(),
            session_type=OnlySessionType.CONTINUOUS,
        )
        return OnlyMarketDataInboundUpdate(
            OnlyMarketDataUpdateId(f"scenario-{sequence}"),
            request.runtime_id,
            request.source_id,
            OnlyDataSequence(sequence),
            request.data_version,
            instrument_id,
            OnlyMarketDataType.BAR,
            OnlyBarUpdate(bar),
            ts_event,
            ts_init,
        )
