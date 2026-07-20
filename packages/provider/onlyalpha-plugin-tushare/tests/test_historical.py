from datetime import UTC, datetime

from onlyalpha_plugin_tushare.data_source.provider import (
    OnlyTushareHistoricalDataProvider,
)

from onlyalpha.cache.historical import (
    OnlyHistoricalCacheService,
    OnlyParquetHistoricalCacheStore,
)
from onlyalpha.cache.historical.models import OnlyCachePolicy, OnlyHistoricalDataRequest
from onlyalpha.core.ranges import OnlyTimeRange

from .support import OnlyFakeFrame, row


class OnlyCountingClient:
    def __init__(self) -> None:
        self.calls = 0

    def pro_bar(self, **parameters: object) -> object:
        self.calls += 1
        return OnlyFakeFrame([row()])


def test_cache_vertical_slice_reloads_parquet_and_cache_only_skips_client(
    tmp_path, instrument, calendar, bar_type
) -> None:
    client = OnlyCountingClient()
    creations = 0

    def create_client() -> OnlyCountingClient:
        nonlocal creations
        creations += 1
        return client

    provider = OnlyTushareHistoricalDataProvider(
        "tushare-history", instrument, calendar, create_client
    )
    requested = OnlyTimeRange(
        datetime(2025, 1, 2, 16, tzinfo=UTC), datetime(2025, 1, 6, 16, tzinfo=UTC)
    )
    request = OnlyHistoricalDataRequest(instrument.instrument_id, bar_type, requested)
    service = OnlyHistoricalCacheService(OnlyParquetHistoricalCacheStore(tmp_path))

    first = service.load(request, provider)
    second = service.load(request, provider, OnlyCachePolicy.CACHE_ONLY)

    assert creations == client.calls == 1
    assert first.records == second.records
    assert first.manifest.resolved_ranges == (requested,)
    assert first.statistics.content_fingerprint == second.statistics.content_fingerprint
    assert second.statistics.cache_hit
