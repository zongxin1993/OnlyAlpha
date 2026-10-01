"""Request-local, non-authoritative phase accounting for market-data operations."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from time import perf_counter_ns
from typing import ParamSpec, TypeVar

from onlyalpha.domain.market import OnlyBarSemantic

_LOGGER = logging.getLogger(__name__)
_P = ParamSpec("_P")
_R = TypeVar("_R")


@dataclass
class _Phase:
    calls: int = 0
    inclusive_ns: int = 0
    exclusive_ns: int = 0


@dataclass
class OnlyMarketDataPerformance:
    operation: str
    acquisition_id: str | None = None
    scope_fingerprint: str | None = None
    source_id: str | None = None
    instrument_id: str | None = None
    resolution_mode: str | None = None
    target_semantic: OnlyBarSemantic | None = None
    base_semantic: OnlyBarSemantic | None = None
    phases: dict[str, _Phase] = field(default_factory=dict)
    _stack: list[int] = field(default_factory=list)
    _accounted_ns: int = 0

    def bind(
        self,
        *,
        acquisition_id: str | None = None,
        scope_fingerprint: str | None = None,
        source_id: str | None = None,
        instrument_id: str | None = None,
        resolution_mode: str | None = None,
        target_semantic: OnlyBarSemantic | None = None,
        base_semantic: OnlyBarSemantic | None = None,
    ) -> None:
        """Only explicit semantic identities, never provider configuration or credentials."""
        self.acquisition_id = acquisition_id
        self.scope_fingerprint = scope_fingerprint
        self.source_id = source_id
        self.instrument_id = instrument_id
        self.resolution_mode = resolution_mode
        self.target_semantic = target_semantic
        self.base_semantic = base_semantic

    def emit(self, total_ns: int, error_type: str | None) -> None:
        residual_ns = total_ns - self._accounted_ns
        payload = {
            "operation": self.operation,
            "outcome": "RETURNED" if error_type is None else "ERROR",
            "error_type": error_type,
            "correlation": {
                "acquisition_id": self.acquisition_id,
                "scope_fingerprint": self.scope_fingerprint,
                "source_id": self.source_id,
                "instrument_id": self.instrument_id,
                "resolution_mode": self.resolution_mode,
                "target_semantic": None if self.target_semantic is None else self.target_semantic.to_dict(),
                "base_semantic": None if self.base_semantic is None else self.base_semantic.to_dict(),
            },
            "total_ms": total_ns / 1_000_000,
            "acquisition_total_ms" if self.operation == "COMMAND" else "final_query_ms": total_ns / 1_000_000,
            "accounted_ms": self._accounted_ns / 1_000_000,
            "residual_ms": residual_ns / 1_000_000,
            "residual_ratio": residual_ns / total_ns if total_ns else 0,
            "phases": {
                name: {
                    "calls": phase.calls,
                    "inclusive_ms": phase.inclusive_ns / 1_000_000,
                    "exclusive_ms": phase.exclusive_ns / 1_000_000,
                }
                for name, phase in sorted(self.phases.items())
            },
        }
        try:
            _LOGGER.info("market_data_performance %s", json.dumps(payload, sort_keys=True))
        except Exception:
            # Diagnostic transport cannot change an already decided command/query outcome.
            # Missing logs remain unavailable evidence; they never certify a performance PASS.
            pass


_CURRENT: ContextVar[OnlyMarketDataPerformance | None] = ContextVar("market_data_performance", default=None)


@contextmanager
def only_market_data_performance(operation: str) -> Iterator[OnlyMarketDataPerformance]:
    current = _CURRENT.get()
    if current is not None and current.operation == operation:
        # The HTTP adapter and its synchronous Application call are one request.
        yield current
        return
    measurement = OnlyMarketDataPerformance(operation)
    token = _CURRENT.set(measurement)
    started = perf_counter_ns()
    error_type: str | None = None
    try:
        yield measurement
    except BaseException as exc:
        error_type = type(exc).__name__
        raise
    finally:
        total_ns = perf_counter_ns() - started
        _CURRENT.reset(token)
        measurement.emit(total_ns, error_type)


@contextmanager
def only_market_data_phase(name: str) -> Iterator[None]:
    measurement = _CURRENT.get()
    if measurement is None:
        yield
        return
    started = perf_counter_ns()
    measurement._stack.append(0)
    try:
        yield
    finally:
        elapsed_ns = perf_counter_ns() - started
        children_ns = measurement._stack.pop()
        phase = measurement.phases.setdefault(name, _Phase())
        phase.calls += 1
        phase.inclusive_ns += elapsed_ns
        phase.exclusive_ns += elapsed_ns - children_ns
        if measurement._stack:
            measurement._stack[-1] += elapsed_ns
        else:
            measurement._accounted_ns += elapsed_ns


def only_market_data_timed(name: str) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    def decorate(function: Callable[_P, _R]) -> Callable[_P, _R]:
        @wraps(function)
        def measured(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            with only_market_data_phase(name):
                return function(*args, **kwargs)

        return measured

    return decorate


def only_current_market_data_performance() -> OnlyMarketDataPerformance | None:
    return _CURRENT.get()
