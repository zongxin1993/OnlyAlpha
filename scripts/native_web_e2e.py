"""Run the Shipping native Host and ordinary browser flows in the sole test namespace."""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import os
import platform
import queue
import signal
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import uuid
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.database_guard import assert_test_database
from scripts.dev_verification import source_inputs
from scripts.native_workstation_build import build
from scripts.runtime_artifacts import product_versions, verify_artifacts

ROOT = Path(__file__).resolve().parents[1]


def observe_stopped_backtest(probe: Path, user_data: Path, run_id: str) -> dict:
    # Call only after Host SIGTERM + positive process join. Do not retry a busy,
    # unreadable or incomplete source; the Runtime owner must reject it.
    if str(uuid.UUID(run_id)) != run_id or uuid.UUID(run_id).version != 4:
        raise ValueError("invalid original Run identity")
    path = user_data / "backtest" / "runtime" / run_id / "runtime.sqlite3"
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        # These two values are observed identity inputs, not validated proof.
        # No Python frame/dictionary/replay codec or digest admission is involved.
        raw = db.execute("SELECT payload FROM meta WHERE singleton=1").fetchone()
        if raw is None:
            raise RuntimeError("missing runtime identity")
        identity = json.loads(raw[0])
    finally:
        db.close()
    request = {
        "user_data": str(user_data),
        "run_id": run_id,
        "configuration": identity["configuration"],
        "kernel_artifact": identity["kernel_artifact"],
    }
    actual = subprocess.run(
        [str(probe), "--read-backtest-runtime-source"],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        check=True,
        timeout=120,
    )
    observation = json.loads(actual.stdout)
    if observation["schema_version"] != 1 or observation["run_id"] != run_id:
        raise RuntimeError("wrong observation identity")
    return observation


def require_paused_backtest(observation: dict) -> None:
    assert observation["execution_prefix"] and observation["replay_prefix"]
    last = observation["steps"][-1]
    assert last["kind"] == "PAUSE" and last["status"] == "PAUSED"
    assert last["input_finished"] is False and last["input_cancelled"] is False
    state = observation["state"]
    assert state["status"] == "PAUSED" and state["input_finished"] is False
    assert state.get("input_cancelled", False) is False
    assert state["outcome"] is None


def require_resumed_backtest(before: dict, after: dict) -> None:
    assert after["run_id"] == before["run_id"] and after["binding"] == before["binding"]
    assert after["execution_prefix"][: len(before["execution_prefix"])] == before["execution_prefix"]
    assert after["replay_prefix"][: len(before["replay_prefix"])] == before["replay_prefix"]
    assert after["steps"][: len(before["steps"])] == before["steps"]
    later = after["steps"][len(before["steps"]) :]
    assert later and later[0]["kind"] == "RESUME" and later[0]["status"] == "RUNNING"
    assert later[-1]["kind"] == "TERMINATE" and later[-1]["status"] == "TERMINATED"
    assert after["state"]["outcome"]["status"] == "COMPLETED"


def clickhouse_namespace(backend: Path, database: str, *, initialize: bool) -> None:
    command = "--initialize-test-clickhouse" if initialize else "--drop-test-clickhouse"
    result = subprocess.run([str(backend), command, database], check=True, capture_output=True, text=True, timeout=30)
    record = json.loads(result.stdout)
    field = "applied" if initialize else "dropped"
    if (
        not isinstance(record, dict)
        or set(record) != {"schema_version", "database", field}
        or type(record["schema_version"]) is not int
        or record["schema_version"] != 1
        or record["database"] != database
        or (
            initialize
            and record[field]
            != [
                "0001_market_data_foundation",
                "0002_market_data_integration_runtime_provenance",
            ]
        )
        or (not initialize and record[field] is not True)
    ):
        raise ValueError("NATIVE_CLICKHOUSE_NAMESPACE_RESPONSE_INVALID")


def selected_artifact(root: Path, directory: Path, digest: str) -> dict[str, Any]:
    if not directory.is_absolute() or directory.is_symlink() or (directory / "manifest.json").is_symlink():
        raise ValueError("NATIVE_ARTIFACT_SYMLINK")
    raw = (directory / "manifest.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("NATIVE_ARTIFACT_SELECTION_MISMATCH")
    backend, frontend = product_versions(root)
    return verify_artifacts(directory, source_inputs(root), backend, frontend_version=frontend, manifest_sha256=digest)


def research_deployment_id(backend: Path, command: list[str], dsn: str) -> str:
    result = subprocess.run(
        [str(backend), *command],
        env={**os.environ, "ONLYALPHA_POSTGRES_DSN": dsn},
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )

    def unique(fields: list[tuple[str, Any]]) -> dict[str, Any]:
        value = dict(fields)
        if len(value) != len(fields):
            raise ValueError("RESEARCH_DEPLOYMENT_NATIVE_RESPONSE_INVALID")
        return value

    if len(result.stdout) > 32768:
        raise ValueError("RESEARCH_DEPLOYMENT_NATIVE_RESPONSE_INVALID")
    payload = json.loads(result.stdout, object_pairs_hook=unique)
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema_version", "semantic_store_id"}
        or type(payload["schema_version"]) is not int
        or payload["schema_version"] != 1
        or not isinstance(payload["semantic_store_id"], str)
    ):
        raise ValueError("RESEARCH_DEPLOYMENT_NATIVE_RESPONSE_INVALID")
    identity = uuid.UUID(payload["semantic_store_id"])
    if identity.version != 4 or str(identity) != payload["semantic_store_id"]:
        raise ValueError("RESEARCH_DEPLOYMENT_NATIVE_RESPONSE_INVALID")
    return str(identity)


