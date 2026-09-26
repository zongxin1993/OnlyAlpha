"""Bounded Binance Spot operational probe over the existing public transports."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from onlyalpha.plugin.integration import OnlyIntegrationProbeCheck
from onlyalpha.plugin.integration_probe import (
    OnlyIntegrationProbeCheckResult,
    OnlyIntegrationProbeCheckStatus,
    OnlyIntegrationProbeFailureKind,
    OnlyIntegrationProbeRequest,
    OnlyIntegrationProbeResult,
)
from onlyalpha_plugin_binance.errors import OnlyBinanceError, OnlyBinanceSchemaError
from onlyalpha_plugin_binance.spot.reference.client import OnlyBinanceSpotReferenceClient
from onlyalpha_plugin_binance.spot.reference.dto import OnlyBinanceSpotExchangeInfo

from .historical import OnlyBinanceSpotHistoricalClient
from .websocket import OnlyBinanceWebSocketTransport


class OnlyBinanceSpotProbe:
    def __init__(
        self,
        reference: OnlyBinanceSpotReferenceClient,
        historical: OnlyBinanceSpotHistoricalClient,
        websocket: OnlyBinanceWebSocketTransport,
        *,
        raw_stream_url: Callable[[str], str],
        context_observations: tuple[str, ...] = (),
        utc_now: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
        bind_deadline: Callable[[float], None] | None = None,
    ) -> None:
        self._reference = reference
        self._historical = historical
        self._websocket = websocket
        self._raw_stream_url = raw_stream_url
        self._context_observations = context_observations
        self._utc_now = utc_now
        self._monotonic = monotonic
        self._bind_deadline = bind_deadline or (lambda _deadline: None)

    def probe(self, request: OnlyIntegrationProbeRequest) -> OnlyIntegrationProbeResult:
        started_at = self._utc_now()
        symbol = request.probe_instrument
        server_time_ms: int | None = None
        checks: list[OnlyIntegrationProbeCheckResult] = []
        connectivity_failed = False

        for check in request.required_checks:
            if connectivity_failed:
                checks.append(_skipped(check))
                continue
            if symbol is None or not symbol.isalnum() or symbol != symbol.upper():
                checks.append(
                    _failed(
                        check,
                        OnlyIntegrationProbeFailureKind.FAILED,
                        "BINANCE_PROBE_SYMBOL_INVALID",
                        observations=self._context_for(check),
                    )
                )
                continue
            if self._monotonic() >= request.deadline_monotonic:
                checks.append(
                    _failed(
                        check,
                        OnlyIntegrationProbeFailureKind.DEGRADED,
                        "INTEGRATION_PROBE_TIMEOUT",
                        observations=self._context_for(check),
                    )
                )
                continue

            check_started = self._monotonic()
            check_deadline = min(request.deadline_monotonic, check_started + request.policy.per_check_timeout_seconds)
            self._bind_deadline(check_deadline)
            if check is OnlyIntegrationProbeCheck.CONNECTIVITY:
                result, server_time_ms = self._connectivity(check_started)
            elif check is OnlyIntegrationProbeCheck.REFERENCE_DATA:
                result = self._reference_data(symbol, check_started)
            elif check is OnlyIntegrationProbeCheck.HISTORICAL_DATA:
                result = self._historical_data(symbol, server_time_ms, check_started)
            elif check is OnlyIntegrationProbeCheck.REALTIME_DATA:
                result = self._realtime_data(symbol, check_started)
            else:
                result = _skipped(check)
            if self._monotonic() > check_deadline:
                result = _failed(
                    check,
                    (
                        OnlyIntegrationProbeFailureKind.OFFLINE
                        if check is OnlyIntegrationProbeCheck.CONNECTIVITY
                        else OnlyIntegrationProbeFailureKind.DEGRADED
                    ),
                    "INTEGRATION_PROBE_TIMEOUT",
                    latency_ms=result.latency_ms,
                    observations=self._context_for(check),
                )
                if check is OnlyIntegrationProbeCheck.CONNECTIVITY:
                    server_time_ms = None
            if check is OnlyIntegrationProbeCheck.CONNECTIVITY:
                connectivity_failed = result.status is OnlyIntegrationProbeCheckStatus.FAIL
            checks.append(result)

        return OnlyIntegrationProbeResult.create(
            request,
            probe_instrument=symbol,
            checks=tuple(checks),
            started_at=started_at,
            completed_at=self._utc_now(),
        )

    def _connectivity(self, started: float) -> tuple[OnlyIntegrationProbeCheckResult, int | None]:
        try:
            ping = json.loads(self._reference.ping())
            clock = json.loads(self._reference.server_time())
            if ping != {} or not isinstance(clock, dict):
                raise ValueError
            server_time = clock.get("serverTime")
            if not isinstance(server_time, int) or isinstance(server_time, bool) or server_time < 0:
                raise ValueError
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
            return self._schema_failure(
                OnlyIntegrationProbeCheck.CONNECTIVITY, started, "BINANCE_CONNECTIVITY_SCHEMA_INVALID"
            ), None
        except OnlyBinanceError:
            return self._unavailable(
                OnlyIntegrationProbeCheck.CONNECTIVITY,
                started,
                OnlyIntegrationProbeFailureKind.OFFLINE,
                "BINANCE_CONNECTIVITY_UNAVAILABLE",
            ), None
        return self._passed(
            OnlyIntegrationProbeCheck.CONNECTIVITY, started, (f"server_time_ms={server_time}",)
        ), server_time

    def _reference_data(self, symbol: str, started: float) -> OnlyIntegrationProbeCheckResult:
        try:
            payload = OnlyBinanceSpotExchangeInfo.parse(self._reference.exchange_info((symbol,))).raw
            symbols = payload["symbols"]
            if not any(isinstance(item, Mapping) and item.get("symbol") == symbol for item in symbols):
                return self._schema_failure(
                    OnlyIntegrationProbeCheck.REFERENCE_DATA, started, "BINANCE_REFERENCE_SYMBOL_MISSING"
                )
        except OnlyBinanceSchemaError:
            return self._schema_failure(
                OnlyIntegrationProbeCheck.REFERENCE_DATA, started, "BINANCE_REFERENCE_SCHEMA_INVALID"
            )
        except OnlyBinanceError:
            return self._unavailable(
                OnlyIntegrationProbeCheck.REFERENCE_DATA,
                started,
                OnlyIntegrationProbeFailureKind.DEGRADED,
                "BINANCE_REFERENCE_UNAVAILABLE",
            )
        return self._passed(OnlyIntegrationProbeCheck.REFERENCE_DATA, started, (f"symbol={symbol}",))

    def _historical_data(
        self, symbol: str, server_time_ms: int | None, started: float
    ) -> OnlyIntegrationProbeCheckResult:
        if server_time_ms is None:
            return self._schema_failure(
                OnlyIntegrationProbeCheck.HISTORICAL_DATA, started, "BINANCE_CONNECTIVITY_SCHEMA_INVALID"
            )
        end_ms = server_time_ms - server_time_ms % 60_000
        start_ms = end_ms - 120_000
        try:
            rows = self._historical.klines(symbol, start_ms, end_ms, 3)
            _validate_klines(rows, start_ms=start_ms, end_ms=end_ms)
        except (IndexError, InvalidOperation, KeyError, TypeError, ValueError, OnlyBinanceSchemaError):
            return self._schema_failure(
                OnlyIntegrationProbeCheck.HISTORICAL_DATA, started, "BINANCE_HISTORICAL_SCHEMA_INVALID"
            )
        except OnlyBinanceError:
            return self._unavailable(
                OnlyIntegrationProbeCheck.HISTORICAL_DATA,
                started,
                OnlyIntegrationProbeFailureKind.DEGRADED,
                "BINANCE_HISTORICAL_UNAVAILABLE",
            )
        return self._passed(OnlyIntegrationProbeCheck.HISTORICAL_DATA, started, (f"bar_count={len(rows)}",))

    def _realtime_data(self, symbol: str, started: float) -> OnlyIntegrationProbeCheckResult:
        try:
            self._websocket.connect(self._raw_stream_url(f"{symbol.lower()}@depth5"))
            payload = json.loads(self._websocket.receive())
            _validate_partial_depth(payload)
        except (json.JSONDecodeError, UnicodeDecodeError, InvalidOperation, KeyError, TypeError, ValueError):
            return self._schema_failure(
                OnlyIntegrationProbeCheck.REALTIME_DATA, started, "BINANCE_REALTIME_SCHEMA_INVALID"
            )
        except (OnlyBinanceError, TimeoutError):
            return self._unavailable(
                OnlyIntegrationProbeCheck.REALTIME_DATA,
                started,
                OnlyIntegrationProbeFailureKind.DEGRADED,
                "BINANCE_REALTIME_UNAVAILABLE",
            )
        finally:
            self._websocket.close()
        return self._passed(
            OnlyIntegrationProbeCheck.REALTIME_DATA,
            started,
            ("event=partial_depth", f"symbol={symbol}"),
        )

    def _passed(
        self, check: OnlyIntegrationProbeCheck, started: float, observations: tuple[str, ...] = ()
    ) -> OnlyIntegrationProbeCheckResult:
        return OnlyIntegrationProbeCheckResult(
            check,
            OnlyIntegrationProbeCheckStatus.PASS,
            self._latency(started),
            observations=self._context_for(check) + observations,
        )

    def _schema_failure(
        self, check: OnlyIntegrationProbeCheck, started: float, error_code: str
    ) -> OnlyIntegrationProbeCheckResult:
        return _failed(
            check,
            OnlyIntegrationProbeFailureKind.FAILED,
            error_code,
            latency_ms=self._latency(started),
            observations=self._context_for(check),
        )

    def _unavailable(
        self,
        check: OnlyIntegrationProbeCheck,
        started: float,
        kind: OnlyIntegrationProbeFailureKind,
        error_code: str,
    ) -> OnlyIntegrationProbeCheckResult:
        return _failed(
            check,
            kind,
            error_code,
            latency_ms=self._latency(started),
            observations=self._context_for(check),
        )

    def _context_for(self, check: OnlyIntegrationProbeCheck) -> tuple[str, ...]:
        return self._context_observations if check is OnlyIntegrationProbeCheck.CONNECTIVITY else ()

    def _latency(self, started: float) -> int:
        return max(0, int((self._monotonic() - started) * 1000))


def _validate_klines(rows: Sequence[Sequence[object]], *, start_ms: int, end_ms: int) -> None:
    if not 1 <= len(rows) <= 3:
        raise ValueError
    open_times: list[int] = []
    for row in rows:
        if len(row) < 11:
            raise ValueError
        open_time = _integer(row[0])
        close_time = _integer(row[6])
        open_price, high, low, close, volume = (Decimal(str(row[index])) for index in (1, 2, 3, 4, 5))
        if (
            not all(value.is_finite() for value in (open_price, high, low, close, volume))
            or volume < 0
            or low > min(open_price, close)
            or high < max(open_price, close)
            or high < low
            or not start_ms <= open_time < end_ms
            or close_time < open_time
            or close_time >= end_ms
            or open_time + 60_000 > end_ms
        ):
            raise ValueError
        open_times.append(open_time)
    if open_times != sorted(open_times) or len(open_times) != len(set(open_times)):
        raise ValueError


def _validate_partial_depth(payload: object) -> None:
    if not isinstance(payload, dict):
        raise ValueError
    if _integer(payload["lastUpdateId"]) < 0:
        raise ValueError
    for side in (payload.get("bids"), payload.get("asks")):
        if not isinstance(side, list) or not side or len(side) > 5:
            raise ValueError
        for level in side:
            if not isinstance(level, list | tuple) or len(level) < 2:
                raise ValueError
            price, quantity = (Decimal(str(value)) for value in level[:2])
            if not price.is_finite() or not quantity.is_finite() or price <= 0 or quantity < 0:
                raise ValueError


def _integer(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError
    return int(str(value))


def _failed(
    check: OnlyIntegrationProbeCheck,
    kind: OnlyIntegrationProbeFailureKind,
    error_code: str,
    *,
    latency_ms: int = 0,
    observations: tuple[str, ...] = (),
) -> OnlyIntegrationProbeCheckResult:
    return OnlyIntegrationProbeCheckResult(
        check,
        OnlyIntegrationProbeCheckStatus.FAIL,
        latency_ms,
        failure_kind=kind,
        error_code=error_code,
        detail="Provider probe failed",
        observations=observations,
    )


def _skipped(check: OnlyIntegrationProbeCheck) -> OnlyIntegrationProbeCheckResult:
    return OnlyIntegrationProbeCheckResult(check, OnlyIntegrationProbeCheckStatus.SKIPPED, 0)


__all__ = ["OnlyBinanceSpotProbe"]
