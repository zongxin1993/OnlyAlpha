from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from onlyalpha_plugin_binance.common.http import OnlyBinancePublicHttpClient
from onlyalpha_plugin_binance.errors import OnlyBinanceError
from onlyalpha_plugin_binance.spot.data_source.websocket import OnlyBinanceWebSocketTransport


class _Response:
    status = 200

    def __init__(self, payload: bytes, headers: dict[str, str]) -> None:
        self.payload = payload
        self.headers = headers
        self.read_limit: int | None = None

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        self.read_limit = limit
        return self.payload[:limit]


def test_json_media_type_with_charset_and_bounded_read(monkeypatch) -> None:
    response = _Response(b'{"ok":true}', {"Content-Type": "application/json; charset=utf-8"})
    monkeypatch.setattr("onlyalpha_plugin_binance.common.http.urlopen", lambda *args, **kwargs: response)
    client = OnlyBinancePublicHttpClient("https://api.binance.com", max_response_bytes=32)
    assert client.get_json("/api/v3/ping") == b'{"ok":true}'
    assert response.read_limit == 33


def test_declared_or_streamed_oversize_response_fails_closed(monkeypatch) -> None:
    declared = _Response(
        b"{}",
        {"Content-Type": "application/json", "Content-Length": "33"},
    )
    monkeypatch.setattr("onlyalpha_plugin_binance.common.http.urlopen", lambda *args, **kwargs: declared)
    client = OnlyBinancePublicHttpClient("https://api.binance.com", max_response_bytes=32)
    with pytest.raises(OnlyBinanceError, match="BINANCE_PUBLIC_RESPONSE_TOO_LARGE"):
        client.get_json("/api/v3/exchangeInfo")
    assert declared.read_limit is None

    streamed = _Response(b"{" + b" " * 40, {"Content-Type": "application/json"})
    monkeypatch.setattr("onlyalpha_plugin_binance.common.http.urlopen", lambda *args, **kwargs: streamed)
    with pytest.raises(OnlyBinanceError, match="BINANCE_PUBLIC_RESPONSE_TOO_LARGE"):
        client.get_json("/api/v3/exchangeInfo")
    assert streamed.read_limit == 33


def test_non_json_media_type_fails_before_body_interpretation(monkeypatch) -> None:
    response = _Response(b"{}", {"Content-Type": "text/plain"})
    monkeypatch.setattr("onlyalpha_plugin_binance.common.http.urlopen", lambda *args, **kwargs: response)
    client = OnlyBinancePublicHttpClient("https://api.binance.com")
    with pytest.raises(OnlyBinanceError, match="BINANCE_PUBLIC_RESPONSE_MEDIA_TYPE_INVALID"):
        client.get_json("/api/v3/ping")


def test_raw_response_is_observed_before_json_interpretation(monkeypatch) -> None:
    response = _Response(b"{invalid", {"Content-Type": "application/json"})
    monkeypatch.setattr("onlyalpha_plugin_binance.common.http.urlopen", lambda *args, **kwargs: response)
    observed = []
    client = OnlyBinancePublicHttpClient(
        "https://api.binance.com",
        response_observer=lambda path, parameters, payload: observed.append((path, parameters, payload)),
    )

    with pytest.raises(OnlyBinanceError, match="BINANCE_PUBLIC_RESPONSE_NOT_JSON"):
        client.get_json("/api/v3/klines", {"symbol": "BTCUSDT"})

    assert observed == [("/api/v3/klines", {"symbol": "BTCUSDT"}, b"{invalid")]


def test_each_http_request_uses_only_remaining_probe_deadline(monkeypatch) -> None:
    response = _Response(b"{}", {"Content-Type": "application/json"})
    observed_timeouts: list[float] = []
    monkeypatch.setattr(
        "onlyalpha_plugin_binance.common.http.urlopen",
        lambda _request, *, timeout: observed_timeouts.append(timeout) or response,
    )
    readings = iter((1.0, 4.5))
    client = OnlyBinancePublicHttpClient(
        "https://api.binance.com",
        timeout_seconds=5.0,
        deadline_monotonic=6.0,
        monotonic=lambda: next(readings),
    )

    client.get_json("/api/v3/ping")
    client.get_json("/api/v3/time")

    assert observed_timeouts == [5.0, 1.5]


def test_websocket_connect_and_receive_use_only_remaining_probe_deadline(monkeypatch) -> None:
    class Connection:
        def __init__(self) -> None:
            self.timeouts: list[float] = []

        def settimeout(self, timeout: float) -> None:
            self.timeouts.append(timeout)

        def recv(self) -> bytes:
            return b"{}"

        def close(self) -> None:
            return None

    connection = Connection()
    connect_timeouts: list[float] = []
    monkeypatch.setitem(
        sys.modules,
        "websocket",
        SimpleNamespace(
            create_connection=lambda _url, *, timeout, enable_multithread: (
                connect_timeouts.append(timeout) or connection
            )
        ),
    )
    readings = iter((1.0, 4.5))
    transport = OnlyBinanceWebSocketTransport(
        timeout_seconds=5.0,
        max_message_bytes=32,
        deadline_monotonic=6.0,
        monotonic=lambda: next(readings),
    )

    transport.connect("wss://example.test/ws")
    assert transport.receive() == b"{}"

    assert connect_timeouts == [5.0]
    assert connection.timeouts == [1.5]


