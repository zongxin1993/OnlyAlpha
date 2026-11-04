"""Bounded synchronous WebSocket transport; payload semantics live elsewhere."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import Protocol

from onlyalpha_plugin_binance.errors import OnlyBinanceError


class OnlyBinanceWebSocketConnection(Protocol):
    def recv(self) -> str | bytes: ...
    def settimeout(self, timeout: float) -> None: ...
    def close(self) -> None: ...


class OnlyBinanceWebSocketTransport:
    def __init__(
        self,
        *,
        timeout_seconds: float,
        max_message_bytes: int,
        deadline_monotonic: float | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if deadline_monotonic is not None and (not math.isfinite(deadline_monotonic) or deadline_monotonic <= 0):
            raise ValueError("BINANCE_WEBSOCKET_CONFIGURATION_INVALID")
        self._timeout = timeout_seconds
        self._max_message_bytes = max_message_bytes
        self._deadline_monotonic = deadline_monotonic
        self._monotonic = monotonic
        self._connection: OnlyBinanceWebSocketConnection | None = None

    def connect(self, url: str) -> None:
        try:
            import websocket

            self._connection = websocket.create_connection(
                url, timeout=self._remaining_timeout(), enable_multithread=True
            )
        except Exception as exc:
            raise OnlyBinanceError(f"BINANCE_WEBSOCKET_CONNECT_FAILED: {type(exc).__name__}") from exc

    def receive(self) -> bytes:
        if self._connection is None:
            raise OnlyBinanceError("BINANCE_WEBSOCKET_NOT_CONNECTED")
        try:
            self._connection.settimeout(self._remaining_timeout())
            raw = self._connection.recv()
        except Exception as exc:
            raise OnlyBinanceError(f"BINANCE_WEBSOCKET_RECEIVE_FAILED: {type(exc).__name__}") from exc
        payload = raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)
        if len(payload) > self._max_message_bytes:
            raise OnlyBinanceError("BINANCE_WEBSOCKET_MESSAGE_TOO_LARGE")
        return payload

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _remaining_timeout(self) -> float:
        if self._deadline_monotonic is None:
            return self._timeout
        remaining = self._deadline_monotonic - self._monotonic()
        if remaining <= 0:
            raise OnlyBinanceError("BINANCE_WEBSOCKET_DEADLINE_EXCEEDED")
        return min(self._timeout, remaining)

    def bind_deadline(self, deadline_monotonic: float) -> None:
        if not math.isfinite(deadline_monotonic) or deadline_monotonic <= 0:
            raise ValueError("BINANCE_WEBSOCKET_CONFIGURATION_INVALID")
        self._deadline_monotonic = deadline_monotonic
