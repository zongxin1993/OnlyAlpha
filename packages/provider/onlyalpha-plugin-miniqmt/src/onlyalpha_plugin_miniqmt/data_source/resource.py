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
    OnlyMarketDataUpdateId,
)
from onlyalpha.data.models import (
    OnlyBarUpdate,
    OnlyHistoricalDataStream,
    OnlyMarketDataConnectionResult,
    OnlyMarketDataConnectionSnapshot,
    OnlyMarketDataInboundUpdate,
    OnlyMarketDataSubscriptionRequest,
    OnlyMarketDataSubscriptionResult,
    OnlyMarketDataUnsubscriptionRequest,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.plugin.lifecycle import OnlyPluginLifecycleState

from ..descriptor import DATA_DESCRIPTOR
from ..lifecycle import OnlyMiniQmtLifecycle
from .live import OnlyMiniQmtLiveNormalizer


class OnlyMiniQmtDataSource:
    def __init__(self, request: object, config: object, xtdata: object) -> None:
        self._request, self._config, self._xtdata = request, config, xtdata
        self._life = OnlyMiniQmtLifecycle()
        self._subscriptions: dict[str, tuple[int, ...]] = {}
        self._normalizer = OnlyMiniQmtLiveNormalizer(request)

    plugin_descriptor = DATA_DESCRIPTOR

    @property
    def plugin_resource_id(self) -> str:
        return str(self.source_id)

    @property
    def source_id(self):
        return self._request.source_id

    @property
    def state(self):
        return self._life.state

    @property
    def capabilities(self):
        return frozenset(
            {
                OnlyMarketDataCapability.CONNECT,
                OnlyMarketDataCapability.SUBSCRIBE_BAR,
                OnlyMarketDataCapability.SUBSCRIBE_QUOTE,
                OnlyMarketDataCapability.UNSUBSCRIBE,
                OnlyMarketDataCapability.QUERY_HISTORICAL_BAR,
                OnlyMarketDataCapability.QUERY_INSTRUMENT,
                OnlyMarketDataCapability.QUERY_CALENDAR,
            }
        )

    def initialize(self) -> None:
        self._life.initialize()

    def connect(self) -> OnlyMarketDataConnectionResult:
        self._life.state = OnlyPluginLifecycleState.CONNECTED
        return self._connection_result(
            OnlyMarketDataRequestStatus.ACCEPTED,
            OnlyMarketDataConnectionState.CONNECTED,
        )

    def authenticate(self) -> OnlyMarketDataConnectionResult:
        return self._connection_result(OnlyMarketDataRequestStatus.ACCEPTED, OnlyMarketDataConnectionState.READY)

    def disconnect(self) -> OnlyMarketDataConnectionResult:
        self.stop()
        return self._connection_result(
            OnlyMarketDataRequestStatus.ACCEPTED,
            OnlyMarketDataConnectionState.DISCONNECTED,
        )

    def connection_snapshot(self) -> OnlyMarketDataConnectionSnapshot:
        state = (
            OnlyMarketDataConnectionState.READY
            if self.state is OnlyPluginLifecycleState.RUNNING
            else OnlyMarketDataConnectionState.CONNECTED
            if self.state is OnlyPluginLifecycleState.CONNECTED
            else OnlyMarketDataConnectionState.DISCONNECTED
        )
        return OnlyMarketDataConnectionSnapshot(OnlyMarketDataGatewayId(str(self.source_id)), state)

    def start(self) -> None:
        self._life.start()

    def stop(self) -> None:
        for sequences in tuple(self._subscriptions.values()):
            for sequence in sequences:
                self._xtdata.unsubscribe_quote(sequence)
        self._subscriptions.clear()
        self._life.stop()

    close = stop

    def health(self):
        return self._life.health()

    def load_bars(self, request):
        from .historical import load_bars

        if self._request.historical_cache_service is not None:
            from .provider import OnlyMiniQmtHistoricalDataProvider

            provider = OnlyMiniQmtHistoricalDataProvider(
                self._xtdata, self._request, request.data_version, request.batch_size
            )
            updates = []
            sequence = 0
            for bar_type in sorted(request.bar_types, key=str):
                cache_request = OnlyHistoricalDataRequest(
                    bar_type.instrument_id,
                    bar_type,
                    OnlyTimeRange(request.data_range.start_time, request.data_range.end_time),
                )
                result = self._request.historical_cache_service.load(cache_request, provider, self._config.cache_policy)
                for bar in result.records:
                    sequence += 1
                    timestamp = OnlyTimestamp.from_datetime(bar.ts_event)
                    updates.append(
                        OnlyMarketDataInboundUpdate(
                            OnlyMarketDataUpdateId(f"miniqmt-cache-{sequence}"),
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

        return OnlyHistoricalDataStream(load_bars(self._xtdata, self._request, request), request.batch_size)

    def load_quotes(self, request):
        return OnlyHistoricalDataStream((), request.batch_size)

    def load_trades(self, request):
        return OnlyHistoricalDataStream((), request.batch_size)

    def subscribe(self, request: OnlyMarketDataSubscriptionRequest) -> OnlyMarketDataSubscriptionResult:
        if self._request.market_data_sink is None:
            return OnlyMarketDataSubscriptionResult(
                OnlyMarketDataRequestStatus.REJECTED,
                None,
                "Runtime market_data_sink is required",
            )
        if OnlyMarketDataType.TRADE in request.data_types:
            return OnlyMarketDataSubscriptionResult(
                OnlyMarketDataRequestStatus.UNSUPPORTED_CAPABILITY,
                None,
                "XtQuant snapshot ticks cannot be represented as individual trades",
            )
        sequences: list[int] = []
        for instrument_id in sorted(request.instrument_ids, key=str):
            if OnlyMarketDataType.QUOTE in request.data_types:
                sequences.append(self._subscribe(instrument_id, "tick"))
            for bar_type in sorted(
                (item for item in request.bar_types if item.instrument_id == instrument_id),
                key=str,
            ):
                sequences.append(self._subscribe(instrument_id, self._normalizer.period(bar_type)))
        if not sequences:
            return OnlyMarketDataSubscriptionResult(OnlyMarketDataRequestStatus.REJECTED, None, "empty subscription")
        subscription_id = f"miniqmt:{request.request_id}"
        self._subscriptions[subscription_id] = tuple(sequences)
        return OnlyMarketDataSubscriptionResult(OnlyMarketDataRequestStatus.ACCEPTED, subscription_id)

    def unsubscribe(self, request: OnlyMarketDataUnsubscriptionRequest) -> OnlyMarketDataSubscriptionResult:
        sequences = self._subscriptions.pop(request.subscription_id, ())
        for sequence in sequences:
            self._xtdata.unsubscribe_quote(sequence)
        status = OnlyMarketDataRequestStatus.ACCEPTED if sequences else OnlyMarketDataRequestStatus.REJECTED
        return OnlyMarketDataSubscriptionResult(status, request.subscription_id if sequences else None)

    def instrument(self, instrument_id):
        from .reference import instrument

        return instrument(self._xtdata, instrument_id)

    def calendar(self, calendar_id):
        from .reference import calendar

        return calendar(self._xtdata, calendar_id)

    def market_rule(self, instrument_id):
        return None

    def _subscribe(self, instrument_id, period: str) -> int:
        from ..mapping.exchange import to_xt_symbol

        symbol = to_xt_symbol(instrument_id)
        return self._xtdata.subscribe_quote(
            symbol,
            period=period,
            callback=lambda raw: self._normalizer.publish(raw, instrument_id, period),
        )

    def _connection_result(self, status, state):
        return OnlyMarketDataConnectionResult(
            status,
            OnlyMarketDataConnectionSnapshot(OnlyMarketDataGatewayId(str(self.source_id)), state),
        )
