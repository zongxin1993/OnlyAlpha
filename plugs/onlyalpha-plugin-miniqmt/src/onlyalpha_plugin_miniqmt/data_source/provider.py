"""MiniQMT vendor adapter for OnlyAlpha's provider-neutral cache service."""

from typing import Any

from onlyalpha.cache.historical.models import OnlyHistoricalCacheKey
from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.data.historical import OnlyDataQualityReport, OnlyHistoricalDataRequest, OnlyHistoricalFetchResult
from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.data.models import OnlyHistoricalBarRequest, OnlyHistoricalDataRange
from onlyalpha.domain.instrument import OnlyInstrument

from .historical import load_normalized_bars


class OnlyMiniQmtHistoricalDataProvider:
    def __init__(
        self,
        xtdata: Any,
        source_id: OnlyMarketDataSourceId,
        instrument: OnlyInstrument,
        data_version: OnlyDataVersion,
        batch_size: int,
    ) -> None:
        self._xtdata = xtdata
        self._source_id = source_id
        self._instrument = instrument
        self._data_version = data_version
        self._batch_size = batch_size

    def build_cache_key(self, request: OnlyHistoricalDataRequest) -> OnlyHistoricalCacheKey:
        return OnlyHistoricalCacheKey(
            str(self._source_id),
            "bars",
            request.instrument_id,
            request.bar_type,
            request.price_adjustment,
            request.adjustment_reference,
            time_semantics_version=2,
        )

    def fetch(self, request: OnlyHistoricalDataRequest, time_range: OnlyTimeRange) -> OnlyHistoricalFetchResult:
        source_request = OnlyHistoricalBarRequest(
            f"cache:{request.instrument_id}",
            frozenset({request.instrument_id}),
            frozenset({request.bar_type}),
            OnlyHistoricalDataRange(time_range.start, time_range.end),
            self._data_version,
            batch_size=self._batch_size,
        )
        bars = load_normalized_bars(
            self._xtdata,
            {request.instrument_id: self._instrument},
            source_request,
        )
        coverage = (
            (
                OnlyTimeRange(
                    min(item.bar_start for item in bars),
                    max(item.bar_end for item in bars),
                ),
            )
            if bars
            else ()
        )
        return OnlyHistoricalFetchResult(
            bars,
            (time_range,),
            coverage,
            OnlyDataQualityReport(True),
            {
                "vendor": "miniqmt",
                "source_timezone": "Asia/Shanghai",
                "price_adjustment": request.price_adjustment.value,
            },
        )
