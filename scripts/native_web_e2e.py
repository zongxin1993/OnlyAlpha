"""Run the Shipping native Host and ordinary browser flows in the sole test namespace."""

from __future__ import annotations

import argparse
import hashlib
import http.server
import json
import os
import platform
import queue
import signal
import socket
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
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from onlyalpha.persistence.clickhouse import (
    OnlyClickHouseClient,
    OnlyClickHouseConfig,
    OnlyClickHouseMigrationAuthority,
    only_assert_clickhouse_test_database,
)
from onlyalpha.persistence.postgres import only_assert_postgres_test_database
from scripts.dev_verification import source_inputs
from scripts.native_workstation_build import build
from scripts.runtime_artifacts import product_versions, verify_artifacts

ROOT = Path(__file__).resolve().parents[1]


def selected_artifact(root: Path, directory: Path, digest: str) -> dict[str, Any]:
    if not directory.is_absolute() or directory.is_symlink() or (directory / "manifest.json").is_symlink():
        raise ValueError("NATIVE_ARTIFACT_SYMLINK")
    raw = (directory / "manifest.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("NATIVE_ARTIFACT_SELECTION_MISMATCH")
    backend, frontend = product_versions(root)
    return verify_artifacts(directory, source_inputs(root), backend, frontend_version=frontend, manifest_sha256=digest)


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
        ],
        cwd=ROOT,
        env=environment,
        check=True,
    )
    probe = output / target / "debug/examples/command-postgres-probe"

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
def controlled_source_https(output: Path) -> Iterator[tuple[Path, dict[str, Any]]]:
    """Controlled external Binance input; never a Product/Authority substitute.

    The host runner owns the explicit official-hostname mapping. This process
    stays unprivileged and fails if the exact loopback TLS listener is unavailable.
    """
    hostname = "data-api.binance.vision"
    if os.geteuid() == 0 or socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM) != socket.getaddrinfo(
        "127.0.0.1", 443, type=socket.SOCK_STREAM
    ):
        raise RuntimeError("CONTROLLED_SOURCE_REQUIRES_UNPRIVILEGED_EXACT_LOOPBACK_MAPPING")
    fixture: dict[str, Any] = {}
    violations: list[str] = []
    guard = threading.Lock()
    evidence = output / "controlled-source-https.jsonl"
    # Frozen external-input scope. Unrecorded bars return []; they do not prove
    # market absence and do not authorize the product to invent complete inputs.
    first_ms, exclusive_end_ms, stride_ms = 1767139200000, 1767744000000, 900000

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
            "extendedKeyUsage=serverAuth\nsubjectAltName=DNS:data-api.binance.vision\n"
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
            if name != hostname:
                record({"kind": "rejected_sni", "sni": name}, "CONTROLLED_SOURCE_UNEXPECTED_SNI")
                raise ssl.SSLError("CONTROLLED_SOURCE_UNEXPECTED_SNI")
            connection.onlyalpha_sni = name  # type: ignore[union-attr]

        tls.set_servername_callback(accept_sni)

        class ExternalInputServer(http.server.HTTPServer):
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

            def do_GET(self) -> None:
                request = urlsplit(self.path)
                query: dict[str, list[str]] = {}
                sni = getattr(self.connection, "onlyalpha_sni", None)
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
                    elif request.path == "/api/v3/klines":
                        if set(query) != {"symbol", "interval", "startTime", "endTime", "limit"} or any(
                            len(v) != 1 for v in query.values()
                        ):
                            raise ValueError("CONTROLLED_SOURCE_UNEXPECTED_QUERY")
                        if query["symbol"] != ["BTCUSDT"] or query["interval"] != ["15m"] or query["limit"] != ["1000"]:
                            raise ValueError("CONTROLLED_SOURCE_UNEXPECTED_QUERY")
                        start, end = query["startTime"][0], query["endTime"][0]
                        if not start.isascii() or not start.isdecimal() or not end.isascii() or not end.isdecimal():
                            raise ValueError("CONTROLLED_SOURCE_UNEXPECTED_QUERY")
                        lower, upper = int(start), int(end) + 1
                        if not first_ms <= lower < upper <= exclusive_end_ms or lower % stride_ms or upper % stride_ms:
                            raise ValueError("CONTROLLED_SOURCE_UNEXPECTED_RANGE")
                        response = [row for row in fixture["klines"] if lower <= row[0] < upper][:1000]
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
    probe = ROOT / "test-results/rust-kernel/target" / target / "debug/examples/command-postgres-probe"
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


@contextmanager
def agent_database(dsn: str, output: Path, backend: Path, installation: Path) -> Iterator[Path]:
    """Infrastructure precondition only: separate unprivileged test database and keys."""
    only_assert_postgres_test_database(dsn)
    name = "oa_agent_browser_" + uuid.uuid4().hex + "_test"
    with psycopg.connect(dsn, autocommit=True) as admin:
        password = uuid.uuid4().hex
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE").format(
                sql.Identifier(name), sql.Literal(password)
            )
        )
        try:
            admin.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(name), sql.Identifier(name)))
            try:
                admin.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name)))
                root = output / "agent-state"
                dsn_file = output / "agent-installation.dsn"
                dsn_file.write_text(make_conninfo(dsn, dbname=name, user=name, password=password))
                dsn_file.chmod(0o600)
                subprocess.run(
                    [
                        str(installation / "env/bin/python"),
                        "-B",
                        "-I",
                        "-m",
                        "onlyalpha_agent",
                        "provision",
                        "--root",
                        str(root),
                        "--backend-root",
                        str(backend),
                        "--dsn-file",
                        str(dsn_file),
                    ],
                    cwd=installation,
                    env={},
                    check=True,
                )
                yield root
            finally:
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        finally:
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(name)))


