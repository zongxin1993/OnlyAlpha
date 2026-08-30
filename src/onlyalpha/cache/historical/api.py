"""Provider and store ports for historical data caching."""

from typing import Protocol

from onlyalpha.cache.historical.models import (
    OnlyCacheInspection,
    OnlyCacheManifest,
    OnlyCacheWriteResult,
    OnlyHistoricalCacheKey,
    OnlyHistoricalTradeCacheKey,
    OnlyTypedHistoricalCacheKey,
)
from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.data.historical import models as historical_models
from onlyalpha.domain.market import OnlyBar, OnlyTradeTick


class OnlyHistoricalCacheProvider(Protocol):
    def build_cache_key(self, request: historical_models.OnlyHistoricalDataRequest) -> OnlyHistoricalCacheKey: ...
    def fetch(
        self, request: historical_models.OnlyHistoricalDataRequest, time_range: OnlyTimeRange
    ) -> historical_models.OnlyHistoricalFetchResult: ...


class OnlyHistoricalTradeCacheProvider(Protocol):
    def build_trade_cache_key(
        self, request: historical_models.OnlyHistoricalTradeDataRequest
    ) -> OnlyHistoricalTradeCacheKey: ...
    def fetch_trades(
        self, request: historical_models.OnlyHistoricalTradeDataRequest, time_range: OnlyTimeRange
    ) -> historical_models.OnlyHistoricalTradeFetchResult: ...


class OnlyHistoricalCacheStore(Protocol):
    def inspect(self, key: OnlyTypedHistoricalCacheKey, requested_range: OnlyTimeRange) -> OnlyCacheInspection: ...
    def read(self, key: OnlyHistoricalCacheKey, time_range: OnlyTimeRange) -> tuple[OnlyBar, ...]: ...
    def write(
        self, key: OnlyHistoricalCacheKey, result: historical_models.OnlyHistoricalFetchResult
    ) -> OnlyCacheWriteResult: ...
    def manifest(self, key: OnlyHistoricalCacheKey) -> OnlyCacheManifest: ...
    def invalidate(self, key: OnlyHistoricalCacheKey, time_range: OnlyTimeRange | None = None) -> None: ...
    def read_trades(self, key: OnlyHistoricalTradeCacheKey, time_range: OnlyTimeRange) -> tuple[OnlyTradeTick, ...]: ...
    def write_trades(
        self, key: OnlyHistoricalTradeCacheKey, result: historical_models.OnlyHistoricalTradeFetchResult
    ) -> OnlyCacheWriteResult: ...
