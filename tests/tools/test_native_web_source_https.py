"""Real loopback TLS tests of the scoped external input, never Product acceptance.

Run serially in the original uid10001 validation service. No hosts/root/Provider
change: only this Python process's DNS observation is redirected to loopback.
"""

from __future__ import annotations

import hashlib
import json
import socket
import ssl
from pathlib import Path

import pytest

from scripts import native_web_e2e as owner

HOST = "data-api.binance.vision"
START = 1767139200000
END = 1767744000000
QUERY = f"/api/v3/klines?symbol=BTCUSDT&interval=15m&startTime={START}&endTime={START + 899999}&limit=1000"


@pytest.fixture
def loopback_dns(monkeypatch):
    resolve = socket.getaddrinfo

    def local(host, *args, **kwargs):
        return resolve("127.0.0.1" if host == HOST else host, *args, **kwargs)

    monkeypatch.setattr(owner.socket, "getaddrinfo", local)


def exchange(ca, path=QUERY, *, host=HOST, server_name=HOST, method="GET", context=None):
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


def install_input(fixture):
    fixture.update(exchange_info={"timezone": "UTC", "symbols": []}, klines=[])


def test_scoped_https_uses_actual_ca_hostname_verification_and_records_empty_raw_response(tmp_path, loopback_dns):
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
    tmp_path, loopback_dns, monkeypatch, failure
):
    if failure == "wrong-certificate-hostname":
        run = owner.subprocess.run

        def wrong_san(command, **kwargs):
            if command[:3] == ["openssl", "x509", "-req"]:
                path = Path(command[command.index("-extfile") + 1])
                path.write_text(path.read_text().replace(f"DNS:{HOST}", "DNS:unrelated.invalid"))
            return run(command, **kwargs)

        # Vary only the peer certificate input. Real TLS validation remains on;
        # SNI is still the expected official host, so this proves client SAN checking.
        monkeypatch.setattr(owner.subprocess, "run", wrong_san)
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
def test_unexpected_external_requests_fail_the_whole_scoped_fixture(tmp_path, loopback_dns, change):
    with pytest.raises(RuntimeError, match="CONTROLLED_SOURCE_REQUEST_REJECTED"):
        with owner.controlled_source_https(tmp_path) as (ca, fixture):
            install_input(fixture)
            status, _ = exchange(ca, **change)
            assert status in {400, 501}


def test_wrong_sni_is_rejected_during_real_handshake_and_marks_fixture_failed(tmp_path, loopback_dns):
    with pytest.raises(RuntimeError, match="CONTROLLED_SOURCE_REQUEST_REJECTED"):
        with owner.controlled_source_https(tmp_path) as (ca, fixture):
            install_input(fixture)
            with pytest.raises(ssl.SSLError):
                exchange(ca, server_name="unrelated.invalid")