@contextmanager
def running_agent(root: Path, installation: Path, output: Path) -> Iterator[subprocess.Popen[bytes]]:
    from scripts.agent_runtime import launch

    with (output / "agent.log").open("wb") as log:
        child = launch(root, installation, stdout=subprocess.PIPE, stderr=log)
        stream = child.stdout
        assert stream is not None
        events: queue.Queue[bytes] = queue.Queue()

        def read() -> None:
            for line in stream:
                log.write(line)
                log.flush()
                events.put(line)
            events.put(b"")

        reader = threading.Thread(target=read, name="agent-startup")
        reader.start()
        try:
            deadline = time.monotonic() + 20
            while True:
                line = events.get(timeout=max(0, deadline - time.monotonic()))
                if line.strip() == b"ONLYALPHA_AGENT_READY":
                    break
                if not line:
                    raise RuntimeError("Agent exited before READY")
            yield child
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired as error:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
                raise RuntimeError("Agent did not drain") from error
            finally:
                reader.join(timeout=5)
                if reader.is_alive():
                    raise RuntimeError("Agent stdout did not drain")
        # Uvicorn drains then re-raises its received SIGTERM; retain that standard exit identity.
        if child.returncode not in {0, -signal.SIGTERM}:
            raise RuntimeError("Agent failed its owned lifecycle")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", action="store_true", help="Include the independent Shipping Agent service")
    parser.add_argument(
        "--retained-market-input", action="store_true", help="Include declared controlled pre-collected Source facts"
    )
    parser.add_argument(
        "--controlled-source-https",
        action="store_true",
        help="Serve scoped controlled external input with normal official-host TLS",
    )
    parser.add_argument("--contract-fuzz", action="store_true", help="Fuzz all declared Implemented native operations")
    parser.add_argument(
        "--restart-check", action="store_true", help="Repeat selected browser checks after a fully drained Host restart"
    )
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--artifact-sha256")
    parser.add_argument("--grep", help="Select the affected ordinary Shipping UI tests only")
    parser.add_argument("tests", nargs="*")
    args = parser.parse_args()
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
        controlled_source_https(output)
        if args.controlled_source_https
        else nullcontext((Path("/etc/ssl/certs/ca-certificates.crt"), {}))
    )
    with external as (source_trust, external_fixture):
        return _run(args, output, source_trust, external_fixture)


def _run(args: argparse.Namespace, output: Path, source_trust: Path, external_fixture: dict[str, Any]) -> int:
    operation = os.environ["ONLYALPHA_DEV_VERIFICATION_OPERATION_ID"]
    dsn = os.environ["ONLYALPHA_POSTGRES_DSN"]
    only_assert_postgres_test_database(dsn)
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    subprocess.run([sys.executable, "-m", "scripts.database", "migrate"], cwd=ROOT, check=True)
    data = output / "user-data"
    for relative in ("backtest/evidence", "secrets"):
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
    # Infrastructure provisioning uses the same selected native owner as deployment.
    # This establishes no Factor, Study, Runtime Generation, Dataset or Research Run.
    from scripts.database import _initialize_deployment

    _initialize_deployment(dsn, data, executable)
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
    only_assert_clickhouse_test_database(database)
    ch = OnlyClickHouseClient(
        OnlyClickHouseConfig(
            os.environ["ONLYALPHA_TEST_CLICKHOUSE_URL"],
            database=database,
            user=os.environ["ONLYALPHA_TEST_CLICKHOUSE_USER"],
            password=os.environ["ONLYALPHA_TEST_CLICKHOUSE_PASSWORD"],
            storage_policy=os.environ["ONLYALPHA_TEST_CLICKHOUSE_STORAGE_POLICY"],
        )
    )
    OnlyClickHouseMigrationAuthority(ch).migrate()
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

    def run_host(phase: str, agent_pid: int | None = None) -> int:
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
                            "ONLYALPHA_BROWSER_CONTROLLED_SOURCE_HTTPS": "1" if args.controlled_source_https else "0",
                            "ONLYALPHA_BROWSER_HOST_PID": str(child.pid),
                            "ONLYALPHA_BROWSER_USER_DATA_ROOT": str(data),
                            "ONLYALPHA_BROWSER_AGENT_PID": str(agent_pid or ""),
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

    try:
        if args.agent:
            with agent_database(dsn, output, data, resources / "agent") as agent_root:
                with running_agent(agent_root, resources / "agent", output) as agent:
                    result = run_host("initial", agent.pid)
                if result == 0 and args.restart_check:
                    restarted = output / "after-restart"
                    restarted.mkdir(exist_ok=True)
                    with running_agent(agent_root, resources / "agent", restarted) as agent:
                        result = run_host("restored", agent.pid)
        else:
            result = run_host("initial")
            if result == 0 and args.restart_check:
                result = run_host("restored")
        return result
    finally:
        ch.execute(f"DROP DATABASE IF EXISTS {database} SYNC", database="default")


if __name__ == "__main__":
    raise SystemExit(main())
