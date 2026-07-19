"""Strict standard-Bar validation."""

from onlyalpha.cache.historical.models import (
    OnlyDataQualityIssue,
    OnlyDataQualityReport,
    OnlyDataQualitySeverity,
    OnlyHistoricalCacheKey,
)
from onlyalpha.domain.market import OnlyBar


def only_validate_historical_bars(key: OnlyHistoricalCacheKey, records: tuple[OnlyBar, ...]) -> OnlyDataQualityReport:
    issues: list[OnlyDataQualityIssue] = []
    previous: tuple[int, str] | None = None
    for bar in records:
        marker = (int(bar.ts_event.timestamp() * 1_000_000), bar.to_json())
        reason = None
        if bar.instrument_id != key.instrument_id or bar.bar_type != key.bar_type:
            reason = "Bar identity does not match cache key"
        elif min(bar.open.value, bar.high.value, bar.low.value, bar.close.value) <= 0:
            reason = "OHLC values must be positive"
        elif bar.volume.value < 0 or (bar.turnover is not None and bar.turnover.amount < 0):
            reason = "volume and turnover cannot be negative"
        elif previous is not None and marker <= previous:
            reason = "Bars must be unique and strictly ordered by event time"
        if reason:
            issues.append(
                OnlyDataQualityIssue(
                    "INVALID_BAR", OnlyDataQualitySeverity.ERROR, reason, bar.instrument_id, bar.ts_event
                )
            )
        previous = marker
    return OnlyDataQualityReport(not issues, tuple(issues))
