"""Controlled Binance wire inputs for isolated Browser acceptance.

Importable Provider factory identity stays independent of the HTTP fixture main.
No Product API, Authority composition or database provisioning is loaded here.
Synthetic payloads and hash-bound recorded payloads do not certify live transport.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request

from onlyalpha_plugin_binance.spot.data_source.factory import OnlyBinanceSpotDataSourceFactory

from onlyalpha.plugin.data_source import (
    OnlyDataSourceDiscoveryCapabilitiesV1,
    OnlyDataSourceInstrumentCatalogRequestV1,
    OnlyDataSourceInstrumentV1,
    OnlyDataSourceQuoteRequestV1,
    OnlyDataSourceQuoteV1,
)

NOW = datetime(2026, 1, 25, tzinfo=UTC)


def _kline(start_ms: int, step_ms: int) -> list[object]:
    # Deterministic external wire data, never a canonical market-fact fixture.
    return [start_ms, "100", "110", "90", "105", "2", start_ms + step_ms - 1, "205", 3, "1", "100"]


class _PublicWireResponse:
    status = 200

    def __init__(self, document: object) -> None:
        self._body = json.dumps(document, separators=(",", ":")).encode()
        self.headers = {"Content-Type": "application/json", "Content-Length": str(len(self._body))}

    def read(self, maximum: int) -> bytes:
        return self._body[:maximum]

    def __enter__(self) -> _PublicWireResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _wire(request: Request, *, timeout: float) -> _PublicWireResponse:
    from urllib.parse import parse_qs, urlsplit

    del timeout
    parsed = urlsplit(request.full_url)
    query = parse_qs(parsed.query)
    if parsed.path == "/api/v3/exchangeInfo":
        return _PublicWireResponse(
            {
                "timezone": "UTC",
                "exchangeFilters": [],
                "symbols": [
                    {
                        "symbol": symbol,
                        "status": "TRADING",
                        "baseAsset": symbol.removesuffix("USDT"),
                        "quoteAsset": "USDT",
                        "filters": [
                            {"filterType": "PRICE_FILTER", "tickSize": "0.01000000"},
                            {"filterType": "LOT_SIZE", "stepSize": "0.00001000", "minQty": "0.00001000"},
                        ],
                    }
                    for symbol in json.loads(query.get("symbols", ['["BTCUSDT","ETHUSDT","SOLUSDT"]'])[0])
                ],
            }
        )
    if parsed.path == "/api/v3/klines":
        assert query["symbol"] == ["BTCUSDT"]
        stride = {"1m": 60_000, "15m": 900_000}[query["interval"][0]]
        return _PublicWireResponse(
            [
                _kline(value, stride)
                for value in range(int(query["startTime"][0]), int(query["endTime"][0]) + 1, stride)
            ][: int(query["limit"][0])]
        )
    if parsed.path == "/api/v3/time":
        return _PublicWireResponse({"serverTime": int(NOW.timestamp() * 1000)})
    raise AssertionError("Unexpected external request: " + parsed.path)


class _WatchlistWireFactory(OnlyBinanceSpotDataSourceFactory):
    """Only external transport is controlled, including inside spawned workers.

    The actual Binance catalog/quote parsers, factory descriptor/configuration and
    Product provider-process lifecycle remain unchanged.
    """

    def __init__(self, *, quotes_enabled: bool = False, recording_path: str | None = None) -> None:
        self._quotes_enabled = quotes_enabled
        self._recording_path = recording_path

    def discovery_capabilities(self, plugin_config: object) -> OnlyDataSourceDiscoveryCapabilitiesV1:
        return replace(super().discovery_capabilities(plugin_config), quotes=self._quotes_enabled)

    def list_instruments(
        self, request: OnlyDataSourceInstrumentCatalogRequestV1
    ) -> tuple[OnlyDataSourceInstrumentV1, ...]:
        wire = _recorded_wire(Path(self._recording_path))[0] if self._recording_path else _watchlist_wire
        with patch("onlyalpha_plugin_binance.common.http.urlopen", side_effect=wire):
            return super().list_instruments(request)

    def quotes(self, request: OnlyDataSourceQuoteRequestV1) -> tuple[OnlyDataSourceQuoteV1, ...]:
        with patch("onlyalpha_plugin_binance.common.http.urlopen", side_effect=_watchlist_wire):
            return super().quotes(request)


def _watchlist_wire(request: Request, *, timeout: float) -> _PublicWireResponse:
    from urllib.parse import parse_qs, urlsplit

    parsed = urlsplit(request.full_url)
    if parsed.path == "/api/v3/ticker/24hr":
        symbols = json.loads(parse_qs(parsed.query)["symbols"][0])
        return _PublicWireResponse(
            [
                {
                    "symbol": symbol,
                    "lastPrice": "105.00",
                    "priceChangePercent": "2.50",
                    "closeTime": int(NOW.timestamp() * 1000),
                }
                for symbol in symbols
            ]
        )
    return _wire(request, timeout=timeout)


def _recorded_wire(path: Path) -> tuple[Callable[..., _PublicWireResponse], str, str]:
    """Acceptance-only recorded venue input; missing/changed capture fails closed."""
    from urllib.parse import parse_qs, urlsplit

    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == path.with_suffix(".sha256").read_text().strip()
    recording = json.loads(raw)
    assert recording["source_kind"] == "CAPTURED_REAL_BINANCE_PUBLIC_HISTORY"
    assert recording["before_ns"] == str(int(NOW.timestamp()) * 1_000_000_000)
    captured_bars: dict[str, list[object]] = {}
    captured_info = None
    for item in recording["requests"]:
        assert item["status"] == 200
        parsed = urlsplit(item["url"])
        assert parsed.scheme == "https" and parsed.hostname == "data-api.binance.vision"
        body = (path.parent / item["path"]).read_bytes()
        assert hashlib.sha256(body).hexdigest() == item["body_sha256"]
        query = parse_qs(parsed.query)
        if parsed.path == "/api/v3/exchangeInfo":
            assert captured_info is None and json.loads(query["symbols"][0]) == ["BTCUSDT"]
            captured_info = json.loads(body)
        else:
            assert parsed.path == "/api/v3/klines" and query["symbol"] == ["BTCUSDT"]
            captured_bars.setdefault(query["interval"][0], []).extend(json.loads(body))
    assert captured_info == recording["exchange_info"] and captured_bars == recording["bars"]

    def replay(request: Request, *, timeout: float) -> _PublicWireResponse:
        del timeout
        parsed = urlsplit(request.full_url)
        query = parse_qs(parsed.query)
        assert parsed.scheme == "https" and parsed.hostname == "data-api.binance.vision"
        if parsed.path == "/api/v3/exchangeInfo":
            assert json.loads(query.get("symbols", ['["BTCUSDT"]'])[0]) == ["BTCUSDT"]
            return _PublicWireResponse(recording["exchange_info"])
        assert parsed.path == "/api/v3/klines" and query["symbol"] == ["BTCUSDT"]
        interval = query["interval"][0]
        left, right = int(query["startTime"][0]), int(query["endTime"][0])
        limit = int(query["limit"][0])
        rows = recording["bars"][interval]
        assert rows[0][0] <= left <= right <= rows[-1][6]
        selected = [row for row in rows if left <= row[0] <= right][:limit]
        assert selected
        return _PublicWireResponse(selected)

    return replay, digest, str(recording["bars"]["15m"][-1][4])
