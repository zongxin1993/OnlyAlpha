from __future__ import annotations

from datetime import UTC, datetime, timedelta

from onlyalpha_plugin_binance.spot.data_source.historical import (
    OnlyBinanceSpotHistoricalClient,
    OnlyBinanceSpotHistoricalProvider,
)

from onlyalpha.cache.historical import OnlyHistoricalCacheService, OnlyParquetHistoricalCacheStore
from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.data.historical import OnlyHistoricalDataRequest, OnlyHistoricalTradeDataRequest
from onlyalpha.data.identifiers import OnlyDataVersion


class FakeHistoricalClient:
    def __init__(self, klines, locator=(), trades=()):  # type: ignore[no-untyped-def]
        self.klines_result = klines
        self.locator = locator
        self.trades = trades
        self.kline_calls: list[tuple[int, int]] = []

    def klines(self, symbol: str, start_ms: int, end_ms: int, limit: int):  # type: ignore[no-untyped-def]
        self.kline_calls.append((start_ms, end_ms))
        return [item for item in self.klines_result if start_ms <= int(item[0]) < end_ms][:limit]

    def aggregate_trade_locator(self, symbol: str, start_ms: int, end_ms: int):  # type: ignore[no-untyped-def]
        return self.locator

    def historical_trades(self, symbol: str, from_id: int, limit: int):  # type: ignore[no-untyped-def]
        return [item for item in self.trades if int(item["id"]) >= from_id][:limit]


class FakeHttpClient:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls: list[tuple[str, object]] = []

    def get_json(self, path: str, parameters=None):  # type: ignore[no-untyped-def]
        self.calls.append((path, parameters))
        return self.payload


def _provider(client, now: datetime, instrument_bar_type):  # type: ignore[no-untyped-def]
    instrument, bar_type = instrument_bar_type
    return (
        OnlyBinanceSpotHistoricalProvider(
            client,
            instrument,
            bar_type,
            OnlyDataVersion("binance-v1"),
            page_size=2,
            now=lambda: now,
            source_id="binance",
        ),
        instrument,
        bar_type,
    )


def _kline(start: datetime):
    start_ms = int(start.timestamp() * 1000)
    return [start_ms, "10.00", "11.00", "9.00", "10.50", "100", start_ms + 59_999, "1050", 42, "0", "0"]


def test_reference_price_client_uses_exact_rest_semantics() -> None:
    http = FakeHttpClient(b'{"symbol":"BTCUSDT","referencePrice":"10.00","timestamp":1767225600123}')
    client = OnlyBinanceSpotHistoricalClient(http)  # type: ignore[arg-type]

    assert client.reference_price("BTCUSDT") == {
        "symbol": "BTCUSDT",
        "referencePrice": "10.00",
        "timestamp": 1_767_225_600_123,
    }
    assert http.calls == [("/api/v3/referencePrice", {"symbol": "BTCUSDT"})]

    missing = FakeHttpClient(b'{"code":-2043,"msg":"This symbol does not have a reference price."}')
    assert OnlyBinanceSpotHistoricalClient(missing).reference_price("BTCUSDT") is None  # type: ignore[arg-type]


def test_historical_bar_exact_half_open_range_and_open_tail_cannot_close_coverage(tmp_path, binance_bar_type) -> None:  # type: ignore[no-untyped-def]
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(minutes=3)
    client = FakeHistoricalClient([_kline(start + timedelta(minutes=item)) for item in range(3)])
    provider, instrument, bar_type = _provider(client, end, binance_bar_type)
    time_range = OnlyTimeRange(start, end)
    result = provider.fetch(OnlyHistoricalDataRequest(instrument.instrument_id, bar_type, time_range), time_range)
    assert tuple(item.bar_start for item in result.records) == tuple(
        start + timedelta(minutes=item) for item in range(3)
    )
    assert result.resolved_ranges == (time_range,)
    assert all(start <= item.bar_start < item.bar_end <= end for item in result.records)
    cached = OnlyHistoricalCacheService(OnlyParquetHistoricalCacheStore(tmp_path)).load_bars(
        OnlyHistoricalDataRequest(instrument.instrument_id, bar_type, time_range), provider
    )
    assert tuple(item.bar_start for item in cached.records) == tuple(
        start + timedelta(minutes=item) for item in range(3)
    )

    open_tail_provider, instrument, bar_type = _provider(client, end - timedelta(seconds=1), binance_bar_type)
    incomplete = open_tail_provider.fetch(
        OnlyHistoricalDataRequest(instrument.instrument_id, bar_type, time_range), time_range
    )
    assert len(incomplete.records) == 2
    assert incomplete.resolved_ranges == ()


def test_historical_raw_trade_locator_rows_are_not_emitted_and_range_is_exact(binance_bar_type) -> None:  # type: ignore[no-untyped-def]
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(seconds=2)
    start_ms = int(start.timestamp() * 1000)
    trades = [
        {"id": 10, "price": "10.00", "qty": "1", "time": start_ms - 1, "isBuyerMaker": False},
        {"id": 11, "price": "10.00", "qty": "1", "time": start_ms, "isBuyerMaker": False},
        {"id": 12, "price": "11.00", "qty": "2", "time": start_ms + 1_000, "isBuyerMaker": True},
        {"id": 13, "price": "12.00", "qty": "3", "time": start_ms + 2_000, "isBuyerMaker": False},
    ]
    client = FakeHistoricalClient([], locator=({"a": 999, "f": 10},), trades=trades)
    provider, instrument, _ = _provider(client, end + timedelta(seconds=1), binance_bar_type)
    time_range = OnlyTimeRange(start, end)
    result = provider.fetch_trades(OnlyHistoricalTradeDataRequest(instrument.instrument_id, time_range), time_range)
    assert tuple(str(item.trade_id) for item in result.records) == ("11", "12")
    assert result.resolved_ranges == (time_range,)
    assert all(start <= item.ts_event < end for item in result.records)
