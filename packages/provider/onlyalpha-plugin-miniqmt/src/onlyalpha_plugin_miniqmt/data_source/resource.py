import hashlib
import json
from datetime import timedelta
from threading import Lock
from typing import Any

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
from onlyalpha.data.warmup import (
    OnlyHistoricalWarmupDiagnostic,
    OnlyHistoricalWarmupRequest,
    OnlyHistoricalWarmupResult,
    OnlyHistoricalWarmupStatus,
)
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyInstrumentId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.plugin.data_source import OnlyDataSourceCreateRequest
from onlyalpha.plugin.lifecycle import OnlyPluginHealth, OnlyPluginLifecycleState

from ..config import OnlyMiniQmtConfig
from ..descriptor import DATA_DESCRIPTOR
from ..lifecycle import OnlyMiniQmtLifecycle
from .live import OnlyMiniQmtLiveNormalizer


class OnlyMiniQmtDataSource:
    def __init__(self, request: OnlyDataSourceCreateRequest, config: OnlyMiniQmtConfig, xtdata: Any) -> None:
        self._request, self._config, self._xtdata = request, config, xtdata
        self._life = OnlyMiniQmtLifecycle()
        self._subscriptions: dict[str, tuple[int, ...]] = {}
        self._normalizer = OnlyMiniQmtLiveNormalizer(request)
        self._subscription_lock = Lock()
        self._accepting_callbacks = True
        self._shutdown_started = False

    plugin_descriptor = DATA_DESCRIPTOR

    @property
    def plugin_resource_id(self) -> str:
        return str(self.source_id)

    @property
    def source_id(self) -> OnlyMarketDataSourceId:
        return self._request.source_id

    @property
    def state(self) -> OnlyPluginLifecycleState:
        return self._life.state

    @property
    def capabilities(self) -> frozenset[OnlyMarketDataCapability]:
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
        with self._subscription_lock:
            self._accepting_callbacks = False
            self._shutdown_started = True
            subscriptions = tuple(self._subscriptions.values())
            self._subscriptions.clear()
        failure: Exception | None = None
        for sequences in subscriptions:
            for sequence in sequences:
                try:
                    self._xtdata.unsubscribe_quote(sequence)
                except Exception as exc:
                    failure = failure or exc
        self._life.stop()
        if failure is not None:
            raise failure

    close = stop

    def health(self) -> OnlyPluginHealth:
        return self._life.health()

    def set_live_sequence_floor(self, sequence: int) -> None:
        self._normalizer.set_sequence_floor(sequence)

    def load_bars(self, request: OnlyHistoricalBarRequest) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        from .historical import load_bars

        if self._request.historical_cache_service is not None:
            from .provider import OnlyMiniQmtHistoricalDataProvider

            provider = OnlyMiniQmtHistoricalDataProvider(
                self._xtdata, self._request, request.data_version, request.batch_size
            )
            updates: list[OnlyMarketDataInboundUpdate] = []
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

    def load_warmup(self, request: OnlyHistoricalWarmupRequest) -> OnlyHistoricalWarmupResult:
        from onlyalpha.cache.historical.models import OnlyHistoricalDataRequest
        from onlyalpha.core.ranges import OnlyTimeRange

        from ..historical_worker.cache import (
            OnlyMiniQmtIsolatedWarmupCacheProvider,
            OnlyMiniQmtWarmupFetchError,
        )
        from ..historical_worker.client import OnlyMiniQmtHistoricalIsolatedClient

        if self._request.runtime_state_root is None:
            raise RuntimeError("MiniQMT isolated warmup requires a Runtime state root")
        client = OnlyMiniQmtHistoricalIsolatedClient(
            self._request,
            self._config.require_path(),
            self._request.runtime_state_root / "warmup",
        )
        cache = self._request.historical_cache_service
        if cache is None:
            return client.load_warmup(request)
        end = request.end_time.to_datetime()
        cache_request = OnlyHistoricalDataRequest(
            request.instrument_id,
            request.bar_type,
            OnlyTimeRange(request.requested_start.to_datetime(), end + timedelta(microseconds=1)),
            request.adjustment_type,
            metadata={
                "data_version": str(request.data_version),
                "compatibility_profile_id": request.compatibility_profile_id,
            },
        )
        provider = OnlyMiniQmtIsolatedWarmupCacheProvider(client, request, str(self.source_id))
        try:
            loaded = cache.load(cache_request, provider, self._config.cache_policy)
        except OnlyMiniQmtWarmupFetchError as exc:
            if isinstance(exc.result, OnlyHistoricalWarmupResult):
                return exc.result
            raise
        except Exception as exc:
            request_fingerprint = _warmup_request_fingerprint(request)
            return OnlyHistoricalWarmupResult(
                status=OnlyHistoricalWarmupStatus.PROTOCOL_ERROR,
                bars=(),
                request_fingerprint=request_fingerprint,
                content_fingerprint=None,
                first_bar_end=None,
                last_bar_end=None,
                bootstrap_observed_at=request.bootstrap_observed_at,
                requested_start=request.requested_start,
                requested_end=request.end_time,
                provider_raw_bar_count=0,
                accepted_bar_count=0,
                rejected_out_of_range_count=0,
                provider_raw_last_bar_end=None,
                accepted_last_bar_end=None,
                provider="miniqmt",
                provider_version=None,
                compatibility_profile_id=request.compatibility_profile_id,
                diagnostic=OnlyHistoricalWarmupDiagnostic(
                    "MINIQMT_HISTORICAL_CACHE_FAILED",
                    str(exc),
                    None,
                    None,
                    None,
                    request_fingerprint,
                    None,
                    None,
                    request.compatibility_profile_id,
                    str(self._config.userdata_mini_path.resolve()),
                ),
            )
        bars = tuple(loaded.records[-request.required_bars :])
        if len(bars) < request.required_bars:
            request_fingerprint = _warmup_request_fingerprint(request)
            return OnlyHistoricalWarmupResult(
                status=OnlyHistoricalWarmupStatus.INVALID_DATA,
                bars=(),
                request_fingerprint=request_fingerprint,
                content_fingerprint=None,
                first_bar_end=None,
                last_bar_end=None,
                bootstrap_observed_at=request.bootstrap_observed_at,
                requested_start=request.requested_start,
                requested_end=request.end_time,
                provider_raw_bar_count=0,
                accepted_bar_count=0,
                rejected_out_of_range_count=0,
                provider_raw_last_bar_end=None,
                accepted_last_bar_end=None,
                provider="miniqmt",
                provider_version=None,
                compatibility_profile_id=request.compatibility_profile_id,
                diagnostic=OnlyHistoricalWarmupDiagnostic(
                    "MINIQMT_HISTORICAL_CACHE_INSUFFICIENT",
                    "validated historical cache does not contain the required warmup Bars",
                    None,
                    None,
                    None,
                    request_fingerprint,
                    None,
                    None,
                    request.compatibility_profile_id,
                    str(self._config.userdata_mini_path.resolve()),
                ),
            )
        request_fingerprint = _warmup_request_fingerprint(request)
        content_fingerprint = hashlib.sha256("\n".join(bar.to_json() for bar in bars).encode()).hexdigest()
        metadata = loaded.manifest.metadata
        provider_raw_last_ns = metadata.get("provider_raw_last_bar_end_ns")
        accepted_last_ns = metadata.get("accepted_last_bar_end_ns")
        return OnlyHistoricalWarmupResult(
            status=OnlyHistoricalWarmupStatus.SUCCESS,
            bars=bars,
            request_fingerprint=request_fingerprint,
            content_fingerprint=content_fingerprint,
            first_bar_end=OnlyTimestamp.from_datetime(bars[0].bar_end),
            last_bar_end=OnlyTimestamp.from_datetime(bars[-1].bar_end),
            bootstrap_observed_at=request.bootstrap_observed_at,
            requested_start=request.requested_start,
            requested_end=request.end_time,
            provider_raw_bar_count=_metadata_integer(
                metadata.get("provider_raw_bar_count", len(bars)), "provider_raw_bar_count"
            ),
            accepted_bar_count=len(bars),
            rejected_out_of_range_count=_metadata_integer(
                metadata.get("rejected_out_of_range_count", 0), "rejected_out_of_range_count"
            ),
            provider_raw_last_bar_end=OnlyTimestamp.from_datetime(bars[-1].bar_end)
            if provider_raw_last_ns is None
            else OnlyTimestamp.from_unix_nanos(_metadata_integer(provider_raw_last_ns, "provider_raw_last_bar_end_ns")),
            accepted_last_bar_end=OnlyTimestamp.from_datetime(bars[-1].bar_end)
            if accepted_last_ns is None
            else OnlyTimestamp.from_unix_nanos(_metadata_integer(accepted_last_ns, "accepted_last_bar_end_ns")),
            provider="miniqmt",
            provider_version=None if metadata.get("provider_version") is None else str(metadata["provider_version"]),
            compatibility_profile_id=request.compatibility_profile_id,
            diagnostic=None,
        )

    def load_quotes(self, request: OnlyHistoricalQuoteRequest) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        return OnlyHistoricalDataStream((), request.batch_size)

    def load_trades(self, request: OnlyHistoricalTradeRequest) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        return OnlyHistoricalDataStream((), request.batch_size)

    def subscribe(self, request: OnlyMarketDataSubscriptionRequest) -> OnlyMarketDataSubscriptionResult:
        with self._subscription_lock:
            if self._shutdown_started:
                return OnlyMarketDataSubscriptionResult(
                    OnlyMarketDataRequestStatus.REJECTED,
                    None,
                    "MiniQMT DataSource shutdown has started",
                )
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
        with self._subscription_lock:
            if self._shutdown_started:
                for sequence in sequences:
                    self._xtdata.unsubscribe_quote(sequence)
                return OnlyMarketDataSubscriptionResult(
                    OnlyMarketDataRequestStatus.REJECTED,
                    None,
                    "MiniQMT DataSource shutdown started during subscription",
                )
            self._subscriptions[subscription_id] = tuple(sequences)
        return OnlyMarketDataSubscriptionResult(OnlyMarketDataRequestStatus.ACCEPTED, subscription_id)

    def unsubscribe(self, request: OnlyMarketDataUnsubscriptionRequest) -> OnlyMarketDataSubscriptionResult:
        with self._subscription_lock:
            sequences = self._subscriptions.pop(request.subscription_id, ())
        for sequence in sequences:
            self._xtdata.unsubscribe_quote(sequence)
        status = OnlyMarketDataRequestStatus.ACCEPTED if sequences else OnlyMarketDataRequestStatus.REJECTED
        return OnlyMarketDataSubscriptionResult(status, request.subscription_id if sequences else None)

    def instrument(self, instrument_id: OnlyInstrumentId) -> OnlyInstrument | None:
        from .reference import instrument

        return instrument(self._xtdata, instrument_id)

    def calendar(self, calendar_id: OnlyCalendarId) -> OnlyTradingCalendar | None:
        from .reference import calendar

        return calendar(self._xtdata, calendar_id)

    def market_rule(self, instrument_id: OnlyInstrumentId) -> None:
        return None

    def _subscribe(self, instrument_id: OnlyInstrumentId, period: str) -> int:
        from ..mapping.exchange import to_xt_symbol

        symbol = to_xt_symbol(instrument_id)
        # XtQuant's minute-K callback is activated with count=-1. The callback
        # may also deliver the current day's tail, which is intentionally
        # buffered before Warmup and reconciled against the Runtime watermark.
        count = 0 if period == "tick" else -1
        return int(
            self._xtdata.subscribe_quote(
                symbol,
                period=period,
                count=count,
                callback=lambda raw: self._publish_live(raw, instrument_id, period),
            )
        )

    def _publish_live(self, raw: Any, instrument_id: OnlyInstrumentId, period: str) -> None:
        with self._subscription_lock:
            if not self._accepting_callbacks:
                return
            self._normalizer.publish(raw, instrument_id, period)

    def _connection_result(
        self,
        status: OnlyMarketDataRequestStatus,
        state: OnlyMarketDataConnectionState,
    ) -> OnlyMarketDataConnectionResult:
        return OnlyMarketDataConnectionResult(
            status,
            OnlyMarketDataConnectionSnapshot(OnlyMarketDataGatewayId(str(self.source_id)), state),
        )


def _warmup_request_fingerprint(request: OnlyHistoricalWarmupRequest) -> str:
    payload = {
        "request_id": request.request_id,
        "runtime_id": str(request.runtime_id),
        "instrument_id": str(request.instrument_id),
        "bar_type": request.bar_type.to_dict(),
        "required_bars": request.required_bars,
        "end_time_ns": request.end_time.unix_nanos,
        "data_version": str(request.data_version),
        "adjustment_type": request.adjustment_type.value,
        "timeout_seconds": request.timeout_seconds,
        "compatibility_profile_id": request.compatibility_profile_id,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _metadata_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"MiniQMT historical cache metadata {field} must be an integer")
    return int(value)
