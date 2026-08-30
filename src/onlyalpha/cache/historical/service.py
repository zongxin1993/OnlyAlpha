"""Policy orchestration for historical cache reads and provider fetches."""

from onlyalpha.cache.historical.api import (
    OnlyHistoricalCacheProvider,
    OnlyHistoricalCacheStore,
    OnlyHistoricalTradeCacheProvider,
)
from onlyalpha.cache.historical.models import (
    OnlyCachePolicy,
    OnlyCacheStatistics,
    OnlyHistoricalDataResult,
    OnlyHistoricalTradeDataResult,
)
from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.data.historical import (
    OnlyDataQualityReport,
    OnlyHistoricalDataRequest,
    OnlyHistoricalTradeDataRequest,
    only_validate_historical_bars,
    only_validate_historical_trades,
)


class OnlyHistoricalCacheError(RuntimeError):
    pass


class OnlyHistoricalCacheService:
    def __init__(self, store: OnlyHistoricalCacheStore) -> None:
        self._store = store

    def load(
        self,
        request: OnlyHistoricalDataRequest,
        provider: OnlyHistoricalCacheProvider,
        policy: OnlyCachePolicy = OnlyCachePolicy.PREFER_CACHE,
    ) -> OnlyHistoricalDataResult:
        key = provider.build_cache_key(request)
        inspection = self._store.inspect(key, request.time_range)
        if inspection.issues and policy is OnlyCachePolicy.CACHE_ONLY:
            raise OnlyHistoricalCacheError(inspection.issues[0].message)
        missing = (request.time_range,) if policy is OnlyCachePolicy.FORCE_REFRESH else inspection.missing_ranges
        if missing and policy is OnlyCachePolicy.CACHE_ONLY:
            raise OnlyHistoricalCacheError("valid cache does not fully cover the requested range")
        rows_fetched = 0
        partitions_written = 0
        issues = list(inspection.issues)
        for time_range in missing:
            fetched = provider.fetch(request, time_range)
            rows_fetched += len(fetched.records)
            issues.extend(fetched.quality_report.issues)
            validation = only_validate_historical_bars(key.instrument_id, key.bar_type, fetched.records)
            issues.extend(validation.issues)
            in_range = all(
                time_range.contains(item.bar_start if key.timestamp_semantics.value == "bar_open" else item.ts_event)
                for item in fetched.records
            )
            coverage_valid = _coverage_within(time_range, fetched.resolved_ranges)
            if not fetched.quality_report.valid or not validation.valid or not in_range or not coverage_valid:
                raise OnlyHistoricalCacheError("provider data failed strict historical Bar validation")
            partitions_written += self._store.write(key, fetched).partitions_written
        final = self._store.inspect(key, request.time_range)
        if not final.valid or final.manifest is None:
            raise OnlyHistoricalCacheError("cache remains incomplete after fetch")
        records = self._store.read(key, request.time_range)
        validation = only_validate_historical_bars(key.instrument_id, key.bar_type, records)
        if not validation.valid:
            raise OnlyHistoricalCacheError("cached data failed validation")
        report = OnlyDataQualityReport(not any(item.severity.value == "error" for item in issues), tuple(issues))
        statistics = OnlyCacheStatistics(
            not missing,
            len(final.manifest.partition_hashes),
            partitions_written,
            len(records),
            rows_fetched,
            tuple(missing),
            final.manifest.content_fingerprint,
        )
        return OnlyHistoricalDataResult(records, final.manifest, report, statistics)

    load_bars = load

    def load_trades(
        self,
        request: OnlyHistoricalTradeDataRequest,
        provider: OnlyHistoricalTradeCacheProvider,
        policy: OnlyCachePolicy = OnlyCachePolicy.PREFER_CACHE,
    ) -> OnlyHistoricalTradeDataResult:
        key = provider.build_trade_cache_key(request)
        inspection = self._store.inspect(key, request.time_range)
        if inspection.issues and policy is OnlyCachePolicy.CACHE_ONLY:
            raise OnlyHistoricalCacheError(inspection.issues[0].message)
        missing = (request.time_range,) if policy is OnlyCachePolicy.FORCE_REFRESH else inspection.missing_ranges
        if missing and policy is OnlyCachePolicy.CACHE_ONLY:
            raise OnlyHistoricalCacheError("valid cache does not fully cover the requested range")
        rows_fetched = 0
        partitions_written = 0
        issues = list(inspection.issues)
        for time_range in missing:
            fetched = provider.fetch_trades(request, time_range)
            rows_fetched += len(fetched.records)
            issues.extend(fetched.quality_report.issues)
            validation = only_validate_historical_trades(key.instrument_id, fetched.records)
            issues.extend(validation.issues)
            in_range = all(time_range.contains(item.ts_event) for item in fetched.records)
            coverage_valid = _coverage_within(time_range, fetched.resolved_ranges)
            if not fetched.quality_report.valid or not validation.valid or not in_range or not coverage_valid:
                raise OnlyHistoricalCacheError("provider data failed strict historical Trade validation")
            partitions_written += self._store.write_trades(key, fetched).partitions_written
        final = self._store.inspect(key, request.time_range)
        if not final.valid or final.manifest is None:
            raise OnlyHistoricalCacheError("cache remains incomplete after Trade fetch")
        records = self._store.read_trades(key, request.time_range)
        validation = only_validate_historical_trades(key.instrument_id, records)
        if not validation.valid:
            raise OnlyHistoricalCacheError("cached Trade data failed validation")
        report = OnlyDataQualityReport(not any(item.severity.value == "error" for item in issues), tuple(issues))
        statistics = OnlyCacheStatistics(
            not missing,
            len(final.manifest.partition_hashes),
            partitions_written,
            len(records),
            rows_fetched,
            tuple(missing),
            final.manifest.content_fingerprint,
        )
        return OnlyHistoricalTradeDataResult(records, final.manifest, report, statistics)


def _coverage_within(requested: OnlyTimeRange, coverage: tuple[OnlyTimeRange, ...]) -> bool:
    return all(requested.start <= item.start and item.end <= requested.end for item in coverage)
