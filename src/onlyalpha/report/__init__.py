"""User-facing projections of immutable backtest outputs."""

from onlyalpha.report.renderers import (
    OnlyConsoleBacktestReport,
    OnlyJsonBacktestReport,
    OnlyMarkdownBacktestReport,
)

__all__ = [
    "OnlyConsoleBacktestReport",
    "OnlyJsonBacktestReport",
    "OnlyMarkdownBacktestReport",
]
