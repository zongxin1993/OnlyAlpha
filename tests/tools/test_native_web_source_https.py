"""Real loopback TLS tests of the scoped external input, never Product acceptance.

Run serially in the original uid10001 validation service. No hosts/root/Provider
change: only this Python process's DNS observation is redirected to loopback.
"""

from __future__ import annotations

import hashlib
import json
import socket
import ssl
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import native_web_e2e as owner

HOST = "data-api.binance.vision"
START = 1767139200000
END = 1767744000000
QUERY = f"/api/v3/klines?symbol=BTCUSDT&interval=15m&startTime={START}&endTime={START + 899999}&limit=1000"


@pytest.fixture
def loopback_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    resolve = socket.getaddrinfo

    def local(host: Any, *args: Any, **kwargs: Any) -> Any:
        return resolve("127.0.0.1" if host == HOST else host, *args, **kwargs)

    monkeypatch.setattr("scripts.native_web_e2e.socket.getaddrinfo", local)


def exchange(
    ca: Path,
    path: str = QUERY,
    *,
    host: str = HOST,
    server_name: str = HOST,
    method: str = "GET",
    context: ssl.SSLContext | None = None,
) -> tuple[int, bytes]:
    tls = context or ssl.create_default_context(cafile=str(ca))
    assert tls.verify_mode == ssl.CERT_REQUIRED and tls.check_hostname
    with socket.create_connection(("127.0.0.1", 443), timeout=5) as transport:
        with tls.wrap_socket(transport, server_hostname=server_name) as connection:
            connection.sendall(f"{method} {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode())
            chunks = []
            while raw := connection.recv(65536):
                chunks.append(raw)
    headers, body = b"".join(chunks).split(b"\r\n\r\n", 1)
    return int(headers.split(b" ", 2)[1]), body


def install_input(fixture: dict[str, Any]) -> None:
    fixture.update(exchange_info={"timezone": "UTC", "symbols": []}, klines=[])


def test_scoped_https_uses_actual_ca_hostname_verification_and_records_empty_raw_response(
    tmp_path: Path, loopback_dns: None
) -> None:
    with owner.controlled_source_https(tmp_path) as (ca, fixture):
        install_input(fixture)
        assert exchange(ca) == (200, b"[]")
    records = [json.loads(line) for line in (tmp_path / "controlled-source-https.jsonl").read_text().splitlines()]
    response = next(record for record in records if record.get("path") == "/api/v3/klines")
    assert response["sni"] == response["host"] == HOST
    assert response["status"] == 200 and response["response_rows"] == 0
    assert response["raw_response_sha256"] == hashlib.sha256(b"[]").hexdigest()
    assert records[0]["scope_start_ms"] == START and records[0]["scope_end_ms"] == END


@pytest.mark.parametrize("failure", ["untrusted-ca", "wrong-certificate-hostname"])
def test_real_tls_handshake_rejects_untrusted_ca_or_wrong_certificate_hostname(
    tmp_path: Path, loopback_dns: None, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    if failure == "wrong-certificate-hostname":
        run = subprocess.run

        def wrong_san(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
            if command[:3] == ["openssl", "x509", "-req"]:
                path = Path(command[command.index("-extfile") + 1])
                path.write_text(path.read_text().replace(f"DNS:{HOST}", "DNS:unrelated.invalid"))
            return run(command, **kwargs)

        # Vary only the peer certificate input. Real TLS validation remains on;
        # SNI is still the expected official host, so this proves client SAN checking.
        monkeypatch.setattr("scripts.native_web_e2e.subprocess.run", wrong_san)
    with owner.controlled_source_https(tmp_path) as (ca, fixture):
        install_input(fixture)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT) if failure == "untrusted-ca" else None
        with pytest.raises(ssl.SSLCertVerificationError) as rejected:
            exchange(ca, context=context)
        if failure == "wrong-certificate-hostname":
            assert rejected.value.verify_code == 62  # OpenSSL hostname mismatch.


@pytest.mark.parametrize(
    "change",
    [
        {"host": "unrelated.invalid"},
        {"host": HOST + "\r\nHost: unrelated.invalid"},
        {"path": "/api/v3/not-declared"},
        {"path": QUERY + "&symbol=BTCUSDT"},
        {"path": QUERY.replace(f"startTime={START}", f"startTime={START + 1}")},
        {"path": QUERY.replace(f"endTime={START + 899999}", f"endTime={END}")},
        {"path": QUERY.replace(f"startTime={START}", f"startTime={START - 900000}")},
        {"method": "POST"},
    ],
)
def test_unexpected_external_requests_fail_the_whole_scoped_fixture(
    tmp_path: Path, loopback_dns: None, change: dict[str, Any]
) -> None:
    with pytest.raises(RuntimeError, match="CONTROLLED_SOURCE_REQUEST_REJECTED"):
        with owner.controlled_source_https(tmp_path) as (ca, fixture):
            install_input(fixture)
            status, _ = exchange(ca, **change)
            assert status in {400, 501}


def test_wrong_sni_is_rejected_during_real_handshake_and_marks_fixture_failed(
    tmp_path: Path, loopback_dns: None
) -> None:
    with pytest.raises(RuntimeError, match="CONTROLLED_SOURCE_REQUEST_REJECTED"):
        with owner.controlled_source_https(tmp_path) as (ca, fixture):
            install_input(fixture)
            with pytest.raises(ssl.SSLError):
                exchange(ca, server_name="unrelated.invalid")


def test_backtest_profile_returns_exact_minute_input_and_declares_empty_chart_context(
    tmp_path: Path, loopback_dns: None
) -> None:
    first, end = 1735861200000, 1735905600000
    query = f"/api/v3/klines?symbol=BTCUSDT&interval=1m&startTime={first}&endTime={end - 1}&limit=1000"
    chart = "/api/v3/klines?symbol=BTCUSDT&interval=15m&startTime=1792806300000&endTime=1793706299999&limit=1000"
    with owner.controlled_source_https(tmp_path, backtest=True) as (ca, fixture):
        install_input(fixture)
        status, raw = exchange(ca, query)
        rows = json.loads(raw)
        assert status == 200 and len(rows) == 740
        assert rows[0][0] == first and rows[-1][6] == end - 1
        assert [row[0] for row in rows] == list(range(first, end, 60000))
        assert rows[0][1:6] == ["90000.00", "90001.00", "89999.00", "90000.00", "100"]
        assert rows[60][4] == "96000.00" and rows[120][4] == "90000.00"
        assert exchange(ca, chart) == (200, b"[]")


def test_backtest_external_rules_are_complete_and_do_not_change_retained_instrument_steps(
    tmp_path: Path, loopback_dns: None
) -> None:
    query = "/api/v3/exchangeInfo?showPermissionSets=false&symbols=%5B%22BTCUSDT%22%5D"
    with owner.controlled_source_https(tmp_path, backtest=True) as (ca, fixture):
        install_input(fixture)
        status, raw = exchange(ca, query)
        symbol = json.loads(raw)["symbols"][0]
        assert status == 200
        assert symbol["symbol"] == "BTCUSDT" and symbol["isSpotTradingAllowed"] is True
        assert "MARKET" in symbol["orderTypes"]
        assert [
            symbol[key]
            for key in (
                "baseAssetPrecision",
                "quoteAssetPrecision",
                "baseCommissionPrecision",
                "quoteCommissionPrecision",
            )
        ] == [8, 8, 8, 8]
        filters = {item["filterType"]: item for item in symbol["filters"]}
        assert filters["PRICE_FILTER"]["tickSize"] == "0.01"
        assert filters["LOT_SIZE"] == {
            "filterType": "LOT_SIZE",
            "stepSize": "0.000001",
            "minQty": "0.000001",
            "maxQty": "9000",
        }
        assert filters["NOTIONAL"] == {
            "filterType": "NOTIONAL",
            "minNotional": "5",
            "applyMinToMarket": True,
            "maxNotional": "9000000",
            "applyMaxToMarket": False,
            "avgPriceMins": 5,
        }
    with owner.controlled_source_https(tmp_path) as (ca, fixture):
        install_input(fixture)
        assert json.loads(exchange(ca, query)[1]) == fixture["exchange_info"]


@pytest.mark.parametrize("change", ["earlier", "later", "unaligned", "other-interval", "wide-chart"])
def test_backtest_profile_refuses_undeclared_minute_or_chart_range(
    tmp_path: Path, loopback_dns: None, change: str
) -> None:
    first, end = 1735861200000, 1735905600000
    query = f"/api/v3/klines?symbol=BTCUSDT&interval=1m&startTime={first}&endTime={end - 1}&limit=1000"
    if change == "earlier":
        query = query.replace(str(first), str(first - 60000))
    elif change == "later":
        query = query.replace(str(end - 1), str(end + 59999))
    elif change == "unaligned":
        query = query.replace(str(first), str(first + 1))
    elif change == "other-interval":
        query = query.replace("interval=1m", "interval=5m")
    else:
        query = "/api/v3/klines?symbol=BTCUSDT&interval=15m&startTime=1792806300000&endTime=1793707199999&limit=1000"
    with pytest.raises(RuntimeError, match="CONTROLLED_SOURCE_REQUEST_REJECTED"):
        with owner.controlled_source_https(tmp_path, backtest=True) as (ca, fixture):
            install_input(fixture)
            status, _ = exchange(ca, query)
            assert status == 400
