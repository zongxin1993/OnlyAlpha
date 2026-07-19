"""Runtime-facing collection of immutable result facts."""

from onlyalpha.collector.backtest import (
    OnlyBacktestResultCollector,
    OnlyCollectedBacktestFacts,
    OnlyResultCollectorError,
    OnlyResultCollectorLifecycle,
)

__all__ = [
    "OnlyBacktestResultCollector",
    "OnlyCollectedBacktestFacts",
    "OnlyResultCollectorError",
    "OnlyResultCollectorLifecycle",
]
