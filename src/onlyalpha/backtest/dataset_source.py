"""Immutable Dataset Snapshot adapter for the existing historical DataSource SPI."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from onlyalpha.data.enums import (
    OnlyDataSequenceSemantics,
    OnlyMarketDataCapability,
    OnlyMarketDataQualityFlag,
    OnlyMarketDataType,
)
from onlyalpha.data.historical.models import OnlyHistoricalFactRequest
from onlyalpha.data.identifiers import OnlyDataSequence
from onlyalpha.data.identity import only_bar_update_id
from onlyalpha.data.models import (
    OnlyBarUpdate,
    OnlyHistoricalBarRequest,
    OnlyHistoricalDataStream,
    OnlyHistoricalQuoteRequest,
    OnlyHistoricalTradeRequest,
    OnlyMarketDataInboundUpdate,
    OnlyMarketDataQuality,
)
from onlyalpha.data.ports import OnlyMarketDataCapabilities
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.plugin.capabilities import (
    OnlyCheckpointCapability,
    OnlyDataSourceCapabilities,
    OnlyPluginValidationIssue,
)
from onlyalpha.plugin.data_source import OnlyDataSource, OnlyDataSourceCreateRequest
from onlyalpha.plugin.descriptor import OnlyPluginDescriptor, OnlyPluginType
from onlyalpha.plugin.lifecycle import OnlyPluginHealth, OnlyPluginHealthStatus, OnlyPluginLifecycleState
from onlyalpha.plugin.version import ONLYALPHA_PLUGIN_API_VERSION
from onlyalpha.research.dataset import OnlyResearchDatasetSnapshotStore

_DESCRIPTOR = OnlyPluginDescriptor(
    "onlyalpha-dataset-snapshot",
    OnlyPluginType.DATA_SOURCE,
    "1.0.0",
    ONLYALPHA_PLUGIN_API_VERSION,
    "OnlyAlpha immutable Dataset Snapshot",
    "OnlyAlpha",
    OnlyDataSourceCapabilities(
        historical_bars=True,
        historical_reference_prices=True,
        historical_funding_rates=True,
        historical_settlements=True,
        supports_runtime_checkpoint=OnlyCheckpointCapability.STATELESS,
    ),
)


@dataclass(frozen=True, slots=True)
class OnlyBacktestDatasetSourceConfig:
    snapshot_fingerprint: str
    dataset_binding_fingerprint: str

    def __post_init__(self) -> None:
        for value in (self.snapshot_fingerprint, self.dataset_binding_fingerprint):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError("BACKTEST_DATASET_SOURCE_IDENTITY_INVALID")


class OnlyBacktestEconomicFactReader:
    def load_for_binding(self, binding_fingerprint: str) -> tuple[OnlyMarketDataInboundUpdate, ...]:
        return ()


class OnlyBacktestDatasetSourceFactory:
    def __init__(
        self,
        datasets: OnlyResearchDatasetSnapshotStore,
        economic_facts: OnlyBacktestEconomicFactReader | None = None,
    ) -> None:
        self._datasets = datasets
        self._economic_facts = economic_facts or OnlyBacktestEconomicFactReader()

    @property
    def descriptor(self) -> OnlyPluginDescriptor:
        return _DESCRIPTOR

    def parse_config(self, extensions: Mapping[str, object]) -> OnlyBacktestDatasetSourceConfig:
        if set(extensions) != {"snapshot_fingerprint", "dataset_binding_fingerprint"}:
            raise ValueError("BACKTEST_DATASET_SOURCE_CONFIGURATION_INVALID")
        return OnlyBacktestDatasetSourceConfig(
            str(extensions["snapshot_fingerprint"]),
            str(extensions["dataset_binding_fingerprint"]),
        )

    def validate_request(self, request: OnlyDataSourceCreateRequest) -> Sequence[OnlyPluginValidationIssue]:
        if not isinstance(request.plugin_config, OnlyBacktestDatasetSourceConfig):
            return (OnlyPluginValidationIssue("PLUGIN_CONFIG_INVALID", "Dataset Snapshot config is invalid"),)
        try:
            verified = self._datasets.load_verified_table(request.plugin_config.snapshot_fingerprint)
        except Exception:
            return (OnlyPluginValidationIssue("DATASET_SNAPSHOT_UNAVAILABLE", "Dataset Snapshot is unavailable"),)
        definition = verified.snapshot.definition
        configured_bar_types = tuple(request.bar_types.values())
        if (
            definition.instruments != tuple(sorted(request.instruments, key=str))
            or definition.time_range.start != request.clock.now()
            or not configured_bar_types
            or any(
                bar_type.specification != definition.bar_specification
                or bar_type.aggregation_source is not definition.aggregation_source
                for bar_type in configured_bar_types
            )
        ):
            return (OnlyPluginValidationIssue("DATASET_CONTRACT_MISMATCH", "Dataset and Runtime contract differ"),)
        return ()

    def create(self, request: OnlyDataSourceCreateRequest) -> OnlyDataSource:
        config = request.plugin_config
        if not isinstance(config, OnlyBacktestDatasetSourceConfig):
            raise TypeError("Dataset Snapshot Factory requires typed config")
        verified = self._datasets.load_verified_table(config.snapshot_fingerprint)
        bars = self._datasets.load_bars(config.snapshot_fingerprint)
        updates = tuple(
            OnlyMarketDataInboundUpdate(
                only_bar_update_id(
                    request.source_id,
                    bar.instrument_id,
                    bar.bar_type,
                    bar.bar_start,
                    request.data_version,
                ),
                request.runtime_id,
                request.source_id,
                OnlyDataSequence(index),
                request.data_version,
                bar.instrument_id,
                OnlyMarketDataType.BAR,
                OnlyBarUpdate(bar),
                OnlyTimestamp.from_datetime(bar.ts_event),
                OnlyTimestamp.from_datetime(bar.ts_init),
                OnlyMarketDataQuality(frozenset({OnlyMarketDataQualityFlag.UNADJUSTED})),
                metadata=(("dataset_snapshot_fingerprint", verified.snapshot.snapshot_fingerprint),),
                sequence_semantics=OnlyDataSequenceSemantics.MONOTONIC,
            )
            for index, bar in enumerate(bars, start=1)
        )
        facts = self._economic_facts.load_for_binding(config.dataset_binding_fingerprint)
        return cast(OnlyDataSource, OnlyBacktestDatasetSource(request, updates, facts))


class OnlyBacktestDatasetSource:
    _CAPABILITIES: OnlyMarketDataCapabilities = frozenset(
        {
            OnlyMarketDataCapability.QUERY_HISTORICAL_BAR,
            OnlyMarketDataCapability.QUERY_HISTORICAL_QUOTE,
            OnlyMarketDataCapability.QUERY_HISTORICAL_TRADE,
        }
    )

    def __init__(
        self,
        request: OnlyDataSourceCreateRequest,
        bars: tuple[OnlyMarketDataInboundUpdate, ...],
        facts: tuple[OnlyMarketDataInboundUpdate, ...],
    ) -> None:
        self._request = request
        self._bars = bars
        self._facts = facts
        self._state = OnlyPluginLifecycleState.CREATED

    @property
    def plugin_descriptor(self) -> OnlyPluginDescriptor:
        return _DESCRIPTOR

    @property
    def plugin_resource_id(self) -> str:
        return str(self.source_id)

    @property
    def source_id(self):  # type: ignore[no-untyped-def]
        return self._request.source_id

    @property
    def capabilities(self) -> OnlyMarketDataCapabilities:
        return self._CAPABILITIES

    @property
    def state(self) -> OnlyPluginLifecycleState:
        return self._state

    def initialize(self) -> None:
        if self._state is OnlyPluginLifecycleState.CREATED:
            self._state = OnlyPluginLifecycleState.INITIALIZED

    def connect(self) -> None:
        self.initialize()
        if self._state is OnlyPluginLifecycleState.INITIALIZED:
            self._state = OnlyPluginLifecycleState.CONNECTED

    def start(self) -> None:
        self.connect()
        if self._state is OnlyPluginLifecycleState.CONNECTED:
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

    def load_bars(self, request: OnlyHistoricalBarRequest) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        selected = tuple(
            update
            for update in self._bars
            if update.instrument_id in request.instrument_ids
            and update.bar_type in request.bar_types
            and request.data_range.start_time <= update.ts_event.to_datetime() < request.data_range.end_time
            and update.data_version == request.data_version
        )
        return OnlyHistoricalDataStream(selected, request.batch_size)

    def load_quotes(self, request: OnlyHistoricalQuoteRequest) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        return OnlyHistoricalDataStream((), request.batch_size)

    def load_trades(self, request: OnlyHistoricalTradeRequest) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        return OnlyHistoricalDataStream((), request.batch_size)

    def load_facts(self, request: OnlyHistoricalFactRequest) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        selected = tuple(
            update
            for update in self._facts
            if update.instrument_id == request.instrument_id
            and update.data_type is request.fact_family
            and request.time_range.start <= update.ts_event.to_datetime() < request.time_range.end
            and update.data_version == request.data_version
            and (
                request.reference_price_kind is None
                or getattr(getattr(update.payload, "fact", None), "kind", None) is request.reference_price_kind
            )
        )
        return OnlyHistoricalDataStream(selected, request.batch_size)


__all__ = [name for name in globals() if name.startswith("Only")]
