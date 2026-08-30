"""Binance Spot DataSource composition and lifecycle."""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from datetime import datetime, timedelta

from onlyalpha.cache.historical.service import OnlyHistoricalCacheService
from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.data.enums import (
    OnlyDataSequenceSemantics,
    OnlyMarketDataCapability,
    OnlyMarketDataConnectionState,
    OnlyMarketDataRequestStatus,
    OnlyMarketDataType,
)
from onlyalpha.data.evidence import OnlyRawProviderObservation
from onlyalpha.data.historical import OnlyHistoricalDataRequest, OnlyHistoricalTradeDataRequest
from onlyalpha.data.identifiers import (
    OnlyDataSequence,
    OnlyDataVersion,
    OnlyMarketDataGatewayId,
    OnlyMarketDataSourceId,
    OnlyMarketDataUpdateId,
)
from onlyalpha.data.identity import only_bar_update_id, only_market_reference_update_id, only_trade_update_id
from onlyalpha.data.models import (
    OnlyBarUpdate,
    OnlyHistoricalBarRequest,
    OnlyHistoricalDataStream,
    OnlyHistoricalQuoteRequest,
    OnlyHistoricalTradeRequest,
    OnlyMarketDataConnectionResult,
    OnlyMarketDataConnectionSnapshot,
    OnlyMarketDataInboundUpdate,
    OnlyMarketDataPayload,
    OnlyMarketDataSubscriptionRequest,
    OnlyMarketDataSubscriptionResult,
    OnlyMarketDataUnsubscriptionRequest,
    OnlyMarketReferenceUpdate,
    OnlyTradeTickUpdate,
)
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyInstrumentId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.market import OnlyBar, OnlyBarType, OnlyMarketReferenceTick, OnlyTradeTick
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.plugin.data_source import OnlyDataSourceCreateRequest
from onlyalpha.plugin.lifecycle import OnlyPluginHealth, OnlyPluginHealthStatus, OnlyPluginLifecycleState
from onlyalpha_plugin_binance.common.http import OnlyBinancePublicHttpClient
from onlyalpha_plugin_binance.errors import OnlyBinanceError

from ...descriptor import DATA_DESCRIPTOR
from .config import OnlyBinanceSpotDataSourceConfig
from .continuity import OnlyBinanceSpotContinuityCoordinator
from .historical import OnlyBinanceSpotHistoricalClient, OnlyBinanceSpotHistoricalProvider
from .normalize import (
    only_normalize_reference_price,
    only_normalize_rest_kline,
    only_normalize_ws_kline,
    only_normalize_ws_trade,
)
from .websocket import OnlyBinanceWebSocketTransport