def test_gzip_is_negotiated_and_observer_receives_decoded_json(monkeypatch) -> None:
    import gzip

    decoded = b'{"ok":true}'
    compressed = gzip.compress(decoded)
    response = _Response(
        compressed,
        {"Content-Type": "application/json", "Content-Encoding": "gzip", "Content-Length": str(len(compressed))},
    )

    def open_request(request, **kwargs):
        assert request.get_header("Accept-encoding") == "gzip"
        return response

    monkeypatch.setattr("onlyalpha_plugin_binance.common.http.urlopen", open_request)
    observed = []
    client = OnlyBinancePublicHttpClient(
        "https://api.binance.com", max_response_bytes=64, response_observer=lambda *args: observed.append(args)
    )
    assert client.get_json("/api/v3/ping") == decoded
    assert observed[0][2] == decoded


def test_gzip_expansion_is_bounded_independently_of_wire_size(monkeypatch) -> None:
    import gzip

    compressed = gzip.compress(b'{"padding":"' + b"a" * 1024 + b'"}')
    assert len(compressed) < 64
    response = _Response(compressed, {"Content-Type": "application/json", "Content-Encoding": "gzip"})
    monkeypatch.setattr("onlyalpha_plugin_binance.common.http.urlopen", lambda *args, **kwargs: response)
    client = OnlyBinancePublicHttpClient("https://api.binance.com", max_response_bytes=64)
    with pytest.raises(OnlyBinanceError, match="BINANCE_PUBLIC_RESPONSE_TOO_LARGE"):
        client.get_json("/api/v3/exchangeInfo")


@pytest.mark.parametrize(
    "encoding,payload,code",
    [
        ("br", b"{}", "ENCODING_UNSUPPORTED"),
        ("gzip", b"not gzip", "ENCODING_INVALID"),
    ],
)
def test_unsupported_or_malformed_encoding_fails_closed(monkeypatch, encoding, payload, code) -> None:
    response = _Response(payload, {"Content-Type": "application/json", "Content-Encoding": encoding})
    monkeypatch.setattr("onlyalpha_plugin_binance.common.http.urlopen", lambda *args, **kwargs: response)
    with pytest.raises(OnlyBinanceError, match="BINANCE_PUBLIC_RESPONSE_" + code):
        OnlyBinancePublicHttpClient("https://api.binance.com").get_json("/api/v3/ping")


def test_gzip_invalid_json_is_still_observed_then_rejected(monkeypatch) -> None:
    import gzip

    response = _Response(gzip.compress(b"{invalid"), {"Content-Type": "application/json", "Content-Encoding": "gzip"})
    monkeypatch.setattr("onlyalpha_plugin_binance.common.http.urlopen", lambda *args, **kwargs: response)
    observed = []
    client = OnlyBinancePublicHttpClient(
        "https://api.binance.com", response_observer=lambda *args: observed.append(args)
    )
    with pytest.raises(OnlyBinanceError, match="BINANCE_PUBLIC_RESPONSE_NOT_JSON"):
        client.get_json("/api/v3/ping")
    assert observed[0][2] == b"{invalid"


def test_gzip_wire_limit_is_independent_of_decoded_size(monkeypatch) -> None:
    import gzip

    decoded = b'{"random":"ab9D1wxy4"}'
    compressed = gzip.compress(decoded)
    assert len(decoded) < 32 < len(compressed)
    response = _Response(
        compressed,
        {"Content-Type": "application/json", "Content-Encoding": "gzip", "Content-Length": str(len(compressed))},
    )
    monkeypatch.setattr("onlyalpha_plugin_binance.common.http.urlopen", lambda *args, **kwargs: response)
    with pytest.raises(OnlyBinanceError, match="BINANCE_PUBLIC_RESPONSE_TOO_LARGE"):
        OnlyBinancePublicHttpClient("https://api.binance.com", max_response_bytes=32).get_json("/api/v3/ping")
    assert response.read_limit is None


@pytest.mark.parametrize("corruption", ["truncated", "checksum", "trailing"])
def test_corrupt_gzip_fails_without_observing_a_partial_json(monkeypatch, corruption) -> None:
    import gzip

    payload = gzip.compress(b'{"ok":true}')
    if corruption == "truncated":
        payload = payload[:-1]
    elif corruption == "checksum":
        payload = payload[:-8] + bytes([payload[-8] ^ 1]) + payload[-7:]
    else:
        payload += b"garbage"
    response = _Response(payload, {"Content-Type": "application/json", "Content-Encoding": "gzip"})
    monkeypatch.setattr("onlyalpha_plugin_binance.common.http.urlopen", lambda *args, **kwargs: response)
    observed = []
    client = OnlyBinancePublicHttpClient(
        "https://api.binance.com", response_observer=lambda *args: observed.append(args)
    )
    with pytest.raises(OnlyBinanceError, match="BINANCE_PUBLIC_RESPONSE_ENCODING_INVALID"):
        client.get_json("/api/v3/ping")
    assert observed == []
