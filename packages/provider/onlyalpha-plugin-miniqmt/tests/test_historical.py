from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from onlyalpha_plugin_miniqmt.data_source.historical import load_bars
from onlyalpha_plugin_miniqmt.data_source.provider import (
    OnlyMiniQmtHistoricalDataProvider,
)

from onlyalpha.cache.historical import (
    OnlyHistoricalCacheService,
    OnlyParquetHistoricalCacheStore,
)
from onlyalpha.cache.historical.models import OnlyCachePolicy, OnlyHistoricalDataRequest
from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.data.models import OnlyHistoricalBarRequest, OnlyHistoricalDataRange
from onlyalpha.domain.enums import (
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyPriceType,
)
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyBarSpecification, OnlyBarType


class OnlyFakeXtData:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.downloads: list[tuple[object, ...]] = []

    def download_history_data(self, *args: object) -> None:
        self.downloads.append(args)

    def get_market_data_ex(self, *args: object, **kwargs: object) -> dict[str, object]:
        return {"600000.SH": self.rows}


def _request() -> OnlyHistoricalBarRequest:
    instrument = OnlyInstrumentId.parse("600000.XSHG")
    bar_type = OnlyBarType(
        instrument,
        OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
        OnlyAggregationSource.EXTERNAL,
    )
    return OnlyHistoricalBarRequest(
        "history-1",
        frozenset({instrument}),
        frozenset({bar_type}),
        OnlyHistoricalDataRange(
            datetime(2026, 1, 5, 1, 30, tzinfo=UTC),
            datetime(2026, 1, 5, 1, 33, tzinfo=UTC),
        ),
        OnlyDataVersion("test-v1"),
    )


def test_history_is_sorted_deduplicated_and_utc() -> None:
    rows = [
        {
            "time": 1_767_576_660_000,
            "open": "10.02",
            "high": "10.05",
            "low": "10.01",
            "close": "10.04",
            "volume": 200,
        },
        {
            "time": 1_767_576_600_000,
            "open": "10.00",
            "high": "10.03",
            "low": "9.99",
            "close": "10.02",
            "volume": 100,
        },
        {
            "time": 1_767_576_600_000,
            "open": "10.00",
            "high": "10.03",
            "low": "9.99",
            "close": "10.02",
            "volume": 100,
        },
    ]
    source = OnlyFakeXtData(rows)
    create = SimpleNamespace(runtime_id=OnlyRuntimeId("runtime"), source_id=OnlyMarketDataSourceId("miniqmt"))
    result = load_bars(source, create, _request())
    assert len(result) == 2
    assert result[0].ts_event < result[1].ts_event
    assert all(item.payload.bar.ts_event.tzinfo is UTC for item in result)


def test_invalid_ohlc_is_rejected() -> None:
    source = OnlyFakeXtData(
        [
            {
                "time": 1_767_576_600_000,
                "open": 10,
                "high": 9,
                "low": 8,
                "close": 10,
                "volume": 1,
            }
        ]
    )
    create = SimpleNamespace(runtime_id=OnlyRuntimeId("runtime"), source_id=OnlyMarketDataSourceId("miniqmt"))
    with pytest.raises(ValueError, match="invalid OHLC"):
        load_bars(source, create, _request())


def test_cache_only_second_load_does_not_call_xtquant(tmp_path) -> None:
    source = OnlyFakeXtData(
        [
            {
                "time": 1_767_576_600_000,
                "open": "10.00",
                "high": "10.03",
                "low": "9.99",
                "close": "10.02",
                "volume": 100,
            }
        ]
    )
    create = SimpleNamespace(runtime_id=OnlyRuntimeId("runtime"), source_id=OnlyMarketDataSourceId("miniqmt"))
    request = _request()
    bar_type = next(iter(request.bar_types))
    cache_request = OnlyHistoricalDataRequest(
        bar_type.instrument_id,
        bar_type,
        OnlyTimeRange(request.data_range.start_time, datetime(2026, 1, 5, 1, 31, tzinfo=UTC)),
    )
    provider = OnlyMiniQmtHistoricalDataProvider(source, create, request.data_version, request.batch_size)
    service = OnlyHistoricalCacheService(OnlyParquetHistoricalCacheStore(tmp_path))
    first = service.load(cache_request, provider)
    downloads = len(source.downloads)
    second = service.load(cache_request, provider, OnlyCachePolicy.CACHE_ONLY)
    assert len(source.downloads) == downloads
    assert first.records == second.records
    assert first.manifest.content_fingerprint == second.manifest.content_fingerprint
