"""Narrow real-time, historical and reference-data ports."""

from collections.abc import Callable
from typing import Protocol

from onlyalpha.data.enums import OnlyMarketDataCapability
from onlyalpha.data.identifiers import OnlyMarketDataSourceId
from onlyalpha.data.models import (
    OnlyHistoricalBarRequest,
    OnlyHistoricalDataStream,
    OnlyHistoricalQuoteRequest,
    OnlyHistoricalTradeRequest,
    OnlyMarketDataConnectionResult,
    OnlyMarketDataConnectionSnapshot,
    OnlyMarketDataInboundUpdate,
    OnlyMarketDataSubscriptionRequest,
    OnlyMarketDataSubscriptionResult,
    OnlyMarketDataUnsubscriptionRequest,
)
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyInstrumentId
from onlyalpha.domain.instrument import OnlyInstrument

OnlyMarketDataCapabilities = frozenset[OnlyMarketDataCapability]
OnlyMarketDataUpdateSink = Callable[[OnlyMarketDataInboundUpdate], None]


class OnlyMarketDataConnectionPort(Protocol):
    def connect(self) -> OnlyMarketDataConnectionResult: ...
    def authenticate(self) -> OnlyMarketDataConnectionResult: ...
    def disconnect(self) -> OnlyMarketDataConnectionResult: ...
    def connection_snapshot(self) -> OnlyMarketDataConnectionSnapshot: ...


class OnlyMarketDataSubscriptionPort(Protocol):
    def subscribe(self, request: OnlyMarketDataSubscriptionRequest) -> OnlyMarketDataSubscriptionResult: ...
    def unsubscribe(self, request: OnlyMarketDataUnsubscriptionRequest) -> OnlyMarketDataSubscriptionResult: ...


class OnlyMarketDataStreamPort(Protocol):
    def publish(self, update: OnlyMarketDataInboundUpdate) -> None: ...


class OnlyMarketDataGateway(OnlyMarketDataConnectionPort, OnlyMarketDataSubscriptionPort, Protocol):
    @property
    def source_id(self) -> OnlyMarketDataSourceId: ...

    @property
    def capabilities(self) -> OnlyMarketDataCapabilities: ...


class OnlyHistoricalDataSource(Protocol):
    @property
    def source_id(self) -> OnlyMarketDataSourceId: ...

    @property
    def capabilities(self) -> OnlyMarketDataCapabilities: ...

    def load_bars(self, request: OnlyHistoricalBarRequest) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]: ...
    def load_quotes(
        self, request: OnlyHistoricalQuoteRequest
    ) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]: ...
    def load_trades(
        self, request: OnlyHistoricalTradeRequest
    ) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]: ...


OnlyHistoricalBarSource = OnlyHistoricalDataSource
OnlyHistoricalQuoteSource = OnlyHistoricalDataSource
OnlyHistoricalTradeSource = OnlyHistoricalDataSource


class OnlyInstrumentDataSource(Protocol):
    def instrument(self, instrument_id: OnlyInstrumentId) -> OnlyInstrument | None: ...


class OnlyTradingCalendarDataSource(Protocol):
    def calendar(self, calendar_id: OnlyCalendarId) -> OnlyTradingCalendar | None: ...


class OnlyReferenceDataSource(
    OnlyInstrumentDataSource,
    OnlyTradingCalendarDataSource,
    Protocol,
):
    @property
    def source_id(self) -> OnlyMarketDataSourceId: ...


class OnlyCorporateActionDataSource(Protocol):
    """Reserved Port; complex corporate-action processing is out of scope."""

    @property
    def source_id(self) -> OnlyMarketDataSourceId: ...


class OnlyRemoteHistoricalDataSource(OnlyHistoricalDataSource, Protocol):
    """Exploration-only remote Port; deterministic replay requires a local versioned snapshot."""