def initialize_backtest_evidence(backend: Path, resources: Path, data: Path, dsn: str, namespace: str) -> None:
    """Explicit empty Infrastructure owner, before any business acceptance."""
    result = subprocess.run(
        [str(backend), "--initialize-fresh-backtest-evidence", str(data), str(resources / "schema")],
        env={**os.environ, "ONLYALPHA_POSTGRES_DSN": dsn},
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )

    def unique(fields: list[tuple[str, Any]]) -> dict[str, Any]:
        value = dict(fields)
        if len(value) != len(fields):
            raise ValueError("BACKTEST_EVIDENCE_NATIVE_RESPONSE_INVALID")
        return value

    if len(result.stdout) > 32768:
        raise ValueError("BACKTEST_EVIDENCE_NATIVE_RESPONSE_INVALID")
    payload = json.loads(result.stdout, object_pairs_hook=unique)
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema_version", "semantic_store_id", "initialized"}
        or type(payload["schema_version"]) is not int
        or payload["schema_version"] != 1
        or payload["semantic_store_id"] != namespace
        or payload["initialized"] is not True
    ):
        raise ValueError("BACKTEST_EVIDENCE_NATIVE_RESPONSE_INVALID")


def initialize_runtime_registry(backend: Path, resources: Path, data: Path, dsn: str) -> None:
    """Infrastructure precondition only: no Generation, activation or work exists."""
    result = subprocess.run(
        [str(backend), "--initialize-fresh-runtime-registry", str(data), str(resources / "schema")],
        env={**os.environ, "ONLYALPHA_POSTGRES_DSN": dsn},
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )

    def unique(fields: list[tuple[str, Any]]) -> dict[str, Any]:
        value = dict(fields)
        if len(value) != len(fields):
            raise ValueError("RUNTIME_REGISTRY_NATIVE_RESPONSE_INVALID")
        return value

    if len(result.stdout) > 32768:
        raise ValueError("RUNTIME_REGISTRY_NATIVE_RESPONSE_INVALID")
    payload = json.loads(result.stdout, object_pairs_hook=unique)
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema_version", "active_for_new_work", "states"}
        or type(payload["schema_version"]) is not int
        or payload["schema_version"] != 1
        or payload["active_for_new_work"] is not None
        or payload["states"] != {}
    ):
        raise ValueError("RUNTIME_REGISTRY_NATIVE_RESPONSE_INVALID")


