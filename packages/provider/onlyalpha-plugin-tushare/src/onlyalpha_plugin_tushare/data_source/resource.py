from __future__ import annotations

from onlyalpha.cache.historical.models import OnlyHistoricalDataRequest
from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.data.enums import (
    OnlyMarketDataCapability,
    OnlyMarketDataConnectionState,
    OnlyMarketDataRequestStatus,
    OnlyMarketDataType,
)
from onlyalpha.data.identifiers import (
    OnlyDataSequence,
    OnlyMarketDataGatewayId,
    OnlyMarketDataSourceId,
    OnlyMarketDataUpdateId,
)
from onlyalpha.data.models import (
    OnlyBarUpdate,
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
from onlyalpha.domain.enums import OnlyAdjustmentType
from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyInstrumentId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.plugin.data_source import OnlyDataSourceCreateRequest
from onlyalpha.plugin.lifecycle import (
    OnlyPluginHealth,
    OnlyPluginHealthStatus,
    OnlyPluginLifecycleState,
)

from ..config import OnlyTushareConfig
from ..descriptor import DATA_DESCRIPTOR
from ..errors import OnlyTushareError
from ..sdk.adapter import OnlyTushareClient, OnlyTushareSdkClient
from ..sdk.loader import load_tushare
from .provider import OnlyTushareHistoricalDataProvider
from .time_semantics import only_tushare_date_range


class OnlyTushareHistoricalDataSource:
    plugin_descriptor = DATA_DESCRIPTOR

    def __init__(
        self, request: OnlyDataSourceCreateRequest, config: OnlyTushareConfig
    ) -> None:
        self._request = request
        self._config = config
        self._state = OnlyPluginLifecycleState.CREATED

    @property
    def plugin_resource_id(self) -> str:
        return str(self.source_id)

    @property
    def source_id(self) -> OnlyMarketDataSourceId:
        return self._request.source_id

    @property
    def state(self) -> OnlyPluginLifecycleState:
        return self._state

    @property
    def capabilities(self) -> frozenset[OnlyMarketDataCapability]:
        return frozenset(
            {
                OnlyMarketDataCapability.QUERY_HISTORICAL_BAR,
                OnlyMarketDataCapability.QUERY_INSTRUMENT,
                OnlyMarketDataCapability.QUERY_CALENDAR,
            }
        )

    def initialize(self) -> None:
        self._state = OnlyPluginLifecycleState.INITIALIZED

    def connect(self) -> OnlyMarketDataConnectionResult:
        self._state = OnlyPluginLifecycleState.CONNECTED
        return self._connection(OnlyMarketDataConnectionState.CONNECTED)

    def authenticate(self) -> OnlyMarketDataConnectionResult:
        return self._connection(OnlyMarketDataConnectionState.READY)

    def start(self) -> None:
        self._state = OnlyPluginLifecycleState.RUNNING

    def stop(self) -> None:
        self._state = OnlyPluginLifecycleState.STOPPED

    close = stop

    def disconnect(self) -> OnlyMarketDataConnectionResult:
        self.stop()
        return self._connection(OnlyMarketDataConnectionState.DISCONNECTED)

    def health(self) -> OnlyPluginHealth:
        status = (
            OnlyPluginHealthStatus.HEALTHY
            if self._state is OnlyPluginLifecycleState.RUNNING
            else OnlyPluginHealthStatus.UNKNOWN
        )
        return OnlyPluginHealth(status)

    def load_bars(
        self, request: OnlyHistoricalBarRequest
    ) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        cache = self._request.historical_cache_service
        if cache is None:
            raise OnlyTushareError(
                "TUSHARE_CACHE_REQUIRED", "historical cache service is required"
            )
        updates = []
        sequence = 0
        for bar_type in sorted(request.bar_types, key=str):
            instrument = self._request.instruments[bar_type.instrument_id]
            if instrument.trading_calendar_id is None:
                raise OnlyTushareError(
                    "TUSHARE_CALENDAR_REQUIRED", "instrument calendar is required"
                )
            calendar = self._request.calendars[instrument.trading_calendar_id]
            time_range = OnlyTimeRange(
                request.data_range.start_time, request.data_range.end_time
            )
            reference = None
            if self._config.adjustment is OnlyAdjustmentType.FORWARD:
                reference = only_tushare_date_range(time_range, calendar)[1]
            cache_request = OnlyHistoricalDataRequest(
                bar_type.instrument_id,
                bar_type,
                time_range,
                self._config.adjustment,
                reference,
            )
            provider = OnlyTushareHistoricalDataProvider(
                str(self.source_id), instrument, calendar, self._create_client
            )
            result = cache.load(cache_request, provider, self._config.cache_policy)
            for bar in result.records:
                sequence += 1
                timestamp = OnlyTimestamp.from_datetime(bar.ts_event)
                updates.append(
                    OnlyMarketDataInboundUpdate(
                        OnlyMarketDataUpdateId(f"tushare-cache-{sequence}"),
                        self._request.runtime_id,
                        self._request.source_id,
                        OnlyDataSequence(sequence),
                        request.data_version,
                        bar.instrument_id,
                        OnlyMarketDataType.BAR,
                        OnlyBarUpdate(bar),
                        timestamp,
                        timestamp,
                        metadata=(
                            (
                                "content_fingerprint",
                                result.manifest.content_fingerprint,
                            ),
                        ),
                    )
                )
        return OnlyHistoricalDataStream(tuple(updates), request.batch_size)

    def load_quotes(
        self, request: OnlyHistoricalQuoteRequest
    ) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        return OnlyHistoricalDataStream((), request.batch_size)

    def load_trades(
        self, request: OnlyHistoricalTradeRequest
    ) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        return OnlyHistoricalDataStream((), request.batch_size)

    def subscribe(
        self, request: OnlyMarketDataSubscriptionRequest
    ) -> OnlyMarketDataSubscriptionResult:
        return OnlyMarketDataSubscriptionResult(
            OnlyMarketDataRequestStatus.UNSUPPORTED_CAPABILITY,
            None,
            "historical-only plugin",
        )

    def unsubscribe(
        self, request: OnlyMarketDataUnsubscriptionRequest
    ) -> OnlyMarketDataSubscriptionResult:
        return OnlyMarketDataSubscriptionResult(
            OnlyMarketDataRequestStatus.UNSUPPORTED_CAPABILITY,
            None,
            "historical-only plugin",
        )

    def instrument(self, instrument_id: OnlyInstrumentId) -> OnlyInstrument | None:
        return self._request.instruments.get(instrument_id)

    def calendar(self, calendar_id: OnlyCalendarId) -> OnlyTradingCalendar | None:
        return self._request.calendars.get(calendar_id)

    def market_rule(self, instrument_id: OnlyInstrumentId) -> None:
        return None

    def _create_client(self) -> OnlyTushareClient:
        return OnlyTushareSdkClient(load_tushare(), self._config.resolve_token())

    def _connection(
        self, state: OnlyMarketDataConnectionState
    ) -> OnlyMarketDataConnectionResult:
        return OnlyMarketDataConnectionResult(
            OnlyMarketDataRequestStatus.ACCEPTED,
            OnlyMarketDataConnectionSnapshot(
                OnlyMarketDataGatewayId(str(self.source_id)), state
            ),
        )
