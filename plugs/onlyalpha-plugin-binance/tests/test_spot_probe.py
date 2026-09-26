from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib import import_module

import pytest
from onlyalpha_plugin_binance.errors import OnlyBinanceError
from onlyalpha_plugin_binance.spot.data_source.factory import OnlyBinanceSpotDataSourceFactory
from onlyalpha_plugin_binance.spot.data_source.probe import OnlyBinanceSpotProbe

from onlyalpha.plugin.integration import OnlyIntegrationProbeCheck
from onlyalpha.plugin.integration_probe import (
    OnlyIntegrationProbePolicy,
    OnlyIntegrationProbeRequest,
    OnlyIntegrationProbeStatus,
)

NOW = datetime(2026, 1, 1, 0, 3, tzinfo=UTC)
NOW_MS = int(NOW.timestamp() * 1000)
factory_module = import_module("onlyalpha_plugin_binance.spot.data_source.factory")


class _Reference:
    def __init__(
        self, *, ping: bytes = b"{}", server_time: bytes | None = None, symbols: tuple[str, ...] = ("BTCUSDT",)
    ) -> None:
        self.ping_payload = ping
        self.time_payload = server_time or json.dumps({"serverTime": NOW_MS}).encode()
        self.symbols = symbols
        self.exchange_info_calls: list[tuple[str, ...]] = []

    def ping(self) -> bytes:
        return self.ping_payload

    def server_time(self) -> bytes:
        return self.time_payload

    def exchange_info(self, symbols: tuple[str, ...]) -> bytes:
        self.exchange_info_calls.append(symbols)
        return json.dumps(
            {
                "timezone": "UTC",
                "exchangeFilters": [],
                "symbols": [{"symbol": symbol} for symbol in self.symbols],
            }
        ).encode()


class _Historical:
    def __init__(self, rows: list[list[object]] | None = None) -> None:
        self.rows = rows if rows is not None else [_kline(NOW_MS - 120_000), _kline(NOW_MS - 60_000)]
        self.calls: list[tuple[str, int, int, int]] = []

    def klines(self, symbol: str, start_ms: int, end_ms: int, limit: int) -> list[list[object]]:
        self.calls.append((symbol, start_ms, end_ms, limit))
        return self.rows


class _WebSocket:
    def __init__(self, payload: bytes | Exception | None = None, *, connect_error: Exception | None = None) -> None:
        self.payload = (
            payload or json.dumps({"lastUpdateId": 1, "bids": [["99", "2"]], "asks": [["101", "3"]]}).encode()
        )
        self.connect_error = connect_error
        self.urls: list[str] = []
        self.closed = 0

    def connect(self, url: str) -> None:
        self.urls.append(url)
        if self.connect_error is not None:
            raise self.connect_error

    def receive(self) -> bytes:
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload

    def close(self) -> None:
        self.closed += 1


def _kline(start_ms: int) -> list[object]:
    return [start_ms, "100", "110", "90", "105", "2", start_ms + 59_999, "205", 3, "1", "100"]


def _request() -> OnlyIntegrationProbeRequest:
    return OnlyIntegrationProbeRequest(
        probe_attempt_id="11111111-1111-4111-8111-111111111111",
        integration_id="22222222-2222-4222-8222-222222222222",
        revision_fingerprint="a" * 64,
        type_id="binance.spot.market_data",
        type_descriptor_fingerprint="b" * 64,
        public_configuration={"environment": "LIVE", "timeout_seconds": 5.0},
        probe_configuration={"instrument": "BTCUSDT"},
        required_checks=(
            OnlyIntegrationProbeCheck.CONNECTIVITY,
            OnlyIntegrationProbeCheck.REFERENCE_DATA,
            OnlyIntegrationProbeCheck.HISTORICAL_DATA,
            OnlyIntegrationProbeCheck.REALTIME_DATA,
        ),
        probe_instrument="BTCUSDT",
        policy=OnlyIntegrationProbePolicy(),
        deadline_monotonic=10.0,
        resolved_secrets={},
    )


