import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from onlyalpha.cache.historical import OnlyHistoricalCacheService, OnlyParquetHistoricalCacheStore
from onlyalpha.cache.historical.models import (
    OnlyCachePolicy,
    OnlyHistoricalCacheKey,
    OnlyHistoricalTradeCacheKey,
)
from onlyalpha.core.ranges import OnlyTimeRange, only_merge_ranges, only_missing_ranges
from onlyalpha.data.historical import (
    OnlyDataQualityReport,
    OnlyHistoricalDataRequest,
    OnlyHistoricalFetchResult,
    OnlyHistoricalTradeDataRequest,
    OnlyHistoricalTradeFetchResult,
)
from onlyalpha.domain.errors import OnlyValidationError
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyTradeId

from ..domain_conformance.support.market_data import build_bar, build_trade_tick


def test_time_ranges_merge_adjacency_and_find_middle_gap() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    requested = OnlyTimeRange(start, start + timedelta(days=4))
    coverage = (
        OnlyTimeRange(start, start + timedelta(days=1)),
        OnlyTimeRange(start + timedelta(days=1), start + timedelta(days=2)),
        OnlyTimeRange(start + timedelta(days=3), start + timedelta(days=4)),
    )
    assert only_merge_ranges(coverage)[:1] == (OnlyTimeRange(start, start + timedelta(days=2)),)
    assert only_missing_ranges(requested, coverage) == (
        OnlyTimeRange(start + timedelta(days=2), start + timedelta(days=3)),
    )
    with pytest.raises(OnlyValidationError):
        OnlyTimeRange(datetime(2026, 1, 1), datetime(2026, 1, 2))


class OnlyFakeProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.bar = build_bar()

    def build_cache_key(self, request: OnlyHistoricalDataRequest) -> OnlyHistoricalCacheKey:
        return OnlyHistoricalCacheKey("fake", "bars", request.instrument_id, request.bar_type, request.price_adjustment)

    def fetch(self, request: OnlyHistoricalDataRequest, time_range: OnlyTimeRange) -> OnlyHistoricalFetchResult:
        self.calls += 1
        return OnlyHistoricalFetchResult(
            (self.bar,),
            (time_range,),
            (OnlyTimeRange(self.bar.bar_start, self.bar.bar_end),),
            OnlyDataQualityReport(True),
            {"vendor": "fake"},
        )


def test_first_load_writes_then_reads_parquet_and_cache_only_does_not_fetch(tmp_path) -> None:
    provider = OnlyFakeProvider()
    requested = OnlyTimeRange(provider.bar.bar_start, provider.bar.ts_event + timedelta(microseconds=1))
    request = OnlyHistoricalDataRequest(provider.bar.instrument_id, provider.bar.bar_type, requested)
    service = OnlyHistoricalCacheService(OnlyParquetHistoricalCacheStore(tmp_path))

    first = service.load(request, provider)
    second = service.load(request, provider, OnlyCachePolicy.CACHE_ONLY)

    assert provider.calls == 1
    assert first.records == second.records == (provider.bar,)
    assert first.statistics.content_fingerprint == second.statistics.content_fingerprint
    assert second.statistics.cache_hit


class OnlyFakeTradeProvider:
    def __init__(self, data_version: str) -> None:
        self.calls = 0
        self.trade = build_trade_tick()
        self.trades = (self.trade,)
        self.data_version = data_version
        self.ranges: list[OnlyTimeRange] = []

    def build_trade_cache_key(self, request: OnlyHistoricalTradeDataRequest) -> OnlyHistoricalTradeCacheKey:
        return OnlyHistoricalTradeCacheKey(
            "fake",
            "trades",
            request.instrument_id,
            data_version=self.data_version,
        )

    def fetch_trades(
        self, request: OnlyHistoricalTradeDataRequest, time_range: OnlyTimeRange
    ) -> OnlyHistoricalTradeFetchResult:
        self.calls += 1
        self.ranges.append(time_range)
        return OnlyHistoricalTradeFetchResult(
            tuple(item for item in self.trades if time_range.contains(item.ts_event)),
            (time_range,),
            (time_range,),
            OnlyDataQualityReport(True),
            {"vendor": "fake"},
        )


def test_typed_trade_cache_is_local_first_and_data_version_isolated(tmp_path) -> None:
    provider_v1 = OnlyFakeTradeProvider("normalizer-v1")
    provider_v2 = OnlyFakeTradeProvider("normalizer-v2")
    requested = OnlyTimeRange(
        provider_v1.trade.ts_event - timedelta(seconds=1),
        provider_v1.trade.ts_event + timedelta(seconds=1),
    )
    request = OnlyHistoricalTradeDataRequest(provider_v1.trade.instrument_id, requested)
    service = OnlyHistoricalCacheService(OnlyParquetHistoricalCacheStore(tmp_path))

    first = service.load_trades(request, provider_v1)
    cached = service.load_trades(request, provider_v1, OnlyCachePolicy.CACHE_ONLY)
    second_version = service.load_trades(request, provider_v2)

    assert provider_v1.calls == 1
    assert provider_v2.calls == 1
    assert first.records == cached.records == second_version.records == (provider_v1.trade,)
    assert first.statistics.content_fingerprint != second_version.statistics.content_fingerprint


