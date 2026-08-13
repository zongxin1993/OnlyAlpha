from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

from onlyalpha.cache.historical import OnlyHistoricalCacheService, OnlyParquetHistoricalCacheStore
from onlyalpha.cache.historical.models import OnlyCachePolicy, OnlyHistoricalCacheKey
from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.data.historical import OnlyDataQualityReport, OnlyHistoricalFetchResult
from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import OnlySessionType
from onlyalpha.domain.identifiers import OnlyCalendarId
from onlyalpha.domain.time import OnlyTimeZone
from onlyalpha.research.dataset import (
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyResearchDatasetDefinition,
    OnlyResearchDatasetMaterializationPlan,
    OnlyResearchDatasetMaterializer,
)
from tests.domain_conformance.support.instruments import build_instruments
from tests.domain_conformance.support.market_data import build_bar


class _Provider:
    def __init__(self, request, bar) -> None:
        self.request = request
        self.bar = bar

    def build_cache_key(self, request):
        return OnlyHistoricalCacheKey(
            str(self.request.source_id),
            "bars",
            request.instrument_id,
            request.bar_type,
            request.price_adjustment,
            request.adjustment_reference,
        )

    def fetch(self, request, time_range):
        return OnlyHistoricalFetchResult(
            (self.bar,), (time_range,), (), OnlyDataQualityReport(True), {"vendor": str(self.request.source_id)}
        )


class _Factory:
    def __init__(self, bar) -> None:
        self.bar = bar
        self.requests = []

    def create_historical_provider(self, request):
        self.requests.append(request)
        return _Provider(request, self.bar)


def _plan(source: str, factory: _Factory):
    bar = factory.bar
    instrument = replace(build_instruments()["a_share"], trading_calendar_id=OnlyCalendarId("XSHG"))
    calendar = OnlyTradingCalendar(
        instrument.trading_calendar_id,
        instrument.instrument_id.venue,
        OnlyTimeZone("Asia/Shanghai"),
        (OnlyTradingSession("regular", time(9, 30), time(15), OnlySessionType.REGULAR),),
    )
    definition = OnlyResearchDatasetDefinition(
        (bar.instrument_id,),
        bar.bar_type.specification,
        bar.bar_type.aggregation_source,
        OnlyTimeRange(bar.bar_start, bar.ts_event + timedelta(seconds=1)),
    )
    return OnlyResearchDatasetMaterializationPlan(
        definition,
        OnlyMarketDataSourceId(source),
        factory,
        {},
        {instrument.instrument_id: instrument},
        {instrument.trading_calendar_id: calendar},
        OnlyDataVersion("v1"),
        OnlyCachePolicy.PREFER_CACHE,
        100,
        Path("."),
        f"plugin-{source}",
        "1.0",
    )


def test_materializer_provider_identity_changes_provenance_not_snapshot(tmp_path) -> None:
    bar = build_bar()
    snapshots = []
    for source in ("provider-a", "provider-b"):
        factory = _Factory(bar)
        root = tmp_path / source
        snapshot = OnlyResearchDatasetMaterializer(
            OnlyHistoricalCacheService(OnlyParquetHistoricalCacheStore(root / "cache")),
            OnlyParquetResearchDatasetSnapshotStore(root / "datasets"),
            lambda: datetime(2026, 1, 1, tzinfo=UTC),
        ).materialize(_plan(source, factory))
        snapshots.append(snapshot)
        request = factory.requests[0]
        assert (
            not hasattr(request, "runtime_id") and not hasattr(request, "clock") and not hasattr(request, "event_bus")
        )
    assert snapshots[0].snapshot_fingerprint == snapshots[1].snapshot_fingerprint
    assert snapshots[0].content_fingerprint == snapshots[1].content_fingerprint
    assert snapshots[0].provenance != snapshots[1].provenance
