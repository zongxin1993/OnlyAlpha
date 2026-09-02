from __future__ import annotations

import pytest
from onlyalpha_plugin_binance.common.http import OnlyBinancePublicHttpClient
from onlyalpha_plugin_binance.errors import OnlyBinanceError


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