def _probe(
    *,
    reference: _Reference | None = None,
    historical: _Historical | None = None,
    websocket: _WebSocket | None = None,
) -> tuple[OnlyBinanceSpotProbe, _Reference, _Historical, _WebSocket]:
    reference = reference or _Reference()
    historical = historical or _Historical()
    websocket = websocket or _WebSocket()
    return (
        OnlyBinanceSpotProbe(
            reference,
            historical,
            websocket,
            raw_stream_url=lambda stream: f"wss://example.test/ws/{stream}",
            utc_now=lambda: NOW,
            monotonic=lambda: 1.0,
        ),
        reference,
        historical,
        websocket,
    )


def _checks(result) -> dict[OnlyIntegrationProbeCheck, object]:  # type: ignore[no-untyped-def]
    return {item.check: item for item in result.checks}


def test_bin_01_ping_and_time_success() -> None:
    probe, _, _, _ = _probe()

    result = probe.probe(_request())

    assert result.overall_status is OnlyIntegrationProbeStatus.READY
    assert _checks(result)[OnlyIntegrationProbeCheck.CONNECTIVITY].status.value == "PASS"  # type: ignore[union-attr]


def test_bin_02_malformed_connectivity_response_fails_semantically_and_short_circuits() -> None:
    probe, reference, historical, websocket = _probe(reference=_Reference(server_time=b'{"serverTime":"bad"}'))

    result = probe.probe(_request())

    assert result.overall_status is OnlyIntegrationProbeStatus.FAILED
    checks = _checks(result)
    assert checks[OnlyIntegrationProbeCheck.CONNECTIVITY].error_code == "BINANCE_CONNECTIVITY_SCHEMA_INVALID"  # type: ignore[union-attr]
    assert all(checks[item].status.value == "SKIPPED" for item in tuple(_request().required_checks)[1:])  # type: ignore[union-attr]
    assert reference.exchange_info_calls == []
    assert historical.calls == []
    assert websocket.urls == []


def test_bin_03_exchange_info_includes_probe_symbol_and_is_symbol_scoped() -> None:
    probe, reference, _, _ = _probe()

    result = probe.probe(_request())

    assert _checks(result)[OnlyIntegrationProbeCheck.REFERENCE_DATA].status.value == "PASS"  # type: ignore[union-attr]
    assert reference.exchange_info_calls == [("BTCUSDT",)]


def test_bin_04_missing_probe_symbol_fails() -> None:
    probe, _, _, _ = _probe(reference=_Reference(symbols=("ETHUSDT",)))

    result = probe.probe(_request())

    assert result.overall_status is OnlyIntegrationProbeStatus.FAILED
    assert _checks(result)[OnlyIntegrationProbeCheck.REFERENCE_DATA].error_code == "BINANCE_REFERENCE_SYMBOL_MISSING"  # type: ignore[union-attr]


def test_bin_05_small_closed_one_minute_bar_sample_passes_without_cache() -> None:
    probe, _, historical, _ = _probe()

    result = probe.probe(_request())

    assert _checks(result)[OnlyIntegrationProbeCheck.HISTORICAL_DATA].status.value == "PASS"  # type: ignore[union-attr]
    assert historical.calls == [("BTCUSDT", NOW_MS - 120_000, NOW_MS, 3)]


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [_kline(NOW_MS - 60_000), _kline(NOW_MS - 120_000)],
        [_kline(NOW_MS - 120_000), _kline(NOW_MS - 120_000)],
        [[NOW_MS - 60_000, "100", "90", "95", "105", "-1", NOW_MS - 1, "0", 1, "0", "0"]],
        [_kline(NOW_MS)],
    ],
)
def test_bin_06_malformed_bars_fail(rows: list[list[object]]) -> None:
    probe, _, _, _ = _probe(historical=_Historical(rows))

    result = probe.probe(_request())

    assert result.overall_status is OnlyIntegrationProbeStatus.FAILED
    assert _checks(result)[OnlyIntegrationProbeCheck.HISTORICAL_DATA].error_code == "BINANCE_HISTORICAL_SCHEMA_INVALID"  # type: ignore[union-attr]


