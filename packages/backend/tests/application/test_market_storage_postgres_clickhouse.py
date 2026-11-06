"""Native PG/CH storage capability, controlled technical fixtures only; no UI claim."""

from __future__ import annotations

import base64
import functools
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import struct
import subprocess
import threading
import tomllib
import urllib.parse
import urllib.request
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

import psycopg
import pytest
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_payload

from packages.backend.tests.application.support.native_research_market_fixture import (
    MarketStorageInputs,
    strategy_preparation_case,
)
from packages.backend.tests.application.support.native_research_market_fixture import (
    market_database as native_market_database,
)
from packages.backend.tests.application.test_runtime_installation_postgres import (
    native_environment_case as native_environment_case,
)
from scripts.native_http_contract import native_executable

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.clickhouse, pytest.mark.timeout(120)]
AT = datetime(2026, 10, 22, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[4]


@functools.cache
def _build_market_probe(*, release: bool = False) -> Path:
    # A formal frozen-source process can prepare this producer before pytest's
    # scenario budget, then reuse that same build. Never reuse a persisted binary.
    from scripts.rust_kernel_check import compiler_environment, prepare_cargo_home

    target = {"aarch64": "aarch64-unknown-linux-gnu", "x86_64": "x86_64-unknown-linux-gnu"}[platform.machine()]
    output = ROOT / "test-results/rust-kernel/target"
    env = compiler_environment(os.environ, output)
    env["RUSTUP_TOOLCHAIN"] = tomllib.loads((ROOT / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
    prepare_cargo_home(Path("/usr/local/cargo/registry"), Path(env["CARGO_HOME"]))
    subprocess.run(
        [
            "cargo",
            "build",
            "--frozen",
            "--offline",
            *(["--release"] if release else []),
            "--target",
            target,
            "-j1",
            "-p",
            "onlyalpha-backend",
            "--example",
            "command-postgres-probe",
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )
    return output / target / ("release" if release else "debug") / "examples/command-postgres-probe"


@pytest.fixture(scope="session")
def market_probe() -> Path:
    # Ordinary DB/storage tests retain their original dev producer.
    return _build_market_probe()


@dataclass(frozen=True)
class ClickHouseObservations(MarketStorageInputs):
    """SQL is only setup/fault injection or independent physical observation."""

    def execute(self, sql: str) -> bytes:
        assert self.config.database.startswith("onlyalpha_test_")
        separator = "&" if "?" in self.config.url else "?"
        url = self.config.url + separator + urllib.parse.urlencode({"database": self.config.database})
        authorization = base64.b64encode(f"{self.config.user}:{self.config.password}".encode()).decode()
        request = urllib.request.Request(url, data=sql.encode(), headers={"Authorization": "Basic " + authorization})
        with urllib.request.urlopen(request, timeout=5) as response:
            return cast(bytes, response.read())

    def query_json(self, sql: str) -> tuple[dict[str, Any], ...]:
        raw = self.execute(sql + " FORMAT JSONEachRow")
        return tuple(json.loads(line) for line in raw.splitlines())


@contextmanager
def market_database(postgres_dsn: str) -> Iterator[ClickHouseObservations]:
    with native_market_database(postgres_dsn) as inputs:
        yield ClickHouseObservations(inputs.config)


@pytest.fixture
def database(postgres_dsn: str) -> Iterator[ClickHouseObservations]:
    with market_database(postgres_dsn) as client:
        yield client


def fixture(action: str, *, binary: Path | None = None, **values: Any) -> dict[str, Any]:
    # Transport only: all business IDs, Domain restoration, WAL and Dataset IO
    # below are performed by the shipping Rust owners in the existing probe.
    result = subprocess.run(
        [str(binary or _build_market_probe())],
        input=json.dumps(
            {"op": "market-storage", "request": {"op": "fixture", "action": action, "at": AT.isoformat(), **values}}
        ),
        text=True,
        capture_output=True,
        timeout=30,
        check=True,
    )
    record = cast(dict[str, Any], json.loads(result.stdout))
    assert "error" not in record, (record, result.stderr)
    return record


def _scope_payload(segment: dict[str, Any]) -> dict[str, Any]:
    return {
        key: segment[key]
        for key in (
            "source_id",
            "market",
            "instrument_id",
            "data_kind",
            "start_ns",
            "end_ns",
            "data_version",
            "bar_type",
            "first_sequence",
            "last_sequence",
            "bar_construction",
        )
    }


def _quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


# Independent physical proof observer: exact durable schema column order and tags.
# The SQL evaluates all columns, including zero-row partitions, not record_hash alone.
_PHYSICAL_COLUMNS = {
    "market_raw_event": (
        ("raw_event_id", "S"),
        ("source_id", "S"),
        ("provider", "S"),
        ("venue", "S"),
        ("market", "S"),
        ("stream", "S"),
        ("capture_session_id", "S"),
        ("segment_id", "S"),
        ("segment_content_hash", "S"),
        ("record_ordinal", "I"),
        ("provider_event_type", "S"),
        ("provider_event_id", "S"),
        ("provider_sequence", "I"),
        ("ts_event_ns", "I"),
        ("ts_receive_ns", "I"),
        ("ts_ingest_ns", "I"),
        ("payload_codec", "S"),
        ("provider_schema", "S"),
        ("integration_binding_fingerprint", "S"),
        ("provenance", "S"),
        ("raw_payload_base64", "S"),
        ("raw_sha256", "S"),
        ("record_hash", "S"),
    ),
    "market_trade": (
        ("canonical_fact_id", "S"),
        ("source_id", "S"),
        ("instrument_id", "S"),
        ("segment_id", "S"),
        ("segment_content_hash", "S"),
        ("capture_session_id", "S"),
        ("raw_event_id", "S"),
        ("provider_event_id", "S"),
        ("provider_sequence", "I"),
        ("ts_event_ns", "I"),
        ("ts_receive_ns", "I"),
        ("ts_ingest_ns", "I"),
        ("price", "D"),
        ("price_precision", "I"),
        ("quantity", "D"),
        ("quantity_precision", "I"),
        ("aggressor_side", "S"),
        ("provenance", "S"),
        ("quality_state", "S"),
        ("canonical_payload_json", "S"),
        ("canonical_payload_hash", "S"),
        ("normalizer_id", "S"),
        ("normalizer_version", "S"),
        ("record_hash", "S"),
    ),
    "market_bar": (
        ("canonical_fact_id", "S"),
        ("source_id", "S"),
        ("instrument_id", "S"),
        ("segment_id", "S"),
        ("segment_content_hash", "S"),
        ("capture_session_id", "S"),
        ("raw_event_id", "S"),
        ("ts_event_ns", "I"),
        ("ts_receive_ns", "I"),
        ("ts_ingest_ns", "I"),
        ("bar_start_ns", "I"),
        ("bar_end_ns", "I"),
        ("bar_type_json", "S"),
        ("open", "D"),
        ("high", "D"),
        ("low", "D"),
        ("close", "D"),
        ("price_precision", "I"),
        ("volume", "D"),
        ("quantity_precision", "I"),
        ("quote_volume", "D"),
        ("trade_count", "I"),
        ("provenance", "S"),
        ("quality_state", "S"),
        ("canonical_payload_json", "S"),
        ("canonical_payload_hash", "S"),
        ("normalizer_id", "S"),
        ("normalizer_version", "S"),
        ("record_hash", "S"),
    ),
    "market_reference_price": (
        ("canonical_fact_id", "S"),
        ("source_id", "S"),
        ("instrument_id", "S"),
        ("segment_id", "S"),
        ("segment_content_hash", "S"),
        ("capture_session_id", "S"),
        ("raw_event_id", "S"),
        ("ts_event_ns", "I"),
        ("ts_receive_ns", "I"),
        ("ts_ingest_ns", "I"),
        ("reference_kind", "S"),
        ("price", "D"),
        ("price_precision", "I"),
        ("provenance", "S"),
        ("quality_state", "S"),
        ("canonical_payload_json", "S"),
        ("canonical_payload_hash", "S"),
        ("normalizer_id", "S"),
        ("normalizer_version", "S"),
        ("record_hash", "S"),
    ),
}


def _physical_row_sql(table: str) -> str:
    parts = []
    for column, tag in _PHYSICAL_COLUMNS[table]:
        rendered = f"toString({column})"
        parts.append(f"if(isNull({column}), '{tag}N', concat('{tag}V', toString(length({rendered})), ':', {rendered}))")
    return "concat(" + ", ".join(parts) + ")"


def _assert_physical_inputs(
    client: ClickHouseObservations, segment: dict[str, Any], records: list[dict[str, Any]]
) -> None:
    """Independent OAMD-to-column assertions; never writes a market fact."""
    from decimal import Decimal

    expected: dict[str, list[dict[str, Any]]] = {table: [] for table in _PHYSICAL_COLUMNS}
    for ordinal, bundle in enumerate(records):
        evidence, facts = bundle["evidence"], bundle["canonical_facts"]
        raw = {
            key: evidence[key]
            for key in (
                "raw_event_id",
                "source_id",
                "provider",
                "venue",
                "market",
                "stream",
                "capture_session_id",
                "provider_event_type",
                "provider_event_id",
                "provider_sequence",
                "ts_event_ns",
                "ts_receive_ns",
                "payload_codec",
                "provider_schema",
                "provenance",
                "raw_sha256",
            )
        }
        raw.update(
            segment_id=segment["segment_id"],
            segment_content_hash=segment["content_hash"],
            record_ordinal=ordinal,
            ts_ingest_ns=min((fact["ts_ingest_ns"] for fact in facts), default=evidence["ts_receive_ns"]),
            raw_payload_base64=evidence["payload_base64"],
        )
        if evidence.get("integration_binding_fingerprint") is not None:
            raw["integration_binding_fingerprint"] = evidence["integration_binding_fingerprint"]
        raw["record_hash"] = fixture("record-hash", row=raw)["fingerprint"]
        expected["market_raw_event"].append(raw)
        for fact in facts:
            payload = fact["canonical_payload"]["payload"]["value"]
            row = {
                key: fact[key]
                for key in (
                    "canonical_fact_id",
                    "source_id",
                    "instrument_id",
                    "segment_id",
                    "capture_session_id",
                    "raw_event_id",
                    "ts_event_ns",
                    "ts_receive_ns",
                    "ts_ingest_ns",
                    "provenance",
                    "quality_state",
                    "canonical_payload_hash",
                    "normalizer_id",
                    "normalizer_version",
                )
            }
            row.update(
                segment_content_hash=segment["content_hash"],
                canonical_payload_json=json.dumps(
                    fact["canonical_payload"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ),
            )
            if fact["data_kind"] == "BAR":
                for key in ("open", "high", "low", "close", "volume", "quote_volume"):
                    row[key] = None if payload[key] is None else payload[key]["value"]
                row.update(
                    price_precision=payload["open"]["precision"],
                    quantity_precision=payload["volume"]["precision"],
                    trade_count=payload["trade_count"],
                    bar_type_json=json.dumps(
                        payload["bar_type"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
                    ),
                )
                for key in ("bar_start", "bar_end"):
                    value = datetime.fromisoformat(payload[key]) - datetime(1970, 1, 1, tzinfo=UTC)
                    row[key + "_ns"] = (value.days * 86400 + value.seconds) * 1_000_000_000 + value.microseconds * 1000
                table = "market_bar"
            elif fact["data_kind"] == "TRADE":
                row.update(
                    price=payload["price"]["value"],
                    quantity=payload["quantity"]["value"],
                    price_precision=payload["price"]["precision"],
                    quantity_precision=payload["quantity"]["precision"],
                    provider_event_id=payload["trade_id"]["value"],
                    provider_sequence=payload["sequence"],
                    aggressor_side=payload["aggressor_side"],
                )
                table = "market_trade"
            else:
                assert fact["data_kind"] == "MARKET_REFERENCE"
                row.update(
                    reference_kind=payload["reference_kind"],
                    price=None if payload["price"] is None else payload["price"]["value"],
                    price_precision=None if payload["price"] is None else payload["price"]["precision"],
                )
                table = "market_reference_price"
            row["record_hash"] = fixture("record-hash", row=row)["fingerprint"]
            expected[table].append(row)
    for table, wanted in expected.items():
        actual = client.query_json(
            "SELECT * FROM "
            + table
            + " ORDER BY "
            + ("record_ordinal" if table == "market_raw_event" else "canonical_fact_id")
        )
        wanted.sort(key=lambda row: row.get("record_ordinal", row.get("canonical_fact_id")))
        assert len(actual) == len(wanted)
        for observed, original in zip(actual, wanted, strict=True):
            assert set(observed) == {column for column, _ in _PHYSICAL_COLUMNS[table]}
            for column, tag in _PHYSICAL_COLUMNS[table]:
                left, right = observed[column], original.get(column)
                if left is None or right is None:
                    assert left is right, (table, column)
                elif tag == "D":
                    assert Decimal(str(left)) == Decimal(str(right)), (table, column)
                elif tag == "I":
                    assert int(left) == int(right), (table, column)
                else:
                    assert left == right, (table, column)


def observed_frames(raw: bytes) -> tuple[dict[str, Any], ...]:
    # Independent framing observer, also safe while the real Rust writer owns
    # the live WAL. This does not construct or certify business identities.
    frames: list[dict[str, Any]] = []
    offset = 0
    while offset < len(raw):
        header = raw[offset : offset + 53]
        assert len(header) == 53 and header[:5] == b"OAMD\x01"
        length, ordinal = struct.unpack(">QQ", header[5:21])
        payload = raw[offset + 53 : offset + 53 + length]
        assert len(payload) == length and ordinal == len(frames)
        assert hashlib.sha256(payload).digest() == header[21:]
        frames.append(json.loads(payload))
        offset += 53 + length
    assert offset == len(raw)
    return tuple(frames)


def _strategy_probe_diagnostics(stderr: str | bytes | None) -> None:
    import sys

    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    # Only bounded static phase/line labels from the existing source diagnostics.
    # Never dump the request, stdout, environment, arbitrary child errors or IDs.
    for line in (stderr or "").splitlines()[-256:]:
        if re.fullmatch(
            r"\[strategy-(?:evaluation|evidence)\] (?:phase=[a-z][a-z0-9-]{0,63}|invalid line=[0-9]{1,10}|input-pin=[a-z][a-z0-9-]{0,63})",
            line,
        ):
            print(line, file=sys.stderr, flush=True)


def probe(
    binary: Path, client: ClickHouseObservations, op: str, *, process_timeout: int = 30, **values: Any
) -> dict[str, Any]:
    request = {"op": op, "at": AT.isoformat(), "database": client.config.database, "url": client.config.url, **values}
    env = dict(os.environ)
    env.update(ONLYALPHA_CLICKHOUSE_USER=client.config.user, ONLYALPHA_CLICKHOUSE_PASSWORD=client.config.password)
    try:
        result = subprocess.run(
            [str(binary)],
            input=json.dumps({"op": "market-storage", "request": request}),
            text=True,
            capture_output=True,
            timeout=process_timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as error:
        if op in {"strategy-evidence-phase", "strategy-worker-phase"}:
            _strategy_probe_diagnostics(error.stderr)
        raise
    assert result.returncode == 0, result.stderr
    parsed = cast(dict[str, Any], json.loads(result.stdout))
    if op == "strategy-evidence-phase" and "error" in parsed:
        # Preserve the exact returned error/old assertions and the same safe
        # phase surface for both ordinary errors and outer-harness timeouts.
        _strategy_probe_diagnostics(result.stderr)
    if op == "dataset-research" and "error" in parsed:
        parsed["worker_stderr"] = result.stderr
    return parsed


def test_retained_source_fixture_prepares_only_declared_market_inputs(
    market_probe: Path, database: ClickHouseObservations, postgres_dsn: str, tmp_path: Path
) -> None:
    """Technical precondition proof, never the Factor/Study/Research UI acceptance."""

    native = native_executable(release=False)
    tables = (
        "market_data_revision",
        "research_run",
        "private_factor_authoring_outcome",
        "factor_proposal_snapshot",
        "factor_study_snapshot",
        "research_factor_study_authorization",
    )

    def inventory() -> dict[str, int]:
        with psycopg.connect(postgres_dsn) as connection:
            return {name: connection.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in tables}

    before = inventory()
    result = probe(
        market_probe,
        database,
        "retained-source-prerequisite",
        user_data=str(tmp_path / "user-data"),
        selected_backend=str(native),
        selected_backend_sha256=hashlib.sha256(native.read_bytes()).hexdigest(),
        integration_id=str(uuid.uuid4()),
        create_command=str(uuid.uuid4()),
        publish_command=str(uuid.uuid4()),
        source_trust="/etc/ssl/certs/ca-certificates.crt",
    )
    assert "error" not in result, result
    assert inventory() == before
    assert result["source"]["expected_type_id"] == "binance.spot.market_data"
    assert result["source"]["source_id"] == "binance.spot.market_data.live"
    assert result["segment"]["data_version"] == "binance.spot.market_data@1.1"
    assert result["segment"]["canonical_count"] == 575
    assert int(result["last_event_ns"]) < int(result["protected_start_ns"])
    assert (
        result["source"]["integration_revision_fingerprint"]
        == result["segment"]["bar_construction"]["plan"]["integration_revision_fingerprint"]
    )
    assert result["binding_fingerprint"] == result["segment"]["integration_binding_fingerprint"]
    assert result["selected_backend_sha256"] == hashlib.sha256(native.read_bytes()).hexdigest()
    assert not (tmp_path / "user-data/research").exists()
    assert not (tmp_path / "user-data/runtime").exists()


def retained(
    root: Path,
    kind: str = "BAR",
    *,
    index: int = 0,
    segment_id: str = "retained",
    binding: str | None = None,
    raw_payload: bytes | None = None,
    updates: list[dict[str, Any]] | None = None,
) -> tuple[Path, dict[str, Any]]:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    history = json.loads((Path(__file__).parent / "fixtures/market_wal_history.json").read_text())
    specs = (
        updates if updates is not None else ([{"index": index}] if kind in {"BAR", "TRADE", "MARKET_REFERENCE"} else [])
    )
    result = fixture(
        "retained",
        root=str(root),
        id=segment_id,
        kind=kind,
        binding=binding,
        raw_payload_base64=None if raw_payload is None else base64.b64encode(raw_payload).decode(),
        bundle=json.loads(history["native_bundle_json"]),
        updates=specs,
    )
    return root, result["segment"]


def retained_records(root: Path, segment: dict[str, Any]) -> dict[str, Any]:
    return fixture("read", root=str(root), id=segment["segment_id"])


def drain(
    binary: Path, client: ClickHouseObservations, wal: Path, segment: dict[str, Any], **options: Any
) -> dict[str, Any]:
    scope = None if segment["canonical_count"] == 0 else _scope_payload(segment)
    return probe(binary, client, "drain", root=str(wal), ids=[segment["segment_id"]], scope=scope, **options)


@pytest.mark.parametrize("kind", ["BAR", "TRADE", "MARKET_REFERENCE", "RAW_ONLY", "RAW_BAR"])
def test_native_first_write_all_retained_families_and_exact_original_proofs(
    market_probe: Path, database: ClickHouseObservations, postgres_dsn: str, tmp_path: Path, kind: str
) -> None:
    wal, segment = retained(tmp_path, kind, index=0 if kind == "BAR" else 10)
    prepared = retained_records(wal, segment)
    records = prepared["records"]
    result = drain(market_probe, database, wal, segment)
    assert "error" not in result, result
    assert not list(tmp_path.glob("*.sealed.wal"))
    record = probe(market_probe, database, "segment", id=segment["segment_id"])
    reference = prepared
    assert record["proof"]["raw_count"] == segment["raw_count"] == len(records)
    assert (
        record["proof"]["canonical_count"]
        == segment["canonical_count"]
        == sum(len(row["canonical_facts"]) for row in records)
    )
    assert {part["table"] for part in record["proof"]["partitions"]} == {
        "market_raw_event",
        "market_trade",
        "market_bar",
        "market_reference_price",
    }
    assert len(record["proof"]["partitions"]) == 4
    if kind == "TRADE":
        assert database.query_json("SELECT provider_event_id FROM market_trade") == ({"provider_event_id": "10"},)
        assert records[0]["canonical_facts"][0]["canonical_payload"]["payload"]["value"]["trade_id"] == {
            "schema_version": 1,
            "value": "10",
        }
    _assert_physical_inputs(database, segment, records)
    for partition in record["proof"]["partitions"]:
        table = partition["table"]
        observed = database.query_json(
            "SELECT count() AS n, lower(hex(SHA256(arrayStringConcat(arraySort(groupArray("
            + _physical_row_sql(table)
            + ")),'')))) AS digest FROM "
            + table
        )[0]
        assert int(str(observed["n"])) == partition["row_count"]
        assert observed["digest"] == partition["row_set_digest"]
    assert record["proof"]["segment_metadata_fingerprint"] == reference["metadata_fingerprint"]
    assert record["segment"]["created_at"] == segment["created_at"]
    if kind in {"BAR", "TRADE"}:
        revision = result["revision"]
        read = probe(market_probe, database, "read", id=revision["revision_id"])
        assert read["facts"] == [records[0]["canonical_facts"][0]]
        assert read["manifest"]["fingerprint"] == reference["manifest"]["fingerprint"]
        assert read["revision"]["fingerprint"] == revision["fingerprint"]
    elif kind == "MARKET_REFERENCE":
        assert result["manifest"]["coverage_status"] == "UNPROVABLE"
        assert result["revision"] is None
    else:
        assert result["manifest"] is None


@pytest.mark.parametrize("kind", ["BAR", "TRADE"])
def test_original_published_proof_does_not_authorize_a_wrong_current_wal_projection(
    market_probe: Path, database: ClickHouseObservations, postgres_dsn: str, tmp_path: Path, kind: str
) -> None:
    wal, segment = retained(tmp_path, kind, index=0 if kind == "BAR" else 10)
    stopped = drain(market_probe, database, wal, segment, stop="CatalogCommitted")
    assert stopped == {"error": "MARKET_DATA_RECOVERY_STOPPED"}
    original = probe(market_probe, database, "segment", id=segment["segment_id"])
    # The retained current projection starts valid. Inject only the old invalid
    # TradeId column spelling as a controlled physical fault, never a Python writer.
    with psycopg.connect(postgres_dsn) as connection:
        revision_id, revision_fingerprint, manifest_id = connection.execute(
            "SELECT revision_id, revision_fingerprint, manifest_id FROM market_data_revision"
        ).fetchone()
        seal_id = connection.execute(
            "SELECT seal_id FROM market_revision_seal WHERE revision_id=%s", (revision_id,)
        ).fetchone()[0]
    read = probe(market_probe, database, "read", id=revision_id)
    assert "error" not in read
    assert read["revision"]["fingerprint"] == revision_fingerprint
    assert read["manifest"]["manifest_id"] == manifest_id
    assert read["seal"]["seal_id"] == seal_id
    proof_before = original["proof"]
    if kind == "TRADE":
        current = retained_records(wal, segment)
        bad_row = fixture("wrong-trade-row", segment=segment, fact=current["records"][0]["canonical_facts"][0])
        assert bad_row["provider_event_id"] == "{'schema_version': 1, 'value': '10'}"
        database.execute(
            "ALTER TABLE market_trade UPDATE provider_event_id="
            + _quote(bad_row["provider_event_id"])
            + ",record_hash="
            + _quote(bad_row["record_hash"])
            + " WHERE 1 SETTINGS mutations_sync=2"
        )
        # The historical proof is internally consistent with every bad physical
        # column, including the row hash. Only re-deriving the current WAL can
        # reject this state; a simple proof-vs-CH comparison must succeed.
        partitions = []
        for part in original["proof"]["partitions"]:
            table = part["table"]
            observed = database.query_json(
                "SELECT count() AS n, lower(hex(SHA256(arrayStringConcat(arraySort(groupArray("
                + _physical_row_sql(table)
                + ")),'')))) AS digest FROM "
                + table
            )[0]
            assert int(observed["n"]) == part["row_count"]
            partitions.append({"table": table, "row_count": int(observed["n"]), "row_set_digest": observed["digest"]})
        proof_before = fixture("physical-proof-record", segment=segment, partitions=partitions)
        assert proof_before != original["proof"]
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(
                "ALTER TABLE market_segment_physical_proof DISABLE TRIGGER market_segment_physical_proof_reject_mutation"
            )
            changed = connection.execute(
                "UPDATE market_segment_physical_proof SET proof_fingerprint=%s,proof=%s::jsonb WHERE segment_id=%s",
                (proof_before["fingerprint"], json.dumps(proof_before), segment["segment_id"]),
            )
            assert changed.rowcount == 1
            connection.execute(
                "ALTER TABLE market_segment_physical_proof ENABLE TRIGGER market_segment_physical_proof_reject_mutation"
            )
        accepted_history = probe(market_probe, database, "segment", id=segment["segment_id"])
        assert accepted_history == {"segment": original["segment"], "proof": proof_before}
        assert probe(market_probe, database, "read", id=revision_id) == read
    with psycopg.connect(postgres_dsn) as c:
        before = c.execute("SELECT to_jsonb(t) FROM market_data_revision t").fetchall()
    before_wal = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    before_physical = {
        table: database.query_json(f"SELECT * FROM {table}")
        for table in ("market_raw_event", "market_trade", "market_bar", "market_reference_price")
    }
    # Original immutable proof is necessary, but cannot waive current full-column
    # WAL projection integrity. Python's wrong TradeId display is not supported.
    recovered = probe(market_probe, database, "recover", root=str(tmp_path), startup=True)
    if kind == "TRADE":
        assert recovered == {"error": "MARKET_DATA_EVIDENCE_UNPROVABLE"}
        assert all((tmp_path / name).read_bytes() == raw for name, raw in before_wal.items())
        assert not list(tmp_path.glob("*.gc.*"))
    else:
        assert recovered == {"count": 1}, recovered
        assert not (tmp_path / f"{segment['segment_id']}.sealed.wal").exists()
    assert probe(market_probe, database, "segment", id=segment["segment_id"])["proof"] == proof_before
    assert {table: database.query_json(f"SELECT * FROM {table}") for table in before_physical} == before_physical

    with psycopg.connect(postgres_dsn) as c:
        assert c.execute("SELECT to_jsonb(t) FROM market_data_revision t").fetchall() == before


@pytest.mark.parametrize("stop", ["BeforeStore", "RawWritten", "StoreWritten", "Verified", "CatalogCommitted"])
def test_every_durable_boundary_preserves_recoverable_or_explicit_partial_state(
    market_probe: Path, database: ClickHouseObservations, tmp_path: Path, stop: str
) -> None:
    wal, segment = retained(tmp_path)
    stopped = drain(market_probe, database, wal, segment, stop=stop)
    assert stopped == {"error": "MARKET_DATA_RECOVERY_STOPPED"}
    assert (tmp_path / "retained.sealed.wal").exists()
    recovered = probe(market_probe, database, "recover", root=str(tmp_path), startup=True)
    if stop == "RawWritten":
        assert recovered == {"error": "MARKET_DATA_IDENTITY_CONFLICT"}
        assert (tmp_path / "retained.sealed.wal").exists()
    else:
        assert recovered == {"count": 1}, recovered
        assert not (tmp_path / "retained.sealed.wal").exists()


class DelayedOriginal:
    """Lose the first raw INSERT ACK, hold original dispatch until explicit barrier."""

    def __init__(self, target: str) -> None:
        self.target = target
        self.captured = threading.Event()
        self.release = threading.Event()
        self.committed = threading.Event()
        self.inserts = 0
        self.error: Exception | None = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:
                pass

            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers["Content-Length"]))
                is_insert = body.startswith(b"INSERT INTO market_raw_event")
                if is_insert:
                    owner.inserts += 1
                if is_insert and not owner.captured.is_set():
                    owner.captured.set()
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    if not owner.release.wait(20):
                        owner.error = RuntimeError("release barrier not reached")
                        return
                    try:
                        owner.forward(self.path, body, self.headers.get("Authorization"))
                    except Exception as error:
                        owner.error = error
                    finally:
                        owner.committed.set()
                    return
                try:
                    data = owner.forward(self.path, body, self.headers.get("Authorization"))
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except Exception:
                    self.send_error(502)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def forward(self, path: str, body: bytes, authorization: str | None) -> bytes:
        request = urllib.request.Request(self.target.rstrip("/") + path, data=body)
        if authorization:
            request.add_header("Authorization", authorization)
        with urllib.request.urlopen(request, timeout=10) as response:
            return cast(bytes, response.read())

    def close(self) -> None:
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def test_ambiguous_submit_then_absent_restart_never_resends_delayed_original(
    market_probe: Path, database: ClickHouseObservations, tmp_path: Path
) -> None:
    wal, segment = retained(tmp_path, "RAW_ONLY")
    delayed = DelayedOriginal(database.config.url)
    try:
        assert drain(market_probe, database, wal, segment, url=delayed.url) == {
            "error": "MARKET_DATA_SUBMISSION_UNKNOWN"
        }
        assert delayed.captured.is_set()
        assert int(str(database.query_json("SELECT count() AS n FROM market_raw_event")[0]["n"])) == 0
        # Fresh native process/connection; no volatile knowledge of original send.
        assert drain(market_probe, database, wal, segment, url=delayed.url) == {
            "error": "MARKET_DATA_SUBMISSION_UNKNOWN"
        }
        assert delayed.inserts == 1
        delayed.release.set()
        assert delayed.committed.wait(10), "original completion barrier"
        assert delayed.error is None
        assert int(str(database.query_json("SELECT count() AS n FROM market_raw_event")[0]["n"])) == 1
        result = drain(market_probe, database, wal, segment, url=delayed.url)
        assert "error" not in result, result
        assert delayed.inserts == 1
    finally:
        delayed.close()


def test_intent_preserves_admission_occurrences_and_reuses_complete_history_from_older_binding(
    market_probe: Path, database: ClickHouseObservations, postgres_dsn: str, tmp_path: Path
) -> None:
    wal, segment = retained(tmp_path)
    scope = _scope_payload(segment)
    intent = probe(market_probe, database, "intent", scope=scope, provenance="REST_BACKFILL", binding="b" * 64)
    assert intent["admitted_at"] == AT.isoformat()
    assert (
        probe(
            market_probe,
            database,
            "intent",
            scope=scope,
            provenance="REST_BACKFILL",
            binding="b" * 64,
            at=(AT + timedelta(hours=1)).isoformat(),
        )
        == intent
    )
    first = probe(market_probe, database, "lease-busy", id=intent["acquisition_id"])
    assert first["outcome"] is None and first["attempt_number"] == 1
    resumed = probe(market_probe, database, "lease-start", id=intent["acquisition_id"])
    assert resumed["attempt_number"] == 2 and resumed["outcome"] is None
    failed = probe(
        market_probe, database, "failure", id=intent["acquisition_id"], detail="explicit controlled provider failure"
    )
    assert failed["outcome"] == "FAILED"
    second = probe(market_probe, database, "lease-start", id=intent["acquisition_id"])
    assert second["attempt_number"] == 3 and second["attempt_id"] != first["attempt_id"]
    result = drain(market_probe, database, wal, segment)
    completed = probe(
        market_probe,
        database,
        "complete",
        id=intent["acquisition_id"],
        revision_id=result["revision"]["revision_id"],
        detail="exact complete sealed scope",
    )
    assert completed["outcome"] == "COMPLETE"
    assert completed["started_at"] == second["started_at"]
    with psycopg.connect(postgres_dsn) as c:
        assert c.execute("SELECT count(*) FROM market_data_acquisition_attempt").fetchone() == (3,)
        assert c.execute("SELECT count(*) FROM market_data_acquisition_attempt_outcome").fetchone() == (2,)
        assert c.execute(
            "SELECT count(*) FROM market_data_acquisition_attempt_outcome WHERE attempt_id=%s", (first["attempt_id"],)
        ).fetchone() == (0,)


@pytest.mark.parametrize(
    "case",
    [
        "missing-proof",
        "missing-zero-partition",
        "source-owner",
        "nested-construction",
        "whole-context",
        "manifest-ref",
        "duplicate-ordinal",
        "complete-different-scope",
    ],
)
def test_selected_owner_and_relation_mutations_fail_closed(
    market_probe: Path, database: ClickHouseObservations, postgres_dsn: str, tmp_path: Path, case: str
) -> None:
    wal, segment = retained(tmp_path)
    result = drain(market_probe, database, wal, segment)
    rid = result["revision"]["revision_id"]
    with psycopg.connect(postgres_dsn) as c:
        if case == "missing-proof":
            c.execute(
                "ALTER TABLE market_segment_physical_proof DISABLE TRIGGER market_segment_physical_proof_reject_mutation"
            )
            c.execute("DELETE FROM market_segment_physical_proof")
        elif case == "missing-zero-partition":
            c.execute(
                "ALTER TABLE market_segment_physical_proof DISABLE TRIGGER market_segment_physical_proof_reject_mutation"
            )
            c.execute(
                "UPDATE market_segment_physical_proof SET proof=jsonb_set(proof,'{partitions}',(proof->'partitions')-0)"
            )
        elif case == "source-owner":
            c.execute("ALTER TABLE market_source DISABLE TRIGGER market_source_reject_mutation")
            c.execute("UPDATE market_source SET provider='foreign'")
        elif case == "nested-construction":
            c.execute("ALTER TABLE market_data_revision DISABLE TRIGGER market_data_revision_reject_mutation")
            c.execute("UPDATE market_data_revision SET scope=scope #- '{bar_construction,plan,source_id}'")
        elif case == "whole-context":
            c.execute("ALTER TABLE market_data_revision DISABLE TRIGGER market_data_revision_reject_mutation")
            c.execute("UPDATE market_data_revision SET scope='{}'::jsonb")
        elif case == "manifest-ref":
            c.execute(
                "ALTER TABLE market_coverage_manifest_segment DISABLE TRIGGER market_coverage_manifest_segment_reject_mutation"
            )
            c.execute("DELETE FROM market_coverage_manifest_segment")
        elif case == "duplicate-ordinal":
            c.execute("ALTER TABLE market_revision_segment DISABLE TRIGGER market_revision_segment_reject_mutation")
            c.execute("UPDATE market_revision_segment SET ordinal=3")
        elif case == "complete-different-scope":
            c.execute("ALTER TABLE market_data_revision DISABLE TRIGGER market_data_revision_reject_mutation")
            c.execute(
                "UPDATE market_data_revision SET scope=jsonb_set(scope,'{end_ns}',to_jsonb((scope->>'end_ns')::bigint+60000000000))"
            )
    assert "error" in probe(market_probe, database, "read", id=rid)
    scope = _scope_payload(segment)
    range_result = probe(market_probe, database, "range", scope=scope, intervals=[[scope["start_ns"], scope["end_ns"]]])
    assert "error" in range_result


def test_physical_column_corruption_is_not_hidden_by_payload_or_record_hash(
    market_probe: Path, database: ClickHouseObservations, tmp_path: Path
) -> None:
    wal, segment = retained(tmp_path)
    result = drain(market_probe, database, wal, segment)
    database.execute(
        "ALTER TABLE market_bar UPDATE close=close+1 WHERE segment_id='retained' SETTINGS mutations_sync=2"
    )
    assert probe(market_probe, database, "read", id=result["revision"]["revision_id"]) == {
        "error": "MARKET_DATA_EVIDENCE_UNPROVABLE"
    }


def test_range_membership_excludes_unrelated_overlapping_segment(
    market_probe: Path, database: ClickHouseObservations, tmp_path: Path
) -> None:
    first_wal, first = retained(tmp_path / "first", index=0, segment_id="first")
    first_result = drain(market_probe, database, first_wal, first)
    second_wal, second = retained(tmp_path / "second", index=1, segment_id="second")
    assert first["start_ns"] is not None
    wider = _scope_payload({**second, "start_ns": first["start_ns"]})
    incomplete = probe(market_probe, database, "drain", root=str(second_wal), ids=[second["segment_id"]], scope=wider)
    assert incomplete["manifest"]["coverage_status"] == "INCOMPLETE"
    scope = _scope_payload(first)
    queried = probe(market_probe, database, "range", scope=scope, intervals=[[first["start_ns"], second["end_ns"]]])
    assert queried["status"] == "INCOMPLETE" and queried["facts"] == []
    assert len(queried["evidence"]) == 1
    assert queried["evidence"][0]["revision_id"] == first_result["revision"]["revision_id"]
    assert queried["gaps"] == [{"start_ns": first["end_ns"], "end_ns": second["end_ns"]}]


@pytest.mark.parametrize(
    "state",
    [
        "stage-prefix",
        "marked",
        "moved",
        "metadata-removed",
        "content-removed",
        "missing-marker",
        "wrong-hash",
        "missing-coverage",
    ],
)
def test_real_gc_restart_requires_exact_physical_and_applicable_catalog_authority(
    market_probe: Path, database: ClickHouseObservations, postgres_dsn: str, tmp_path: Path, state: str
) -> None:
    wal, segment = retained(tmp_path)
    assert drain(market_probe, database, wal, segment, stop="CatalogCommitted") == {
        "error": "MARKET_DATA_RECOVERY_STOPPED"
    }
    marker = json.dumps(
        {"schema_version": 1, "segment_id": segment["segment_id"], "content_hash": segment["content_hash"]},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    if state == "stage-prefix":
        (tmp_path / "retained.gc.json.tmp").write_bytes(marker[:20])
    elif state == "wrong-hash":
        (tmp_path / "retained.gc.json").write_bytes(marker.replace(segment["content_hash"].encode(), b"a" * 64))
    else:
        (tmp_path / "retained.gc.json").write_bytes(marker)
    if state in {"moved", "metadata-removed", "content-removed", "missing-marker"}:
        (tmp_path / "retained.sealed.wal").rename(tmp_path / "retained.gc.wal")
    if state in {"metadata-removed", "content-removed"}:
        (tmp_path / "retained.segment.json").unlink()
    if state == "content-removed":
        (tmp_path / "retained.gc.wal").unlink()
    if state == "missing-marker":
        (tmp_path / "retained.gc.json").unlink()
    if state == "missing-coverage":
        with psycopg.connect(postgres_dsn) as c:
            c.execute("ALTER TABLE market_revision_seal DISABLE TRIGGER market_revision_seal_reject_mutation")
            c.execute("DELETE FROM market_revision_seal")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    result = probe(market_probe, database, "recover", root=str(tmp_path), startup=True)
    if state in {"missing-marker", "wrong-hash", "missing-coverage"}:
        assert "error" in result
        assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before
    else:
        assert result == {"count": 0}, result
        assert sorted(p.name for p in tmp_path.iterdir()) == [".writer.lock"]


class RecorderBarrierProxy:
    def __init__(self, target: str, root: Path) -> None:
        self.appended = threading.Event()
        self.release = threading.Event()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:
                pass

            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers["Content-Length"]))
                if body.startswith(b"INSERT INTO market_raw_event"):
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as control:
                        control.settimeout(10)
                        control.connect(str(root / "recorder-control.sock"))
                        control.sendall(b"G")
                        assert control.recv(1) == b"A"
                    owner.appended.set()
                    assert owner.release.wait(20), "physical write release barrier"
                request = urllib.request.Request(target.rstrip("/") + self.path, data=body)
                if token := self.headers.get("Authorization"):
                    request.add_header("Authorization", token)
                with urllib.request.urlopen(request, timeout=10) as response:
                    data = response.read()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def close(self) -> None:
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def test_real_pending_drain_does_not_block_recording_or_consume_live_open_segment(
    market_probe: Path, database: ClickHouseObservations, postgres_dsn: str, tmp_path: Path
) -> None:
    wal, segment = retained(tmp_path)
    bundle = json.loads(json.dumps(retained_records(wal, segment)["records"][0]))
    bundle["canonical_facts"] = []
    proxy = RecorderBarrierProxy(database.config.url, tmp_path)
    child = None
    try:
        request = {
            "op": "drain-record",
            "root": str(tmp_path),
            "scope": _scope_payload(segment),
            "ids": [segment["segment_id"]],
            "live_bundle": bundle,
            "at": AT.isoformat(),
            "url": proxy.url,
            "database": database.config.database,
        }
        env = dict(
            os.environ,
            ONLYALPHA_CLICKHOUSE_USER=database.config.user,
            ONLYALPHA_CLICKHOUSE_PASSWORD=database.config.password,
        )
        child = subprocess.Popen(
            [str(market_probe)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        assert child.stdin is not None
        child.stdin.write(json.dumps({"op": "market-storage", "request": request}))
        child.stdin.close()
        child.stdin = None
        assert proxy.appended.wait(15), "recorder completed two durable appends while physical request is held"
        assert child.poll() is None, "drain must still await the controlled physical request"
        frames = tuple(observed_frames((tmp_path / "live.open.wal").read_bytes()))
        assert len(frames) == 2
        assert not (tmp_path / "live.segment.json").exists()
        with psycopg.connect(postgres_dsn) as c:
            assert c.execute("SELECT count(*) FROM market_ingest_segment").fetchone() == (0,)
            assert c.execute(
                "SELECT count(*) FROM market_recovery_event WHERE outcome='STORE_SUBMISSION_STARTED'"
            ).fetchone() == (1,)
        proxy.release.set()
        output, error = child.communicate(timeout=20)
        assert child.returncode == 0, error
        result = json.loads(output)
        assert result["appended"] is True and result["live_open"] is True
        assert not (tmp_path / "retained.sealed.wal").exists()
        assert len(tuple(observed_frames((tmp_path / "live.open.wal").read_bytes()))) == 2
    finally:
        proxy.release.set()
        if child is not None and child.poll() is None:
            child.kill()
            child.communicate(timeout=5)
        proxy.close()


def test_operation_cumulative_budget_fails_before_dispatch_and_does_not_certify_empty(
    market_probe: Path, database: ClickHouseObservations, postgres_dsn: str, tmp_path: Path
) -> None:
    first, a = retained(tmp_path, segment_id="a", raw_payload=b"x" * 6000)
    second, b = retained(tmp_path, segment_id="b", raw_payload=b"x" * 6000)
    budget = 20000
    # Each isolated segment fits; two retained payloads exceed the same bound.
    for wal, segment in ((first, a), (second, b)):
        result = drain(market_probe, database, wal, segment, max_bytes=budget, stop="BeforeStore")
        assert result == {"error": "MARKET_DATA_RECOVERY_STOPPED"}
    request: dict[str, Any] = dict(root=str(tmp_path), ids=[a["segment_id"], b["segment_id"]], scope=_scope_payload(a))
    assert probe(market_probe, database, "drain", max_bytes=budget, **request) == {
        "error": "MARKET_DATA_STORE_UNAVAILABLE"
    }
    with psycopg.connect(postgres_dsn) as c:
        assert c.execute("SELECT count(*) FROM market_recovery_event").fetchone() == (0,)
    assert int(str(database.query_json("SELECT count() AS n FROM market_raw_event")[0]["n"])) == 0
    assert (tmp_path / "a.sealed.wal").exists() and (tmp_path / "b.sealed.wal").exists()
    result = probe(market_probe, database, "drain", **request)
    assert result["revision"] is not None
    assert probe(market_probe, database, "read", id=result["revision"]["revision_id"], max_bytes=budget) == {
        "error": "MARKET_DATA_STORE_UNAVAILABLE"
    }


def test_native_empty_raw_payload_is_a_physical_value(
    market_probe: Path, database: ClickHouseObservations, tmp_path: Path
) -> None:
    wal, segment = retained(tmp_path, "RAW_ONLY", raw_payload=b"")
    result = drain(market_probe, database, wal, segment)
    assert "error" not in result
    assert database.query_json("SELECT raw_payload_base64 FROM market_raw_event") == ({"raw_payload_base64": ""},)


def test_old_gc_history_and_current_binding_gap_compose_exact_success_without_producer_equality(
    market_probe: Path, database: ClickHouseObservations, postgres_dsn: str, tmp_path: Path
) -> None:
    old_wal, old = retained(tmp_path / "old", index=0, segment_id="old")
    old_result = drain(market_probe, database, old_wal, old)
    assert old_result["revision"] is not None
    assert not (old_wal / "old.sealed.wal").exists()
    new_wal, new = retained(tmp_path / "new", index=1, segment_id="new", binding="b" * 64)
    assert old["integration_binding_fingerprint"] is None and new["integration_binding_fingerprint"] == "b" * 64
    assert new["end_ns"] is not None
    scope = _scope_payload({**old, "end_ns": new["end_ns"]})
    intent = probe(market_probe, database, "intent", scope=scope, provenance="REST_BACKFILL", binding="b" * 64)
    probe(market_probe, database, "lease-start", id=intent["acquisition_id"])
    new_result = drain(market_probe, database, new_wal, new)
    assert new_result["revision"] is not None
    assert probe(
        market_probe,
        database,
        "complete",
        id=intent["acquisition_id"],
        revision_id=new_result["revision"]["revision_id"],
        detail="unrelated incomplete requested coverage",
    ) == {"error": "MARKET_DATA_EVIDENCE_UNPROVABLE"}
    references = sorted([[old["segment_id"], old["content_hash"]], [new["segment_id"], new["content_hash"]]])
    result = probe(market_probe, database, "compose", scope=scope, refs=references)
    assert result["manifest"]["coverage_status"] == "COMPLETE"
    assert result["revision"]["segment_refs"] == references
    read = probe(market_probe, database, "read", id=result["revision"]["revision_id"])
    assert len(read["facts"]) == 2
    complete = probe(
        market_probe,
        database,
        "complete",
        id=intent["acquisition_id"],
        revision_id=result["revision"]["revision_id"],
        detail="old history plus exact current gap",
    )
    assert complete["outcome"] == "COMPLETE"
    assert not list(old_wal.glob("*.sealed.wal")) and not list(new_wal.glob("*.sealed.wal"))
    wrong = [references[0], references[1].copy()]
    wrong[1][1] = "f" * 64
    assert probe(market_probe, database, "compose", scope=scope, refs=wrong) == {
        "error": "MARKET_DATA_EVIDENCE_UNPROVABLE"
    }
    assert probe(market_probe, database, "compose", scope=scope, refs=[references[0], references[0]]) == {
        "error": "MARKET_DATA_EVIDENCE_UNPROVABLE"
    }
    assert probe(market_probe, database, "compose", scope=scope, refs=references, max_bytes=2000) == {
        "error": "MARKET_DATA_STORE_UNAVAILABLE"
    }
    foreign_wal, foreign = retained(tmp_path / "foreign", "TRADE", index=10, segment_id="foreign")
    drain(market_probe, database, foreign_wal, foreign)
    wrong_family = sorted([references[0], [foreign["segment_id"], foreign["content_hash"]]])
    assert probe(market_probe, database, "compose", scope=scope, refs=wrong_family) == {
        "error": "MARKET_DATA_EVIDENCE_UNPROVABLE"
    }
    with psycopg.connect(postgres_dsn) as c:
        count = c.execute("SELECT count(*) FROM market_data_revision").fetchone()
        c.execute(
            "ALTER TABLE market_segment_physical_proof DISABLE TRIGGER market_segment_physical_proof_reject_mutation"
        )
        c.execute("DELETE FROM market_segment_physical_proof WHERE segment_id=%s", (old["segment_id"],))
    assert probe(market_probe, database, "compose", scope=scope, refs=references) == {
        "error": "MARKET_DATA_EVIDENCE_UNPROVABLE"
    }
    with psycopg.connect(postgres_dsn) as c:
        assert c.execute("SELECT count(*) FROM market_data_revision").fetchone() == count


def test_range_query_explicitly_rejects_non_bar_family(
    market_probe: Path, database: ClickHouseObservations, tmp_path: Path
) -> None:
    _wal, segment = retained(tmp_path, "TRADE", index=10)
    scope = _scope_payload(segment)
    assert probe(market_probe, database, "range", scope=scope, intervals=[[scope["start_ns"], scope["end_ns"]]]) == {
        "error": "MARKET_DATA_INPUT_INVALID"
    }


def test_latest_exact_family_selects_stored_metadata_and_never_falls_back_from_bad_latest(
    market_probe: Path, database: ClickHouseObservations, tmp_path: Path
) -> None:
    old_wal, old = retained(tmp_path / "old", index=0, segment_id="old")
    family = _scope_payload(old)
    assert probe(market_probe, database, "latest", scope=family) == {"error": "SEALED_REVISION_NOT_FOUND"}
    first = drain(market_probe, database, old_wal, old)
    new_wal, new = retained(tmp_path / "new", index=1, segment_id="new")
    newest = drain(market_probe, database, new_wal, new)
    selected = probe(market_probe, database, "latest", scope=family)
    assert selected["revision"]["revision_id"] == newest["revision"]["revision_id"]
    assert selected["revision"]["revision_id"] != first["revision"]["revision_id"]
    assert len(selected["facts"]) == 1 and selected["facts"][0]["segment_id"] == new["segment_id"]
    database.execute("ALTER TABLE market_bar UPDATE close=close+1 WHERE segment_id='new' SETTINGS mutations_sync=2")
    assert probe(market_probe, database, "latest", scope=family) == {"error": "MARKET_DATA_EVIDENCE_UNPROVABLE"}


def test_unknown_occurrence_is_retained_when_a_new_execution_reacquires_the_exact_lease(
    market_probe: Path, database: ClickHouseObservations, postgres_dsn: str, tmp_path: Path
) -> None:
    _wal, segment = retained(tmp_path)
    intent = probe(
        market_probe,
        database,
        "intent",
        scope=_scope_payload(segment),
        provenance="REST_BACKFILL",
        binding="b" * 64,
    )
    first = probe(market_probe, database, "lease-start", id=intent["acquisition_id"])
    assert first["outcome"] is None
    second = probe(market_probe, database, "lease-start", id=intent["acquisition_id"])
    assert "error" not in second, second
    assert second["attempt_number"] == 2, second
    assert second["attempt_id"] != first["attempt_id"] and second["outcome"] is None
    with psycopg.connect(postgres_dsn) as c:
        assert c.execute("SELECT count(*) FROM market_data_acquisition_attempt").fetchone() == (2,)
        assert c.execute("SELECT count(*) FROM market_data_acquisition_attempt_outcome").fetchone() == (0,)
        assert c.execute(
            "SELECT attempt_id FROM market_data_acquisition_attempt WHERE attempt_number=1"
        ).fetchone() == (first["attempt_id"],)


def test_current_native_trade_published_before_gc_recovers_with_all_columns_exact(
    market_probe: Path, database: ClickHouseObservations, postgres_dsn: str, tmp_path: Path
) -> None:
    wal, segment = retained(tmp_path, "TRADE", index=10)
    assert drain(market_probe, database, wal, segment, stop="CatalogCommitted") == {
        "error": "MARKET_DATA_RECOVERY_STOPPED"
    }
    before = probe(market_probe, database, "segment", id=segment["segment_id"])
    assert database.query_json("SELECT provider_event_id FROM market_trade") == ({"provider_event_id": "10"},)
    assert (tmp_path / f"{segment['segment_id']}.sealed.wal").exists()
    assert probe(market_probe, database, "recover", root=str(tmp_path), startup=True) == {"count": 1}
    assert not (tmp_path / f"{segment['segment_id']}.sealed.wal").exists()
    assert probe(market_probe, database, "segment", id=segment["segment_id"]) == before


@pytest.mark.parametrize("case", ["complete", "duplicate", "conflict", "timestamp", "payload"])
def test_range_filters_intervals_only_after_whole_revision_proof(
    market_probe: Path, database: ClickHouseObservations, tmp_path: Path, case: str
) -> None:
    def sealed(name: str, updates: list[dict[str, Any]]) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
        wal, segment = retained(tmp_path / name, segment_id=name, updates=updates)
        facts = retained_records(wal, segment)["records"][0]["canonical_facts"]
        return wal, segment, facts

    wal, segment, facts = sealed("wide", [{"index": index} for index in range(3)])
    published = drain(market_probe, database, wal, segment)
    assert published["manifest"]["coverage_status"] == "COMPLETE"
    scope = _scope_payload(segment)
    start = scope["start_ns"]
    end = scope["end_ns"]
    assert isinstance(start, int) and isinstance(end, int)
    stride = (end - start) // 3
    intervals = [[start, start + stride], [start + 2 * stride, end]]
    if case in {"duplicate", "conflict"}:
        duplicate_wal, duplicate_segment, _ = sealed(
            "another", [{"index": 0, "close": "101.50000000" if case == "conflict" else "101.00000000"}]
        )
        assert (
            drain(market_probe, database, duplicate_wal, duplicate_segment)["manifest"]["coverage_status"] == "COMPLETE"
        )
    if case in {"timestamp", "payload"}:
        # This middle fact is outside both requested intervals but remains inside
        # the exact selected Revision, so its physical proof must still be read.
        payload = {**facts[1]["canonical_payload"], "ts_event": "malformed-timestamp"} if case == "timestamp" else {}
        mutation = "canonical_payload_json=" + _quote(
            json.dumps(only_canonical_payload(payload), sort_keys=True, separators=(",", ":"))
        )
        database.execute(
            f"ALTER TABLE market_bar UPDATE {mutation} WHERE segment_id='wide' AND ts_event_ns={start + 2 * stride} SETTINGS mutations_sync=2"
        )
    result = probe(market_probe, database, "range", scope=scope, intervals=list(reversed(intervals)))
    if case == "conflict":
        assert result == {"error": "MARKET_DATA_IDENTITY_CONFLICT"}
    elif case in {"timestamp", "payload"}:
        assert result == {"error": "MARKET_DATA_EVIDENCE_UNPROVABLE"}
    else:
        assert result["status"] == "COMPLETE"
        assert result["complete_intervals"] == result["expected"] == 2
        assert result["gaps"] == result["issues"] == []
        assert [fact["canonical_fact_id"] for fact in result["facts"]] == [
            facts[index]["canonical_fact_id"] for index in (0, 2)
        ]
        assert len(result["facts"]) == 2
        assert len(result["evidence"]) == (2 if case == "duplicate" else 1)


def test_native_sealed_dataset_materialization_matches_sdk_and_survives_ack_loss(
    market_probe: Path, database: ClickHouseObservations, postgres_dsn: str, tmp_path: Path
) -> None:
    wal_root = tmp_path / "wal"
    wal_root.mkdir()
    wal, segment = retained(wal_root, "BAR")
    reference = retained_records(wal, segment)
    bar = reference["records"][0]["canonical_facts"][0]["canonical_payload"]["payload"]["value"]
    sealed = drain(market_probe, database, wal, segment)
    assert "error" not in sealed, sealed
    scope = _scope_payload(segment)
    assert scope["bar_construction"] is not None
    first = datetime.fromisoformat(bar["ts_event"])
    definition = {
        "schema_version": 2,
        "dataset_type": "HISTORICAL_BAR",
        "instruments": [scope["instrument_id"]],
        "bar_semantic": scope["bar_construction"]["plan"]["target_semantic"],
        "time_range": {"start": first.isoformat(), "end": (first + timedelta(minutes=1)).isoformat()},
        "quality_policy": "STRICT",
        "closed_only": True,
    }
    revision = sealed["revision"]
    reference = fixture(
        "dataset-reference", definition=definition, scope=scope, revision=revision, seal=sealed["seal"], bars=[bar]
    )
    expected, request = reference["snapshot"], reference["request"]
    dataset_root = tmp_path / "datasets"
    dataset_root.mkdir()
    args = dict(
        id=revision["revision_id"],
        definition=definition,
        scope=_scope_payload(scope),
        dataset_root=str(dataset_root),
    )
    env = dict(os.environ)
    env.update(ONLYALPHA_CLICKHOUSE_USER=database.config.user, ONLYALPHA_CLICKHOUSE_PASSWORD=database.config.password)
    lost_ack = subprocess.run(
        [str(market_probe)],
        input=json.dumps(
            {
                "op": "market-storage",
                "request": {
                    "op": "dataset-materialize",
                    "at": AT.isoformat(),
                    "database": database.config.database,
                    "url": database.config.url,
                    **args,
                    "fault_after_dataset": True,
                },
            }
        ),
        text=True,
        capture_output=True,
        timeout=30,
        env=env,
    )
    assert lost_ack.returncode == 73, lost_ack.stderr
    assert lost_ack.stdout == ""
    original = probe(market_probe, database, "dataset-materialize", **args)
    assert "error" not in original, original
    assert original["snapshot"]["snapshot_fingerprint"] == expected
    assert original["lineage"]["materialization_id"] == reference["materialization"]

    def read_original() -> dict[str, Any]:
        return fixture(
            "dataset-read", dataset_root=str(dataset_root), materialization=original["lineage"]["materialization_id"]
        )

    restored = read_original()
    assert restored["bars"] == [bar]
    assert restored["lineage"]["request_fingerprint"] == request
    # Read actual immutable Parquet independently of the backend Dataset reader.
    import pyarrow.parquet as parquet

    files = list(dataset_root.glob("sha256/*/*/data/*.parquet"))
    assert len(files) == 1
    rows = parquet.read_table(files[0]).to_pylist()
    from decimal import Decimal

    assert [
        {
            key: format(value, "f")
            if isinstance(value, Decimal)
            else value.isoformat()
            if isinstance(value, datetime)
            else value.isoformat()
            if isinstance(value, date)
            else value
            for key, value in row.items()
        }
        for row in rows
    ] == reference["rows"]
    again = probe(market_probe, database, "dataset-materialize", **args)
    assert again == original
    # Existing immutable Snapshot stays readable when its physical source becomes
    # unprovable, but it cannot bless a new materialization from corrupt source.
    database.execute("ALTER TABLE market_bar UPDATE close = close + 1 WHERE 1 SETTINGS mutations_sync=2")
    refused = probe(market_probe, database, "dataset-materialize", **args)
    assert "error" in refused
    assert read_original()["bars"] == [bar]


@pytest.fixture(scope="session")
def native_research_algorithm_bundle(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, str]:
    from scripts.build_algorithm_sdk import install

    root = tmp_path_factory.mktemp("native-research-algorithms")
    wheels = root / "wheels"
    installation = root / "installed"
    artifact = install(wheels, installation)
    return wheels, installation, artifact


@pytest.fixture(scope="session")
def native_research_executor(market_probe: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Prepare the selected executable once; every Runtime still pins its bytes."""
    executable = tmp_path_factory.mktemp("native-research-executor") / "executor"
    shutil.copyfile(market_probe, executable)
    subprocess.run(["strip", "--strip-debug", str(executable)], check=True, timeout=30)
    executable.chmod(0o500)
    return executable


# 原生安装/发布/重定位专项已迁至独立模块；市场场景继续复用其受控安装前置条件。
@pytest.fixture(
    scope="module",
    params=[
        "normal",
        "queued-cancel",
        "stale-reentry",
        "cancel-empty",
        "cancel-complete",
        "cancel-partial",
        "cancel-corrupt",
        "heartbeat-unknown",
        "budget",
        "budget-with-result",
        "source-revoked",
        "wrong-native-version",
        "node-authority-loss",
    ],
)
def native_research_case(
    request: pytest.FixtureRequest,
    market_probe: Path,
    native_research_executor: Path,
    tmp_path_factory: pytest.TempPathFactory,
    native_research_algorithm_bundle: tuple[Path, Path, str],
) -> Iterator[dict[str, Any]]:
    from packages.backend.tests.postgres_fixtures import reset_postgres_test_namespace

    # The four stages share one guarded namespace, Command and Run. No stage
    # resets storage or silently executes an earlier missing stage.
    dsn = reset_postgres_test_namespace()
    with market_database(dsn) as database:
        case = prepare_native_research_case(
            market_probe,
            native_research_executor,
            database,
            dsn,
            tmp_path_factory.mktemp("native-research-" + request.param),
            request.param,
            native_research_algorithm_bundle,
        )
        yield case


def prepare_native_research_case(
    market_probe: Path,
    native_research_executor: Path,
    database: ClickHouseObservations,
    postgres_dsn: str,
    tmp_path: Path,
    mode: str,
    native_research_algorithm_bundle: tuple[Path, Path, str],
) -> dict[str, Any]:
    from uuid import uuid4

    from packages.backend.tests.application.support.research_admission_reference import build
    from packages.backend.tests.application.test_factor_proposals_postgres import call, grant, proposal

    # Existing C2 owning writer performs the first confirmation; no fixture SQL makes a Factor.
    _, token = grant(market_probe, postgres_dsn, owner="local-developer")
    candidate = proposal(market_probe, token)
    candidate["candidate"] = {
        "name": "收盘价观察",
        "purpose": "独立单次研究",
        "hypothesis": "fixture",
        "expression": {"input": "close"},
    }
    history = 0
    if mode == "normal":
        candidate["candidate"]["expression"] = json.loads(
            (ROOT / "packages/backend/tests/application/fixtures/research_factor.json").read_text()
        )["candidate"]["expression"]
        candidate["candidate"].update(name="放量动量", purpose="验证带历史窗口的真实算法闭包")
        history = 20
    staged = call(market_probe, "stage", token=token, body=candidate, actor="local-developer")
    # grant helper defaults to owner; establish the actual Human owner explicitly.
    if "error" in staged:
        raise AssertionError(staged)
    fp = staged["effect"]["proposal_fingerprint"]
    view = call(market_probe, "read", fingerprint=fp, actor="local-developer")
    accepted = call(
        market_probe, "confirm", actor="local-developer", body={"schema_version": 1, "proposal_fingerprint": fp}
    )
    assert "error" not in accepted, accepted
    command = str(uuid4())
    work_id = fixture("run-id", binary=market_probe, command=command)["run_id"]
    factor = build(
        tmp_path / "runtime",
        native_research_executor,
        work_id=work_id,
        candidate_record=candidate["candidate"],
        draft_record=view["snapshot"]["preview"]["draft"],
        algorithm_bundle=native_research_algorithm_bundle,
    )
    actual = tmp_path / "runtime/native-executor"
    semantic = tmp_path / "semantic"
    semantic.mkdir(mode=0o700)
    provision = probe(actual, database, "strategy-evidence-provision", semantic_root=str(semantic))
    assert "error" not in provision, provision
    research = semantic / "research"
    datasets = research / "datasets"
    projection = research / "experiment-memory"
    source_roots = provision["source_roots"]
    updates = [{"index": i, "close": f"{100 + (i % 7) * 0.12 + (i % 11) * 0.01:.8f}"} for i in range(128 + history)]
    wal, segment = retained(tmp_path / "wal", segment_id="research-input", updates=updates)
    assert "error" not in drain(actual, database, wal, segment)
    scope = _scope_payload(segment)
    composed = probe(
        actual,
        database,
        "compose",
        scope=_scope_payload(scope),
        refs=[(segment["segment_id"], segment["content_hash"])],
    )
    assert "error" not in composed, composed
    first = datetime.fromtimestamp(segment["start_ns"] // 1_000_000_000, UTC) + timedelta(minutes=1)
    end = first + timedelta(minutes=128 + history)
    definition = {
        "schema_version": 2,
        "dataset_type": "HISTORICAL_BAR",
        "instruments": [scope["instrument_id"]],
        "bar_semantic": scope["bar_construction"]["plan"]["target_semantic"],
        "time_range": {"start": first.isoformat(), "end": end.isoformat()},
        "quality_policy": "STRICT",
        "closed_only": True,
    }
    start_ns = scope["start_ns"] + (history + 1) * 60_000_000_000
    end_ns = start_ns + 128 * 60_000_000_000
    study = {
        "schema_version": 1,
        "bar_ns": 60_000_000_000,
        "horizon_bars": 1,
        "samples": [
            {"role": "DEVELOPMENT", "start_ns": start_ns, "end_ns": start_ns + 64 * 60_000_000_000},
            {"role": "OUT_OF_SAMPLE", "start_ns": start_ns + 64 * 60_000_000_000, "end_ns": end_ns},
        ],
        "protected_start_ns": end_ns,
        "protected_end_ns": end_ns + 64 * 60_000_000_000,
        "expected_block_length": 4,
        "replicates": 4096,
        "confidence_bps": 9500,
        "seed": "00" * 32,
    }
    request = dict(
        at="2026-10-29T00:00:00Z",
        id=composed["revision"]["revision_id"],
        definition=definition,
        scope=_scope_payload(scope),
        dataset_root=str(datasets),
        factor=factor,
        study=study,
        research_command=command,
        proposal_fingerprint=fp,
        semantic_root=str(semantic),
        research_root=str(research),
        projection_root=str(projection),
        source_roots=source_roots,
        initialize_evidence=False,
        policy_id="onlyalpha.factor-research",
        mode=mode,
    )
    return dict(
        actual=actual,
        database=database,
        postgres_dsn=postgres_dsn,
        request=request,
        work_id=work_id,
        result=None,
        next_stage="prepare",
    )


@pytest.mark.parametrize("stage", ["prepare", "submit", "execute", "inspect"])
def test_native_one_run_research_uses_real_confirmation_and_immutable_evidence(
    native_research_case: dict[str, Any], stage: str
) -> None:
    case = native_research_case
    # Collection order is explicit and checked. A selected later stage cannot
    # silently prepare/submit/execute a different Run or pass without its input.
    assert case["next_stage"] == stage, "select all four stages of this scenario"
    actual, database, request = case["actual"], case["database"], case["request"]
    work_id, mode = case["work_id"], request["mode"]
    if stage == "prepare":
        with psycopg.connect(case["postgres_dsn"]) as db:
            assert db.execute("SELECT count(*) FROM research_run WHERE run_id=%s", (work_id,)).fetchone() == (0,)
            assert db.execute(
                "SELECT count(*) FROM product_command_receipt WHERE command_id=%s", (request["research_command"],)
            ).fetchone() == (0,)
        assert actual.is_file()
        case["next_stage"] = "submit"
        return
    if stage == "submit":
        result = probe(actual, database, "dataset-research", phase="submit", **request)
        assert "error" not in result, result
        assert result["run_id"] == work_id
        assert result["state"] == {
            "queued-cancel": "CANCELLED",
            "source-revoked": "DENIED",
        }.get(mode, "QUEUED")
        case["result"] = result
        if result["state"] == "QUEUED":
            request.update(initialize_evidence=False, materialization_id=result["materialization_id"])
        case["next_stage"] = "execute"
    elif stage == "execute":
        result = case["result"]
        if result["state"] == "QUEUED":
            result = probe(actual, database, "dataset-research", phase="execute", **request)
        assert "error" not in result, result
        assert result["run_id"] == work_id
        case["result"] = result
        case["next_stage"] = "inspect"
    else:
        result = case["result"]
        if result["state"] == "COMPLETED":
            # A completed reader must work without the selected live Runtime directory.
            runtime = Path(request["factor"]["runtime_root"])
            held = runtime.with_name(runtime.name + "-held-for-read-proof")
            runtime.rename(held)
            try:
                result = probe(
                    held / actual.relative_to(runtime), database, "dataset-research", phase="inspect", **request
                )
            finally:
                held.rename(runtime)
            assert "error" not in result, result
            assert result["run_id"] == work_id
            if request["mode"] == "normal":
                provenance = probe(actual, database, "dataset-research", phase="report-inspect", **request)
                assert provenance == {
                    "run_id": work_id,
                    "state": "COMPLETED",
                    "report_provenance_regressions": "VERIFIED",
                }
                for relative in ("statistics-results/sha256", "calculation-results/sha256", "datasets/sha256"):
                    restored = probe(
                        actual,
                        database,
                        "dataset-research",
                        phase="source-cut-inspect",
                        missing_upstream=relative,
                        **request,
                    )
                    assert restored == {"source_cut_regressions": "VERIFIED", "missing_upstream": relative}
        case["result"] = result
        case["next_stage"] = "done"
    result = case["result"]
    with psycopg.connect(case["postgres_dsn"]) as db:
        receipts = db.execute(
            "SELECT count(*) FROM product_command_receipt WHERE command_id=%s", (request["research_command"],)
        ).fetchone()
        assert receipts == ((0,) if mode == "source-revoked" else (1,))
    assert "error" not in result, result
    assert result["run_id"] == work_id
    expected = {
        "queued-cancel": "CANCELLED",
        "cancel-empty": "CANCELLED",
        "cancel-partial": "CANCELLED",
        "cancel-corrupt": "FAILED",
        "budget": "FAILED",
        "budget-with-result": "FAILED",
        "source-revoked": "DENIED",
        "wrong-native-version": "QUEUED",
        "node-authority-loss": "RUNNING",
    }.get(mode, "COMPLETED")
    if stage == "submit":
        return
    assert result["state"] == expected
    with psycopg.connect(case["postgres_dsn"]) as db:
        assert db.execute(
            "SELECT count(*) FROM research_run_attempt WHERE run_id=%s AND state='ACTIVE'", (work_id,)
        ).fetchone() == ((1,) if mode == "node-authority-loss" else (0,))
    if mode == "node-authority-loss":
        assert result["node_fence_verified"] is True
    if stage == "inspect" and expected == "COMPLETED":
        assert "report" in result, result
        report = result["report"]
        assert len(report["statistics"]) == 2
        for statistic in report["statistics"]:
            assert statistic["analysis"]["pearson"]["uncertainty_status"] == "AVAILABLE", statistic["analysis"]
            assert statistic["analysis"]["spearman"]["uncertainty_status"] == "AVAILABLE", statistic["analysis"]


def test_native_strategy_environment_retains_target_calculation_artifact_without_provider_substitution(
    native_environment_case: dict[str, Any],
    tmp_path: Path,
) -> None:
    import hashlib

    case = native_environment_case
    root, executable, artifact, vector = (case[k] for k in ["root", "executable", "artifact", "vector"])

    def run(kind: str, runtime: Path, fresh: bool) -> dict[str, Any]:
        result = subprocess.run(
            [str(executable)],
            input=json.dumps(
                {
                    "op": "runtime-environment",
                    "preparation_kind": kind,
                    "factor": vector,
                    "release_root": str(root),
                    "runtime_root": str(runtime),
                    "algorithm_artifact": artifact,
                    "fresh": fresh,
                    "at": "2026-11-01T01:00:00Z",
                }
            ),
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        )
        record = cast(dict[str, Any], json.loads(result.stdout))
        assert "error" not in record, (record, result.stderr)
        return record

    # Separate exact requests preserve the original Factor wire and history.
    legacy_root = tmp_path / "use_test_factor_runtime"
    legacy = run("FACTOR", legacy_root, True)
    assert not any(i["kind"] == "TARGET" for i in legacy["manifest"]["implementations"])
    legacy_history = (legacy_root / "generation-events.jsonl").read_bytes()
    runtime = tmp_path / "use_test_strategy_runtime"
    first = run("STRATEGY", runtime, True)
    manifest = first["manifest"]
    assert first["snapshot"] == {
        "active_for_new_work": None,
        "states": {manifest["runtime_generation_fingerprint"]: "READY"},
    }
    assert len(manifest["artifact_sha256s"]) == len(legacy["manifest"]["artifact_sha256s"]) + 1
    artifacts = [
        json.loads((runtime / "artifacts" / digest[:2] / digest / "manifest.json").read_text())
        for digest in manifest["artifact_sha256s"]
    ]
    targets = [m for m in artifacts if m["distribution_name"] == "onlyalpha-backend-algorithms"]
    assert len(targets) == 1
    target = targets[0]
    # Re-enter the actual Rust preparation/publication owners. Registry's
    # install_artifact validates the complete Artifact manifest/fingerprint,
    # physical wheel SHA/size and exact existing retained pair; no Python DTO
    # can stand in for that proof or rewrite the original Generation history.
    original_target = (
        runtime / "artifacts" / target["artifact_sha256"][:2] / target["artifact_sha256"] / "manifest.json"
    ).read_bytes()
    original_history = (runtime / "generation-events.jsonl").read_bytes()
    assert run("STRATEGY", runtime, False) == first
    assert (
        runtime / "artifacts" / target["artifact_sha256"][:2] / target["artifact_sha256"] / "manifest.json"
    ).read_bytes() == original_target
    assert (runtime / "generation-events.jsonl").read_bytes() == original_history
    assert target["role"] == "CALCULATION" and target["schema_version"] == 1
    assert target["tested_core_execution_fingerprint"] == only_canonical_fingerprint(manifest["core_execution"])
    assert target["assets"] == []
    assert all(target[k] is None for k in ("provider_id", "provider_version", "provider_content_fingerprint"))
    assert target["implementations"]
    assert all(i["kind"] == "TARGET" and i["backend"] == "RESEARCH" for i in target["implementations"])
    assert all(i in first["manifest"]["implementations"] for i in target["implementations"])
    wheel = next((root / "wheels").glob("onlyalpha_backend_algorithms-*.whl"))
    assert target["artifact_sha256"] == hashlib.sha256(wheel.read_bytes()).hexdigest()
    retained = runtime / "artifacts" / target["artifact_sha256"][:2] / target["artifact_sha256"] / "artifact.whl"
    assert retained.read_bytes() == wheel.read_bytes()
    # Target is a Calculation library, not another Quant Asset Provider.
    assert first["manifest"]["providers"] == legacy["manifest"]["providers"]
    assert first["proof"]["catalog"] == legacy["proof"]["catalog"]
    observation = first["proof"]["algorithm_observation"]
    assert observation["contract"] == "ONLYALPHA_STRATEGY_EXECUTABLE_PREPARATION_V1"
    assert observation["target_artifact_sha256"] == target["artifact_sha256"]
    projected = [
        {
            "kind": c["type"]["kind"],
            "type_id": c["type"]["type_id"],
            "semantic_version": c["type"]["semantic_version"],
            "backend": c["backend"],
            "implementation_fingerprint": c["implementation_fingerprint"],
        }
        for c in observation["target_calculations"]
    ]
    assert sorted(projected, key=only_canonical_fingerprint) == sorted(
        target["implementations"], key=only_canonical_fingerprint
    )
    history = (runtime / "generation-events.jsonl").read_bytes()
    assert run("STRATEGY", runtime, False) == first
    assert (runtime / "generation-events.jsonl").read_bytes() == history
    assert (legacy_root / "generation-events.jsonl").read_bytes() == legacy_history
    # A missing selected Target wheel refuses the whole explicit request.
    missing = wheel.with_suffix(".retained")
    wheel.rename(missing)
    try:
        result = subprocess.run(
            [str(executable)],
            input=json.dumps(
                {
                    "op": "runtime-environment",
                    "preparation_kind": "STRATEGY",
                    "factor": vector,
                    "release_root": str(root),
                    "runtime_root": str(tmp_path / "use_test_missing_target"),
                    "algorithm_artifact": artifact,
                    "fresh": True,
                    "at": "2026-11-01T01:00:00Z",
                }
            ),
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        )
        assert "error" in json.loads(result.stdout)
        assert not (tmp_path / "use_test_missing_target").exists()
    finally:
        missing.rename(wheel)


@pytest.mark.parametrize(
    "fault",
    [
        "normal",
        "context",
        "window",
        "missing-composition",
        "native",
        "evaluate",
        "eval-spec",
        "eval-cancel",
        "eval-dataset",
    ],
)
def test_actual_strategy_preparation_consumes_composer_runtime_and_sealed_dataset(
    native_environment_case: dict[str, Any],
    market_probe: Path,
    database: ClickHouseObservations,
    postgres_dsn: str,
    tmp_path: Path,
    fault: str,
) -> None:
    prepared_case = strategy_preparation_case(native_environment_case, market_probe, database, tmp_path, fault)
    selected, arguments, vector, revision, strategy_id, evaluating = (
        prepared_case[k] for k in ["selected", "arguments", "vector", "revision", "strategy_id", "evaluating"]
    )
    if fault == "native":
        # Prove this fault is a valid, differently loaded native ELF, rather
        # than an unreadable/corrupt capability observation.
        observed = subprocess.run(
            [str(selected), "--describe-native-runtime"],
            env={},
            text=True,
            capture_output=True,
            timeout=30,
            check=True,
        )
        image = json.loads(observed.stdout)["image"]
        assert image["artifact"] == hashlib.sha256(selected.read_bytes()).hexdigest()
        assert image["artifact"] != hashlib.sha256(native_environment_case["executable"].read_bytes()).hexdigest()
    actual = probe(selected, database, "dataset-strategy-prepare", **arguments)
    with psycopg.connect(postgres_dsn) as conn:
        assert conn.execute("SELECT count(*) FROM research_run").fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM product_command_admission WHERE command_kind IN ('CREATE_RESEARCH_RUN','FREEZE_STRATEGY','PROMOTE_STRATEGY')"
        ).fetchone() == (0,)
        compositions = conn.execute(
            "SELECT count(*) FROM private_strategy_research_composition WHERE private_strategy_id=%s", (strategy_id,)
        ).fetchone()
    if fault in {"context", "window", "missing-composition", "native"}:
        expected = {
            "context": "RESEARCH_EXECUTABLE_INPUT_MISMATCH",
            "window": "RESEARCH_EXECUTABLE_INPUT_MISMATCH",
            "missing-composition": "PRIVATE_STRATEGY_COMPOSITION_CORRUPT",
            "native": "RESEARCH_NATIVE_IMAGE_MISMATCH",
        }[fault]
        assert actual == {"error": expected}, {
            "fault": fault,
            "actual_error": actual.get("error"),
            "actual_keys": sorted(actual),
        }
        assert compositions == ((0,) if fault == "missing-composition" else (1,))
        return
    if fault in {"eval-spec", "eval-cancel", "eval-dataset"}:
        expected = {
            "eval-spec": "STRATEGY_RESEARCH_EVALUATION_INPUT_MISMATCH",
            "eval-cancel": "RESEARCH_EXECUTION_CANCELLED",
            "eval-dataset": "DATASET_SNAPSHOT_CORRUPT",
        }[fault]
        assert actual == {"error": expected}, actual
        assert compositions == (1,)
        if fault == "eval-dataset":
            manifests = list(Path(arguments["dataset_root"]).glob("sha256/*/*/manifest.json"))
            assert len(manifests) == 1 and manifests[0].read_bytes() == b"not an immutable Dataset manifest"
        return
    assert "error" not in actual, actual
    prepared, spec = actual["prepared_inputs"], actual["specification"]
    assert prepared["contract"] == "ONLYALPHA_STRATEGY_RESEARCH_PREPARED_INPUTS_V1"
    assert spec["schema_version"] == 5 and spec["kind"] == "PRIVATE_STRATEGY_RESEARCH"
    assert prepared["runtime_work_binding"]["work_id"] == "use_test_strategy_prepare"
    assert prepared["composition"] == actual["original_resolution"]["composition"]
    assert prepared["composition"]["private_strategy_revision_fingerprint"] == revision["revision_fingerprint"]
    assert prepared["input_window"] == spec["input_window"]
    assert prepared["input_window"]["warmup_bars"] == 20
    assert prepared["dataset_snapshot_fingerprint"] == spec["scientific_specification"]["dataset_snapshot_fingerprint"]
    assert prepared["run_specification_fingerprint"] == actual["specification_fingerprint"]
    request = prepared["algorithm_resolution_request"]
    assert request["contract"] == "ONLYALPHA_CALCULATION_INSTANCES_RESOLVE_V1"
    assert request["sources"][0]["revision_fingerprint"] == vector["revision"]["revision_fingerprint"]
    assert request["target_artifact"]["sha256"] == prepared["algorithm_resolution"]["target_artifact_sha256"]
    assert prepared["algorithm_resolution"] == actual["original_resolution"]["algorithm_resolution"]
    assert prepared["native_implementations"]
    assert all(i["calculation_type_reference"]["kind"] == "PREDICATE" for i in prepared["native_implementations"])
    bindings = {b["node_fingerprint"]: b for b in spec["implementation_bindings"]}
    predicates = [
        n["definition"] for n in spec["decision"]["decision_graph"]["nodes"] if n["definition"]["kind"] == "PREDICATE"
    ]
    assert len(bindings) == len(spec["decision"]["decision_graph"]["nodes"])
    assert len(prepared["native_implementations"]) == 2 * len({d["type_id"] for d in predicates})
    from onlyalpha.calculation.definition import OnlyCalculationDefinition

    for definition_record in predicates:
        node = OnlyCalculationDefinition.from_dict(definition_record).fingerprint
        for backend, key in [
            ("RESEARCH", "research_implementation_fingerprint"),
            ("TRADING", "trading_implementation_fingerprint"),
        ]:
            manifests = [
                m
                for m in prepared["native_implementations"]
                if m["backend_kind"] == backend
                and all(
                    m["calculation_type_reference"][field] == definition_record[field]
                    for field in ("kind", "type_id", "semantic_version")
                )
            ]
            assert len(manifests) == 1
            assert bindings[node][key] == manifests[0]["implementation_fingerprint"]
    for node in prepared["algorithm_resolution"]["nodes"]:
        if node["definition"]["kind"] == "TARGET":
            assert [m["backend_kind"] for m in node["implementations"]] == ["RESEARCH"]
            assert node["definition_fingerprint"] not in bindings
        else:
            for implementation in node["implementations"]:
                key = (
                    "research_implementation_fingerprint"
                    if implementation["backend_kind"] == "RESEARCH"
                    else "trading_implementation_fingerprint"
                )
                assert bindings[node["definition_fingerprint"]][key] == implementation["implementation_fingerprint"]
    assert "strategy_fingerprint" not in prepared and "strategy_fingerprint" not in spec
    if evaluating:
        _assert_actual_strategy_evaluation(actual, prepared_case["axis_ns"])
    assert probe(selected, database, "dataset-strategy-prepare", **arguments) == actual


def _assert_actual_strategy_evaluation(actual: dict[str, Any], axis: list[int]) -> None:
    """Independent value checks over two actual numerical producers; no evidence grant."""
    from onlyalpha.calculation.definition import OnlyCalculationDefinition

    evaluation, spec = actual["evaluation"], actual["specification"]
    assert evaluation["schema_version"] == 1
    assert evaluation["contract"] == "ONLYALPHA_STRATEGY_EVALUATION_OBSERVATION_V1"
    assert evaluation["run_specification_fingerprint"] == actual["specification_fingerprint"]
    assert (
        evaluation["dataset_snapshot_fingerprint"] == spec["scientific_specification"]["dataset_snapshot_fingerprint"]
    )
    assert evaluation["input_window"] == spec["input_window"]
    # The scientific Calculation/Statistics axis stays the full immutable Dataset.
    # Warmup is intrinsic NULL; the separate report window contains 720 samples.
    assert len(axis) == 740 and evaluation["axis"] == axis
    assert evaluation["observation_count"] == 720
    assert evaluation["axis"][-1] < int(spec["input_window"]["observation_end_ns"])
    research = {row["node_fingerprint"]: row for row in evaluation["research_outputs"]}
    streaming = {row["node_fingerprint"]: row for row in evaluation["streaming_outputs"]}
    nodes = {
        OnlyCalculationDefinition.from_dict(row["definition"]).fingerprint: row["definition"]
        for row in spec["decision"]["decision_graph"]["nodes"]
    }
    bindings = {row["node_fingerprint"]: row for row in spec["implementation_bindings"]}
    assert len(research) == len(evaluation["research_outputs"]) == len(nodes)
    assert len(streaming) == len(evaluation["streaming_outputs"]) == len(nodes)
    assert research.keys() == streaming.keys() == nodes.keys()
    for node, definition in nodes.items():
        assert research[node]["implementation_fingerprint"] == bindings[node]["research_implementation_fingerprint"]
        assert streaming[node]["implementation_fingerprint"] == bindings[node]["trading_implementation_fingerprint"]
        # Every port and every row is compared, including all native Predicates.
        assert research[node]["values"] == streaming[node]["values"]
        assert set(research[node]["values"]) == {port["name"] for port in definition["outputs"]}
        assert all(len(column) == 740 for column in research[node]["values"].values())
    factor = next(key for key, definition in nodes.items() if definition["kind"] == "FACTOR")
    feature = research[factor]["values"]["value"]
    null = {"type": "NULL", "value": None}
    assert feature[:20] == [null] * 20
    assert feature[20] == {"type": "DECIMAL", "value": "0.002"}
    assert feature[21] == {"type": "DECIMAL", "value": "-0.001"}
    for key, definition in nodes.items():
        if definition["type_id"] == "onlyalpha.operator.delay":
            assert research[key]["values"]["value"][:20] == [null] * 20
            assert research[key]["values"]["value"][20] == {"type": "DECIMAL", "value": "101"}
        if definition["type_id"] == "onlyalpha.operator.rolling_mean":
            assert research[key]["values"]["value"][:19] == [null] * 19
            assert research[key]["values"]["value"][19] == {"type": "DECIMAL", "value": "2"}
    restored = evaluation["restoration"]
    assert restored["processed_rows"] == 370
    assert restored["before_checkpoint_fingerprint"] == restored["restored_checkpoint_fingerprint"]
    assert len(restored["before_checkpoint_fingerprint"]) == 64
    decisions = evaluation["decisions"]
    assert len(decisions) == len(axis) and [row["at_ns"] for row in decisions] == axis
    assert all(row["status"] == "BLOCKED" and row["decision"] is None for row in decisions[:20])
    for index, row in enumerate(decisions[20:], 20):
        assert row["status"] == "READY"
        for role in ("eligibility", "entry", "exit"):
            selector = spec["decision"]["signal_semantics"][role]
            observed = research[selector["node_fingerprint"]]["values"][selector["output_name"]][index]
            assert row["decision"][role] is (False if observed["type"] == "NULL" else observed["value"])
    assert decisions[20]["decision"] == {"eligibility": True, "entry": True, "exit": False}
    assert decisions[21]["decision"] == {"eligibility": True, "entry": False, "exit": True}
    targets = {row["node_fingerprint"]: row for row in evaluation["target_outputs"]}
    target_definitions = {
        OnlyCalculationDefinition.from_dict(row["definition"]).fingerprint: row["definition"]
        for row in spec["target_graph"]["nodes"]
    }
    assert targets.keys() == target_definitions.keys() and not targets.keys() & streaming.keys()
    assert len(targets) == 1
    target = next(iter(targets.values()))["values"]["target_value"]
    assert target[-5:] == [null] * 5 and all(value["type"] == "DECIMAL" for value in target[:-5])
    assert target[15] == {"type": "DECIMAL", "value": "0.002"}
    assert all(len(row["values"]["target_value"]) == 740 for row in targets.values())
    for node in actual["prepared_inputs"]["algorithm_resolution"]["nodes"]:
        if node["definition"]["kind"] == "TARGET":
            assert [m["backend_kind"] for m in node["implementations"]] == ["RESEARCH"]
            assert (
                targets[node["definition_fingerprint"]]["implementation_fingerprint"]
                == node["implementations"][0]["implementation_fingerprint"]
            )
    statistics = evaluation["statistics"]
    assert len(statistics) == len(spec["scientific_specification"]["statistics"]) == 2
    assert {result["plan"]["definition"]["method"] for result in statistics} == {"IC", "RANK_IC"}
    for result in statistics:
        plan = result["plan"]
        assert only_canonical_fingerprint(plan) == result["statistics_fingerprint"]
        assert plan["definition"]["method"] in {"IC", "RANK_IC"}
        assert plan["feature"]["node_fingerprint"] == factor
        assert plan["target"]["node_fingerprint"] in targets
        assert [row["ts_event_ns"] for row in result["rows"]] == axis
        assert len(result["rows"]) == 740
        for index, row in enumerate(result["rows"]):
            # Existing public Stats1: one cross-section per timestamp, not one
            # 720-observation time-series correlation or invented significance.
            count = int(feature[index]["type"] != "NULL" and target[index]["type"] != "NULL")
            expected = {
                "ts_event_ns": axis[index],
                "statistic_value": None,
                "sample_count": count,
                "status": "INSUFFICIENT_OBSERVATIONS",
            }
            assert row == expected
    _assert_complete_strategy_profiles(evaluation, nodes, bindings)
    assert (
        not {
            "run_id",
            "research_result_fingerprint",
            "freeze_relation",
            "published_strategy_revision",
            "permission",
            "equivalence_evidence",
        }
        & evaluation.keys()
    )


@pytest.mark.parametrize(
    "mode", ["normal", "source-denied", "physical-loss", "cancel-await", "sql-error", "commit-no-reply"]
)
def test_strategy_submission_reuses_original_command_and_run_with_physical_session_fencing(
    native_environment_case: dict[str, Any],
    market_probe: Path,
    database: ClickHouseObservations,
    postgres_dsn: str,
    tmp_path: Path,
    mode: str,
) -> None:
    from uuid import uuid4

    command = str(uuid4())
    work_id = fixture("run-id", binary=market_probe, command=command)["run_id"]
    case = strategy_preparation_case(native_environment_case, market_probe, database, tmp_path, work_id=work_id)
    selected, arguments = case["selected"], case["arguments"]
    semantic = tmp_path / "use_test_semantic"
    semantic.mkdir(mode=0o700)
    provision = probe(selected, database, "strategy-evidence-provision", semantic_root=str(semantic))
    assert "error" not in provision, provision
    research = semantic / "research"
    dataset_root, projection = research / "datasets", research / "experiment-memory"
    roots = provision["source_roots"]
    review_file = tmp_path / "use_test_original_review.json"
    arguments.update(
        dataset_root=str(dataset_root),
        research_command=command,
        submission_mode=mode,
        policy_id="onlyalpha.factor-research",
        semantic_root=str(semantic),
        research_root=str(research),
        projection_root=str(projection),
        source_roots=roots,
        initialize_evidence=False,
        review_file=str(review_file),
    )
    if mode == "commit-no-reply":
        payload = {
            "op": "dataset-strategy-prepare",
            "at": AT.isoformat(),
            "database": database.config.database,
            "url": database.config.url,
            **arguments,
        }
        environment = {
            **os.environ,
            "ONLYALPHA_CLICKHOUSE_USER": database.config.user,
            "ONLYALPHA_CLICKHOUSE_PASSWORD": database.config.password,
        }
        crashed = subprocess.run(
            [str(selected)],
            input=json.dumps({"op": "market-storage", "request": payload}),
            capture_output=True,
            text=True,
            timeout=30,
            env=environment,
        )
        assert crashed.returncode == 86, crashed.stdout + crashed.stderr
        review = json.loads(review_file.read_text())
        actual = {"run_id": work_id, **review}
    else:
        actual = probe(selected, database, "dataset-strategy-prepare", **arguments)
        assert "error" not in actual, actual
    from packages.backend.tests.postgres_link import wait_no_advisory_locks

    wait_no_advisory_locks(postgres_dsn, actual["backend_pid"])
    with psycopg.connect(postgres_dsn) as conn:
        counts = [
            conn.execute(f"SELECT count(*) FROM {table} WHERE run_id=%s", (work_id,)).fetchone()[0]
            for table in ("research_run", "research_strategy_study_authorization", "research_novelty_admission")
        ]
        commands = conn.execute(
            "SELECT count(*) FROM product_command_admission WHERE command_id=%s", (command,)
        ).fetchone()[0]
        receipts = conn.execute(
            "SELECT count(*) FROM product_command_receipt WHERE command_id=%s", (command,)
        ).fetchone()[0]
        if mode in ("source-denied", "physical-loss", "cancel-await", "sql-error"):
            assert counts == [0, 0, 0]
            assert commands == receipts == 0
            assert actual["writer_valid"] is (mode == "source-denied")
            return
        assert counts == [1, 1, 1] and commands == receipts == 1
        row = conn.execute(
            "SELECT specification_schema_version,origin_kind,strategy_research_composition_fingerprint,specification_fingerprint,specification_payload FROM research_run WHERE run_id=%s",
            (work_id,),
        ).fetchone()
        assert row[0:2] == (5, "PRIVATE_STRATEGY") and len(row[2]) == 64
        specification = json.loads(row[4])
        assert row[3] == only_canonical_fingerprint(specification)
        science = only_canonical_fingerprint(specification["scientific_specification"])
        assert row[3] != science
        auth = json.loads(
            conn.execute(
                "SELECT payload FROM research_strategy_study_authorization WHERE run_id=%s", (work_id,)
            ).fetchone()[0]
        )
        assert auth["specification_fingerprint"] == row[3]
        assert auth["scientific_specification_fingerprint"] == science
        assert auth["composition_fingerprint"] == row[2]
        assert auth["prepared_inputs"]["runtime_work_binding"]["work_id"] == work_id
        assert conn.execute(
            "SELECT count(*) FROM research_factor_study_authorization WHERE run_id=%s", (work_id,)
        ).fetchone() == (0,)
        attempts = conn.execute(
            "SELECT state,attempt_number FROM research_run_attempt WHERE run_id=%s", (work_id,)
        ).fetchall()
        assert attempts == ([] if mode == "commit-no-reply" else [("CANCELLED", 1)])
    # A fresh process only asks for the original accepted Command. It cannot
    # depend on an available Runtime, current Source permission or mutable head.
    runtime = Path(arguments["runtime_root"])
    unavailable = runtime.with_name("use_test_runtime_unavailable")
    runtime.rename(unavailable)
    try:
        recovered = probe(
            selected,
            database,
            "strategy-submission-outcome",
            scope=arguments["scope"],
            study=actual["study"],
            study_fingerprint=actual["study_fingerprint"],
        )
        assert recovered == {
            "run_id": work_id,
            "state": "QUEUED" if mode == "commit-no-reply" else "CANCELLED",
            "specification_fingerprint": row[3],
            "scientific_specification_fingerprint": science,
        }
    finally:
        unavailable.rename(runtime)
    # Forward DDL must require a Strategy5 authorization for every Strategy5
    # Run in the same commit, rather than treating a valid payload as a grant.
    with psycopg.connect(postgres_dsn) as conn:
        with pytest.raises(psycopg.Error):
            with conn.transaction():
                other = str(uuid4())
                conn.execute(
                    "INSERT INTO research_run SELECT (jsonb_populate_record(NULL::research_run,to_jsonb(r)||jsonb_build_object('run_id',%s::text))).* FROM research_run r WHERE run_id=%s",
                    (other, work_id),
                )
                conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
        assert conn.execute("SELECT count(*) FROM research_run WHERE run_id=%s", (work_id,)).fetchone() == (1,)
    # An internally consistent hash over a corrupted authorization is still not
    # its original scientific proof. Recovery refuses it without healing facts.
    from onlyalpha.canonical import only_canonical_json

    corrupted = {**auth, "scientific_specification_fingerprint": "f" * 64}
    raw = only_canonical_json(corrupted)
    with psycopg.connect(postgres_dsn) as conn:
        conn.execute("ALTER TABLE research_strategy_study_authorization DISABLE TRIGGER USER")
        conn.execute(
            "UPDATE research_strategy_study_authorization SET payload=%s,fingerprint=%s WHERE run_id=%s",
            (raw, hashlib.sha256(raw.encode()).hexdigest(), work_id),
        )
        conn.execute("ALTER TABLE research_strategy_study_authorization ENABLE TRIGGER USER")
    refused = probe(
        selected,
        database,
        "strategy-submission-outcome",
        scope=arguments["scope"],
        study=actual["study"],
        study_fingerprint=actual["study_fingerprint"],
    )
    assert refused == {"error": "RESEARCH_AUTHORIZATION_CORRUPT"}
    with psycopg.connect(postgres_dsn) as conn:
        assert conn.execute(
            "SELECT payload FROM research_strategy_study_authorization WHERE run_id=%s", (work_id,)
        ).fetchone() == (raw,)
        assert conn.execute("SELECT count(*) FROM research_run WHERE run_id=%s", (work_id,)).fetchone() == (1,)
        assert conn.execute(
            "SELECT count(*) FROM product_command_receipt WHERE command_id=%s", (command,)
        ).fetchone() == (1,)


def _assert_complete_strategy_profiles(
    evaluation: dict[str, Any], nodes: dict[str, Any], bindings: dict[str, Any]
) -> None:
    from itertools import product

    from onlyalpha.calculation.definition import OnlyCalculationDefinition

    fixed = {
        "FLAT_SEQUENCE",
        "NEGATIVE_SLOPE_SEQUENCE",
        "POSITIVE_SLOPE_SEQUENCE",
        "QUANTIZATION_BOUNDARY",
        "WARMUP_AND_STEADY_STATE",
        "ZERO_BOUNDARY",
    }
    graph_cases = {case["case_id"]: case for case in evaluation["graph_cases"]}
    assert len(graph_cases) == len(evaluation["graph_cases"]) == 6 and graph_cases.keys() == fixed
    work = len(evaluation["axis"])
    for case in graph_cases.values():
        assert len(case["rows"]) == len(case["axis"]) >= evaluation["input_window"]["warmup_bars"] + 2
        assert [row["at_ns"] for row in case["rows"]] == case["axis"]
        research = {row["node_fingerprint"]: row for row in case["research_outputs"]}
        streaming = {row["node_fingerprint"]: row for row in case["streaming_outputs"]}
        assert research.keys() == streaming.keys() == nodes.keys()
        for node in nodes:
            assert research[node]["values"] == streaming[node]["values"]
            assert research[node]["implementation_fingerprint"] == bindings[node]["research_implementation_fingerprint"]
            assert streaming[node]["implementation_fingerprint"] == bindings[node]["trading_implementation_fingerprint"]
        work += len(case["rows"])
    profiles = {node["node_fingerprint"]: node for node in evaluation["node_profiles"]}
    assert len(profiles) == len(evaluation["node_profiles"]) == len(nodes) and profiles.keys() == nodes.keys()
    for key, node in profiles.items():
        definition = OnlyCalculationDefinition.from_dict(nodes[key])
        required_cases = set(fixed)
        if any(port.nullable for port in definition.inputs):
            required_cases.add("NULLABLE_INPUT_SEMANTICS")
        if any(port.data_type.value == "BOOLEAN" for port in definition.inputs):
            required_cases.add("BOOLEAN_TRUTH_NULL_SEMANTICS")
        if len(definition.outputs) > 1:
            required_cases.add("MULTI_OUTPUT_ALIGNMENT")
        required = sorted(required_cases)
        assert node["profile_covered_cases"] == required
        assert node["research_implementation_fingerprint"] == bindings[key]["research_implementation_fingerprint"]
        assert node["trading_implementation_fingerprint"] == bindings[key]["trading_implementation_fingerprint"]
        cases = {row["case_id"]: row for row in node["cases"]}
        assert len(cases) == len(node["cases"]) == len(required) and cases.keys() == set(required)
        for case in cases.values():
            assert 1 <= len(case["inputs"]) <= 8192
            assert len(case["research_outputs"]) == len(case["trading_outputs"]) == len(case["inputs"])
            assert case["research_outputs"] == case["trading_outputs"]
            assert all(set(row) == {port.name for port in definition.inputs} for row in case["inputs"])
            assert all(set(row) == {port.name for port in definition.outputs} for row in case["research_outputs"])
            work += len(case["inputs"])
        for port in definition.inputs:
            if port.nullable:
                actual = [row[port.name] for row in cases["NULLABLE_INPUT_SEMANTICS"]["inputs"]]
                assert {"type": "NULL", "value": None} in actual
                assert any(value["type"] != "NULL" for value in actual)
        literal = nodes[key]["parameters"].get("literal")
        if literal is not None and literal["type"] == "DECIMAL":
            from decimal import Decimal

            inputs = cases["QUANTIZATION_BOUNDARY"]["inputs"]
            port = definition.inputs[0].name
            equal = [
                index
                for index, row in enumerate(inputs)
                if row[port]["type"] == "DECIMAL" and Decimal(row[port]["value"]) == Decimal(literal["value"])
            ]
            assert equal, "literal equality is a real controlled boundary, not a coverage label"
            operation = definition.type_id.split(".compare.")[1].split(".")[0]
            expected = {"eq": True, "ne": False, "lt": False, "le": True, "gt": False, "ge": True}[operation]
            assert all(
                cases["QUANTIZATION_BOUNDARY"]["research_outputs"][index]["value"]
                == {"type": "BOOLEAN", "value": expected}
                for index in equal
            )
        booleans = [port.name for port in definition.inputs if port.data_type.value == "BOOLEAN"]
        if booleans:
            actual = {
                tuple((row[name]["type"], row[name]["value"]) for name in booleans)
                for row in cases["BOOLEAN_TRUTH_NULL_SEMANTICS"]["inputs"]
            }
            assert actual == set(product((("BOOLEAN", False), ("BOOLEAN", True), ("NULL", None)), repeat=len(booleans)))
    assert work <= 8192


def test_runtime_evidence_reads_original_released_generation_without_execution_or_current_image(
    native_environment_case: dict[str, Any],
    tmp_path: Path,
) -> None:
    from uuid import uuid4

    case = native_environment_case
    executable, release, artifact, vector = (case[k] for k in ["executable", "root", "artifact", "vector"])
    runtime = tmp_path / "use_test_evidence_runtime"
    work = "use_test_original_strategy_evidence"

    def call(op: str, binary: Path = executable, **values: Any) -> dict[str, Any]:
        request = {
            "op": op,
            "runtime_root": str(runtime),
            "work_id": work,
            "owner": "research",
            "generation": generation,
            "at": "2026-11-02T00:00:00Z",
            **values,
        }
        result = subprocess.run([str(binary)], input=json.dumps(request), text=True, capture_output=True, timeout=30)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    made = subprocess.run(
        [str(executable)],
        input=json.dumps(
            {
                "op": "runtime-environment",
                "preparation_kind": "STRATEGY",
                "factor": vector,
                "release_root": str(release),
                "runtime_root": str(runtime),
                "algorithm_artifact": artifact,
                "fresh": True,
                "bind_work": work,
                "activation_command": str(uuid4()),
                "at": "2026-11-01T01:00:00Z",
            }
        ),
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    environment = json.loads(made.stdout)
    assert "error" not in environment, (environment, made.stderr)
    generation = environment["manifest"]["runtime_generation_fingerprint"]
    before = call("runtime-evidence-read")
    assert before["manifest"] == environment["manifest"] and before["input_available"] is True
    assert before["binding"]["work_id"] == work and before["binding"]["reason"] == "research"
    for wrong in [{"work_id": "use_test_foreign_work"}, {"owner": "foreign-owner"}, {"generation": "f" * 64}]:
        assert "error" in call("runtime-evidence-read", **wrong)
    released = call("runtime-work-release")
    assert released["event"]["kind"] == "RuntimeWorkReleased"
    assert released["event"]["generation_fingerprint"] == generation and released["event"]["work_id"] == work
    assert released["event"]["reason"] == "research"
    ledger = (runtime / "generation-events.jsonl").read_bytes()
    assert call("runtime-work-release", at="2026-11-03T00:00:00Z") == released
    assert (runtime / "generation-events.jsonl").read_bytes() == ledger
    for wrong in [{"work_id": "use_test_foreign_work"}, {"owner": "foreign-owner"}, {"generation": "f" * 64}]:
        assert "error" in call("runtime-work-release", **wrong)
        assert (runtime / "generation-events.jsonl").read_bytes() == ledger
    # Historical reading proves the retained original artifact. It must not
    # manufacture its native manifests from this differently loaded current ELF.
    other_image = tmp_path / "use_test_different_current_image"
    other_image.write_bytes(executable.read_bytes() + b"\n# different current image; retained history unchanged\n")
    other_image.chmod(0o500)
    historical = call("runtime-evidence-read", binary=other_image)
    assert historical["manifest"] == before["manifest"] and historical["binding"] == before["binding"]
    assert historical["input_available"] is False
    assert (runtime / "generation-events.jsonl").read_bytes() == ledger
    retained_elf = next(runtime.glob("artifacts/*/*/artifact.elf"))
    retained_elf.chmod(0o700)
    with retained_elf.open("r+b") as stream:
        stream.seek(-1, 2)
        last = stream.read(1)
        stream.seek(-1, 2)
        stream.write(bytes([last[0] ^ 1]))
    retained_elf.chmod(0o500)
    assert "error" in call("runtime-evidence-read"), "retained physical bytes are mandatory even after release"