def seed_private_metadata(factor_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Existing authoring facts for read-only tests, created by their Rust owner.

    Never use this precondition for the authoring UI's creation/publication goal.
    """
    from onlyalpha.algorithm.private_factor import ONLY_PRIVATE_FACTOR_API_V1

    from scripts.rust_kernel_check import compiler_environment, prepare_cargo_home

    target = {"aarch64": "aarch64-unknown-linux-gnu", "x86_64": "x86_64-unknown-linux-gnu"}[platform.machine()]
    output = ROOT / "test-results/rust-kernel/target"
    environment = compiler_environment(os.environ, output)
    environment["RUSTUP_TOOLCHAIN"] = tomllib.loads((ROOT / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
    prepare_cargo_home(Path("/usr/local/cargo/registry"), Path(environment["CARGO_HOME"]))
    subprocess.run(
        [
            "cargo",
            "build",
            "--frozen",
            "--offline",
            "--target",
            target,
            "-j1",
            "-p",
            "onlyalpha-backend",
            "--example",
            "command-postgres-probe",
            "--release",
        ],
        cwd=ROOT,
        env=environment,
        check=True,
    )
    probe = output / target / "release/examples/command-postgres-probe"

    def command(action: str, **values: Any) -> dict[str, Any]:
        request = {
            "op": "factor-authoring",
            "action": action,
            "factor_id": factor_id,
            "command_id": str(uuid.uuid4()),
            "accepted_at": "2026-10-27T00:00:00Z",
            **values,
        }
        response = subprocess.run(
            [str(probe)], input=json.dumps(request), text=True, capture_output=True, check=True, timeout=20
        )
        value = json.loads(response.stdout)
        if not isinstance(value, dict) or "error" in value:
            raise ValueError("NATIVE_METADATA_PRECONDITION_FAILED")
        return value

    draft: dict[str, Any] = {
        "schema_version": 1,
        "factor_id": factor_id,
        "base_revision_fingerprint": None,
        "semantic_version": "1",
        "source_text": "def calculate(api, inputs, parameters):\n    return {'value': inputs['close']}\n",
        "factor_api_version": 1,
        "factor_api_contract_fingerprint": ONLY_PRIVATE_FACTOR_API_V1.api_contract_fingerprint,
        "input_contract": {"close": {"type": "DECIMAL"}},
        "parameter_contract": {},
        "output_contract": {"value": {"type": "DECIMAL"}},
        "description": "Retained native metadata",
        "economic_rationale": "Explicit saved hypothesis",
        "category": "test",
        "tags": ["native"],
    }
    saved = command("save", draft=draft, expected=None)
    first = command("publish", expected=saved["result"]["draft_fingerprint"])["result"]["revision"]
    draft.update(
        {
            "semantic_version": "2",
            "base_revision_fingerprint": first["revision_fingerprint"],
            "source_text": "def calculate(api, inputs, parameters):\n    return {'value': inputs['close'] * 2}\n",
        }
    )
    saved = command("save", draft=draft, expected=saved["result"]["draft_fingerprint"])
    current = command("publish", expected=saved["result"]["draft_fingerprint"])["result"]["revision"]
    return first, current


@contextmanager
def controlled_source_https(
    output: Path, *, backtest: bool = False, chart_sma: bool = False, tushare_daily: bool = False
) -> Iterator[tuple[Path, dict[str, Any]]]:
    """Controlled external Binance input; never a Product/Authority substitute.

    The host runner owns the explicit official-hostname mapping. This process
    stays unprivileged and fails if the exact loopback TLS listener is unavailable.
    """
    hostname = "data-api.binance.vision"
    if os.geteuid() == 0 or socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM) != socket.getaddrinfo(
        "127.0.0.1", 443, type=socket.SOCK_STREAM
    ):
        raise RuntimeError("CONTROLLED_SOURCE_REQUIRES_UNPRIVILEGED_EXACT_LOOPBACK_MAPPING")
    stream_host = "data-stream.binance.vision"
    if chart_sma and socket.getaddrinfo(stream_host, 443, type=socket.SOCK_STREAM) != socket.getaddrinfo(
        "127.0.0.1", 443, type=socket.SOCK_STREAM
    ):
        raise RuntimeError("CONTROLLED_SOURCE_STREAM_MAPPING_REQUIRED")
    tushare_host = "api.tushare.pro"
    if tushare_daily and socket.getaddrinfo(tushare_host, 443, type=socket.SOCK_STREAM) != socket.getaddrinfo(
        "127.0.0.1", 443, type=socket.SOCK_STREAM
    ):
        raise RuntimeError("CONTROLLED_TUSHARE_MAPPING_REQUIRED")
    fixture: dict[str, Any] = {}
    violations: list[str] = []
    guard = threading.Lock()
    evidence = output / "controlled-source-https.jsonl"
    # Frozen external-input scope. Unrecorded bars return []; they do not prove
    # market absence and do not authorize the product to invent complete inputs.
    first_ms, exclusive_end_ms, stride_ms = 1767139200000, 1767744000000, 900000
    now_ms = time.time_ns() // 1_000_000
    chart_anchor = now_ms // stride_ms * stride_ms
    chart_first = chart_anchor - 2400 * stride_ms
    chart_end = chart_anchor + 2 * stride_ms
    # 日线场景从普通首页选择来源。初次打开、刷新、重启可能跨原 Chart 的两个 15m 边界。
    day_home_windows = (
        [(upper - 1000 * stride_ms, upper) for upper in range(chart_anchor, chart_end + 1, stride_ms)]
        if tushare_daily
        else []
    )
    # Explicit synthetic external facts for the approved 20 + 720 minute window.
    # No prepared Dataset, Strategy, Generation or Run is installed by this input.
    minute_first, minute_end = 1735861200000, 1735905600000
    minute_rows: list[list[Any]] = []
    if backtest:
        for index, opened in enumerate(range(minute_first, minute_end, 60000)):
            phase = index % 120
            price = 90000 + min(phase, 120 - phase) * 100
            minute_rows.append(
                [
                    opened,
                    f"{price}.00",
                    f"{price + 1}.00",
                    f"{price - 1}.00",
                    f"{price}.00",
                    "100",
                    opened + 59999,
                    f"{price * 100}.00",
                    100,
                    "50",
                    f"{price * 50}.00",
                    "0",
                ]
            )

    def record(value: dict[str, Any], violation: str | None = None) -> None:
        with guard:
            with evidence.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(value, sort_keys=True) + "\n")
            if violation is not None:
                violations.append(violation)

    with tempfile.TemporaryDirectory(prefix="onlyalpha-source-tls-") as temporary:
        private = Path(temporary)
        private.chmod(0o700)
        ca_key, leaf_key = private / "ca.key", private / "leaf.key"
        for key in (ca_key, leaf_key):
            key.touch(mode=0o600, exist_ok=False)
        ca, csr, leaf = output / "controlled-source-ca.pem", private / "leaf.csr", private / "leaf.pem"
        extensions = private / "leaf.ext"
        extensions.write_text(
            "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=serverAuth\nsubjectAltName=DNS:data-api.binance.vision"
            + (",DNS:data-stream.binance.vision" if chart_sma else "")
            + (",DNS:api.tushare.pro" if tushare_daily else "")
            + "\n"
        )
        commands = (
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-sha256",
                "-days",
                "1",
                "-subj",
                "/CN=OnlyAlpha controlled external input CA",
                "-addext",
                "basicConstraints=critical,CA:TRUE",
                "-keyout",
                str(ca_key),
                "-out",
                str(ca),
            ],
            [
                "openssl",
                "req",
                "-new",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-sha256",
                "-subj",
                "/CN=data-api.binance.vision",
                "-keyout",
                str(leaf_key),
                "-out",
                str(csr),
            ],
            [
                "openssl",
                "x509",
                "-req",
                "-in",
                str(csr),
                "-CA",
                str(ca),
                "-CAkey",
                str(ca_key),
                "-set_serial",
                "2",
                "-days",
                "1",
                "-sha256",
                "-extfile",
                str(extensions),
                "-out",
                str(leaf),
            ],
        )
        for command in commands:
            subprocess.run(command, check=True, capture_output=True, timeout=15)
        for key in (ca_key, leaf_key):
            if key.stat().st_mode & 0o777 != 0o600:
                raise RuntimeError("CONTROLLED_SOURCE_PRIVATE_KEY_MODE")
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.minimum_version = ssl.TLSVersion.TLSv1_2
        tls.load_cert_chain(leaf, leaf_key)

        def accept_sni(connection: ssl.SSLSocket | ssl.SSLObject, name: str | None, _context: Any) -> None:
            if (
                name != hostname
                and not (chart_sma and name == stream_host)
                and not (tushare_daily and name == tushare_host)
            ):
                record({"kind": "rejected_sni", "sni": name}, "CONTROLLED_SOURCE_UNEXPECTED_SNI")
                raise ssl.SSLError("CONTROLLED_SOURCE_UNEXPECTED_SNI")
            connection.onlyalpha_sni = name  # type: ignore[union-attr]

        tls.set_servername_callback(accept_sni)

        class ExternalInputServer(http.server.ThreadingHTTPServer if chart_sma else http.server.HTTPServer):
            def get_request(self) -> tuple[ssl.SSLSocket, Any]:
                connection, address = super().get_request()
                connection.settimeout(5)
                try:
                    return tls.wrap_socket(connection, server_side=True), address
                except BaseException:
                    connection.close()
                    raise

            def handle_error(self, _request: Any, _address: Any) -> None:
                record({"kind": "handler_error"}, "CONTROLLED_SOURCE_HANDLER_FAILED")

        class ExternalInputHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, _format: str, *args: Any) -> None:
                pass

            def chart_stream(self, request: Any) -> None:
                key = self.headers.get("Sec-WebSocket-Key")
                if (
                    request.path != "/ws/btcusdt@kline_15m"
                    or request.query
                    or request.netloc
                    or request.scheme
                    or request.fragment
                    or self.headers.get_all("Host") != [stream_host]
                    or self.headers.get("Upgrade", "").lower() != "websocket"
                    or self.headers.get("Sec-WebSocket-Version") != "13"
                    or key is None
                ):
                    self.send_error(400)
                    return
                accept = base64.b64encode(
                    hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
                ).decode("ascii")
                self.protocol_version = "HTTP/1.1"
                self.send_response(101)
                self.send_header("Upgrade", "websocket")
                self.send_header("Connection", "Upgrade")
                self.send_header("Sec-WebSocket-Accept", accept)
                self.end_headers()
                event_ms = time.time_ns() // 1_000_000
                opened = event_ms // stride_ms * stride_ms
                price = 90000 + (opened // stride_ms) % 100
                payload = json.dumps(
                    {
                        "e": "kline",
                        "E": event_ms,
                        "s": "BTCUSDT",
                        "k": {
                            "s": "BTCUSDT",
                            "i": "15m",
                            "t": opened,
                            "T": opened + stride_ms - 1,
                            "o": str(price),
                            "h": str(price + 1),
                            "l": str(price - 1),
                            "c": str(price),
                            "v": "100",
                            "q": str(price * 100),
                            "n": 100,
                            "V": "50",
                            "Q": str(price * 50),
                            "x": False,
                        },
                    },
                    separators=(",", ":"),
                ).encode()
                self.wfile.write(b"\x81\x7e" + len(payload).to_bytes(2, "big") + payload)
                self.wfile.flush()
                record(
                    {
                        "kind": "chart_stream",
                        "host": stream_host,
                        "path": request.path,
                        "status": 101,
                        "preview_start_ms": opened,
                        "frame_sha256": hashlib.sha256(payload).hexdigest(),
                    }
                )
                self.close_connection = True
                self.connection.settimeout(150)
                self.rfile.read(2)

            def do_POST(self) -> None:
                if not tushare_daily:
                    self.send_error(501)
                    return
                from packages.backend.tests.transport.tushare_daily_product import external_response

                sni = getattr(self.connection, "onlyalpha_sni", None)
                try:
                    if (
                        not tushare_daily
                        or sni != tushare_host
                        or self.headers.get_all("Host") != [tushare_host]
                        or self.path != "/"
                        or self.headers.get_all("Content-Type") != ["application/json"]
                        or self.headers.get_all("Transfer-Encoding") is not None
                    ):
                        raise ValueError("unexpected target")
                    lengths = self.headers.get_all("Content-Length") or []
                    if (
                        len(lengths) != 1
                        or not lengths[0].isascii()
                        or not lengths[0].isdigit()
                        or not 0 < int(lengths[0]) <= 4096
                    ):
                        raise ValueError("unexpected size")
                    api, response = external_response(json.loads(self.rfile.read(int(lengths[0]))))
                    raw = json.dumps(response, ensure_ascii=False).encode()
                    record({"kind": "tushare", "api": api, "response_sha256": hashlib.sha256(raw).hexdigest()})
                    status = 200
                except (ValueError, TypeError, KeyError):
                    record({"kind": "tushare_rejected"}, "CONTROLLED_TUSHARE_REQUEST_REJECTED")
                    raw = b'{"code":-1}'
                    status = 400
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:
                request = urlsplit(self.path)
                query: dict[str, list[str]] = {}
                sni = getattr(self.connection, "onlyalpha_sni", None)
                if chart_sma and sni == stream_host:
                    self.chart_stream(request)
                    return
                response: Any = None
                error: str | None = None
                try:
                    query = parse_qs(request.query, keep_blank_values=True, strict_parsing=True)
                    if (
                        self.headers.get_all("Host") != [hostname]
                        or sni != hostname
                        or request.scheme
                        or request.netloc
                        or request.fragment
                    ):
                        raise ValueError("CONTROLLED_SOURCE_UNEXPECTED_HOST")
                    if not fixture:
                        raise ValueError("CONTROLLED_SOURCE_INPUT_NOT_INSTALLED")
                    if request.path == "/api/v3/exchangeInfo":
                        if query not in (
                            {"showPermissionSets": ["false"], "permissions": ["SPOT"]},
                            {"showPermissionSets": ["false"], "symbols": ['["BTCUSDT"]']},
                        ):
                            raise ValueError("CONTROLLED_SOURCE_UNEXPECTED_QUERY")
                        response = fixture["exchange_info"]
                        if backtest:
                            # Explicit synthetic venue rules, not inferred from
                            # normalized metadata or evidence of historical rules.
                            # Keep the retained Source's instrument tick/step.
                            response = {
                                "timezone": "UTC",
                                "symbols": [
                                    {
                                        "symbol": "BTCUSDT",
                                        "baseAsset": "BTC",
                                        "quoteAsset": "USDT",
                                        "status": "TRADING",
                                        "isSpotTradingAllowed": True,
                                        "orderTypes": ["LIMIT", "MARKET"],
                                        "baseAssetPrecision": 8,
                                        "quoteAssetPrecision": 8,
                                        "baseCommissionPrecision": 8,
                                        "quoteCommissionPrecision": 8,
                                        "filters": [
                                            {
                                                "filterType": "PRICE_FILTER",
                                                "minPrice": "0.01",
                                                "maxPrice": "1000000",
                                                "tickSize": "0.01",
                                            },
                                            {
                                                "filterType": "LOT_SIZE",
                                                "minQty": "0.000001",
                                                "maxQty": "9000",
                                                "stepSize": "0.000001",
                                            },
                                            {
                                                "filterType": "MARKET_LOT_SIZE",
                                                "minQty": "0",
                                                "maxQty": "100",
                                                "stepSize": "0",
                                            },
                                            {
                                                "filterType": "NOTIONAL",
                                                "minNotional": "5",
                                                "applyMinToMarket": True,
                                                "maxNotional": "9000000",
                                                "applyMaxToMarket": False,
                                                "avgPriceMins": 5,
                                            },
                                        ],
                                    }
                                ],
                            }
                    elif request.path == "/api/v3/klines":
                        if set(query) != {"symbol", "interval", "startTime", "endTime", "limit"} or any(
                            len(v) != 1 for v in query.values()
                        ):
                            raise ValueError("CONTROLLED_SOURCE_UNEXPECTED_QUERY")
                        interval = query["interval"]
                        if query["symbol"] != ["BTCUSDT"] or interval not in (["15m"], ["1m"]):
                            raise ValueError("CONTROLLED_SOURCE_UNEXPECTED_QUERY")
                        start, end = query["startTime"][0], query["endTime"][0]
                        if not start.isascii() or not start.isdecimal() or not end.isascii() or not end.isdecimal():
                            raise ValueError("CONTROLLED_SOURCE_UNEXPECTED_QUERY")
                        lower, upper = int(start), int(end) + 1
                        chart_range = chart_sma and interval == ["15m"] and chart_first <= lower < upper <= chart_end
                        limit = query["limit"][0]
                        if chart_range:
                            if (
                                not limit.isascii()
                                or not limit.isdecimal()
                                or len(limit) > 4
                                or not 1 <= int(limit) <= 1000
                                or upper - lower > int(limit) * stride_ms
                            ):
                                raise ValueError("CONTROLLED_SOURCE_UNEXPECTED_QUERY")
                        elif limit != "1000":
                            raise ValueError("CONTROLLED_SOURCE_UNEXPECTED_QUERY")
                        if backtest and interval == ["1m"]:
                            if not minute_first <= lower < upper <= minute_end or lower % 60000 or upper % 60000:
                                raise ValueError("CONTROLLED_SOURCE_UNEXPECTED_RANGE")
                            response = [row for row in minute_rows if lower <= row[0] < upper][:1000]
                        elif interval == ["1m"]:
                            # The Frozen technical consumer supplies its original
                            # two-fill vector. It is distinct from the Web vector.
                            retained = fixture["klines"]
                            if (
                                not minute_first <= lower < upper <= minute_end
                                or lower % 60000
                                or upper % 60000
                                or [row[0] for row in retained] != list(range(minute_first, minute_end, 60000))
                            ):
                                raise ValueError("CONTROLLED_SOURCE_UNEXPECTED_RANGE")
                            response = [row for row in retained if lower <= row[0] < upper][:1000]
                        elif interval == ["15m"]:
                            if lower % stride_ms or upper % stride_ms or lower >= upper:
                                raise ValueError("CONTROLLED_SOURCE_UNEXPECTED_RANGE")
                            if chart_range:
                                response = []
                                for opened in range(lower, upper, stride_ms):
                                    price = 90000 + (opened // stride_ms) % 100
                                    response.append(
                                        [
                                            opened,
                                            str(price),
                                            str(price + 1),
                                            str(price - 1),
                                            str(price),
                                            "100",
                                            opened + stride_ms - 1,
                                            str(price * 100),
                                            100,
                                            "50",
                                            str(price * 50),
                                            "0",
                                        ]
                                    )
                            elif first_ms <= lower < upper <= exclusive_end_ms:
                                response = [row for row in fixture["klines"] if lower <= row[0] < upper][:1000]
                            elif (lower, upper) in day_home_windows:
                                response = []
                            elif (
                                backtest
                                and 1735689600000 <= lower < upper <= 1798761600000
                                and upper - lower <= 1000 * stride_ms
                            ):
                                # The ordinary home chart requests recent 15m history.
                                # This declared precondition has no such observations;
                                # [] is incomplete input, never a claim of market absence.
                                response = []
                            else:
                                raise ValueError("CONTROLLED_SOURCE_UNEXPECTED_RANGE")
                        else:
                            raise ValueError("CONTROLLED_SOURCE_UNEXPECTED_QUERY")
                    else:
                        raise ValueError("CONTROLLED_SOURCE_UNEXPECTED_PATH")
                except (ValueError, KeyError) as failure:
                    error = str(failure)
                    response = {"code": -1100, "msg": "Controlled external input rejected"}
                raw = json.dumps(response, separators=(",", ":"), ensure_ascii=True).encode()
                status = 400 if error else 200
                record(
                    {
                        "method": self.command,
                        "host": self.headers.get("Host"),
                        "sni": sni,
                        "path": request.path,
                        "query": query,
                        "raw_query": request.query,
                        "status": status,
                        "raw_response_sha256": hashlib.sha256(raw).hexdigest(),
                        "response_rows": len(response) if isinstance(response, list) else None,
                    },
                    error,
                )
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(raw)

            def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
                raw = b'{"code":-1100,"msg":"Controlled external method rejected"}'
                record(
                    {
                        "method": getattr(self, "command", None),
                        "path": getattr(self, "path", None),
                        "host": self.headers.get("Host"),
                        "sni": getattr(self.connection, "onlyalpha_sni", None),
                        "status": code,
                        "raw_response_sha256": hashlib.sha256(raw).hexdigest(),
                    },
                    "CONTROLLED_SOURCE_UNEXPECTED_METHOD",
                )
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Connection", "close")
                self.end_headers()
                if getattr(self, "command", None) != "HEAD":
                    self.wfile.write(raw)

        server = ExternalInputServer(("127.0.0.1", 443), ExternalInputHandler)
        record(
            {
                "kind": "listener",
                "uid": os.geteuid(),
                "listener": list(server.server_address),
                "hostname": hostname,
                "public_ca_sha256": hashlib.sha256(ca.read_bytes()).hexdigest(),
                "scope_start_ms": first_ms,
                "scope_end_ms": exclusive_end_ms,
                "backtest_minute_scope": [minute_first, minute_end] if backtest else None,
                "sma_chart_scope": [chart_first, chart_end] if chart_sma else None,
                "empty_chart_scope": [1735689600000, 1798761600000, 1000] if backtest else None,
                **({"tushare_home_chart_windows": day_home_windows} if tushare_daily else {}),
            }
        )
        thread = threading.Thread(target=server.serve_forever, name="controlled-source-https")
        thread.start()
        try:
            yield ca, fixture
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            if thread.is_alive():
                raise RuntimeError("CONTROLLED_SOURCE_LISTENER_DID_NOT_DRAIN")
            if violations:
                raise RuntimeError("CONTROLLED_SOURCE_REQUEST_REJECTED: " + ",".join(violations))


def seed_retained_market_input(
    data: Path, resources: Path, selected: dict[str, Any], output: Path, source_trust: Path
) -> dict[str, Any]:
    """Declared prior, controlled Source facts only; never target Research setup.

    Call after seed_private_metadata has built the current-source existing
    command-postgres-probe, before starting Host. No extra producer or platform.
    The selected runtime artifact must already have passed selected_artifact().
    """
    target = {"aarch64": "aarch64-unknown-linux-gnu", "x86_64": "x86_64-unknown-linux-gnu"}[platform.machine()]
    probe = ROOT / "test-results/rust-kernel/target" / target / "release/examples/command-postgres-probe"
    native = resources / "bin/onlyalpha-backend"
    expected = selected["default_pair"]["backend_sha256"]
    if not probe.is_file() or native.is_symlink() or hashlib.sha256(native.read_bytes()).hexdigest() != expected:
        raise ValueError("RETAINED_SOURCE_SELECTED_INPUT_UNAVAILABLE")
    request = {
        "op": "market-storage",
        "request": {
            "op": "retained-source-prerequisite",
            "user_data": str(data),
            "selected_backend": str(native),
            "selected_backend_sha256": expected,
            "source_trust": str(source_trust),
            "integration_id": str(uuid.uuid4()),
            "create_command": str(uuid.uuid4()),
            "publish_command": str(uuid.uuid4()),
        },
    }
    # Original operation identities are retained before any fixture side effect.
    (output / "controlled-market-input-request.json").write_text(json.dumps(request, sort_keys=True) + "\n")
    result = subprocess.run([str(probe)], input=json.dumps(request), text=True, capture_output=True, timeout=20)
    (output / "controlled-market-input.stderr.log").write_text(result.stderr)
    result.check_returncode()
    value = json.loads(result.stdout)
    if not isinstance(value, dict) or "error" in value or value.get("controlled_external_input") is not True:
        raise ValueError("RETAINED_SOURCE_PRECONDITION_FAILED")
    (output / "controlled-market-input.json").write_text(json.dumps(value, sort_keys=True) + "\n")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--retained-market-input", action="store_true", help="Include declared controlled pre-collected Source facts"
    )
    parser.add_argument(
        "--controlled-source-https",
        action="store_true",
        help="Serve scoped controlled external input with normal official-host TLS",
    )
    parser.add_argument(
        "--backtest-market-input",
        action="store_true",
        help="Declare synthetic one-minute Backtest input and absent recent chart history",
    )
    parser.add_argument("--chart-sma-market-input", action="store_true")
    parser.add_argument("--tushare-daily-market-input", action="store_true")
    parser.add_argument("--contract-fuzz", action="store_true", help="Fuzz all declared Implemented native operations")
    parser.add_argument(
        "--restart-check", action="store_true", help="Repeat selected browser checks after a fully drained Host restart"
    )
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--artifact-sha256")
    parser.add_argument("--grep", help="Select the affected ordinary Shipping UI tests only")
    parser.add_argument("tests", nargs="*")
    args = parser.parse_args()
    if args.tushare_daily_market_input and (
        args.chart_sma_market_input
        or args.backtest_market_input
        or not args.controlled_source_https
        or not args.retained_market_input
    ):
        raise ValueError("TUSHARE_DAY_REQUIRES_DEDICATED_CONTROLLED_SOURCE")
    if args.chart_sma_market_input and (
        args.backtest_market_input or not args.controlled_source_https or not args.retained_market_input
    ):
        raise ValueError("CHART_SMA_INPUT_REQUIRES_CONTROLLED_SOURCE")
    if args.backtest_market_input and not (args.controlled_source_https and args.retained_market_input):
        raise ValueError("BACKTEST_INPUT_REQUIRES_CONTROLLED_SOURCE")
    if args.controlled_source_https and not args.retained_market_input:
        raise ValueError("CONTROLLED_SOURCE_REQUIRES_RETAINED_INPUT")
    if (args.artifact is None) != (args.artifact_sha256 is None):
        raise ValueError("NATIVE_ARTIFACT_EXPLICIT_SELECTION_REQUIRED")
    if args.artifact is not None:
        selected_artifact(ROOT, args.artifact, args.artifact_sha256)
    operation = os.environ["ONLYALPHA_DEV_VERIFICATION_OPERATION_ID"]
    output = ROOT / "test-results/native-web-e2e" / operation
    output.mkdir(parents=True)
    external: AbstractContextManager[tuple[Path, dict[str, Any]]] = (
        controlled_source_https(
            output,
            backtest=args.backtest_market_input,
            chart_sma=args.chart_sma_market_input,
            tushare_daily=args.tushare_daily_market_input,
        )
        if args.controlled_source_https
        else nullcontext((Path("/etc/ssl/certs/ca-certificates.crt"), {}))
    )
    with external as (source_trust, external_fixture):
        return _run(args, output, source_trust, external_fixture)


def _run(args: argparse.Namespace, output: Path, source_trust: Path, external_fixture: dict[str, Any]) -> int:
    operation = os.environ["ONLYALPHA_DEV_VERIFICATION_OPERATION_ID"]
    dsn = os.environ["ONLYALPHA_POSTGRES_DSN"]
    assert_test_database(dsn)
    data = output / "user-data"
    for relative in ("secrets",):
        (data / relative).mkdir(parents=True, mode=0o700)
    key = data / "secrets/dev-master-key"
    key.write_bytes(os.urandom(32))
    key.chmod(0o600)
    # WAL locations are deployment paths, not Command or stream identities.
    # Actual startup must visit every retained location without renaming it.
    wal_parent = data / "market-data/retained-test-source/realtime"
    wal_locations = (
        "00000000000040008000000000000001",
        "00000000-0000-4000-8000-000000000001",
        "capture-location",
    )
    for location in wal_locations:
        (wal_parent / location / "wal").mkdir(parents=True, mode=0o700)
    resources = args.artifact or output / "artifacts"
    if args.artifact is None:
        build(resources)
    selected_sha = args.artifact_sha256 or hashlib.sha256((resources / "manifest.json").read_bytes()).hexdigest()
    selected = selected_artifact(ROOT, resources, selected_sha)
    artifact = selected["algorithm_artifact"]
    (output / "artifact-selection.json").write_text(
        json.dumps(
            {"artifact": str(resources), "manifest_sha256": selected_sha, "default_pair": selected["default_pair"]},
            sort_keys=True,
        )
    )
    (output / "algorithm-artifact.sha256").write_text(artifact + "\n")
    executable = resources / "bin/onlyalpha-backend"
    if conninfo_to_dict(dsn).get("sslmode") not in (None, "disable"):
        raise ValueError("NATIVE_E2E_CONTAINED_POSTGRES_TRANSPORT_REQUIRED")
    operator_dsn = make_conninfo(dsn, sslmode="disable")
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    subprocess.run(
        [str(executable), "--migrate-postgres-schema", str(resources / "schema")],
        env={**os.environ, "ONLYALPHA_POSTGRES_DSN": operator_dsn},
        check=True,
        timeout=120,
    )
    # Infrastructure provisioning uses the same selected native owner as deployment.
    # This establishes no Factor, Study, Runtime Generation, Dataset or Research Run.
    deployment_id = research_deployment_id(
        executable, ["--initialize-research-deployment", str(data), str(resources / "schema")], operator_dsn
    )
    for command in ("--extend-strategy-research-namespace", "--extend-manual-backtest-namespace"):
        if research_deployment_id(executable, [command, str(data)], operator_dsn) != deployment_id:
            raise RuntimeError("RESEARCH_SEMANTIC_STORE_MISMATCH")
    initialize_runtime_registry(executable, resources, data, operator_dsn)
    initialize_backtest_evidence(executable, resources, data, operator_dsn, deployment_id)
    # Retained metadata is a separate precondition; authoring tests create their
    # own Assets and Revisions exclusively through the normal Shipping UI.
    revision, current = seed_private_metadata("private.factor.native_metadata")
    (output / "private-metadata-precondition.json").write_text(
        json.dumps({"first": revision, "current": current}, sort_keys=True)
    )
    if args.retained_market_input:
        retained = seed_retained_market_input(data, resources, selected, output, source_trust)
        if args.controlled_source_https:
            recorded = retained["provider_http_fixture"]
            if set(recorded) != {"exchange_info", "klines"} or len(recorded["klines"]) != 575:
                raise ValueError("CONTROLLED_SOURCE_RECORDED_INPUT_INVALID")
            external_fixture.update(recorded)
    database = "onlyalpha_test_native_host_" + operation.replace("-", "")
    pg = conninfo_to_dict(dsn)
    pg_user = pg.get("user")
    pg_database = pg.get("dbname")
    if (
        pg.get("host") != "postgres"
        or pg.get("port") != "5432"
        or not isinstance(pg_user, str)
        or not pg_user
        or not isinstance(pg_database, str)
        or not pg_database
    ):
        raise ValueError("CANONICAL_DEV_POSTGRES_REQUIRED")
    env = {key: value for key, value in os.environ.items() if not key.startswith("ONLYALPHA_")}
    env.update(
        ONLYALPHA_NATIVE_DEPLOYMENT="CONTAINED_DEVELOPMENT",
        ONLYALPHA_NATIVE_LOCAL_ADDRESS="127.0.0.1",
        ONLYALPHA_NATIVE_GATEWAY="127.0.0.1",
        ONLYALPHA_NATIVE_PUBLICATION="127.0.0.1:5173",
        ONLYALPHA_NATIVE_SCHEMA=str(resources / "schema"),
        ONLYALPHA_NATIVE_WEB_ASSETS=str(resources / "web"),
        ONLYALPHA_NATIVE_ALGORITHMS=str(resources / "algorithms"),
        ONLYALPHA_NATIVE_ALGORITHM_ARTIFACT=artifact,
        ONLYALPHA_NATIVE_SOURCE_TRUST=str(source_trust),
        ONLYALPHA_POSTGRES_DSN=make_conninfo(dsn, sslmode="disable"),
        ONLYALPHA_NATIVE_POSTGRES_PEER=f"{socket.gethostbyname('postgres')}:5432",
        ONLYALPHA_NATIVE_POSTGRES_USER=pg_user,
        ONLYALPHA_NATIVE_POSTGRES_DATABASE=pg_database,
        ONLYALPHA_CLICKHOUSE_URL=os.environ["ONLYALPHA_TEST_CLICKHOUSE_URL"],
        ONLYALPHA_CLICKHOUSE_DATABASE=database,
        ONLYALPHA_CLICKHOUSE_USER=os.environ["ONLYALPHA_TEST_CLICKHOUSE_USER"],
        ONLYALPHA_CLICKHOUSE_PASSWORD=os.environ["ONLYALPHA_TEST_CLICKHOUSE_PASSWORD"],
    )
    selected_artifact(ROOT, resources, selected_sha)

    def run_host(phase: str) -> int:
        phase_output = output if phase == "initial" else output / "after-restart"
        phase_output.mkdir(exist_ok=True)
        started = time.monotonic()
        events: queue.Queue[bytes] = queue.Queue()
        with (phase_output / "native.log").open("wb") as log:
            child = subprocess.Popen(
                [str(executable), "--user-data-root", str(data)],
                env=env,
                stdout=log,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            assert child.stderr is not None

            def read_errors() -> None:
                assert child.stderr is not None
                for line in child.stderr:
                    log.write(line)
                    log.flush()
                    events.put(line)
                events.put(b"")

            reader = threading.Thread(target=read_errors, name="native-host-stderr")
            reader.start()

            def interrupted(number: int, _frame: object) -> None:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGTERM)
                raise InterruptedError(f"native browser verification interrupted by {number}")

            previous = {number: signal.signal(number, interrupted) for number in (signal.SIGTERM, signal.SIGINT)}
            try:
                version = build_version = json.loads((resources / "manifest.json").read_text())["version"]
                while True:
                    remaining = 20 - (time.monotonic() - started)
                    if remaining <= 0:
                        raise TimeoutError("Native Host did not report actual READY within startup budget")
                    line = events.get(timeout=remaining)
                    if not line:
                        raise RuntimeError("Native Host exited before READY")
                    if line.decode().strip() == f"NATIVE_WORKSTATION_READY version={version}":
                        break
                (phase_output / "startup.json").write_text(
                    json.dumps(
                        {
                            "version": build_version,
                            "ready_seconds": time.monotonic() - started,
                            "pid": child.pid,
                            "resources": str(resources),
                            "operation_id": operation,
                        },
                        indent=2,
                    )
                )
                assert sorted(path.name for path in wal_parent.iterdir()) == sorted(wal_locations)
                for location in wal_locations:
                    wal_directory = wal_parent / location / "wal"
                    # Only the real owning Wal::from_directory creates this lock.
                    # This proves traversal rather than a skip of unknown labels.
                    writer_lock = wal_directory / ".writer.lock"
                    assert writer_lock.is_file() and not writer_lock.is_symlink()
                    assert writer_lock.read_bytes() == b""
                    assert {path.name for path in wal_directory.iterdir()} == {".writer.lock"}
                (phase_output / "wal-recovery-locations.json").write_text(json.dumps(wal_locations) + "\n")
                result = 0
                results = {}
                if args.tushare_daily_market_input:
                    from packages.backend.tests.transport.tushare_daily_product import run_product

                    run_product(phase, output, dsn)
                    results["tushare_daily_api"] = 0
                if not args.contract_fuzz or args.tests:
                    browser = subprocess.run(
                        [
                            "npm",
                            "exec",
                            "--",
                            "playwright",
                            "test",
                            "--workers=1",
                            *args.tests,
                            *(["--grep", args.grep] if args.grep else []),
                        ],
                        cwd=ROOT / "packages/frontend",
                        env={
                            **os.environ,
                            "PLAYWRIGHT_BASE_URL": "http://127.0.0.1:5173",
                            "ONLYALPHA_BROWSER_RESTART_PHASE": phase,
                            "ONLYALPHA_BROWSER_TUSHARE_DAILY_INPUT": "1" if args.tushare_daily_market_input else "0",
                            "ONLYALPHA_BROWSER_CHART_SMA_INPUT": "1" if args.chart_sma_market_input else "0",
                            "ONLYALPHA_BROWSER_CONTROLLED_SOURCE_HTTPS": "1" if args.controlled_source_https else "0",
                            "ONLYALPHA_BROWSER_HOST_PID": str(child.pid),
                            "ONLYALPHA_BROWSER_USER_DATA_ROOT": str(data),
                            "ONLYALPHA_BROWSER_RESTART_EVIDENCE": str(output / "factor-restart-input.json"),
                            "ONLYALPHA_BROWSER_CONTROLLED_MARKET_INPUT": (
                                str(output / "controlled-market-input.json") if args.retained_market_input else ""
                            ),
                            "PLAYWRIGHT_OUTPUT_DIR": str(phase_output / "browser"),
                        },
                    )
                    result = browser.returncode
                    results["browser"] = result
                    (phase_output / "functional-results.json").write_text(json.dumps(results, indent=2) + "\n")
                if args.contract_fuzz:
                    from scripts.native_contract_fuzz import run_contract_fuzz

                    fuzz = run_contract_fuzz(executable, output, ROOT)
                    results["contract_fuzz"] = fuzz
                    result = result or fuzz
                (phase_output / "functional-results.json").write_text(json.dumps(results, indent=2) + "\n")
            finally:
                for number, handler in previous.items():
                    signal.signal(number, handler)
                if child.poll() is None:
                    child.send_signal(signal.SIGTERM)
                try:
                    child.wait(timeout=20)
                except subprocess.TimeoutExpired as error:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
                    raise RuntimeError("Native Host did not drain after SIGTERM") from error
                finally:
                    reader.join(timeout=5)
                    if reader.is_alive():
                        raise RuntimeError("Native stderr owner did not drain")
                    remaining_processes = []
                    for entry in Path("/proc").iterdir():
                        if entry.name.isdigit():
                            try:
                                fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
                                if int(fields[2]) == child.pid:
                                    remaining_processes.append(int(entry.name))
                            except (FileNotFoundError, ProcessLookupError):
                                continue
                    (phase_output / "process-drain.json").write_text(
                        json.dumps(
                            {
                                "pid": child.pid,
                                "exit": child.returncode,
                                "remaining_process_group": remaining_processes,
                            },
                            indent=2,
                        )
                    )
                    if remaining_processes:
                        os.killpg(child.pid, signal.SIGKILL)
                        raise RuntimeError("Native process group did not drain")
        if child.returncode != 0:
            raise RuntimeError("Native Host failed its owned lifecycle")
        selected_artifact(ROOT, resources, selected_sha)
        return result

    clickhouse_namespace(executable, database, initialize=True)
    try:
        result = run_host("initial")
        if result == 0 and args.tushare_daily_market_input and args.restart_check:
            from packages.backend.tests.transport.tushare_daily_product import check_stopped_preparation

            target = {"aarch64": "aarch64-unknown-linux-gnu", "x86_64": "x86_64-unknown-linux-gnu"}[platform.machine()]
            probe = ROOT / "test-results/rust-kernel/target" / target / "release/examples/command-postgres-probe"
            check_stopped_preparation(output, dsn, probe, env)
        lifecycle = output / "factor-restart-input.json.backtest-functional-running-recovery"
        paused = None
        if result == 0 and lifecycle.exists():
            if not args.restart_check:
                raise ValueError("RUNNING_RECOVERY_REQUIRES_RESTART_CHECK")
            saved = json.loads(lifecycle.read_text())
            run_id = saved["run"]["run_id"]
            if saved["kind"] != "RUNNING" or saved["path"] != f"/backtest/runs/{run_id}":
                raise ValueError("foreign running recovery evidence")
            target = {"aarch64": "aarch64-unknown-linux-gnu", "x86_64": "x86_64-unknown-linux-gnu"}[platform.machine()]
            probe = ROOT / "test-results/rust-kernel/target" / target / "release/examples/command-postgres-probe"
            # run_host has positively joined the original Host and all children.
            # A naturally completed Run must fail this actual PAUSE fence.
            paused = observe_stopped_backtest(probe, data, run_id)
            require_paused_backtest(paused)
            Path(str(lifecycle) + ".pause").write_text(json.dumps(paused) + "\n")
        if result == 0 and args.restart_check:
            result = run_host("restored")
            if result == 0 and paused is not None:
                resumed = observe_stopped_backtest(probe, data, run_id)
                require_resumed_backtest(paused, resumed)
                Path(str(lifecycle) + ".resumed").write_text(json.dumps(resumed) + "\n")
        return result
    finally:
        clickhouse_namespace(executable, database, initialize=False)


if __name__ == "__main__":
    raise SystemExit(main())
