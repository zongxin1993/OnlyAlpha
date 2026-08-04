"""Adapter from isolated warmup results to the existing historical cache."""

from __future__ import annotations

from onlyalpha.cache.historical.models import (
    OnlyDataQualityReport,
    OnlyHistoricalCacheKey,
    OnlyHistoricalDataRequest,
    OnlyHistoricalFetchResult,
)
from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.data.warmup import OnlyHistoricalWarmupRequest, OnlyHistoricalWarmupStatus

from .client import OnlyMiniQmtHistoricalIsolatedClient


class OnlyMiniQmtWarmupFetchError(RuntimeError):
    def __init__(self, result: object, code: str) -> None:
        super().__init__(f"isolated MiniQMT historical fetch failed closed: {code}")
        self.result = result


class OnlyMiniQmtIsolatedWarmupCacheProvider:
    def __init__(
        self,
        client: OnlyMiniQmtHistoricalIsolatedClient,
        warmup_request: OnlyHistoricalWarmupRequest,
        source_id: str,
    ) -> None:
        self._client = client
        self._warmup_request = warmup_request
        self._source_id = source_id

    def build_cache_key(self, request: OnlyHistoricalDataRequest) -> OnlyHistoricalCacheKey:
        return OnlyHistoricalCacheKey(
            self._source_id,
            "bars",
            request.instrument_id,
            request.bar_type,
            request.price_adjustment,
            request.adjustment_reference,
            time_semantics_version=2,
            data_version=str(self._warmup_request.data_version),
            compatibility_profile_id=self._warmup_request.compatibility_profile_id,
        )

    def fetch(self, request: OnlyHistoricalDataRequest, time_range: OnlyTimeRange) -> OnlyHistoricalFetchResult:
        result = self._client.load_warmup(self._warmup_request)
        if result.status is not OnlyHistoricalWarmupStatus.SUCCESS:
            diagnostic = result.diagnostic
            code = result.status.value if diagnostic is None else diagnostic.code
            raise OnlyMiniQmtWarmupFetchError(result, code)
        observed = (OnlyTimeRange(min(bar.bar_start for bar in result.bars), max(bar.bar_end for bar in result.bars)),)
        return OnlyHistoricalFetchResult(
            result.bars,
            (time_range,),
            observed,
            OnlyDataQualityReport(True),
            {
                "vendor": "miniqmt",
                "data_version": str(self._warmup_request.data_version),
                "compatibility_profile_id": self._warmup_request.compatibility_profile_id,
                "provider_version": result.provider_version,
                "request_fingerprint": result.request_fingerprint,
                "content_fingerprint": result.content_fingerprint,
                "provider_raw_bar_count": result.provider_raw_bar_count,
                "accepted_bar_count": result.accepted_bar_count,
                "rejected_out_of_range_count": result.rejected_out_of_range_count,
                "provider_raw_last_bar_end_ns": None
                if result.provider_raw_last_bar_end is None
                else result.provider_raw_last_bar_end.unix_nanos,
                "accepted_last_bar_end_ns": None
                if result.accepted_last_bar_end is None
                else result.accepted_last_bar_end.unix_nanos,
            },
        )
