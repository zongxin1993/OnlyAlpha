"""Structured diagnostics which preserve the first underlying failure."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from onlyalpha.domain.time import only_require_utc


class OnlyResultDiagnosticSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    FATAL = "FATAL"


class OnlyResultFailureStage(StrEnum):
    CONFIG = "CONFIG"
    PLUGIN_DISCOVERY = "PLUGIN_DISCOVERY"
    DATA_LOAD = "DATA_LOAD"
    CACHE = "CACHE"
    REPLAY = "REPLAY"
    MARKET_DATA_PIPELINE = "MARKET_DATA_PIPELINE"
    INDICATOR = "INDICATOR"
    FACTOR = "FACTOR"
    STRATEGY = "STRATEGY"
    RISK = "RISK"
    ORDER = "ORDER"
    BROKER = "BROKER"
    MATCHING = "MATCHING"
    EXECUTION = "EXECUTION"
    POSITION = "POSITION"
    LEDGER = "LEDGER"
    ACCOUNT = "ACCOUNT"
    RESULT_COLLECTION = "RESULT_COLLECTION"
    ANALYTICS = "ANALYTICS"
    ARTIFACT_WRITE = "ARTIFACT_WRITE"
    REPORT = "REPORT"


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyBacktestFailure:
    failure_id: str
    sequence: int
    severity: OnlyResultDiagnosticSeverity
    stage: OnlyResultFailureStage
    exception_type: str
    message: str
    ts_event: datetime | None = None
    trading_day: date | None = None
    runtime_id: str | None = None
    cluster_id: str | None = None
    strategy_id: str | None = None
    account_id: str | None = None
    source_id: str | None = None
    instrument_id: str | None = None
    bar_type: str | None = None
    order_request_id: str | None = None
    order_id: str | None = None
    execution_id: str | None = None
    traceback: str | None = None

    def __post_init__(self) -> None:
        if self.sequence < 0 or not self.failure_id or not self.exception_type or not self.message:
            raise ValueError("failure identity, type, message, and non-negative sequence are required")
        if self.ts_event is not None:
            only_require_utc(self.ts_event, "failure ts_event")


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyBacktestWarning:
    sequence: int
    code: str
    message: str
    stage: OnlyResultFailureStage


@dataclass(frozen=True, slots=True)
class OnlyBacktestDiagnostics:
    failures: tuple[OnlyBacktestFailure, ...] = ()
    warnings: tuple[OnlyBacktestWarning, ...] = ()
    truncated: bool = False
    total_failure_count: int = 0

    def __post_init__(self) -> None:
        failures = tuple(self.failures)
        warnings = tuple(self.warnings)
        if tuple(sorted(failures, key=lambda item: item.sequence)) != failures:
            raise ValueError("failures must retain stable sequence order")
        if tuple(sorted(warnings, key=lambda item: item.sequence)) != warnings:
            raise ValueError("warnings must retain stable sequence order")
        if self.total_failure_count < len(failures):
            raise ValueError("total_failure_count cannot be smaller than retained failures")
        object.__setattr__(self, "failures", failures)
        object.__setattr__(self, "warnings", warnings)

    @property
    def first_failure(self) -> OnlyBacktestFailure | None:
        return self.failures[0] if self.failures else None
