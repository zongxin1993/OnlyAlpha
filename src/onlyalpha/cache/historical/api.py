"""Provider and store ports for historical data caching."""

from typing import Protocol

from onlyalpha.cache.historical.models import (
    OnlyCacheInspection,
    OnlyCacheManifest,
    OnlyCacheWriteResult,
    OnlyHistoricalCacheKey,
    OnlyHistoricalDataRequest,
    OnlyHistoricalFetchResult,
)
from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.domain.market import OnlyBar


class OnlyHistoricalDataProvider(Protocol):
    def build_cache_key(self, request: OnlyHistoricalDataRequest) -> OnlyHistoricalCacheKey: ...
    def fetch(self, request: OnlyHistoricalDataRequest, time_range: OnlyTimeRange) -> OnlyHistoricalFetchResult: ...


class OnlyHistoricalCacheStore(Protocol):
    def inspect(self, key: OnlyHistoricalCacheKey, requested_range: OnlyTimeRange) -> OnlyCacheInspection: ...
    def read(self, key: OnlyHistoricalCacheKey, time_range: OnlyTimeRange) -> tuple[OnlyBar, ...]: ...
    def write(self, key: OnlyHistoricalCacheKey, result: OnlyHistoricalFetchResult) -> OnlyCacheWriteResult: ...
    def manifest(self, key: OnlyHistoricalCacheKey) -> OnlyCacheManifest: ...
    def invalidate(self, key: OnlyHistoricalCacheKey, time_range: OnlyTimeRange | None = None) -> None: ...
