"""Configuration-driven product backtest API."""

# ruff: noqa: F401

from onlyalpha.backtest.config import OnlyBacktestConfig
from onlyalpha.backtest.result import (
    OnlyBacktestDataSummary,
    OnlyBacktestExecutionSummary,
    OnlyBacktestPerformanceSummary,
    OnlyBacktestResult,
    OnlyBacktestRunSummary,
    OnlyBacktestStatus,
)

__all__ = [name for name in globals() if name.startswith("Only")]