def _optional_int(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


class OnlyBinanceSpotDataSource:
    plugin_descriptor = DATA_DESCRIPTOR

    def __init__(
        self,
        request: OnlyDataSourceCreateRequest,
        config: OnlyBinanceSpotDataSourceConfig,
        *,
        historical_client: OnlyBinanceSpotHistoricalClient | None = None,
        websocket_transport: OnlyBinanceWebSocketTransport | None = None,
    ) -> None:
        self._request = request
        self._config = config
        http = OnlyBinancePublicHttpClient(
            config.environment.rest_base_url,
            timeout_seconds=config.timeout_seconds,
            max_response_bytes=config.max_response_bytes,
            response_observer=self._observe_rest_response,
        )
        self._historical = historical_client or OnlyBinanceSpotHistoricalClient(http)
        self._websocket = websocket_transport or OnlyBinanceWebSocketTransport(
            timeout_seconds=config.timeout_seconds,
            max_message_bytes=config.max_ws_message_bytes,
        )
        self._continuity = OnlyBinanceSpotContinuityCoordinator(config.recovery_buffer_max_events)
        self._state = OnlyPluginLifecycleState.CREATED
        self._subscriptions: dict[str, OnlyMarketDataSubscriptionRequest] = {}
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._websocket_url: str | None = None
        self._symbol_map = {str(item.raw_symbol).upper(): item for item in request.instruments.values()}

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
                OnlyMarketDataCapability.CONNECT,
                OnlyMarketDataCapability.AUTHENTICATE,
                OnlyMarketDataCapability.SUBSCRIBE_BAR,
                OnlyMarketDataCapability.SUBSCRIBE_TRADE,
                OnlyMarketDataCapability.SUBSCRIBE_MARKET_REFERENCE,
                OnlyMarketDataCapability.UNSUBSCRIBE,
                OnlyMarketDataCapability.PUSH_BAR,
                OnlyMarketDataCapability.PUSH_TRADE,
                OnlyMarketDataCapability.PUSH_MARKET_REFERENCE,
                OnlyMarketDataCapability.QUERY_HISTORICAL_BAR,
                OnlyMarketDataCapability.QUERY_HISTORICAL_TRADE,
                OnlyMarketDataCapability.QUERY_INSTRUMENT,
                OnlyMarketDataCapability.QUERY_CALENDAR,
            }
        )

    def initialize(self) -> None:
        self._state = OnlyPluginLifecycleState.INITIALIZED

    def connect(self) -> OnlyMarketDataConnectionResult:
        if self._state not in {OnlyPluginLifecycleState.INITIALIZED, OnlyPluginLifecycleState.STOPPED}:
            return self._connection(OnlyMarketDataRequestStatus.REJECTED, "resource is not initialized")
        self._state = OnlyPluginLifecycleState.CONNECTED
        self._continuity.connected()
        return self._connection(OnlyMarketDataRequestStatus.ACCEPTED)

    def authenticate(self) -> OnlyMarketDataConnectionResult:
        if self._state is not OnlyPluginLifecycleState.CONNECTED:
            return self._connection(OnlyMarketDataRequestStatus.REJECTED, "public source is not connected")
        return self._connection(OnlyMarketDataRequestStatus.ACCEPTED)

    def start(self) -> None:
        if self._state is not OnlyPluginLifecycleState.CONNECTED:
            raise OnlyBinanceError("BINANCE_DATA_SOURCE_NOT_CONNECTED")
        self._state = OnlyPluginLifecycleState.RUNNING

    def stop(self) -> None:
        self._state = OnlyPluginLifecycleState.STOPPING
        self._stop.set()
        self._websocket.close()
        if self._worker is not None and self._worker is not threading.current_thread():
            self._worker.join(timeout=self._config.timeout_seconds)
        self._worker = None
        self._continuity.disconnected()
        self._state = OnlyPluginLifecycleState.STOPPED

    close = stop

    def disconnect(self) -> OnlyMarketDataConnectionResult:
        self.stop()
        return self._connection(OnlyMarketDataRequestStatus.ACCEPTED)

    def health(self) -> OnlyPluginHealth:
        if self._state is OnlyPluginLifecycleState.STOPPED:
            return OnlyPluginHealth(OnlyPluginHealthStatus.STOPPED)
        if self._continuity.state is OnlyMarketDataConnectionState.READY:
            return OnlyPluginHealth(OnlyPluginHealthStatus.HEALTHY)
        if self._continuity.state is OnlyMarketDataConnectionState.FAILED:
            return OnlyPluginHealth(OnlyPluginHealthStatus.UNHEALTHY, "continuity failed")
        return OnlyPluginHealth(OnlyPluginHealthStatus.DEGRADED, self._continuity.state.value)

    def connection_snapshot(self) -> OnlyMarketDataConnectionSnapshot:
        return OnlyMarketDataConnectionSnapshot(OnlyMarketDataGatewayId(str(self.source_id)), self._continuity.state)

    def load_bars(self, request: OnlyHistoricalBarRequest) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        cache = self._require_cache()
        updates: list[OnlyMarketDataInboundUpdate] = []
        for bar_type in sorted(request.bar_types, key=lambda item: item.to_json()):
            instrument = self._request.instruments[bar_type.instrument_id]
            provider = self._provider(instrument.instrument_id, bar_type, request.data_version)
            result = cache.load_bars(
                OnlyHistoricalDataRequest(
                    instrument.instrument_id,
                    bar_type,
                    OnlyTimeRange(request.data_range.start_time, request.data_range.end_time),
                ),
                provider,
                self._config.cache_policy,
            )
            updates.extend(self._bar_update(item, request.data_version) for item in result.records)
        return OnlyHistoricalDataStream(tuple(sorted(updates, key=self._order_key)), request.batch_size)

    def load_trades(self, request: OnlyHistoricalTradeRequest) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        cache = self._require_cache()
        updates: list[OnlyMarketDataInboundUpdate] = []
        for instrument_id in sorted(request.instrument_ids, key=str):
            provider = self._provider(instrument_id, self._request.bar_types[instrument_id], request.data_version)
            result = cache.load_trades(
                OnlyHistoricalTradeDataRequest(
                    instrument_id,
                    OnlyTimeRange(request.data_range.start_time, request.data_range.end_time),
                ),
                provider,
                self._config.cache_policy,
            )
            updates.extend(self._trade_update(item, request.data_version) for item in result.records)
        return OnlyHistoricalDataStream(tuple(sorted(updates, key=self._order_key)), request.batch_size)

    def load_quotes(self, request: OnlyHistoricalQuoteRequest) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        return OnlyHistoricalDataStream((), request.batch_size)

    def subscribe(self, request: OnlyMarketDataSubscriptionRequest) -> OnlyMarketDataSubscriptionResult:
        if self._state is not OnlyPluginLifecycleState.RUNNING:
            return OnlyMarketDataSubscriptionResult(OnlyMarketDataRequestStatus.REJECTED, None, "not running")
        if request.source_id != self.source_id or not request.instrument_ids:
            return OnlyMarketDataSubscriptionResult(OnlyMarketDataRequestStatus.REJECTED, None, "source/scope invalid")
        unsupported = request.data_types - {
            OnlyMarketDataType.BAR,
            OnlyMarketDataType.TRADE,
            OnlyMarketDataType.MARKET_REFERENCE,
        }
        if unsupported:
            return OnlyMarketDataSubscriptionResult(
                OnlyMarketDataRequestStatus.UNSUPPORTED_CAPABILITY, None, "unsupported data family"
            )
        subscription_id = f"BINANCE-{request.request_id}"
        self._subscriptions[subscription_id] = request
        streams = self._streams(request)
        self._websocket_url = f"{self._config.environment.websocket_base_url}/stream?streams={'/'.join(streams)}"
        self._websocket.connect(self._websocket_url)
        self._continuity.subscription_established()
        self._continuity.begin_recovery()
        self._stop.clear()
        self._worker = threading.Thread(target=self._run_worker, name=f"{subscription_id}-ws", daemon=True)
        self._worker.start()
        try:
            baselines = self._initial_baselines(request)
            for update in baselines:
                for accepted in self._continuity.accept_baseline(update, self._recover):
                    self._publish(accepted)
            self._continuity.establish_empty_baseline()
            for update in self._continuity.complete_recovery(self._recover):
                self._publish(update)
        except Exception:
            self._continuity.fail()
            raise
        return OnlyMarketDataSubscriptionResult(OnlyMarketDataRequestStatus.ACCEPTED, subscription_id)

    def unsubscribe(self, request: OnlyMarketDataUnsubscriptionRequest) -> OnlyMarketDataSubscriptionResult:
        if request.subscription_id not in self._subscriptions:
            return OnlyMarketDataSubscriptionResult(OnlyMarketDataRequestStatus.REJECTED, None, "unknown subscription")
        del self._subscriptions[request.subscription_id]
        self.stop()
        return OnlyMarketDataSubscriptionResult(OnlyMarketDataRequestStatus.ACCEPTED, request.subscription_id)

    def ingest_websocket_message(self, payload: bytes) -> tuple[OnlyMarketDataInboundUpdate, ...]:
        receive_ns = self._request.clock.timestamp_ns()
        unknown_observation = OnlyRawProviderObservation(
            source_id=str(self.source_id),
            capture_session_id=f"binance-spot:{self._request.runtime_id}:realtime",
            provider="BINANCE",
            venue="BINANCE",
            market="SPOT",
            stream="UNKNOWN",
            provider_event_type="UNKNOWN",
            ts_receive_ns=receive_ns,
            payload=payload,
        )
        try:
            raw = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._record_evidence(unknown_observation, None)
            raise OnlyBinanceError("BINANCE_WEBSOCKET_FRAME_INVALID") from exc
        if not isinstance(raw, dict):
            self._record_evidence(unknown_observation, None)
            raise OnlyBinanceError("BINANCE_WEBSOCKET_FRAME_INVALID")
        event = raw.get("data", raw)
        if not isinstance(event, dict):
            self._record_evidence(unknown_observation, None)
            raise OnlyBinanceError("BINANCE_WEBSOCKET_EVENT_INVALID")
        event_type = str(event.get("e", "UNKNOWN"))
        provider_id = event.get("t")
        if event_type == "kline" and isinstance(event.get("k"), dict):
            provider_id = event["k"].get("t")
        event_time_ms = _optional_int(event.get("E"))
        observation = OnlyRawProviderObservation(
            source_id=str(self.source_id),
            capture_session_id=f"binance-spot:{self._request.runtime_id}:realtime",
            provider="BINANCE",
            venue="BINANCE",
            market="SPOT",
            stream=event_type,
            provider_event_type=event_type,
            provider_event_id=None if provider_id is None else str(provider_id),
            provider_sequence=_optional_int(provider_id),
            ts_event_ns=None if event_time_ms is None else event_time_ms * 1_000_000,
            ts_receive_ns=receive_ns,
            payload=payload,
        )
        try:
            update = self._normalize_event(event)
        except Exception as exc:
            self._record_evidence(observation, None)
            if isinstance(exc, OnlyBinanceError):
                raise
            raise OnlyBinanceError("BINANCE_WEBSOCKET_NORMALIZATION_FAILED") from exc
        self._record_evidence(observation, update)
        if update is None:
            return ()
        accepted = self._continuity.accept(update, self._recover)
        for item in accepted:
            self._publish(item)
        return accepted

    def _record_evidence(
        self,
        observation: OnlyRawProviderObservation,
        update: OnlyMarketDataInboundUpdate | tuple[OnlyMarketDataInboundUpdate, ...] | None,
    ) -> None:
        sink = self._request.provider_evidence_sink
        if sink is not None:
            sink(observation, update)

    def _observe_rest_response(self, endpoint: str, params: Mapping[str, str], payload: bytes) -> None:
        receive_ns = self._request.clock.timestamp_ns()
        observation = OnlyRawProviderObservation(
            source_id=str(self.source_id),
            capture_session_id=f"binance-spot:{self._request.runtime_id}:rest",
            provider="BINANCE",
            venue="BINANCE",
            market="SPOT",
            stream=endpoint,
            provider_event_type=endpoint.rsplit("/", 1)[-1],
            ts_receive_ns=receive_ns,
            payload=payload,
            provenance="REST_BACKFILL",
        )
        try:
            decoded = json.loads(payload)
            symbol = str(params.get("symbol", "")).upper()
            instrument = self._symbol_map[symbol]
            updates: tuple[OnlyMarketDataInboundUpdate, ...]
            if endpoint == "/api/v3/klines" and isinstance(decoded, list):
                updates = tuple(
                    self._bar_update(
                        only_normalize_rest_kline(row, instrument, self._request.bar_types[instrument.instrument_id]),
                        self._request.data_version,
                    )
                    for row in decoded
                )
            elif endpoint in {"/api/v3/historicalTrades", "/api/v3/trades"} and isinstance(decoded, list):
                from .normalize import only_normalize_rest_trade

                updates = tuple(
                    self._trade_update(only_normalize_rest_trade(row, instrument), self._request.data_version)
                    for row in decoded
                )
            elif endpoint == "/api/v3/referencePrice" and isinstance(decoded, dict) and decoded.get("code") != -2043:
                updates = (
                    self._reference_update(
                        only_normalize_reference_price(decoded, instrument), self._request.data_version
                    ),
                )
            else:
                updates = ()
        except Exception:
            updates = ()
        self._record_evidence(observation, updates)

    def instrument(self, instrument_id: OnlyInstrumentId) -> OnlyInstrument | None:
        return self._request.instruments.get(instrument_id)

    def calendar(self, calendar_id: OnlyCalendarId) -> OnlyTradingCalendar | None:
        return self._request.calendars.get(calendar_id)

    def market_rule(self, instrument_id: OnlyInstrumentId) -> None:
        return None

    def _run_worker(self) -> None:
        backoff = self._config.reconnect_initial_seconds
        while not self._stop.is_set():
            try:
                self.ingest_websocket_message(self._websocket.receive())
                backoff = self._config.reconnect_initial_seconds
            except Exception as exc:
                if self._stop.is_set():
                    return
                self._request.logger.error("Binance WebSocket worker failed: %s", type(exc).__name__)
                self._continuity.disconnected()
                self._websocket.close()
                if self._stop.wait(backoff):
                    return
                backoff = min(backoff * 2, self._config.reconnect_max_seconds)
                try:
                    if self._websocket_url is None:
                        raise OnlyBinanceError("BINANCE_WEBSOCKET_URL_MISSING")
                    self._websocket.connect(self._websocket_url)
                    self._continuity.connected()
                    self._continuity.subscription_established()
                    self._continuity.begin_recovery()
                    requests = tuple(self._subscriptions.values())
                    baselines = tuple(update for request in requests for update in self._initial_baselines(request))
                    for update in sorted(baselines, key=self._order_key):
                        for accepted in self._continuity.accept_baseline(update, self._recover):
                            self._publish(accepted)
                    self._continuity.establish_empty_baseline()
                    for update in self._continuity.complete_recovery(self._recover):
                        self._publish(update)
                except Exception as recovery_exc:
                    self._continuity.fail()
                    self._request.logger.error("Binance WebSocket recovery failed: %s", type(recovery_exc).__name__)

    def _initial_baselines(self, request: OnlyMarketDataSubscriptionRequest) -> tuple[OnlyMarketDataInboundUpdate, ...]:
        now = self._now()
        minute = now.replace(second=0, microsecond=0)
        updates: list[OnlyMarketDataInboundUpdate] = []
        for instrument_id in sorted(request.instrument_ids, key=str):
            instrument = self._request.instruments[instrument_id]
            symbol = str(instrument.raw_symbol)
            if OnlyMarketDataType.BAR in request.data_types:
                bar = self._provider(instrument_id, self._request.bar_types[instrument_id], self._request.data_version)
                normalized = bar.fetch(
                    OnlyHistoricalDataRequest(
                        instrument_id,
                        self._request.bar_types[instrument_id],
                        OnlyTimeRange(minute - timedelta(minutes=1), minute),
                    ),
                    OnlyTimeRange(minute - timedelta(minutes=1), minute),
                ).records
                if len(normalized) != 1:
                    raise OnlyBinanceError("BINANCE_BAR_BASELINE_UNPROVEN")
                updates.append(self._bar_update(normalized[0], self._request.data_version))
            if OnlyMarketDataType.TRADE in request.data_types:
                trade_rows = self._historical.recent_trades(symbol, 1)
                if len(trade_rows) != 1:
                    raise OnlyBinanceError("BINANCE_TRADE_BASELINE_UNPROVEN")
                from .normalize import only_normalize_rest_trade

                updates.append(
                    self._trade_update(only_normalize_rest_trade(trade_rows[0], instrument), self._request.data_version)
                )
            if OnlyMarketDataType.MARKET_REFERENCE in request.data_types:
                reference_payload = self._historical.reference_price(symbol)
                if reference_payload is not None:
                    updates.append(
                        self._reference_update(
                            only_normalize_reference_price(reference_payload, instrument),
                            self._request.data_version,
                        )
                    )
        return tuple(sorted(updates, key=self._order_key))

    def _normalize_event(self, raw: Mapping[str, object]) -> OnlyMarketDataInboundUpdate | None:
        symbol = str(raw.get("s", "")).upper()
        event_type = str(raw.get("e", ""))
        if event_type == "kline":
            kline = raw.get("k")
            if not isinstance(kline, dict):
                raise OnlyBinanceError("BINANCE_KLINE_EVENT_INVALID")
            symbol = str(kline.get("s", symbol)).upper()
            kline_instrument = self._symbol_map[symbol]
            bar = only_normalize_ws_kline(
                kline,
                kline_instrument,
                self._request.bar_types[kline_instrument.instrument_id],
            )
            return None if bar is None else self._bar_update(bar, self._request.data_version)
        event_instrument = self._symbol_map.get(symbol)
        if event_instrument is None:
            raise OnlyBinanceError("BINANCE_EVENT_SYMBOL_NOT_REQUESTED")
        if event_type == "trade":
            return self._trade_update(only_normalize_ws_trade(raw, event_instrument), self._request.data_version)
        if event_type == "referencePrice":
            return self._reference_update(
                only_normalize_reference_price(raw, event_instrument), self._request.data_version
            )
        return None

    def _recover(
        self, update: OnlyMarketDataInboundUpdate, first: int, last: int
    ) -> tuple[OnlyMarketDataInboundUpdate, ...]:
        instrument = self._request.instruments[update.instrument_id]
        if update.data_type is OnlyMarketDataType.TRADE:
            trade_rows = self._historical.historical_trades(str(instrument.raw_symbol), first, last - first + 1)
            from .normalize import only_normalize_rest_trade

            recovered = tuple(
                self._trade_update(only_normalize_rest_trade(item, instrument), update.data_version)
                for item in trade_rows
            )
        elif update.data_type is OnlyMarketDataType.BAR:
            start_ms = first * 60_000
            end_ms = (last + 1) * 60_000
            bar_rows = self._historical.klines(str(instrument.raw_symbol), start_ms, end_ms, last - first + 1)
            from .normalize import only_normalize_rest_kline

            recovered = tuple(
                self._bar_update(
                    only_normalize_rest_kline(item, instrument, self._request.bar_types[update.instrument_id]),
                    update.data_version,
                )
                for item in bar_rows
            )
        else:
            recovered = ()
        if tuple(int(item.source_sequence) for item in recovered) != tuple(range(first, last + 1)):
            return ()
        return recovered

    def _bar_update(self, bar: OnlyBar, data_version: OnlyDataVersion) -> OnlyMarketDataInboundUpdate:
        sequence = int(bar.bar_start.timestamp()) // 60
        return self._envelope(
            only_bar_update_id(self.source_id, bar.instrument_id, bar.bar_type, bar.bar_start, data_version),
            sequence,
            data_version,
            bar.instrument_id,
            OnlyMarketDataType.BAR,
            OnlyBarUpdate(bar),
            bar.ts_event,
            OnlyDataSequenceSemantics.CONTIGUOUS,
        )

    def _trade_update(self, trade: OnlyTradeTick, data_version: OnlyDataVersion) -> OnlyMarketDataInboundUpdate:
        return self._envelope(
            only_trade_update_id(self.source_id, trade.instrument_id, trade.trade_id, data_version),
            trade.sequence,
            data_version,
            trade.instrument_id,
            OnlyMarketDataType.TRADE,
            OnlyTradeTickUpdate(trade),
            trade.ts_event,
            OnlyDataSequenceSemantics.CONTIGUOUS,
        )

    def _reference_update(
        self, reference: OnlyMarketReferenceTick, data_version: OnlyDataVersion
    ) -> OnlyMarketDataInboundUpdate:
        return self._envelope(
            only_market_reference_update_id(
                self.source_id, reference.instrument_id, reference.reference_kind, reference.ts_event, data_version
            ),
            reference.sequence,
            data_version,
            reference.instrument_id,
            OnlyMarketDataType.MARKET_REFERENCE,
            OnlyMarketReferenceUpdate(reference),
            reference.ts_event,
            OnlyDataSequenceSemantics.MONOTONIC,
        )

    def _envelope(
        self,
        update_id: OnlyMarketDataUpdateId,
        sequence: int,
        data_version: OnlyDataVersion,
        instrument_id: OnlyInstrumentId,
        data_type: OnlyMarketDataType,
        payload: OnlyMarketDataPayload,
        ts_event: datetime,
        semantics: OnlyDataSequenceSemantics,
    ) -> OnlyMarketDataInboundUpdate:
        observation = max(ts_event, self._now())
        return OnlyMarketDataInboundUpdate(
            update_id,
            self._request.runtime_id,
            self.source_id,
            OnlyDataSequence(sequence),
            data_version,
            instrument_id,
            data_type,
            payload,
            OnlyTimestamp.from_datetime(ts_event),
            OnlyTimestamp.from_datetime(observation),
            sequence_semantics=semantics,
        )

    def _publish(self, update: OnlyMarketDataInboundUpdate) -> None:
        sink = self._request.market_data_sink
        if sink is not None:
            sink(update)

    def _provider(
        self,
        instrument_id: OnlyInstrumentId,
        bar_type: OnlyBarType,
        data_version: OnlyDataVersion,
    ) -> OnlyBinanceSpotHistoricalProvider:
        return OnlyBinanceSpotHistoricalProvider(
            self._historical,
            self._request.instruments[instrument_id],
            bar_type,
            data_version,
            page_size=self._config.rest_page_size,
            now=self._now,
            source_id=str(self.source_id),
        )

    def _require_cache(self) -> OnlyHistoricalCacheService:
        if self._request.historical_cache_service is None:
            raise OnlyBinanceError("BINANCE_HISTORICAL_CACHE_REQUIRED")
        return self._request.historical_cache_service

    def _now(self) -> datetime:
        return OnlyTimestamp.from_unix_nanos(self._request.clock.timestamp_ns()).to_datetime()

    def _streams(self, request: OnlyMarketDataSubscriptionRequest) -> tuple[str, ...]:
        suffixes = {
            OnlyMarketDataType.BAR: "kline_1m",
            OnlyMarketDataType.TRADE: "trade",
            OnlyMarketDataType.MARKET_REFERENCE: "referencePrice",
        }
        return tuple(
            f"{str(self._request.instruments[instrument_id].raw_symbol).lower()}@{suffixes[data_type]}"
            for instrument_id in sorted(request.instrument_ids, key=str)
            for data_type in sorted(request.data_types, key=lambda item: item.value)
        )

    def _connection(
        self, status: OnlyMarketDataRequestStatus, reason: str | None = None
    ) -> OnlyMarketDataConnectionResult:
        return OnlyMarketDataConnectionResult(status, self.connection_snapshot(), reason)

    @staticmethod
    def _order_key(update: OnlyMarketDataInboundUpdate) -> tuple[int, str]:
        return (update.ts_event.unix_nanos, str(update.update_id))
