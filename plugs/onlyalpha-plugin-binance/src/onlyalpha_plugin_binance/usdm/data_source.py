"""Binance USD-M historical DataSource at the provider boundary."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from onlyalpha.data.enums import (
    OnlyDataSequenceSemantics,
    OnlyMarketDataCapability,
    OnlyMarketDataConnectionState,
    OnlyMarketDataRequestStatus,
    OnlyMarketDataType,
)
from onlyalpha.data.historical.models import OnlyHistoricalFactRequest
from onlyalpha.data.identifiers import (
    OnlyDataSequence,
    OnlyDataVersion,
    OnlyMarketDataGatewayId,
    OnlyMarketDataSourceId,
    OnlyMarketDataUpdateId,
)
from onlyalpha.data.identity import only_bar_update_id
from onlyalpha.data.models import (
    OnlyBarUpdate,
    OnlyFundingRateUpdate,
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
    OnlyReferencePriceUpdate,
)
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.enums import OnlyAdjustmentType, OnlySessionType
from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyInstrumentId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.market import OnlyBar, OnlyBarType, OnlyReferencePriceFact
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.trading import OnlyReferencePriceKind
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.plugin.capabilities import OnlyPluginValidationIssue
from onlyalpha.plugin.data_source import OnlyDataSourceCreateRequest
from onlyalpha.plugin.lifecycle import OnlyPluginHealth, OnlyPluginHealthStatus, OnlyPluginLifecycleState
from onlyalpha_plugin_binance.common.http import OnlyBinancePublicHttpClient
from onlyalpha_plugin_binance.errors import OnlyBinanceError

from ..descriptor import USDM_DATA_CAPABILITIES, USDM_DATA_DESCRIPTOR
from .historical import OnlyBinanceUsdmHistoricalNormalizer


@dataclass(frozen=True, slots=True)
class OnlyBinanceUsdmDataSourceConfig:
    rest_base_url: str = "https://fapi.binance.com"
    timeout_seconds: float = 10.0
    max_response_bytes: int = 8 * 1024 * 1024
    rest_page_size: int = 1000

    def __post_init__(self) -> None:
        if (
            not self.rest_base_url.startswith("https://")
            or not 0 < self.timeout_seconds <= 30
            or self.max_response_bytes <= 0
            or not 1 <= self.rest_page_size <= 1500
        ):
            raise ValueError("BINANCE_USDM_DATA_CONFIGURATION_INVALID")

    @classmethod
    def parse(cls, raw: Mapping[str, object]) -> OnlyBinanceUsdmDataSourceConfig:
        allowed = {"rest_base_url", "timeout_seconds", "max_response_bytes", "rest_page_size"}
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise ValueError(f"BINANCE_USDM_DATA_CONFIG_UNKNOWN_FIELDS: {','.join(unknown)}")
        return cls(
            rest_base_url=str(raw.get("rest_base_url", "https://fapi.binance.com")),
            timeout_seconds=float(str(raw.get("timeout_seconds", 10.0))),
            max_response_bytes=int(str(raw.get("max_response_bytes", 8 * 1024 * 1024))),
            rest_page_size=int(str(raw.get("rest_page_size", 1000))),
        )


class OnlyBinanceUsdmHistoricalClient:
    def __init__(self, http: OnlyBinancePublicHttpClient) -> None:
        self._http = http

    def contract_klines(
        self,
        symbol: str,
        start_ms: int,
        end_ms: int,
        limit: int,
    ) -> Sequence[Sequence[object]]:
        return self._klines("/fapi/v1/klines", "symbol", symbol, start_ms, end_ms, limit)

    def mark_price_klines(self, symbol: str, start_ms: int, end_ms: int, limit: int) -> Sequence[Sequence[object]]:
        return self._klines("/fapi/v1/markPriceKlines", "symbol", symbol, start_ms, end_ms, limit)

    def index_price_klines(self, pair: str, start_ms: int, end_ms: int, limit: int) -> Sequence[Sequence[object]]:
        return self._klines("/fapi/v1/indexPriceKlines", "pair", pair, start_ms, end_ms, limit)

    def _klines(
        self,
        endpoint: str,
        instrument_parameter: str,
        instrument_value: str,
        start_ms: int,
        end_ms: int,
        limit: int,
    ) -> Sequence[Sequence[object]]:
        value = json.loads(
            self._http.get_json(
                endpoint,
                {
                    instrument_parameter: instrument_value,
                    "interval": "1m",
                    "startTime": str(start_ms),
                    "endTime": str(end_ms - 1),
                    "limit": str(limit),
                },
            )
        )
        if not isinstance(value, list) or any(not isinstance(item, list) for item in value):
            raise OnlyBinanceError("BINANCE_USDM_KLINES_RESPONSE_INVALID")
        return value

    def funding_rates(self, symbol: str, start_ms: int, end_ms: int, limit: int) -> Sequence[Mapping[str, object]]:
        value = json.loads(
            self._http.get_json(
                "/fapi/v1/fundingRate",
                {
                    "symbol": symbol,
                    "startTime": str(start_ms),
                    "endTime": str(end_ms - 1),
                    "limit": str(min(limit, 1000)),
                },
            )
        )
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise OnlyBinanceError("BINANCE_USDM_FUNDING_RESPONSE_INVALID")
        return value


class OnlyBinanceUsdmDataSource:
    plugin_descriptor = USDM_DATA_DESCRIPTOR

    def __init__(
        self,
        request: OnlyDataSourceCreateRequest,
        config: OnlyBinanceUsdmDataSourceConfig,
        *,
        historical_client: OnlyBinanceUsdmHistoricalClient | None = None,
    ) -> None:
        self._request = request
        self._config = config
        self._historical = historical_client or OnlyBinanceUsdmHistoricalClient(
            OnlyBinancePublicHttpClient(
                config.rest_base_url,
                timeout_seconds=config.timeout_seconds,
                max_response_bytes=config.max_response_bytes,
            )
        )
        self._normalizer = OnlyBinanceUsdmHistoricalNormalizer()
        self._state = OnlyPluginLifecycleState.CREATED

    @property
    def source_id(self) -> OnlyMarketDataSourceId:
        return self._request.source_id

    @property
    def plugin_resource_id(self) -> str:
        return str(self.source_id)

    @property
    def state(self) -> OnlyPluginLifecycleState:
        return self._state

    @property
    def capabilities(self) -> frozenset[OnlyMarketDataCapability]:
        return frozenset(
            {
                OnlyMarketDataCapability.CONNECT,
                OnlyMarketDataCapability.AUTHENTICATE,
                OnlyMarketDataCapability.QUERY_HISTORICAL_BAR,
                OnlyMarketDataCapability.QUERY_HISTORICAL_REFERENCE_PRICE,
                OnlyMarketDataCapability.QUERY_HISTORICAL_FUNDING_RATE,
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
        return self._connection(OnlyMarketDataRequestStatus.ACCEPTED)

    def authenticate(self) -> OnlyMarketDataConnectionResult:
        if self._state is not OnlyPluginLifecycleState.CONNECTED:
            return self._connection(OnlyMarketDataRequestStatus.REJECTED, "public source is not connected")
        return self._connection(OnlyMarketDataRequestStatus.ACCEPTED)

    def start(self) -> None:
        if self._state is not OnlyPluginLifecycleState.CONNECTED:
            raise OnlyBinanceError("BINANCE_USDM_DATA_SOURCE_NOT_CONNECTED")
        self._state = OnlyPluginLifecycleState.RUNNING

    def stop(self) -> None:
        self._state = OnlyPluginLifecycleState.STOPPED

    close = stop

    def disconnect(self) -> OnlyMarketDataConnectionResult:
        self.stop()
        return self._connection(OnlyMarketDataRequestStatus.ACCEPTED)

    def health(self) -> OnlyPluginHealth:
        if self._state is OnlyPluginLifecycleState.STOPPED:
            return OnlyPluginHealth(OnlyPluginHealthStatus.STOPPED)
        if self._state is OnlyPluginLifecycleState.RUNNING:
            return OnlyPluginHealth(OnlyPluginHealthStatus.HEALTHY)
        return OnlyPluginHealth(OnlyPluginHealthStatus.DEGRADED, self._state.value)

    def connection_snapshot(self) -> OnlyMarketDataConnectionSnapshot:
        state = (
            OnlyMarketDataConnectionState.READY
            if self._state is OnlyPluginLifecycleState.RUNNING
            else OnlyMarketDataConnectionState.CONNECTED
            if self._state is OnlyPluginLifecycleState.CONNECTED
            else OnlyMarketDataConnectionState.DISCONNECTED
        )
        return OnlyMarketDataConnectionSnapshot(OnlyMarketDataGatewayId(str(self.source_id)), state)

    def load_bars(self, request: OnlyHistoricalBarRequest) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        updates: list[OnlyMarketDataInboundUpdate] = []
        start_ms = _milliseconds(request.data_range.start_time)
        end_ms = _milliseconds(request.data_range.end_time)
        for bar_type in sorted(request.bar_types, key=lambda item: item.to_json()):
            instrument = self._request.instruments[bar_type.instrument_id]
            rows = self._paged_klines(instrument, start_ms, end_ms)
            updates.extend(
                self._bar_envelope(
                    only_normalize_binance_usdm_kline(item, instrument, bar_type),
                    request.data_version,
                )
                for item in rows
            )
        return OnlyHistoricalDataStream(tuple(sorted(updates, key=_update_order_key)), request.batch_size)

    def load_facts(self, request: OnlyHistoricalFactRequest) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        instrument = self._request.instruments[request.instrument_id]
        start_ms = _milliseconds(request.time_range.start)
        end_ms = _milliseconds(request.time_range.end)
        updates: list[OnlyMarketDataInboundUpdate] = []
        if request.fact_family is OnlyMarketDataType.REFERENCE_PRICE:
            kind = request.reference_price_kind
            if kind not in {OnlyReferencePriceKind.MARK, OnlyReferencePriceKind.INDEX}:
                raise OnlyBinanceError("BINANCE_USDM_REFERENCE_KIND_UNSUPPORTED")
            reference_rows = self._paged_klines(instrument, start_ms, end_ms, kind=kind)
            for reference_row in reference_rows:
                event_ms = _required_int(reference_row[0], "BINANCE_USDM_KLINE_TIME_INVALID")
                if not start_ms <= event_ms < end_ms:
                    continue
                reference_fact = self._normalizer.reference_price(
                    {
                        "T": event_ms,
                        "p" if kind is OnlyReferencePriceKind.MARK else "i": str(reference_row[1]),
                    },
                    instrument_id=instrument.instrument_id,
                    kind=kind,
                    data_version=str(request.data_version),
                    source_sequence=event_ms,
                    received_at=datetime.fromtimestamp(event_ms / 1000, tz=UTC),
                )
                updates.append(
                    self._fact_envelope(
                        reference_fact.fact_id,
                        event_ms,
                        request.data_version,
                        reference_fact,
                    )
                )
        elif request.fact_family is OnlyMarketDataType.FUNDING_RATE:
            funding_rows = self._paged_funding(instrument, start_ms, end_ms)
            for funding_row in funding_rows:
                funding_ms = _required_int(funding_row.get("fundingTime"), "BINANCE_USDM_FUNDING_TIME_INVALID")
                if not start_ms <= funding_ms < end_ms:
                    continue
                funding_mark, funding_fact = self._normalizer.funding_boundary_facts(
                    dict(funding_row),
                    instrument_id=instrument.instrument_id,
                    data_version=str(request.data_version),
                    source_sequence=funding_ms,
                    received_at=datetime.fromtimestamp(funding_ms / 1000, tz=UTC),
                )
                updates.append(
                    self._fact_envelope(
                        funding_mark.fact_id,
                        funding_ms,
                        request.data_version,
                        funding_mark,
                    )
                )
                updates.append(
                    self._envelope(
                        OnlyMarketDataUpdateId(funding_fact.fact_id),
                        funding_ms,
                        request.data_version,
                        instrument.instrument_id,
                        OnlyMarketDataType.FUNDING_RATE,
                        OnlyFundingRateUpdate(funding_fact),
                        funding_fact.funding_time,
                    )
                )
        else:
            raise OnlyBinanceError("BINANCE_USDM_HISTORICAL_FACT_FAMILY_UNSUPPORTED")
        return OnlyHistoricalDataStream(tuple(sorted(updates, key=_update_order_key)), request.batch_size)

    def load_quotes(self, request: OnlyHistoricalQuoteRequest) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        return OnlyHistoricalDataStream((), request.batch_size)

    def load_trades(self, request: OnlyHistoricalTradeRequest) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        return OnlyHistoricalDataStream((), request.batch_size)

    def subscribe(self, _request: OnlyMarketDataSubscriptionRequest) -> OnlyMarketDataSubscriptionResult:
        return OnlyMarketDataSubscriptionResult(
            OnlyMarketDataRequestStatus.UNSUPPORTED_CAPABILITY, None, "USD-M source is historical-only"
        )

    def unsubscribe(self, _request: OnlyMarketDataUnsubscriptionRequest) -> OnlyMarketDataSubscriptionResult:
        return OnlyMarketDataSubscriptionResult(
            OnlyMarketDataRequestStatus.UNSUPPORTED_CAPABILITY, None, "USD-M source is historical-only"
        )

    def instrument(self, instrument_id: OnlyInstrumentId) -> OnlyInstrument | None:
        return self._request.instruments.get(instrument_id)

    def calendar(self, calendar_id: OnlyCalendarId) -> OnlyTradingCalendar | None:
        return self._request.calendars.get(calendar_id)

    def _paged_klines(
        self,
        instrument: OnlyInstrument,
        start_ms: int,
        end_ms: int,
        *,
        kind: OnlyReferencePriceKind | None = None,
    ) -> tuple[Sequence[object], ...]:
        cursor = start_ms
        rows: list[Sequence[object]] = []
        while cursor < end_ms:
            if kind is None:
                page = tuple(
                    self._historical.contract_klines(
                        str(instrument.raw_symbol), cursor, end_ms, self._config.rest_page_size
                    )
                )
            elif kind is OnlyReferencePriceKind.MARK:
                page = tuple(
                    self._historical.mark_price_klines(
                        str(instrument.raw_symbol), cursor, end_ms, self._config.rest_page_size
                    )
                )
            elif kind is OnlyReferencePriceKind.INDEX:
                page = tuple(
                    self._historical.index_price_klines(
                        str(instrument.raw_symbol), cursor, end_ms, self._config.rest_page_size
                    )
                )
            else:
                raise OnlyBinanceError("BINANCE_USDM_REFERENCE_KIND_UNSUPPORTED")
            if not page:
                break
            open_times = tuple(_required_int(item[0], "BINANCE_USDM_KLINE_TIME_INVALID") for item in page)
            if open_times != tuple(sorted(open_times)) or len(set(open_times)) != len(open_times):
                raise OnlyBinanceError("BINANCE_USDM_KLINE_PAGE_ORDER_INVALID")
            next_cursor = open_times[-1] + 60_000
            if next_cursor <= cursor:
                raise OnlyBinanceError("BINANCE_USDM_KLINE_PAGINATION_NO_PROGRESS")
            rows.extend(page)
            cursor = next_cursor
            if len(page) < self._config.rest_page_size:
                break
        return tuple(rows)

    def _paged_funding(
        self, instrument: OnlyInstrument, start_ms: int, end_ms: int
    ) -> tuple[Mapping[str, object], ...]:
        cursor = start_ms
        rows: list[Mapping[str, object]] = []
        while cursor < end_ms:
            page = tuple(
                self._historical.funding_rates(str(instrument.raw_symbol), cursor, end_ms, self._config.rest_page_size)
            )
            if not page:
                break
            times = tuple(_required_int(item.get("fundingTime"), "BINANCE_USDM_FUNDING_TIME_INVALID") for item in page)
            if times != tuple(sorted(times)) or len(set(times)) != len(times):
                raise OnlyBinanceError("BINANCE_USDM_FUNDING_PAGE_ORDER_INVALID")
            next_cursor = times[-1] + 1
            if next_cursor <= cursor:
                raise OnlyBinanceError("BINANCE_USDM_FUNDING_PAGINATION_NO_PROGRESS")
            rows.extend(page)
            cursor = next_cursor
            if len(page) < min(self._config.rest_page_size, 1000):
                break
        return tuple(rows)

    def _bar_envelope(self, bar: OnlyBar, data_version: OnlyDataVersion) -> OnlyMarketDataInboundUpdate:
        return self._envelope(
            only_bar_update_id(self.source_id, bar.instrument_id, bar.bar_type, bar.bar_start, data_version),
            _milliseconds(bar.bar_start) // 60_000,
            data_version,
            bar.instrument_id,
            OnlyMarketDataType.BAR,
            OnlyBarUpdate(bar),
            bar.ts_event,
            semantics=OnlyDataSequenceSemantics.CONTIGUOUS,
        )

    def _fact_envelope(
        self,
        fact_id: str,
        sequence: int,
        data_version: OnlyDataVersion,
        fact: OnlyReferencePriceFact,
    ) -> OnlyMarketDataInboundUpdate:
        return self._envelope(
            OnlyMarketDataUpdateId(fact_id),
            sequence,
            data_version,
            fact.instrument_id,
            OnlyMarketDataType.REFERENCE_PRICE,
            OnlyReferencePriceUpdate(fact),
            fact.ts_event,
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
        *,
        semantics: OnlyDataSequenceSemantics = OnlyDataSequenceSemantics.MONOTONIC,
    ) -> OnlyMarketDataInboundUpdate:
        timestamp = OnlyTimestamp.from_datetime(ts_event)
        return OnlyMarketDataInboundUpdate(
            update_id,
            self._request.runtime_id,
            self.source_id,
            OnlyDataSequence(sequence),
            data_version,
            instrument_id,
            data_type,
            payload,
            timestamp,
            timestamp,
            sequence_semantics=semantics,
        )

    def _connection(
        self, status: OnlyMarketDataRequestStatus, reason: str | None = None
    ) -> OnlyMarketDataConnectionResult:
        return OnlyMarketDataConnectionResult(status, self.connection_snapshot(), reason)


class OnlyBinanceUsdmDataSourceFactory:
    descriptor = USDM_DATA_DESCRIPTOR

    def __init__(self, historical_client: OnlyBinanceUsdmHistoricalClient | None = None) -> None:
        self._historical_client = historical_client

    def parse_config(self, extensions: Mapping[str, object]) -> OnlyBinanceUsdmDataSourceConfig:
        return OnlyBinanceUsdmDataSourceConfig.parse(extensions)

    def validate_request(self, request: OnlyDataSourceCreateRequest) -> Sequence[OnlyPluginValidationIssue]:
        issues = [
            OnlyPluginValidationIssue("PLUGIN_CAPABILITY_MISSING", item)
            for item in USDM_DATA_CAPABILITIES.missing(request.requested_capabilities)
        ]
        if not isinstance(request.plugin_config, OnlyBinanceUsdmDataSourceConfig):
            issues.append(
                OnlyPluginValidationIssue("BINANCE_USDM_PLUGIN_CONFIG_INVALID", "parsed USD-M config is required")
            )
        return tuple(issues)

    def create(self, request: OnlyDataSourceCreateRequest) -> OnlyBinanceUsdmDataSource:
        if not isinstance(request.plugin_config, OnlyBinanceUsdmDataSourceConfig):
            raise TypeError("Binance USD-M DataSource requires OnlyBinanceUsdmDataSourceConfig")
        return OnlyBinanceUsdmDataSource(
            request,
            request.plugin_config,
            historical_client=self._historical_client,
        )


def _milliseconds(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def _required_int(value: object, code: str) -> int:
    if isinstance(value, bool):
        raise OnlyBinanceError(code)
    try:
        result = int(str(value))
    except (TypeError, ValueError) as exc:
        raise OnlyBinanceError(code) from exc
    if result < 0:
        raise OnlyBinanceError(code)
    return result


def only_normalize_binance_usdm_kline(
    row: Sequence[object], instrument: OnlyInstrument, bar_type: OnlyBarType
) -> OnlyBar:
    if len(row) < 11:
        raise OnlyBinanceError("BINANCE_USDM_KLINE_SHAPE_INVALID")
    start = datetime.fromtimestamp(_required_int(row[0], "BINANCE_USDM_KLINE_TIME_INVALID") / 1000, tz=UTC)
    end = start + timedelta(minutes=1)
    return OnlyBar(
        bar_type=bar_type,
        open=OnlyPrice(Decimal(str(row[1])), instrument.price_precision),
        high=OnlyPrice(Decimal(str(row[2])), instrument.price_precision),
        low=OnlyPrice(Decimal(str(row[3])), instrument.price_precision),
        close=OnlyPrice(Decimal(str(row[4])), instrument.price_precision),
        volume=OnlyQuantity(Decimal(str(row[5])), instrument.quantity_precision),
        quote_volume=OnlyQuantity(Decimal(str(row[7])), instrument.price_precision + instrument.quantity_precision),
        turnover=None,
        trade_count=int(str(row[8])),
        open_interest=None,
        bar_start=start,
        bar_end=end,
        ts_event=end,
        ts_init=end,
        is_closed=True,
        revision=0,
        adjustment_type=OnlyAdjustmentType.RAW,
        trading_day=start.date(),
        session_type=OnlySessionType.CONTINUOUS,
    )


def _update_order_key(update: OnlyMarketDataInboundUpdate) -> tuple[int, int, int, str]:
    priority = (
        update.payload.fact.stable_order[1]
        if isinstance(update.payload, OnlyReferencePriceUpdate | OnlyFundingRateUpdate)
        else 0
    )
    return (
        update.ts_event.unix_nanos,
        priority,
        int(update.source_sequence),
        str(update.update_id),
    )


factory = OnlyBinanceUsdmDataSourceFactory()


__all__ = [
    "OnlyBinanceUsdmDataSource",
    "OnlyBinanceUsdmDataSourceConfig",
    "OnlyBinanceUsdmDataSourceFactory",
    "OnlyBinanceUsdmHistoricalClient",
    "only_normalize_binance_usdm_kline",
    "factory",
]
