"""Bounded Binance Spot REST planning and exact historical acquisition."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime

from onlyalpha.cache.historical.models import (
    OnlyBarTimestampSemantics,
    OnlyHistoricalBarCacheKey,
    OnlyHistoricalTradeCacheKey,
)
from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.data.historical import (
    OnlyDataQualityReport,
    OnlyHistoricalDataRequest,
    OnlyHistoricalFetchResult,
    OnlyHistoricalTradeDataRequest,
    OnlyHistoricalTradeFetchResult,
)
from onlyalpha.data.identifiers import OnlyDataVersion
from onlyalpha.domain.enums import OnlyAdjustmentType
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.market import OnlyBarType
from onlyalpha_plugin_binance.common.http import OnlyBinancePublicHttpClient
from onlyalpha_plugin_binance.errors import OnlyBinanceError

from .normalize import only_normalize_rest_kline, only_normalize_rest_trade


def _milliseconds(value: datetime) -> int:
    return int(value.timestamp() * 1000)


class OnlyBinanceSpotHistoricalClient:
    def __init__(self, http: OnlyBinancePublicHttpClient) -> None:
        self._http = http

    def _get_json(self, endpoint: str, params: Mapping[str, str]) -> bytes:
        return self._http.get_json(endpoint, params)

    def klines(self, symbol: str, start_ms: int, end_ms: int, limit: int) -> Sequence[Sequence[object]]:
        raw = self._get_json(
            "/api/v3/klines",
            {
                "symbol": symbol,
                "interval": "1m",
                "startTime": str(start_ms),
                "endTime": str(end_ms - 1),
                "limit": str(limit),
            },
        )
        value = json.loads(raw)
        if not isinstance(value, list) or any(not isinstance(item, list) for item in value):
            raise OnlyBinanceError("BINANCE_KLINES_RESPONSE_INVALID")
        return value

    def aggregate_trade_locator(self, symbol: str, start_ms: int, end_ms: int) -> Sequence[Mapping[str, object]]:
        raw = self._get_json(
            "/api/v3/aggTrades",
            {"symbol": symbol, "startTime": str(start_ms), "endTime": str(end_ms - 1), "limit": "1"},
        )
        value = json.loads(raw)
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise OnlyBinanceError("BINANCE_TRADE_LOCATOR_RESPONSE_INVALID")
        return value

    def historical_trades(self, symbol: str, from_id: int, limit: int) -> Sequence[Mapping[str, object]]:
        raw = self._get_json(
            "/api/v3/historicalTrades",
            {"symbol": symbol, "fromId": str(from_id), "limit": str(limit)},
        )
        value = json.loads(raw)
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise OnlyBinanceError("BINANCE_HISTORICAL_TRADES_RESPONSE_INVALID")
        return value

    def reference_price(self, symbol: str) -> Mapping[str, object] | None:
        value = json.loads(self._get_json("/api/v3/referencePrice", {"symbol": symbol}))
        if not isinstance(value, dict):
            raise OnlyBinanceError("BINANCE_REFERENCE_PRICE_RESPONSE_INVALID")
        if value.get("code") == -2043:
            return None
        if not {"symbol", "referencePrice", "timestamp"} <= value.keys():
            raise OnlyBinanceError("BINANCE_REFERENCE_PRICE_RESPONSE_INVALID")
        return value

    def recent_trades(self, symbol: str, limit: int = 1) -> Sequence[Mapping[str, object]]:
        value = json.loads(self._get_json("/api/v3/trades", {"symbol": symbol, "limit": str(limit)}))
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise OnlyBinanceError("BINANCE_RECENT_TRADES_RESPONSE_INVALID")
        return value


class OnlyBinanceSpotHistoricalProvider:
    def __init__(
        self,
        client: OnlyBinanceSpotHistoricalClient,
        instrument: OnlyInstrument,
        bar_type: OnlyBarType,
        data_version: OnlyDataVersion,
        *,
        page_size: int,
        now: Callable[[], datetime],
        source_id: str,
    ) -> None:
        self._client = client
        self._instrument = instrument
        self._bar_type = bar_type
        self._data_version = data_version
        self._page_size = page_size
        self._now = now
        self._source_id = source_id

    def build_cache_key(self, request: OnlyHistoricalDataRequest) -> OnlyHistoricalBarCacheKey:
        return OnlyHistoricalBarCacheKey(
            self._source_id,
            "bars",
            request.instrument_id,
            request.bar_type,
            request.price_adjustment,
            request.adjustment_reference,
            data_version=str(self._data_version),
            compatibility_profile_id="BINANCE_SPOT_1M_CLOSED_V1",
            timestamp_semantics=OnlyBarTimestampSemantics.BAR_OPEN,
        )

    def fetch(self, request: OnlyHistoricalDataRequest, time_range: OnlyTimeRange) -> OnlyHistoricalFetchResult:
        if request.price_adjustment is not OnlyAdjustmentType.RAW:
            raise OnlyBinanceError("BINANCE_BAR_ADJUSTMENT_UNSUPPORTED")
        start_ms = _milliseconds(time_range.start)
        end_ms = _milliseconds(time_range.end)
        cursor = start_ms
        rows: list[object] = []
        while cursor < end_ms:
            page = self._client.klines(str(self._instrument.raw_symbol), cursor, end_ms, self._page_size)
            if not page:
                break
            open_times = [int(str(item[0])) for item in page]
            if open_times != sorted(open_times) or len(set(open_times)) != len(open_times):
                raise OnlyBinanceError("BINANCE_KLINE_PAGE_ORDER_INVALID")
            next_cursor = open_times[-1] + 60_000
            if next_cursor <= cursor:
                raise OnlyBinanceError("BINANCE_KLINE_PAGINATION_NO_PROGRESS")
            if any(value < start_ms or value >= end_ms for value in open_times):
                raise OnlyBinanceError("BINANCE_KLINE_OUT_OF_RANGE")
            rows.extend(page)
            cursor = next_cursor
            if len(page) < self._page_size:
                break
        bars = tuple(
            sorted(
                (
                    only_normalize_rest_kline(item, self._instrument, self._bar_type)
                    for item in rows
                    if isinstance(item, Sequence)
                ),
                key=lambda item: item.bar_start,
            )
        )
        closed = tuple(
            item
            for item in bars
            if time_range.start <= item.bar_start and item.bar_end <= time_range.end and item.bar_end <= self._now()
        )
        expected = tuple(range(start_ms, end_ms, 60_000)) if start_ms % 60_000 == 0 else ()
        complete = (
            bool(expected or start_ms == end_ms) and tuple(_milliseconds(item.bar_start) for item in closed) == expected
        )
        resolved = (time_range,) if complete else ()
        observed = tuple(OnlyTimeRange(item.bar_start, item.bar_end) for item in closed)
        return OnlyHistoricalFetchResult(
            closed,
            resolved,
            observed,
            OnlyDataQualityReport(True),
            {"provider": "BINANCE", "family": "BAR", "data_version": str(self._data_version)},
        )

    def build_trade_cache_key(self, request: OnlyHistoricalTradeDataRequest) -> OnlyHistoricalTradeCacheKey:
        return OnlyHistoricalTradeCacheKey(
            self._source_id,
            "trades",
            request.instrument_id,
            data_version=str(self._data_version),
            compatibility_profile_id="BINANCE_SPOT_RAW_TRADE_V1",
        )

    def fetch_trades(
        self, request: OnlyHistoricalTradeDataRequest, time_range: OnlyTimeRange
    ) -> OnlyHistoricalTradeFetchResult:
        start_ms = _milliseconds(time_range.start)
        end_ms = _milliseconds(time_range.end)
        locator = self._client.aggregate_trade_locator(str(self._instrument.raw_symbol), start_ms, end_ms)
        if not locator:
            return OnlyHistoricalTradeFetchResult(
                (),
                (time_range,) if time_range.end <= self._now() else (),
                (),
                OnlyDataQualityReport(True),
                {"provider": "BINANCE", "family": "TRADE", "data_version": str(self._data_version)},
            )
        first = locator[0].get("f", locator[0].get("a"))
        if first is None:
            raise OnlyBinanceError("BINANCE_TRADE_LOCATOR_ID_MISSING")
        cursor = int(str(first))
        raw_rows: list[Mapping[str, object]] = []
        crossed_end = False
        while True:
            page = self._client.historical_trades(str(self._instrument.raw_symbol), cursor, self._page_size)
            if not page:
                break
            ids = [int(str(item["id"])) for item in page]
            if ids != list(range(ids[0], ids[0] + len(ids))) or ids[0] < cursor:
                raise OnlyBinanceError("BINANCE_RAW_TRADE_SEQUENCE_INVALID")
            next_cursor = ids[-1] + 1
            if next_cursor <= cursor:
                raise OnlyBinanceError("BINANCE_TRADE_PAGINATION_NO_PROGRESS")
            raw_rows.extend(page)
            crossed_end = any(int(str(item["time"])) >= end_ms for item in page)
            cursor = next_cursor
            if crossed_end or len(page) < self._page_size:
                break
        trades = tuple(
            sorted(
                (
                    only_normalize_rest_trade(item, self._instrument)
                    for item in raw_rows
                    if start_ms <= int(str(item["time"])) < end_ms
                ),
                key=lambda item: (item.ts_event, str(item.trade_id)),
            )
        )
        complete = crossed_end or (time_range.end <= self._now() and bool(raw_rows))
        return OnlyHistoricalTradeFetchResult(
            trades,
            (time_range,) if complete else (),
            (time_range,) if complete else (),
            OnlyDataQualityReport(True),
            {"provider": "BINANCE", "family": "TRADE", "data_version": str(self._data_version)},
        )