def test_trade_cache_fetches_only_exact_missing_suffix_and_force_refreshes(tmp_path) -> None:
    provider = OnlyFakeTradeProvider("normalizer-v1")
    first_range = OnlyTimeRange(
        provider.trade.ts_event - timedelta(seconds=1),
        provider.trade.ts_event + timedelta(seconds=1),
    )
    full_range = OnlyTimeRange(first_range.start, first_range.end + timedelta(seconds=2))
    service = OnlyHistoricalCacheService(OnlyParquetHistoricalCacheStore(tmp_path))
    service.load_trades(OnlyHistoricalTradeDataRequest(provider.trade.instrument_id, first_range), provider)
    service.load_trades(OnlyHistoricalTradeDataRequest(provider.trade.instrument_id, full_range), provider)
    assert provider.ranges[-1] == OnlyTimeRange(first_range.end, full_range.end)

    service.load_trades(
        OnlyHistoricalTradeDataRequest(provider.trade.instrument_id, full_range),
        provider,
        OnlyCachePolicy.FORCE_REFRESH,
    )
    assert provider.ranges[-1] == full_range


def test_trade_cache_detects_corrupt_partition_and_cache_only_fails_closed(tmp_path) -> None:
    provider = OnlyFakeTradeProvider("normalizer-v1")
    requested = OnlyTimeRange(
        provider.trade.ts_event - timedelta(seconds=1),
        provider.trade.ts_event + timedelta(seconds=1),
    )
    request = OnlyHistoricalTradeDataRequest(provider.trade.instrument_id, requested)
    store = OnlyParquetHistoricalCacheStore(tmp_path)
    service = OnlyHistoricalCacheService(store)
    result = service.load_trades(request, provider)
    relative = next(iter(result.manifest.partition_hashes))
    partition = store._key_root(result.manifest.key) / relative
    partition.write_bytes(b"corrupt")

    with pytest.raises(Exception, match="partition hash mismatch"):
        service.load_trades(request, provider, OnlyCachePolicy.CACHE_ONLY)


def test_trade_cache_empty_resolution_validation_and_manifest_mismatch_fail_closed(tmp_path) -> None:
    provider = OnlyFakeTradeProvider("normalizer-v1")
    empty_range = OnlyTimeRange(
        provider.trade.ts_event + timedelta(days=1),
        provider.trade.ts_event + timedelta(days=1, seconds=1),
    )
    service = OnlyHistoricalCacheService(OnlyParquetHistoricalCacheStore(tmp_path))
    empty = service.load_trades(OnlyHistoricalTradeDataRequest(provider.trade.instrument_id, empty_range), provider)
    assert empty.records == () and empty.manifest.resolved_ranges == (empty_range,)

    missing = OnlyHistoricalTradeDataRequest(
        provider.trade.instrument_id,
        OnlyTimeRange(empty_range.end, empty_range.end + timedelta(seconds=1)),
    )
    with pytest.raises(Exception, match="does not fully cover"):
        service.load_trades(missing, provider, OnlyCachePolicy.CACHE_ONLY)

    invalid = OnlyFakeTradeProvider("invalid-v1")
    invalid.trade = replace(invalid.trade, instrument_id=OnlyInstrumentId.parse("OTHER.XTEST"))
    invalid.trades = (invalid.trade,)
    invalid_range = OnlyTimeRange(
        invalid.trade.ts_event - timedelta(seconds=1), invalid.trade.ts_event + timedelta(seconds=1)
    )
    with pytest.raises(Exception, match="strict historical Trade validation"):
        service.load_trades(
            OnlyHistoricalTradeDataRequest(provider.trade.instrument_id, invalid_range),
            invalid,
        )

    healthy = OnlyFakeTradeProvider("manifest-v1")
    request_range = OnlyTimeRange(
        healthy.trade.ts_event - timedelta(seconds=1), healthy.trade.ts_event + timedelta(seconds=1)
    )
    request = OnlyHistoricalTradeDataRequest(healthy.trade.instrument_id, request_range)
    store = OnlyParquetHistoricalCacheStore(tmp_path / "manifest")
    manifest_result = OnlyHistoricalCacheService(store).load_trades(request, healthy)
    manifest_path = store._key_root(manifest_result.manifest.key) / "manifest.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["key"]["data_version"] = "tampered"
    manifest_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(Exception, match="manifest key mismatch"):
        OnlyHistoricalCacheService(store).load_trades(request, healthy, OnlyCachePolicy.CACHE_ONLY)


def test_trade_cache_read_order_fingerprint_and_atomic_replacement_are_deterministic(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import onlyalpha.cache.historical.store as store_module

    provider = OnlyFakeTradeProvider("normalizer-v1")
    provider.trades = (
        replace(provider.trade, trade_id=OnlyTradeId("1"), sequence=1),
        replace(
            provider.trade,
            trade_id=OnlyTradeId("2"),
            sequence=2,
            ts_event=provider.trade.ts_event + timedelta(milliseconds=1),
            ts_init=provider.trade.ts_init + timedelta(milliseconds=1),
        ),
    )
    requested = OnlyTimeRange(
        provider.trade.ts_event - timedelta(seconds=1), provider.trade.ts_event + timedelta(seconds=1)
    )
    request = OnlyHistoricalTradeDataRequest(provider.trade.instrument_id, requested)
    store = OnlyParquetHistoricalCacheStore(tmp_path)
    service = OnlyHistoricalCacheService(store)
    first = service.load_trades(request, provider)
    refreshed = service.load_trades(request, provider, OnlyCachePolicy.FORCE_REFRESH)
    assert tuple(str(item.trade_id) for item in refreshed.records) == ("1", "2")
    assert refreshed.statistics.content_fingerprint == first.statistics.content_fingerprint

    original_replace = store_module.os.replace
    calls = 0

    def fail_publication(source, destination):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected atomic publication failure")
        return original_replace(source, destination)

    monkeypatch.setattr(store_module.os, "replace", fail_publication)
    with pytest.raises(OSError, match="atomic publication failure"):
        service.load_trades(request, provider, OnlyCachePolicy.FORCE_REFRESH)
    restored = service.load_trades(request, provider, OnlyCachePolicy.CACHE_ONLY)
    assert restored.records == first.records
