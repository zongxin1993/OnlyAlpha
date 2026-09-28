"""Deterministic local Binance-shaped REST and WebSocket probe fixture."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import select
import ssl
import threading
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import ParseResult, parse_qs, urlparse

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

_SCENARIOS = {"ALL_PASS", "REALTIME_FAIL", "OFFLINE", "INVALID_SCHEMA"}
_SERVER_TIME_MS = 1_767_225_780_000
_INTERVAL_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
}


class _State:
    scenario = "ALL_PASS"
    lock = threading.Lock()
    kline_requests: list[dict[str, int | str | None]] = []
    stream_requests: list[str] = []


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
            _State.kline_requests.clear()
            _State.stream_requests.clear()
        self._json({"scenario": scenario})

    def do_GET(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler hook
        path = urlparse(self.path)
        with _State.lock:
            scenario = _State.scenario
        if path.path == "/health":
            self._json({"status": "ready", "scenario": scenario})
        elif path.path == "/__onlyalpha_e2e__/market-data-stats":
            with _State.lock:
                requests = list(_State.kline_requests)
                streams = list(_State.stream_requests)
            self._json(
                {
                    "evidence_kind": "CONTROLLED_TEST_EVIDENCE",
                    "kline_requests": requests,
                    "stream_requests": streams,
                }
            )
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
                    "symbols": "invalid"
                    if scenario == "INVALID_SCHEMA"
                    else [
                        {
                            "symbol": item,
                            "status": "TRADING",
                            "baseAsset": item.removesuffix("USDT"),
                            "quoteAsset": "USDT",
                            "filters": [
                                {"filterType": "PRICE_FILTER", "tickSize": "0.01000000"},
                                {
                                    "filterType": "LOT_SIZE",
                                    "stepSize": "0.00001000",
                                    "minQty": "0.00001000",
                                },
                            ],
                        }
                        for item in symbols
                    ],
                }
            )
        elif path.path == "/api/v3/klines":
            query = parse_qs(path.query)
            start = int(query["startTime"][0])
            end = int(query["endTime"][0]) + 1
            interval = query["interval"][0]
            limit = int(query["limit"][0])
            step = _INTERVAL_MS[interval]
            with _State.lock:
                _State.kline_requests.append(
                    {
                        "symbol": query.get("symbol", [""])[0],
                        "interval": interval,
                        "startTime": start,
                        "endTime": end,
                        "limit": limit,
                    }
                )
            self._json([_kline(value, step) for value in range(start, end, step)][:limit])
        elif self.headers.get("Upgrade", "").lower() == "websocket":
            if scenario == "REALTIME_FAIL":
                self.send_error(HTTPStatus.SERVICE_UNAVAILABLE)
            else:
                self._websocket_market_data(path)
        else:
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def _json(self, value: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _websocket_market_data(self, path: ParseResult) -> None:
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
        query = parse_qs(path.query)
        stream = query.get("streams", [path.path.removeprefix("/ws/")])[0]
        if stream.endswith("@depth5"):
            payload = json.dumps(
                {"lastUpdateId": 1, "bids": [["100", "2"]], "asks": [["101", "2"]]},
                separators=(",", ":"),
            ).encode()
            self.wfile.write(bytes((0x81, len(payload))) + payload)
            self.wfile.flush()
            return
        interval = stream.rsplit("kline_", 1)[-1]
        step = _INTERVAL_MS[interval]
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        start = now_ms // step * step
        with _State.lock:
            _State.stream_requests.append(stream)
        payload = json.dumps(
            {
                "stream": stream,
                "data": {
                    "e": "kline",
                    "E": now_ms,
                    "s": "BTCUSDT",
                    "k": {
                        "t": start,
                        "T": start + step - 1,
                        "s": "BTCUSDT",
                        "i": interval,
                        "o": "100",
                        "h": "110",
                        "l": "90",
                        "c": "105",
                        "v": "2",
                        "q": "205",
                        "n": 3,
                        "x": False,
                    },
                },
            },
            separators=(",", ":"),
        ).encode()
        header = (
            bytes((0x81, len(payload))) if len(payload) <= 125 else bytes((0x81, 126)) + len(payload).to_bytes(2, "big")
        )
        frame = header + payload
        self.wfile.write(frame)
        self.wfile.flush()
        self._serve_websocket(frame)

    def _serve_websocket(self, market_data_frame: bytes) -> None:
        """Keep emitting deterministic market data until the client closes."""
        while True:
            if not select.select([self.connection], [], [], 1)[0]:
                try:
                    self.wfile.write(market_data_frame)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return
                continue
            header = self.rfile.read(2)
            if len(header) != 2:
                return
            opcode = header[0] & 0x0F
            length = header[1] & 0x7F
            if length == 126:
                length = int.from_bytes(self.rfile.read(2), "big")
            elif length == 127:
                length = int.from_bytes(self.rfile.read(8), "big")
            masked = bool(header[1] & 0x80)
            mask = self.rfile.read(4) if masked else b""
            payload = self.rfile.read(length)
            if masked:
                payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
            if opcode == 0x8:
                self.wfile.write(bytes((0x88, 0)))
                self.wfile.flush()
                return
            if opcode == 0x9:
                self.wfile.write(bytes((0x8A, len(payload))) + payload)
                self.wfile.flush()


def _kline(start_ms: int, step_ms: int = 60_000) -> list[object]:
    return [start_ms, "100", "110", "90", "105", "2", start_ms + step_ms - 1, "205", 3, "1", "100"]


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
                    x509.DNSName("data-api.binance.vision"),
                    x509.DNSName("data-stream.binance.vision"),
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