def test_bin_07_websocket_partial_depth_message_passes() -> None:
    probe, _, _, websocket = _probe()

    result = probe.probe(_request())

    assert _checks(result)[OnlyIntegrationProbeCheck.REALTIME_DATA].status.value == "PASS"  # type: ignore[union-attr]
    assert websocket.urls == ["wss://example.test/ws/btcusdt@depth5"]


def test_bin_07_websocket_malformed_partial_depth_fails() -> None:
    probe, _, _, _ = _probe(
        websocket=_WebSocket(json.dumps({"lastUpdateId": 1, "bids": [], "asks": [["101", "3"]]}).encode())
    )

    result = probe.probe(_request())

    assert _checks(result)[OnlyIntegrationProbeCheck.REALTIME_DATA].error_code == "BINANCE_REALTIME_SCHEMA_INVALID"  # type: ignore[union-attr]


@pytest.mark.parametrize("failure", [TimeoutError(), OnlyBinanceError("transport")])
def test_bin_08_websocket_timeout_or_failure_is_degraded(failure: Exception) -> None:
    probe, _, _, _ = _probe(websocket=_WebSocket(failure))

    result = probe.probe(_request())

    assert result.overall_status is OnlyIntegrationProbeStatus.DEGRADED
    assert _checks(result)[OnlyIntegrationProbeCheck.REALTIME_DATA].error_code == "BINANCE_REALTIME_UNAVAILABLE"  # type: ignore[union-attr]


@pytest.mark.parametrize("connect_error", [None, OnlyBinanceError("connect")])
def test_bin_09_websocket_always_closes(connect_error: Exception | None) -> None:
    websocket = _WebSocket(connect_error=connect_error)
    probe, _, _, _ = _probe(websocket=websocket)

    probe.probe(_request())

    assert websocket.closed == 1


def test_bin_10_result_contains_no_raw_provider_payload() -> None:
    secret_marker = "raw-provider-marker"
    probe, _, _, _ = _probe(
        websocket=_WebSocket(
            json.dumps(
                {
                    "lastUpdateId": 1,
                    "bids": [["99", "2"]],
                    "asks": [["101", "3"]],
                    "raw": secret_marker,
                }
            ).encode()
        )
    )

    result = probe.probe(_request())

    assert secret_marker not in json.dumps(result.to_dict())


def test_each_check_binds_io_to_the_smaller_per_check_or_total_deadline() -> None:
    reference = _Reference()
    historical = _Historical()
    websocket = _WebSocket()
    deadlines: list[float] = []
    probe = OnlyBinanceSpotProbe(
        reference,
        historical,
        websocket,
        raw_stream_url=lambda stream: f"wss://example.test/ws/{stream}",
        utc_now=lambda: NOW,
        monotonic=lambda: 8.5,
        bind_deadline=deadlines.append,
    )
    request = _request()

    probe.probe(request)

    assert deadlines == [10.0, 10.0, 10.0, 10.0]


def test_check_returning_after_its_deadline_cannot_pass() -> None:
    readings = iter((1.0, 1.0, 7.0, 7.0))
    probe = OnlyBinanceSpotProbe(
        _Reference(),
        _Historical(),
        _WebSocket(),
        raw_stream_url=lambda stream: f"wss://example.test/ws/{stream}",
        utc_now=lambda: NOW,
        monotonic=lambda: next(readings),
    )
    request = _request()
    request = OnlyIntegrationProbeRequest(
        request.probe_attempt_id,
        request.integration_id,
        request.revision_fingerprint,
        request.type_id,
        request.type_descriptor_fingerprint,
        request.public_configuration,
        request.probe_configuration,
        (OnlyIntegrationProbeCheck.CONNECTIVITY,),
        request.probe_instrument,
        request.policy,
        request.deadline_monotonic,
        request.resolved_secrets,
    )

    result = probe.probe(request)

    check = result.checks[0]
    assert check.status.value == "FAIL"
    assert check.failure_kind.value == "OFFLINE"
    assert check.error_code == "INTEGRATION_PROBE_TIMEOUT"
    assert result.overall_status is OnlyIntegrationProbeStatus.OFFLINE


