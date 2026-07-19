from datetime import UTC, datetime, timedelta

import pytest

from onlyalpha.cache.historical import OnlyHistoricalCacheService, OnlyParquetHistoricalCacheStore
from onlyalpha.cache.historical.models import (
    OnlyCachePolicy,
    OnlyDataQualityReport,
    OnlyHistoricalCacheKey,
    OnlyHistoricalDataRequest,
    OnlyHistoricalFetchResult,
)
from onlyalpha.core.ranges import OnlyTimeRange, only_merge_ranges, only_missing_ranges
from onlyalpha.domain.errors import OnlyValidationError

from ..domain_conformance.support.market_data import build_bar


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
