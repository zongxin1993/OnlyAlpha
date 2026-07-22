"""MiniQMT vendor adapter for OnlyAlpha's provider-neutral cache service."""

from typing import Any

from onlyalpha.cache.historical.models import (
    OnlyDataQualityReport,
    OnlyHistoricalCacheKey,
    OnlyHistoricalDataRequest,
    OnlyHistoricalFetchResult,
)
from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.data.identifiers import OnlyDataVersion
from onlyalpha.data.models import OnlyHistoricalBarRequest, OnlyHistoricalDataRange
from onlyalpha.plugin.data_source import OnlyDataSourceCreateRequest

from .historical import load_bars


class OnlyMiniQmtHistoricalDataProvider:
    def __init__(
        self,
        xtdata: Any,
        create_request: OnlyDataSourceCreateRequest,
        data_version: OnlyDataVersion,
        batch_size: int,
    ) -> None:
        self._xtdata = xtdata
        self._create_request = create_request
        self._data_version = data_version
        self._batch_size = batch_size

    def build_cache_key(self, request: OnlyHistoricalDataRequest) -> OnlyHistoricalCacheKey:
        return OnlyHistoricalCacheKey(
            str(self._create_request.source_id),
            "bars",
            request.instrument_id,
            request.bar_type,
            request.price_adjustment,
            request.adjustment_reference,
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
        updates = load_bars(self._xtdata, self._create_request, source_request)
        bars = tuple(item.payload.bar for item in updates)
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
