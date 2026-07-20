import os
from datetime import UTC, datetime

import pytest
from onlyalpha_plugin_tushare.config import OnlyTushareConfig
from onlyalpha_plugin_tushare.data_source.provider import (
    OnlyTushareHistoricalDataProvider,
)
from onlyalpha_plugin_tushare.sdk.adapter import OnlyTushareSdkClient
from onlyalpha_plugin_tushare.sdk.loader import load_tushare

from onlyalpha.cache.historical import (
    OnlyHistoricalCacheService,
    OnlyParquetHistoricalCacheStore,
)
from onlyalpha.cache.historical.models import OnlyCachePolicy, OnlyHistoricalDataRequest
from onlyalpha.core.ranges import OnlyTimeRange


@pytest.mark.integration
@pytest.mark.requires_tushare
def test_real_tushare_daily_cache_roundtrip(
    tmp_path, instrument, calendar, bar_type
) -> None:
    if "ONLYALPHA_TUSHARE_TOKEN" not in os.environ:
        pytest.skip("ONLYALPHA_TUSHARE_TOKEN is not configured")
    config = OnlyTushareConfig()
    calls = 0

    def create_client() -> OnlyTushareSdkClient:
        nonlocal calls
        calls += 1
        return OnlyTushareSdkClient(load_tushare(), config.resolve_token())

    provider = OnlyTushareHistoricalDataProvider(
        "tushare-real", instrument, calendar, create_client
    )
    requested = OnlyTimeRange(
        datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 11, tzinfo=UTC)
    )
    request = OnlyHistoricalDataRequest(instrument.instrument_id, bar_type, requested)
    service = OnlyHistoricalCacheService(OnlyParquetHistoricalCacheStore(tmp_path))
    first = service.load(request, provider)
    second = service.load(request, provider, OnlyCachePolicy.CACHE_ONLY)
    assert calls == 1
    assert first.records == second.records
    assert first.statistics.content_fingerprint == second.statistics.content_fingerprint
    assert tuple(item.ts_event for item in first.records) == tuple(
        sorted(item.ts_event for item in first.records)
    )
