"""Deterministic local Binance-shaped REST and WebSocket probe fixture."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import ssl
import threading
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

_SCENARIOS = {"ALL_PASS", "REALTIME_FAIL", "OFFLINE", "INVALID_SCHEMA"}
_SERVER_TIME_MS = 1_767_225_780_000


class _State:
    scenario = "ALL_PASS"
    lock = threading.Lock()


class _Handler(BaseHTTPRequestHandler):
    server_version = "OnlyAlphaProbeFixture/1"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_PUT(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler hook
        scenario = self.path.removeprefix("/scenario/")
        if scenario not in _SCENARIOS:
            self._json({"error": "unknown scenario"}, HTTPStatus.BAD_REQUEST)
            return
        with _State.lock:
            _State.scenario = scenario
        self._json({"scenario": scenario})

    def do_GET(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler hook
        path = urlparse(self.path)
        with _State.lock:
            scenario = _State.scenario
        if path.path == "/health":
            self._json({"status": "ready", "scenario": scenario})
        elif scenario == "OFFLINE":
            self._json({"error": "offline"}, HTTPStatus.SERVICE_UNAVAILABLE)
        elif path.path == "/api/v3/ping":
            self._json({})
        elif path.path == "/api/v3/time":
            self._json({"serverTime": _SERVER_TIME_MS})
        elif path.path == "/api/v3/exchangeInfo":
            symbols = json.loads(parse_qs(path.query).get("symbols", ["[]"])[0])
            self._json(
                {
                    "timezone": "UTC",
                    "exchangeFilters": [],
                    "symbols": "invalid" if scenario == "INVALID_SCHEMA" else [{"symbol": item} for item in symbols],
                }
            )
        elif path.path == "/api/v3/klines":
            start = int(parse_qs(path.query)["startTime"][0])
            self._json([_kline(start), _kline(start + 60_000)])
        elif self.headers.get("Upgrade", "").lower() == "websocket":
            if scenario == "REALTIME_FAIL":
                self.send_error(HTTPStatus.SERVICE_UNAVAILABLE)
            else:
                self._websocket_trade()
        else:
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def _json(self, value: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _websocket_trade(self) -> None:
        key = self.headers.get("Sec-WebSocket-Key")
        if key is None:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        ).decode()
        self.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        payload = json.dumps(
            {
                "e": "trade",
                "s": "BTCUSDT",
                "T": _SERVER_TIME_MS,
                "t": 1,
                "p": "100",
                "q": "2",
                "m": False,
            },
            separators=(",", ":"),
        ).encode()
        self.wfile.write(bytes((0x81, len(payload))) + payload)
        self.wfile.flush()


def _kline(start_ms: int) -> list[object]:
    return [start_ms, "100", "110", "90", "105", "2", start_ms + 59_999, "205", 3, "1", "100"]


def _create_tls_identity(directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "api.binance.com")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("api.binance.com"),
                    x509.DNSName("stream.binance.com"),
                    x509.DNSName("binance-probe-fixture"),
                ]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    certificate_path = directory / "ca.crt"
    private_key_path = directory / "server.key"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    private_key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return certificate_path, private_key_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--certificate-directory", required=True, type=Path)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--control-port", type=int, default=8080)
    args = parser.parse_args()

    certificate, private_key = _create_tls_identity(args.certificate_directory)
    control = ThreadingHTTPServer((args.host, args.control_port), _Handler)
    threading.Thread(target=control.serve_forever, daemon=True).start()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certificate, private_key)
    providers = [ThreadingHTTPServer((args.host, port), _Handler) for port in (443, 9443)]
    for provider in providers:
        provider.socket = context.wrap_socket(provider.socket, server_side=True)
    threading.Thread(target=providers[0].serve_forever, daemon=True).start()
    providers[1].serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