def test_endpoint_context_is_recorded_once_within_the_probe_observation_budget() -> None:
    context = (
        "environment=GLOBAL",
        "endpoint_profile=PUBLIC_MARKET_DATA",
        "rest_host=data-api.binance.vision",
    )
    probe = OnlyBinanceSpotProbe(
        _Reference(),
        _Historical(),
        _WebSocket(),
        raw_stream_url=lambda stream: f"wss://example.test/ws/{stream}",
        context_observations=context,
        utc_now=lambda: NOW,
        monotonic=lambda: 1.0,
    )

    result = probe.probe(_request())

    assert sum(len(check.observations) for check in result.checks) == 8
    connectivity = next(check for check in result.checks if check.check is OnlyIntegrationProbeCheck.CONNECTIVITY)
    assert connectivity.observations[:3] == context
    assert all(
        not set(context).intersection(check.observations)
        for check in result.checks
        if check.check is not OnlyIntegrationProbeCheck.CONNECTIVITY
    )


@pytest.mark.parametrize(
    ("configuration", "rest_url", "stream_url"),
    [
        (
            {"environment": "GLOBAL", "endpoint_profile": "PUBLIC_MARKET_DATA"},
            "https://data-api.binance.vision",
            "wss://stream.binance.com:9443/ws/btcusdt@depth5",
        ),
        (
            {"environment": "US", "endpoint_profile": "DEFAULT"},
            "https://api.binance.us",
            "wss://stream.binance.us:9443/ws/btcusdt@depth5",
        ),
        (
            {"environment": "SPOT_TESTNET", "endpoint_profile": "DEFAULT"},
            "https://testnet.binance.vision",
            "wss://stream.testnet.binance.vision/ws/btcusdt@depth5",
        ),
    ],
)
def test_factory_probe_uses_the_canonical_endpoint_context(
    monkeypatch: pytest.MonkeyPatch,
    configuration: dict[str, object],
    rest_url: str,
    stream_url: str,
) -> None:
    captured: dict[str, object] = {}

    class Http:
        def __init__(self, base_url: str, **_kwargs: object) -> None:
            captured["rest_url"] = base_url

        def bind_deadline(self, _deadline: float) -> None:
            pass

    class WebSocket:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def bind_deadline(self, _deadline: float) -> None:
            pass

    class Probe:
        def __init__(self, _reference: object, _historical: object, _websocket: object, **kwargs: object) -> None:
            captured.update(kwargs)

        def probe(self, request: OnlyIntegrationProbeRequest) -> OnlyIntegrationProbeRequest:
            return request

    monkeypatch.setattr(factory_module, "OnlyBinancePublicHttpClient", Http)
    monkeypatch.setattr(factory_module, "OnlyBinanceWebSocketTransport", WebSocket)
    monkeypatch.setattr(factory_module, "OnlyBinanceSpotProbe", Probe)
    request = _request()
    request = OnlyIntegrationProbeRequest(
        request.probe_attempt_id,
        request.integration_id,
        request.revision_fingerprint,
        request.type_id,
        request.type_descriptor_fingerprint,
        configuration,
        request.probe_configuration,
        request.required_checks,
        request.probe_instrument,
        request.policy,
        request.deadline_monotonic,
        request.resolved_secrets,
    )

    assert OnlyBinanceSpotDataSourceFactory().probe(request) is request
    assert captured["rest_url"] == rest_url
    assert captured["raw_stream_url"]("btcusdt@depth5") == stream_url  # type: ignore[operator]
    assert f"environment={configuration['environment']}" in captured["context_observations"]  # type: ignore[operator]
