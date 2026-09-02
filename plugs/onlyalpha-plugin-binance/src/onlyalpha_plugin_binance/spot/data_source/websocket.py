"""Bounded synchronous WebSocket transport; payload semantics live elsewhere."""

from __future__ import annotations

from typing import Protocol

from onlyalpha_plugin_binance.errors import OnlyBinanceError


class OnlyBinanceWebSocketConnection(Protocol):
    def recv(self) -> str | bytes: ...
    def close(self) -> None: ...


class OnlyBinanceWebSocketTransport:
    def __init__(self, *, timeout_seconds: float, max_message_bytes: int) -> None:
        self._timeout = timeout_seconds
        self._max_message_bytes = max_message_bytes
        self._connection: OnlyBinanceWebSocketConnection | None = None

    def connect(self, url: str) -> None:
        try:
            import websocket

            self._connection = websocket.create_connection(url, timeout=self._timeout, enable_multithread=True)
        except Exception as exc:
            raise OnlyBinanceError(f"BINANCE_WEBSOCKET_CONNECT_FAILED: {type(exc).__name__}") from exc

    def receive(self) -> bytes:
        if self._connection is None:
            raise OnlyBinanceError("BINANCE_WEBSOCKET_NOT_CONNECTED")
        try:
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
