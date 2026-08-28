"""Backtest Runtime implementation package."""

# ruff: noqa: F401

from importlib import import_module as _import_module

from onlyalpha.runtime.backtest.recovery_boundary import (
    OnlyBacktestRecoveryBoundary,
    OnlyBacktestRecoveryError,
    OnlyBacktestRecoveryPhase,
    OnlyBacktestRecoverySession,
)
from onlyalpha.runtime.backtest.result import (
    OnlyBacktestDataSummary,
    OnlyBacktestExecutionSummary,
    OnlyBacktestResult,
    OnlyBacktestRunSummary,
    OnlyBacktestStatus,
    OnlyClusterPerformanceSummary,
    OnlyClusterResult,
)

__all__ = [name for name in globals() if name.startswith("Only")]
__all__.append("OnlyBacktestRuntime")


def __getattr__(name: str) -> object:
    if name != "OnlyBacktestRuntime":
        raise AttributeError(name)
    value: object = getattr(_import_module("onlyalpha.runtime.backtest.runtime"), name)
    globals()[name] = value
    return value
