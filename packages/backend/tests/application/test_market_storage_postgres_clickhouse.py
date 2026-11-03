"""Native PG/CH storage capability, controlled technical fixtures only; no UI claim."""

from __future__ import annotations

import functools
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import threading
import tomllib
import urllib.request
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

import psycopg
import pytest
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_payload

from onlyalpha.data.models import OnlyBarUpdate, OnlyMarketDataInboundUpdate
from onlyalpha.market_data.durable.codec import only_encode_record_bundle
from onlyalpha.market_data.durable.models import (
    OnlyCanonicalMarketFactRecord,
    OnlyIngestSegment,
    OnlyMarketDataRecordBundle,
)
from onlyalpha.market_data.durable.revision import OnlyRevisionCommitService, only_build_coverage
from onlyalpha.market_data.durable.wal import OnlyMarketDataWal
from onlyalpha.persistence.clickhouse import (
    OnlyClickHouseClient,
    OnlyClickHouseConfig,
    OnlyClickHouseMarketFactStore,
    only_assert_clickhouse_test_database,
)
from onlyalpha.persistence.clickhouse.market_data_store import _physical_row_sql, _quote
from onlyalpha.persistence.postgres.market_data_catalog import OnlyPostgresMarketDataCatalog, _scope_payload
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from scripts.native_http_contract import native_executable
from scripts.native_web_e2e import clickhouse_namespace
from tests.market_data_durable.conftest import bar_update, reference_update, trade_update

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
            *(["--release"] if release else ["--config", "profile.dev.package.onlyalpha-backend.debug=0"]),
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


@contextmanager
def market_database(postgres_dsn: str) -> Iterator[OnlyClickHouseClient]:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    name = "onlyalpha_test_native_market_storage_" + uuid.uuid4().hex
    only_assert_clickhouse_test_database(name)
    config = OnlyClickHouseConfig(
        os.environ["ONLYALPHA_TEST_CLICKHOUSE_URL"],
        database=name,
        user=os.environ.get("ONLYALPHA_TEST_CLICKHOUSE_USER", "default"),
        password=os.environ.get("ONLYALPHA_TEST_CLICKHOUSE_PASSWORD", ""),
        storage_policy=os.environ.get("ONLYALPHA_TEST_CLICKHOUSE_STORAGE_POLICY", "hot_cold"),
    )
    client = OnlyClickHouseClient(config)
    backend = native_executable(release=True)
    clickhouse_namespace(backend, name, initialize=True)
    try:
        yield client
    finally:
        clickhouse_namespace(backend, name, initialize=False)


@pytest.fixture
def database(postgres_dsn: str) -> Iterator[OnlyClickHouseClient]:
    with market_database(postgres_dsn) as client:
        yield client


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
    binary: Path, client: OnlyClickHouseClient, op: str, *, process_timeout: int = 30, **values: Any
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
    market_probe: Path, database: OnlyClickHouseClient, postgres_dsn: str, tmp_path: Path
) -> None:
    """Technical precondition proof, never the Factor/Study/Research UI acceptance."""
    from scripts.native_http_contract import native_executable

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
) -> tuple[OnlyMarketDataWal, OnlyIngestSegment]:
    fixture = json.loads((Path(__file__).parent / "fixtures/market_wal_history.json").read_text())
    from onlyalpha.market_data.durable.codec import only_decode_record_bundle
    from onlyalpha.market_data.durable.models import OnlyRawProviderEvidence

    evidence = only_decode_record_bundle(fixture["native_bundle_json"].encode()).evidence
    evidence = replace(evidence, capture_session_id=f"capture-{segment_id}", integration_binding_fingerprint=binding)
    if kind not in {"BAR", "RAW_BAR"}:
        evidence = replace(evidence, bar_construction=None)
    # Capture identity is recomputed from its original formal fields, never copied.
    evidence = OnlyRawProviderEvidence.capture(
        source_id=evidence.source_id,
        capture_session_id=evidence.capture_session_id,
        provider=evidence.provider,
        venue=evidence.venue,
        market=evidence.market,
        stream=evidence.stream,
        provider_event_type=evidence.provider_event_type,
        ts_receive_ns=evidence.ts_receive_ns,
        payload=evidence.payload if raw_payload is None else raw_payload,
        provenance=evidence.provenance,
        integration_binding_fingerprint=binding,
        bar_construction=evidence.bar_construction,
    )
    update = (
        bar_update(index)
        if kind == "BAR"
        else trade_update(index)
        if kind == "TRADE"
        else reference_update(index)
        if kind == "MARKET_REFERENCE"
        else None
    )
    facts = (
        ()
        if update is None
        else (
            OnlyCanonicalMarketFactRecord.bind(
                update,
                evidence,
                segment_id=segment_id,
                ts_ingest_ns=123,
                normalizer_id="native-reference",
                normalizer_version="1",
            ),
        )
    )
    wal = OnlyMarketDataWal(root, capacity_bytes=32 * 1024 * 1024, now=lambda: AT)
    wal.open_segment(segment_id)
    wal.append(OnlyMarketDataRecordBundle(evidence, facts))
    segment = wal.seal(sealed_at=AT)
    return wal, segment


def drain(
    binary: Path, client: OnlyClickHouseClient, wal: OnlyMarketDataWal, segment: OnlyIngestSegment, **options: Any
) -> dict[str, Any]:
    scope = None if segment.canonical_count == 0 else _scope_payload(segment.recovery_scope())
    return probe(binary, client, "drain", root=str(wal.root), ids=[segment.segment_id], scope=scope, **options)


@pytest.mark.parametrize("kind", ["BAR", "TRADE", "MARKET_REFERENCE", "RAW_ONLY", "RAW_BAR"])
def test_native_first_write_all_retained_families_and_exact_original_proofs(
    market_probe: Path, database: OnlyClickHouseClient, postgres_dsn: str, tmp_path: Path, kind: str
) -> None:
    wal, segment = retained(tmp_path, kind, index=0 if kind == "BAR" else 10)
    records = wal.read_sealed(segment.segment_id)
    result = drain(market_probe, database, wal, segment)
    assert "error" not in result, result
    assert not list(tmp_path.glob("*.sealed.wal"))
    record = probe(market_probe, database, "segment", id=segment.segment_id)
    if kind != "TRADE":
        expected = (
            OnlyClickHouseMarketFactStore(database)
            .verify_segments((segment,), {segment.segment_id: records})
            .physical_proofs[0]
        )
        assert record["proof"] == expected.to_dict()
    else:
        assert database.query_json("SELECT provider_event_id FROM market_trade") == ({"provider_event_id": "10"},)
        # Known Python projection defect is explicitly outside value parity: the
        # typed canonical payload and original fact/Segment identities remain equal.
        assert (
            OnlyClickHouseMarketFactStore._fact_row(segment, records[0].canonical_facts[0])["provider_event_id"]
            == "{'schema_version': 1, 'value': '10'}"
        )
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
    assert record["proof"]["segment_metadata_fingerprint"] == only_canonical_fingerprint(segment)
    assert record["segment"]["created_at"] == segment.created_at.isoformat()
    if kind in {"BAR", "TRADE"}:
        revision = result["revision"]
        read = probe(market_probe, database, "read", id=revision["revision_id"])
        assert read["facts"] == [only_canonical_payload(records[0].canonical_facts[0])]
        assert (
            read["manifest"]["fingerprint"]
            == only_build_coverage(segment.recovery_scope(), (segment,), records[0].canonical_facts).fingerprint
        )
        py = OnlyPostgresMarketDataCatalog(postgres_dsn)
        assert py.load_sealed_revision(revision["revision_id"])[0].fingerprint == revision["fingerprint"]
    elif kind == "MARKET_REFERENCE":
        assert result["manifest"]["coverage_status"] == "UNPROVABLE"
        assert result["revision"] is None
    else:
        assert result["manifest"] is None


@pytest.mark.parametrize("kind", ["BAR", "TRADE"])
def test_original_published_proof_does_not_authorize_a_wrong_current_wal_projection(
    market_probe: Path, database: OnlyClickHouseClient, postgres_dsn: str, tmp_path: Path, kind: str
) -> None:
    wal, segment = retained(tmp_path, kind, index=0 if kind == "BAR" else 10)
    records = {segment.segment_id: wal.read_sealed(segment.segment_id)}
    facts = OnlyClickHouseMarketFactStore(database)
    facts.write_segments((segment,), records)
    catalog = OnlyPostgresMarketDataCatalog(postgres_dsn, now=lambda: AT)
    manifest, revision, seal = OnlyRevisionCommitService(facts, catalog, now=lambda: AT).commit(
        (segment,), segment.recovery_scope(), records, reason="BACKFILL"
    )
    with psycopg.connect(postgres_dsn) as c:
        before = c.execute("SELECT to_jsonb(t) FROM market_data_revision t").fetchall()
    read = probe(market_probe, database, "read", id=revision.revision_id)
    assert read["manifest"]["fingerprint"] == manifest.fingerprint
    assert read["seal"]["seal_id"] == seal.seal_id
    proof_before = catalog.load_physical_proofs((segment.segment_id,))[0].to_dict()
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
        assert not (tmp_path / f"{segment.segment_id}.sealed.wal").exists()
    assert catalog.load_physical_proofs((segment.segment_id,))[0].to_dict() == proof_before
    assert {table: database.query_json(f"SELECT * FROM {table}") for table in before_physical} == before_physical

    with psycopg.connect(postgres_dsn) as c:
        assert c.execute("SELECT to_jsonb(t) FROM market_data_revision t").fetchall() == before


@pytest.mark.parametrize("stop", ["BeforeStore", "RawWritten", "StoreWritten", "Verified", "CatalogCommitted"])
def test_every_durable_boundary_preserves_recoverable_or_explicit_partial_state(
    market_probe: Path, database: OnlyClickHouseClient, tmp_path: Path, stop: str
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
    market_probe: Path, database: OnlyClickHouseClient, tmp_path: Path
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
    market_probe: Path, database: OnlyClickHouseClient, postgres_dsn: str, tmp_path: Path
) -> None:
    wal, segment = retained(tmp_path)
    scope = _scope_payload(segment.recovery_scope())
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
    market_probe: Path, database: OnlyClickHouseClient, postgres_dsn: str, tmp_path: Path, case: str
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
    scope = _scope_payload(segment.recovery_scope())
    range_result = probe(market_probe, database, "range", scope=scope, intervals=[[scope["start_ns"], scope["end_ns"]]])
    assert "error" in range_result


def test_physical_column_corruption_is_not_hidden_by_payload_or_record_hash(
    market_probe: Path, database: OnlyClickHouseClient, tmp_path: Path
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
    market_probe: Path, database: OnlyClickHouseClient, tmp_path: Path
) -> None:
    first_wal, first = retained(tmp_path / "first", index=0, segment_id="first")
    first_result = drain(market_probe, database, first_wal, first)
    second_wal, second = retained(tmp_path / "second", index=1, segment_id="second")
    assert first.start_ns is not None
    wider = _scope_payload(replace(second.recovery_scope(), start_ns=first.start_ns))
    incomplete = probe(market_probe, database, "drain", root=str(second_wal.root), ids=[second.segment_id], scope=wider)
    assert incomplete["manifest"]["coverage_status"] == "INCOMPLETE"
    scope = _scope_payload(first.recovery_scope())
    queried = probe(market_probe, database, "range", scope=scope, intervals=[[first.start_ns, second.end_ns]])
    assert queried["status"] == "INCOMPLETE" and queried["facts"] == []
    assert len(queried["evidence"]) == 1
    assert queried["evidence"][0]["revision_id"] == first_result["revision"]["revision_id"]
    assert queried["gaps"] == [{"start_ns": first.end_ns, "end_ns": second.end_ns}]


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
    market_probe: Path, database: OnlyClickHouseClient, postgres_dsn: str, tmp_path: Path, state: str
) -> None:
    wal, segment = retained(tmp_path)
    assert drain(market_probe, database, wal, segment, stop="CatalogCommitted") == {
        "error": "MARKET_DATA_RECOVERY_STOPPED"
    }
    marker = json.dumps(
        {"schema_version": 1, "segment_id": segment.segment_id, "content_hash": segment.content_hash},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    if state == "stage-prefix":
        (tmp_path / "retained.gc.json.tmp").write_bytes(marker[:20])
    elif state == "wrong-hash":
        (tmp_path / "retained.gc.json").write_bytes(marker.replace(segment.content_hash.encode(), b"a" * 64))
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
    market_probe: Path, database: OnlyClickHouseClient, postgres_dsn: str, tmp_path: Path
) -> None:
    wal, segment = retained(tmp_path)
    bundle = json.loads(only_encode_record_bundle(wal.read_sealed(segment.segment_id)[0]))
    bundle["canonical_facts"] = []
    proxy = RecorderBarrierProxy(database.config.url, tmp_path)
    child = None
    try:
        request = {
            "op": "drain-record",
            "root": str(tmp_path),
            "scope": _scope_payload(segment.recovery_scope()),
            "ids": [segment.segment_id],
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
        frames = tuple(OnlyMarketDataWal._decode_frames((tmp_path / "live.open.wal").read_bytes(), sealed=False))
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
        assert (
            len(tuple(OnlyMarketDataWal._decode_frames((tmp_path / "live.open.wal").read_bytes(), sealed=False))) == 2
        )
    finally:
        proxy.release.set()
        if child is not None and child.poll() is None:
            child.kill()
            child.communicate(timeout=5)
        proxy.close()


def test_operation_cumulative_budget_fails_before_dispatch_and_does_not_certify_empty(
    market_probe: Path, database: OnlyClickHouseClient, postgres_dsn: str, tmp_path: Path
) -> None:
    first, a = retained(tmp_path, segment_id="a", raw_payload=b"x" * 6000)
    second, b = retained(tmp_path, segment_id="b", raw_payload=b"x" * 6000)
    budget = 20000
    # Each isolated segment fits; two retained payloads exceed the same bound.
    for wal, segment in ((first, a), (second, b)):
        result = drain(market_probe, database, wal, segment, max_bytes=budget, stop="BeforeStore")
        assert result == {"error": "MARKET_DATA_RECOVERY_STOPPED"}
    request = dict(root=str(tmp_path), ids=[a.segment_id, b.segment_id], scope=_scope_payload(a.recovery_scope()))
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
    market_probe: Path, database: OnlyClickHouseClient, tmp_path: Path
) -> None:
    wal, segment = retained(tmp_path, "RAW_ONLY", raw_payload=b"")
    result = drain(market_probe, database, wal, segment)
    assert "error" not in result
    assert database.query_json("SELECT raw_payload_base64 FROM market_raw_event") == ({"raw_payload_base64": ""},)


def test_old_gc_history_and_current_binding_gap_compose_exact_success_without_producer_equality(
    market_probe: Path, database: OnlyClickHouseClient, postgres_dsn: str, tmp_path: Path
) -> None:
    old_wal, old = retained(tmp_path / "old", index=0, segment_id="old")
    old_result = drain(market_probe, database, old_wal, old)
    assert old_result["revision"] is not None
    assert not (old_wal.root / "old.sealed.wal").exists()
    new_wal, new = retained(tmp_path / "new", index=1, segment_id="new", binding="b" * 64)
    assert old.integration_binding_fingerprint is None and new.integration_binding_fingerprint == "b" * 64
    assert new.end_ns is not None
    scope = _scope_payload(replace(old.recovery_scope(), end_ns=new.end_ns))
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
    references = sorted([[old.segment_id, old.content_hash], [new.segment_id, new.content_hash]])
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
    assert not list(old_wal.root.glob("*.sealed.wal")) and not list(new_wal.root.glob("*.sealed.wal"))
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
    wrong_family = sorted([references[0], [foreign.segment_id, foreign.content_hash]])
    assert probe(market_probe, database, "compose", scope=scope, refs=wrong_family) == {
        "error": "MARKET_DATA_EVIDENCE_UNPROVABLE"
    }
    with psycopg.connect(postgres_dsn) as c:
        count = c.execute("SELECT count(*) FROM market_data_revision").fetchone()
        c.execute(
            "ALTER TABLE market_segment_physical_proof DISABLE TRIGGER market_segment_physical_proof_reject_mutation"
        )
        c.execute("DELETE FROM market_segment_physical_proof WHERE segment_id=%s", (old.segment_id,))
    assert probe(market_probe, database, "compose", scope=scope, refs=references) == {
        "error": "MARKET_DATA_EVIDENCE_UNPROVABLE"
    }
    with psycopg.connect(postgres_dsn) as c:
        assert c.execute("SELECT count(*) FROM market_data_revision").fetchone() == count


def test_range_query_explicitly_rejects_non_bar_family(
    market_probe: Path, database: OnlyClickHouseClient, tmp_path: Path
) -> None:
    _wal, segment = retained(tmp_path, "TRADE", index=10)
    scope = _scope_payload(segment.recovery_scope())
    assert probe(market_probe, database, "range", scope=scope, intervals=[[scope["start_ns"], scope["end_ns"]]]) == {
        "error": "MARKET_DATA_INPUT_INVALID"
    }


def test_latest_exact_family_selects_stored_metadata_and_never_falls_back_from_bad_latest(
    market_probe: Path, database: OnlyClickHouseClient, tmp_path: Path
) -> None:
    old_wal, old = retained(tmp_path / "old", index=0, segment_id="old")
    family = _scope_payload(old.recovery_scope())
    assert probe(market_probe, database, "latest", scope=family) == {"error": "SEALED_REVISION_NOT_FOUND"}
    first = drain(market_probe, database, old_wal, old)
    new_wal, new = retained(tmp_path / "new", index=1, segment_id="new")
    newest = drain(market_probe, database, new_wal, new)
    selected = probe(market_probe, database, "latest", scope=family)
    assert selected["revision"]["revision_id"] == newest["revision"]["revision_id"]
    assert selected["revision"]["revision_id"] != first["revision"]["revision_id"]
    assert len(selected["facts"]) == 1 and selected["facts"][0]["segment_id"] == new.segment_id
    database.execute("ALTER TABLE market_bar UPDATE close=close+1 WHERE segment_id='new' SETTINGS mutations_sync=2")
    assert probe(market_probe, database, "latest", scope=family) == {"error": "MARKET_DATA_EVIDENCE_UNPROVABLE"}


def test_unknown_occurrence_is_retained_when_a_new_execution_reacquires_the_exact_lease(
    market_probe: Path, database: OnlyClickHouseClient, postgres_dsn: str, tmp_path: Path
) -> None:
    _wal, segment = retained(tmp_path)
    intent = probe(
        market_probe,
        database,
        "intent",
        scope=_scope_payload(segment.recovery_scope()),
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
    market_probe: Path, database: OnlyClickHouseClient, postgres_dsn: str, tmp_path: Path
) -> None:
    wal, segment = retained(tmp_path, "TRADE", index=10)
    assert drain(market_probe, database, wal, segment, stop="CatalogCommitted") == {
        "error": "MARKET_DATA_RECOVERY_STOPPED"
    }
    before = probe(market_probe, database, "segment", id=segment.segment_id)
    assert database.query_json("SELECT provider_event_id FROM market_trade") == ({"provider_event_id": "10"},)
    assert (tmp_path / f"{segment.segment_id}.sealed.wal").exists()
    assert probe(market_probe, database, "recover", root=str(tmp_path), startup=True) == {"count": 1}
    assert not (tmp_path / f"{segment.segment_id}.sealed.wal").exists()
    assert probe(market_probe, database, "segment", id=segment.segment_id) == before


@pytest.mark.parametrize("case", ["complete", "duplicate", "conflict", "timestamp", "payload"])
def test_range_filters_intervals_only_after_whole_revision_proof(
    market_probe: Path, database: OnlyClickHouseClient, tmp_path: Path, case: str
) -> None:
    def sealed(
        name: str, updates: tuple[OnlyMarketDataInboundUpdate, ...]
    ) -> tuple[OnlyMarketDataWal, OnlyIngestSegment, tuple[OnlyCanonicalMarketFactRecord, ...]]:
        seed, seed_segment = retained(tmp_path / ("seed-" + name), segment_id="seed-" + name)
        evidence = seed.read_sealed(seed_segment.segment_id)[0].evidence
        facts = tuple(
            OnlyCanonicalMarketFactRecord.bind(
                update,
                evidence,
                segment_id=name,
                ts_ingest_ns=123,
                normalizer_id="native-reference",
                normalizer_version="1",
            )
            for update in updates
        )
        wal = OnlyMarketDataWal(tmp_path / name, capacity_bytes=32 * 1024 * 1024, now=lambda: AT)
        wal.open_segment(name)
        wal.append(OnlyMarketDataRecordBundle(evidence, facts))
        return wal, wal.seal(sealed_at=AT), facts

    wal, segment, facts = sealed("wide", tuple(bar_update(index) for index in range(3)))
    published = drain(market_probe, database, wal, segment)
    assert published["manifest"]["coverage_status"] == "COMPLETE"
    scope = _scope_payload(segment.recovery_scope())
    start = scope["start_ns"]
    end = scope["end_ns"]
    assert isinstance(start, int) and isinstance(end, int)
    stride = (end - start) // 3
    intervals = [[start, start + stride], [start + 2 * stride, end]]
    if case in {"duplicate", "conflict"}:
        duplicate_wal, duplicate_segment, _ = sealed(
            "another", (bar_update(0, close="101.50000000" if case == "conflict" else "101.00000000"),)
        )
        assert (
            drain(market_probe, database, duplicate_wal, duplicate_segment)["manifest"]["coverage_status"] == "COMPLETE"
        )
    if case in {"timestamp", "payload"}:
        # This middle fact is outside both requested intervals but remains inside
        # the exact selected Revision, so its physical proof must still be read.
        payload = {**facts[1].canonical_payload, "ts_event": "malformed-timestamp"} if case == "timestamp" else {}
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
            facts[index].canonical_fact_id for index in (0, 2)
        ]
        assert len(result["facts"]) == 2
        assert len(result["evidence"]) == (2 if case == "duplicate" else 1)


def test_native_sealed_dataset_materialization_matches_sdk_and_survives_ack_loss(
    market_probe: Path, database: OnlyClickHouseClient, postgres_dsn: str, tmp_path: Path
) -> None:
    from onlyalpha.core.ranges import OnlyTimeRange
    from onlyalpha.research.dataset.definition import OnlyResearchDatasetDefinition
    from onlyalpha.research.dataset.identity import only_content_fingerprint, only_snapshot_fingerprint
    from onlyalpha.research.dataset.lineage import OnlyMarketDataRevisionBinding, only_dataset_materialization_id
    from onlyalpha.research.dataset.parquet_store import OnlyParquetResearchDatasetSnapshotStore
    from onlyalpha.research.dataset.schema import RESEARCH_BAR_DATASET_SCHEMA_V2
    from onlyalpha.research.dataset.sealed_input_identity import (
        OnlySealedMarketDataMaterializationPlan,
        only_sealed_market_data_input_fingerprints,
    )

    wal_root = tmp_path / "wal"
    wal_root.mkdir()
    wal, segment = retained(wal_root, "BAR")
    sealed = drain(market_probe, database, wal, segment)
    assert "error" not in sealed, sealed
    scope = segment.recovery_scope()
    assert scope.bar_construction is not None
    from onlyalpha.data.models import OnlyBarUpdate

    payload = bar_update(0).payload
    assert isinstance(payload, OnlyBarUpdate)
    bar = payload.bar
    definition = OnlyResearchDatasetDefinition(
        (bar.instrument_id,), bar.bar_type.semantic, OnlyTimeRange(bar.ts_event, bar.ts_event + timedelta(minutes=1))
    )
    revision = sealed["revision"]
    plan = OnlySealedMarketDataMaterializationPlan((revision["revision_id"],), definition, (scope,))
    construction, request = only_sealed_market_data_input_fingerprints(
        plan,
        (
            (
                str(bar.instrument_id),
                scope.bar_construction.fingerprint,
                revision["fingerprint"],
                sealed["seal"]["seal_id"],
            ),
        ),
    )
    expected = only_snapshot_fingerprint(
        definition, RESEARCH_BAR_DATASET_SCHEMA_V2, only_content_fingerprint((bar,)), 1, construction
    )
    dataset_root = tmp_path / "datasets"
    dataset_root.mkdir()
    args = dict(
        id=revision["revision_id"],
        definition=definition.to_dict(),
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
    binding = OnlyMarketDataRevisionBinding(
        scope.source_id, scope.instrument_id, "BAR", revision["revision_id"], revision["fingerprint"]
    )
    assert original["lineage"]["materialization_id"] == only_dataset_materialization_id(
        expected, (binding,), "onlyalpha.sealed-market-data", "1", request
    )
    # Independent reader, actual Parquet bytes and the original SDK Domain values.
    reader = OnlyParquetResearchDatasetSnapshotStore(dataset_root)
    assert reader.load_bars(expected) == (bar,)
    assert reader.load_materialization(original["lineage"]["materialization_id"]).request_fingerprint == request
    again = probe(market_probe, database, "dataset-materialize", **args)
    assert again == original
    # Existing immutable Snapshot stays readable when its physical source becomes
    # unprovable, but it cannot bless a new materialization from corrupt source.
    database.execute("ALTER TABLE market_bar UPDATE close = close + 1 WHERE 1 SETTINGS mutations_sync=2")
    refused = probe(market_probe, database, "dataset-materialize", **args)
    assert "error" in refused
    assert reader.load_bars(expected) == (bar,)


def test_native_executable_input_admission_retains_exact_runtime_and_sealed_dataset(
    market_probe: Path, database: OnlyClickHouseClient, postgres_dsn: str, tmp_path: Path
) -> None:
    from onlyalpha_runtime_generation_manager.registry import OnlyRuntimeGenerationRegistry

    from onlyalpha.core.ranges import OnlyTimeRange
    from onlyalpha.research.dataset.definition import OnlyResearchDatasetDefinition
    from packages.backend.tests.application.support.research_admission_reference import build

    wal_root = tmp_path / "wal"
    wal_root.mkdir()
    refs = []
    first = None
    last = None
    for i in range(2):
        wal, segment = retained(wal_root, "BAR", index=i, segment_id=f"admission-{i}")
        drained = drain(market_probe, database, wal, segment)
        assert "error" not in drained, drained
        refs.append((segment.segment_id, segment.content_hash))
        if first is None:
            first = segment.recovery_scope()
        last = segment.recovery_scope()
    assert first is not None and last is not None
    scope = replace(first, end_ns=last.end_ns)
    composed = probe(market_probe, database, "compose", scope=_scope_payload(scope), refs=refs)
    assert composed["revision"] is not None, composed
    first_update = bar_update(0).payload
    assert isinstance(first_update, OnlyBarUpdate)
    first_bar = first_update.bar
    end = first_bar.ts_event + timedelta(minutes=2)
    definition = OnlyResearchDatasetDefinition(
        (first_bar.instrument_id,), first_bar.bar_type.semantic, OnlyTimeRange(first_bar.ts_event, end)
    )
    factor = build(tmp_path / "runtime", market_probe.parent.parent / "onlyalpha-backend")
    dataset_root = tmp_path / "datasets"
    dataset_root.mkdir()
    args = dict(
        id=composed["revision"]["revision_id"],
        definition=definition.to_dict(),
        scope=_scope_payload(scope),
        dataset_root=str(dataset_root),
        factor=factor,
        observation_start_ns=str(scope.start_ns + 60_000_000_000),
        observation_end_ns=str(scope.end_ns + 60_000_000_000),
    )
    prepared = probe(market_probe, database, "dataset-admit", **args)
    assert "error" not in prepared, prepared
    assert prepared["contract"] == "ONLYALPHA_RESEARCH_PREPARED_INPUTS_V1"
    assert prepared["runtime_generation_fingerprint"] == factor["generation"]
    assert prepared["factor_revision_fingerprint"] == factor["revision"]["revision_fingerprint"]
    assert (
        prepared["dataset_materialization"]["dataset_snapshot_fingerprint"] == prepared["dataset_snapshot_fingerprint"]
    )
    assert probe(market_probe, database, "dataset-admit", **args) == prepared
    assert prepared["execution_binding"]["executor_artifact_sha256"] == factor["executor_sha256"]
    assert prepared["execution_binding"]["core_execution_fingerprint"] == factor["core_execution_fingerprint"]
    assert (
        prepared["execution_binding"]["executor_version"]
        == tomllib.loads((ROOT / "packages/backend/Cargo.toml").read_text())["package"]["version"]
    )
    # Exact native artifact corruption never becomes a different compatible executor.
    sha = factor["executor_sha256"]
    executable = Path(factor["runtime_root"]) / "artifacts" / sha[:2] / sha / "artifact.elf"
    original = executable.read_bytes()
    executable.write_bytes(original + b"tamper")
    assert "error" in probe(market_probe, database, "dataset-admit", **args)
    executable.write_bytes(original)
    registry = OnlyRuntimeGenerationRegistry(Path(factor["runtime_root"]))
    registry.release_work("research-input-fixture", actor="fixture", occurred_at=AT)
    refused = probe(market_probe, database, "dataset-admit", **args)
    assert "error" in refused


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


@pytest.fixture(scope="module")
def native_environment_case(tmp_path_factory: pytest.TempPathFactory, native_research_executor: Path) -> dict[str, Any]:
    import hashlib

    from scripts.build_algorithm_sdk import install
    from scripts.dev_verification import source_inputs
    from scripts.embed_build_provenance import resolve_build_provenance_bytes

    tmp_path = tmp_path_factory.mktemp("native-environment")
    root, runtime = tmp_path / "release", tmp_path / "runtime"
    root.mkdir()
    artifact = install(root / "wheels", root / "algorithms")
    (root / "bin").mkdir()
    executable = root / "bin/onlyalpha-backend"
    shutil.copyfile(native_research_executor, executable)
    executable.chmod(0o500)
    (root / "source-provenance.json").write_bytes(resolve_build_provenance_bytes(ROOT))
    files = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()
    }
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "runtime_root": str(root),
                "version": "0.11.1",
                "algorithm_artifact": artifact,
                "files": files,
                "source_inputs": source_inputs(ROOT),
            }
        )
    )
    vector = json.loads((Path(__file__).parent / "fixtures/research_factor.json").read_text())

    return {
        "root": root,
        "runtime": runtime,
        "executable": executable,
        "artifact": artifact,
        "vector": vector,
        "next": 0,
    }


@pytest.mark.parametrize("stage", ["prepare", "inspect", "relocate"])
def test_native_environment_publication_uses_installed_algorithms_and_original_metadata_contracts(
    native_environment_case: dict[str, Any], stage: str
) -> None:
    """Real persistent stage boundaries; never execute a missing prerequisite."""
    import hashlib

    from onlyalpha.canonical import only_canonical_json
    from onlyalpha.quant_assets.private_factor_provider_snapshot import OnlyPrivateFactorProviderSnapshotV1
    from onlyalpha_backend_algorithms.sdk.private_factor_execution import (
        OnlyPrivateFactorAdapterV1,
        OnlyPrivateFactorIsolatedProgramHost,
        OnlyPrivateFactorSourceArtifactManifestV1,
        only_private_factor_backend_registrations,
    )
    from onlyalpha_gateway_protocol.distribution import OnlyDistributionArtifactManifest
    from onlyalpha_plugin_operators.provider import quant_asset_provider

    from onlyalpha.generation_identity import OnlyRuntimeGenerationManifest, OnlyRuntimeGenerationValidationEvidence
    from onlyalpha.quant_assets import (
        OnlyPrivateFactorRevision,
        OnlyPrivateFactorSnapshotProviderSource,
        OnlyQuantAssetCatalogGeneration,
        OnlyQuantAssetKind,
        OnlyQuantAssetProvider,
        OnlyQuantAssetProviderManifest,
    )
    from scripts.build_algorithm_sdk import install

    case = native_environment_case
    assert stage == ["prepare", "inspect", "relocate"][case["next"]]
    root, runtime, executable, artifact, vector = (
        case[k] for k in ["root", "runtime", "executable", "artifact", "vector"]
    )

    def run(fresh: bool) -> dict[str, Any]:
        result = subprocess.run(
            [str(executable)],
            input=json.dumps(
                {
                    "op": "runtime-environment",
                    "factor": vector,
                    "release_root": str(root),
                    "runtime_root": str(runtime),
                    "algorithm_artifact": artifact,
                    "fresh": fresh,
                    "at": "2026-10-29T01:00:00.123400Z",
                }
            ),
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        )
        value = cast(dict[str, Any], json.loads(result.stdout))
        assert "error" not in value, (value, result.stderr)
        return value

    if stage == "prepare":
        first = run(True)
        generation = OnlyRuntimeGenerationManifest.from_dict(first["manifest"]).runtime_generation_fingerprint
        assert first["snapshot"] == {"active_for_new_work": None, "states": {generation: "READY"}}
        case.update(first=first, before=(runtime / "generation-events.jsonl").read_bytes(), next=1)
        return
    first, before = case["first"], case["before"]
    if stage == "relocate":
        # A locator is not a Generation identity. A fresh physical installation can
        # have a distinct installation proof while supplying the same exact bytes.
        previous = root
        root = root.parent / "relocated-release"
        root.mkdir()
        artifact = install(root / "wheels", root / "algorithms")
        (root / "bin").mkdir()
        shutil.copyfile(executable, root / "bin/onlyalpha-backend")
        (root / "bin/onlyalpha-backend").chmod(0o500)
        shutil.copyfile(previous / "source-provenance.json", root / "source-provenance.json")
        relocated = json.loads((previous / "manifest.json").read_text())
        relocated.update(
            runtime_root=str(root),
            algorithm_artifact=artifact,
            files={
                str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob("*")
                if p.is_file()
            },
        )
        (root / "manifest.json").write_text(json.dumps(relocated))
        rebuilt = run(False)
        assert rebuilt["manifest"] == first["manifest"]
        assert rebuilt["snapshot"] == first["snapshot"]
        assert rebuilt["proof"]["installed_proof_fingerprint"] != first["proof"]["installed_proof_fingerprint"]
        assert (runtime / "generation-events.jsonl").read_bytes() == before
        for record in [first, rebuilt]:
            proof = record["proof"]
            path = (
                runtime
                / "runtime-generation-installed-proof"
                / record["manifest"]["runtime_generation_fingerprint"]
                / f"{proof['installed_proof_fingerprint']}.json"
            )
            assert json.loads(path.read_text()) == proof
        case["next"] = 3
        return
    manifest = OnlyRuntimeGenerationManifest.from_dict(first["manifest"])
    generation = manifest.runtime_generation_fingerprint
    assert first["snapshot"] == {"active_for_new_work": None, "states": {generation: "READY"}}
    assert run(False) == first
    assert (runtime / "generation-events.jsonl").read_bytes() == before
    for sha in manifest.artifact_sha256s:
        artifact_manifest = json.loads((runtime / "artifacts" / sha[:2] / sha / "manifest.json").read_text())
        assert OnlyDistributionArtifactManifest.from_dict(artifact_manifest).to_dict() == artifact_manifest
    expected_validation = OnlyRuntimeGenerationValidationEvidence.from_manifest(manifest).to_dict()
    assert (
        json.loads((runtime / "runtime-generation-validation" / f"{generation}.json").read_text())
        == expected_validation
    )
    binding = manifest.private_factor_bindings[0]
    runtime_artifact = json.loads(
        (
            runtime
            / "artifacts/private-factor-runtime"
            / binding.runtime_artifact_fingerprint[:2]
            / f"{binding.runtime_artifact_fingerprint}.json"
        ).read_text()
    )
    source = OnlyPrivateFactorSourceArtifactManifestV1.from_dict(runtime_artifact["source_artifact"])
    revision = OnlyPrivateFactorRevision.from_dict(vector["revision"])
    snapshot = OnlyPrivateFactorProviderSnapshotV1.from_dict(runtime_artifact["provider_snapshot"])
    entry = snapshot.entries[0]
    registrations = only_private_factor_backend_registrations(
        revision,
        source,
        revision.source_text.encode(),
        OnlyPrivateFactorAdapterV1(
            "RESEARCH", entry.research_adapter_fingerprint, OnlyPrivateFactorIsolatedProgramHost()
        ),
        OnlyPrivateFactorAdapterV1(
            "TRADING", entry.trading_adapter_fingerprint, OnlyPrivateFactorIsolatedProgramHost()
        ),
    )
    private = OnlyQuantAssetProvider(
        OnlyQuantAssetProviderManifest(
            runtime_artifact["provider"]["manifest"]["provider_id"],
            revision.revision_fingerprint,
            OnlyQuantAssetKind.FACTOR,
            OnlyPrivateFactorSnapshotProviderSource(snapshot.snapshot_fingerprint),
        ),
        calculation_registrations=registrations,
        private_factor_snapshot=snapshot,
    )
    catalog = OnlyQuantAssetCatalogGeneration((quant_asset_provider(), private))
    assert first["proof"]["catalog"] == json.loads(only_canonical_json(catalog.descriptor(include_fingerprint=False)))
    assert manifest.catalog_generation_fingerprint == catalog.generation_fingerprint
    vectors = runtime_artifact["equivalence_evidence"]["test_vector_set_fingerprint"]
    retained = json.loads(
        (runtime / "artifacts/private-factor-equivalence" / vectors[:2] / f"{vectors}.json").read_text()
    )
    assert only_canonical_fingerprint(retained) == vectors
    case["next"] = 2


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
    from tests.research.postgres.conftest import reset_postgres_test_namespace

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
    database: OnlyClickHouseClient,
    postgres_dsn: str,
    tmp_path: Path,
    mode: str,
    native_research_algorithm_bundle: tuple[Path, Path, str],
) -> dict[str, Any]:
    import hashlib
    from uuid import UUID, uuid4

    from onlyalpha.core.ranges import OnlyTimeRange
    from onlyalpha.research.dataset.definition import OnlyResearchDatasetDefinition
    from onlyalpha.research.novelty.model import OnlyNoveltyPolicyRevisionV1
    from onlyalpha.research.novelty.store import OnlyNoveltyPolicyStore
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
    digest = bytearray(
        hashlib.sha256(b"ONLYALPHA_NOVELTY_GATED_RESEARCH_RUN_ID_V4\x1f" + command.encode()).digest()[:16]
    )
    digest[6] = (digest[6] & 15) | 64
    digest[8] = (digest[8] & 63) | 128
    work_id = str(UUID(bytes=bytes(digest)))
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
    research = semantic / "research"
    datasets = research / "datasets"
    datasets.mkdir(parents=True)
    projection = research / "experiment-memory"
    projection.mkdir()
    policy = json.loads((ROOT / "packages/backend/tests/application/fixtures/research_novelty.json").read_text())[
        "policy"
    ]
    OnlyNoveltyPolicyStore(semantic).put(OnlyNoveltyPolicyRevisionV1.from_dict(policy))
    source_roots = {
        "RESEARCH_RESULT": str(research / "results"),
        "RESEARCH_STATISTICS": str(research / "statistics-results"),
        "RESEARCH_FACTOR_PAIR_STATISTICS": str(research / "statistics-results"),
        "RESEARCH_SUMMARY_STATISTICS": str(research / "statistics-results"),
    }
    for family, name in [
        ("AGENT_PROVENANCE", "agent-provenance"),
        ("QUALIFICATION_DECISION", "qualification-decisions"),
        ("SEARCH_PROVENANCE", "search-provenance"),
    ]:
        directory = research / name
        directory.mkdir()
        (directory / "sha256").mkdir()
        (directory / ".source-cut.lock").touch(mode=0o600)
        source_roots[family] = str(directory)
    seed, segment = retained(tmp_path / "seed", segment_id="research-seed")
    evidence = seed.read_sealed(segment.segment_id)[0].evidence
    updates = tuple(bar_update(i, close=f"{100 + (i % 7) * 0.12 + (i % 11) * 0.01:.8f}") for i in range(128 + history))
    facts = tuple(
        OnlyCanonicalMarketFactRecord.bind(
            update,
            evidence,
            segment_id="research-input",
            ts_ingest_ns=123,
            normalizer_id="native-reference",
            normalizer_version="1",
        )
        for update in updates
    )
    wal = OnlyMarketDataWal(tmp_path / "wal", capacity_bytes=32 * 1024 * 1024, now=lambda: AT)
    wal.open_segment("research-input")
    wal.append(OnlyMarketDataRecordBundle(evidence, facts))
    segment = wal.seal(sealed_at=AT)
    assert "error" not in drain(actual, database, wal, segment)
    scope = segment.recovery_scope()
    composed = probe(
        actual, database, "compose", scope=_scope_payload(scope), refs=[(segment.segment_id, segment.content_hash)]
    )
    assert "error" not in composed, composed
    first_update = updates[0].payload
    assert isinstance(first_update, OnlyBarUpdate)
    first = first_update.bar.ts_event
    end = first + timedelta(minutes=128 + history)
    definition = OnlyResearchDatasetDefinition(
        (first_update.bar.instrument_id,), first_update.bar.bar_type.semantic, OnlyTimeRange(first, end)
    )
    start_ns = scope.start_ns + (history + 1) * 60_000_000_000
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
        definition=definition.to_dict(),
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
        initialize_evidence=True,
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
        "wrong-native-version": "FAILED",
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

    from onlyalpha_gateway_protocol.distribution import OnlyDistributionArtifactManifest

    from onlyalpha.generation_identity import OnlyRuntimeGenerationManifest

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
    manifest = OnlyRuntimeGenerationManifest.from_dict(first["manifest"])
    assert first["snapshot"] == {
        "active_for_new_work": None,
        "states": {manifest.runtime_generation_fingerprint: "READY"},
    }
    assert (
        len(manifest.artifact_sha256s)
        == len(OnlyRuntimeGenerationManifest.from_dict(legacy["manifest"]).artifact_sha256s) + 1
    )
    artifacts = [
        json.loads((runtime / "artifacts" / digest[:2] / digest / "manifest.json").read_text())
        for digest in manifest.artifact_sha256s
    ]
    targets = [m for m in artifacts if m["distribution_name"] == "onlyalpha-plugin-targets"]
    assert len(targets) == 1
    target = targets[0]
    assert OnlyDistributionArtifactManifest.from_dict(target).to_dict() == target
    assert target["role"] == "CALCULATION" and target["schema_version"] == 1
    assert target["tested_core_execution_fingerprint"] == manifest.core_execution.fingerprint
    assert target["assets"] == []
    assert all(target[k] is None for k in ("provider_id", "provider_version", "provider_content_fingerprint"))
    assert target["implementations"]
    assert all(i["kind"] == "TARGET" and i["backend"] == "RESEARCH" for i in target["implementations"])
    assert all(i in first["manifest"]["implementations"] for i in target["implementations"])
    wheel = next((root / "wheels").glob("onlyalpha_plugin_targets-*.whl"))
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


def strategy_preparation_case(
    native_environment_case: dict[str, Any],
    market_probe: Path,
    database: OnlyClickHouseClient,
    tmp_path: Path,
    fault: str = "normal",
    work_id: str = "use_test_strategy_prepare",
    runtime_root: Path | None = None,
    first_bar_start: datetime | None = None,
    manual_only: bool = False,
) -> dict[str, Any]:
    from uuid import uuid4

    from onlyalpha.core.ranges import OnlyTimeRange
    from onlyalpha.research.dataset.definition import OnlyResearchDatasetDefinition
    from packages.backend.tests.application.test_private_strategy_authoring_postgres import call as author

    # Reuse the real sealed-release producer, rather than a caller-authored
    # Runtime manifest or a value-test preparation grant.
    case = native_environment_case
    executable, release, artifact, vector = (case[k] for k in ["executable", "root", "artifact", "vector"])
    runtime = runtime_root if runtime_root is not None else tmp_path / "use_test_strategy_runtime"
    generation = None
    if not manual_only:
        try:
            result = subprocess.run(
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
                        "bind_work": work_id,
                        "activation_command": str(uuid4()),
                        "at": "2026-11-01T01:00:00Z",
                    }
                ),
                text=True,
                capture_output=True,
                check=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired as error:
            # Preserve the original deadline and expose only the probe's bounded
            # phase markers; the request and deployment environment are not logged.
            for line in (error.stderr or b"").decode("utf-8", errors="replace").splitlines():
                if line.startswith("[runtime-environment] phase="):
                    print(line, flush=True)
            raise
        environment = json.loads(result.stdout)
        assert "error" not in environment, (environment, result.stderr)
        generation = environment["manifest"]["runtime_generation_fingerprint"]
        assert environment["snapshot"]["active_for_new_work"] == generation
    saved = author(
        market_probe,
        vector["draft"]["factor_id"],
        "save",
        op="factor-authoring",
        factor_id=vector["draft"]["factor_id"],
        draft=vector["draft"],
        expected=None,
    )
    assert "error" not in saved, saved
    published = author(
        market_probe,
        vector["draft"]["factor_id"],
        "publish",
        op="factor-authoring",
        factor_id=vector["draft"]["factor_id"],
        expected=saved["result"]["draft_fingerprint"],
    )
    assert published["result"]["revision"] == vector["revision"]

    # Controlled market inputs enter through existing WAL/seal/catalog owners.
    # They are technical inputs, never claimed as real Binance observations.
    seed, seed_segment = retained(tmp_path / "seed", segment_id="use-test-strategy-seed")
    evidence = seed.read_sealed(seed_segment.segment_id)[0].evidence
    evaluating = manual_only or fault == "evaluate" or fault.startswith("eval-")
    row_count = 740 if evaluating else 28
    updates = tuple(
        bar_update(
            i,
            close="101.20200000" if i == 20 else "100.89900000" if i == 21 else "101.00000000",
            first_bar_start=first_bar_start,
        )
        for i in range(row_count)
    )
    facts = tuple(
        OnlyCanonicalMarketFactRecord.bind(
            update,
            evidence,
            segment_id="use-test-strategy-input",
            ts_ingest_ns=123,
            normalizer_id="native-reference",
            normalizer_version="1",
        )
        for update in updates
    )
    wal = OnlyMarketDataWal(tmp_path / "wal", capacity_bytes=32 * 1024 * 1024, now=lambda: AT)
    wal.open_segment("use-test-strategy-input")
    wal.append(OnlyMarketDataRecordBundle(evidence, facts))
    segment = wal.seal(sealed_at=AT)
    assert "error" not in drain(executable, database, wal, segment)
    scope = segment.recovery_scope()
    composed = probe(
        executable, database, "compose", scope=_scope_payload(scope), refs=[(segment.segment_id, segment.content_hash)]
    )
    assert "error" not in composed, composed
    first_update = updates[0].payload
    assert isinstance(first_update, OnlyBarUpdate)
    first = first_update.bar.ts_event
    definition = OnlyResearchDatasetDefinition(
        (first_update.bar.instrument_id,),
        first_update.bar.bar_type.semantic,
        OnlyTimeRange(first, first + timedelta(minutes=row_count)),
    )
    dataset_root = tmp_path / "datasets"
    dataset_root.mkdir()

    calculations = json.loads(
        (ROOT / "packages/backend/tests/application/fixtures/strategy_calculations.json").read_text()
    )
    seed_strategy = json.loads((ROOT / "examples/private-assets/strategy/simple_momentum/strategy.json").read_text())[
        "strategy"
    ]["definition"]
    seed_strategy["calculations"] = calculations["instances"]
    seed_strategy["factor_revision_dependencies"] = calculations["factor_revision_dependencies"]
    seed_strategy["signals"]["entry"]["operator"] = ">="
    seed_strategy["signals"]["entry"]["right"]["value"]["value"] = "0.001"
    seed_strategy["universe"] = {"kind": "SINGLE_INSTRUMENT", "instruments": [str(first_update.bar.instrument_id)]}
    seed_strategy["market_input"]["bar_semantic"] = definition.to_dict()["bar_semantic"]
    seed_strategy["market_input"]["construction_requirement"]["recipe"] = _scope_payload(scope)["bar_construction"][
        "plan"
    ]["resolved_recipe"]
    strategy_id = "private.strategy.use_test_s" + uuid4().hex
    strategy = {
        "schema_version": 1,
        "strategy_id": strategy_id,
        "base_revision_fingerprint": None,
        "semantic_version": "1",
        "description": "Actual input proof",
        "tags": [],
        "definition": seed_strategy,
    }
    saved = author(market_probe, strategy_id, "save", draft=strategy, expected=None)
    assert "error" not in saved, saved
    revision = author(market_probe, strategy_id, "publish", expected=saved["result"]["draft_fingerprint"])["result"][
        "revision"
    ]
    context = None
    if not manual_only:
        reference = json.loads(
            (ROOT / "packages/backend/tests/application/fixtures/strategy_specification.json").read_text()
        )
        context = {
            "schema_version": 1,
            "start": (first + timedelta(minutes=20)).isoformat(),
            "end": (first + timedelta(minutes=29 if fault == "window" else row_count)).isoformat(),
            "targets": [
                {
                    "instance_key": "forward_return",
                    "type_reference": {
                        "kind": "TARGET",
                        "type_id": "onlyalpha.target.forward_return",
                        "semantic_version": "1",
                    },
                    "parameters": {"exit_offset": {"kind": "FIXED", "value": {"type": "INTEGER", "value": 5}}},
                    "published_outputs": ["target_value"],
                    "primary_output": None,
                    "input_bindings": [
                        {"input_name": "entry_price", "source": "bar.close"},
                        {"input_name": "exit_price", "source": "bar.close"},
                    ],
                }
            ],
            "statistics": [
                {
                    "variable": {"kind": "VARIABLE", "instance_key": "momentum", "output_name": "value"},
                    "target_instance_key": "forward_return",
                    "definition": reference["specification"]["statistics"][0]["definition"],
                }
            ],
            "display_metadata": {},
        }
        if evaluating:
            rank = context["statistics"][0]
            context["statistics"].append({**rank, "definition": {**rank["definition"], "method": "RANK_IC"}})
    selected = executable
    if fault == "native":
        selected = tmp_path / "different-backend-image"
        selected.write_bytes(executable.read_bytes() + b"\n# different actual loaded native image\n")
        selected.chmod(0o500)
    arguments = dict(
        id=composed["revision"]["revision_id"],
        definition=definition.to_dict(),
        scope=_scope_payload(scope),
        dataset_root=str(dataset_root),
        strategy_id=strategy_id,
        strategy_revision=revision["revision_fingerprint"],
        strategy_context=context,
        strategy_fault=fault,
        strategy_evaluation=evaluating,
        runtime_root=str(runtime),
        runtime_generation=generation,
        algorithm_root=str(release / "algorithms"),
        algorithm_artifact=artifact,
    )
    return dict(
        selected=selected,
        arguments=arguments,
        vector=vector,
        revision=revision,
        strategy_id=strategy_id,
        evaluating=evaluating,
        updates=updates,
    )


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
    database: OnlyClickHouseClient,
    postgres_dsn: str,
    tmp_path: Path,
    fault: str,
) -> None:
    prepared_case = strategy_preparation_case(native_environment_case, market_probe, database, tmp_path, fault)
    selected, arguments, vector, revision, strategy_id, evaluating = (
        prepared_case[k] for k in ["selected", "arguments", "vector", "revision", "strategy_id", "evaluating"]
    )
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
        assert actual == {"error": expected}
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
        _assert_actual_strategy_evaluation(actual, prepared_case["updates"])
    assert probe(selected, database, "dataset-strategy-prepare", **arguments) == actual


def _assert_actual_strategy_evaluation(
    actual: dict[str, Any], updates: tuple[OnlyMarketDataInboundUpdate, ...]
) -> None:
    """Independent value checks over two actual numerical producers; no evidence grant."""
    from onlyalpha.calculation.definition import OnlyCalculationDefinition

    from onlyalpha.domain.time import OnlyTimestamp
    from onlyalpha.research.evaluation.plan import OnlyResearchStatisticsPlan
    from onlyalpha.research.evaluation.result import OnlyResearchStatisticRow, OnlyResearchStatisticStatus

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
    assert all(isinstance(update.payload, OnlyBarUpdate) for update in updates)
    axis = [
        OnlyTimestamp.from_datetime(cast(OnlyBarUpdate, update.payload).bar.ts_event).to_unix_nanos()
        for update in updates
    ]
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
        plan = OnlyResearchStatisticsPlan.from_dict(result["plan"])
        assert plan.statistics_fingerprint == result["statistics_fingerprint"]
        assert plan.definition.method.value in {"IC", "RANK_IC"}
        assert plan.feature.node_fingerprint == factor
        assert plan.target.node_fingerprint in targets
        assert [row["ts_event_ns"] for row in result["rows"]] == axis
        assert len(result["rows"]) == 740
        for index, row in enumerate(result["rows"]):
            # Existing public Stats1: one cross-section per timestamp, not one
            # 720-observation time-series correlation or invented significance.
            count = int(feature[index]["type"] != "NULL" and target[index]["type"] != "NULL")
            expected = OnlyResearchStatisticRow(
                axis[index], None, count, OnlyResearchStatisticStatus.INSUFFICIENT_OBSERVATIONS
            )
            assert row == expected.semantic_payload()
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
    database: OnlyClickHouseClient,
    postgres_dsn: str,
    tmp_path: Path,
    mode: str,
) -> None:
    from uuid import UUID, uuid4

    from onlyalpha.research.novelty.model import OnlyNoveltyPolicyRevisionV1
    from onlyalpha.research.novelty.store import OnlyNoveltyPolicyStore

    command = str(uuid4())
    digest = bytearray(
        hashlib.sha256(b"ONLYALPHA_NOVELTY_GATED_RESEARCH_RUN_ID_V4\x1f" + command.encode()).digest()[:16]
    )
    digest[6], digest[8] = (digest[6] & 15) | 64, (digest[8] & 63) | 128
    work_id = str(UUID(bytes=bytes(digest)))
    case = strategy_preparation_case(native_environment_case, market_probe, database, tmp_path, work_id=work_id)
    selected, arguments = case["selected"], case["arguments"]
    semantic = tmp_path / "use_test_semantic"
    research = semantic / "research"
    dataset_root, projection = research / "datasets", research / "experiment-memory"
    dataset_root.mkdir(parents=True)
    projection.mkdir()
    policy = json.loads((ROOT / "packages/backend/tests/application/fixtures/research_novelty.json").read_text())[
        "policy"
    ]
    OnlyNoveltyPolicyStore(semantic).put(OnlyNoveltyPolicyRevisionV1.from_dict(policy))
    roots = {
        "RESEARCH_RESULT": str(research / "results"),
        "RESEARCH_STATISTICS": str(research / "statistics-results"),
        "RESEARCH_FACTOR_PAIR_STATISTICS": str(research / "statistics-results"),
        "RESEARCH_SUMMARY_STATISTICS": str(research / "statistics-results"),
    }
    for family, name in [
        ("AGENT_PROVENANCE", "agent-provenance"),
        ("QUALIFICATION_DECISION", "qualification-decisions"),
        ("SEARCH_PROVENANCE", "search-provenance"),
    ]:
        directory = research / name
        directory.mkdir()
        (directory / "sha256").mkdir()
        (directory / ".source-cut.lock").touch(mode=0o600)
        roots[family] = str(directory)
    review_file = tmp_path / "use_test_original_review.json"
    arguments.update(
        dataset_root=str(dataset_root),
        research_command=command,
        submission_mode=mode,
        semantic_root=str(semantic),
        research_root=str(research),
        projection_root=str(projection),
        source_roots=roots,
        initialize_evidence=True,
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
    from tests.support.postgres_link import wait_no_advisory_locks

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

    from onlyalpha.calculation.equivalence import only_required_calculation_equivalence_profile

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
        required = only_required_calculation_equivalence_profile(definition)
        assert node["profile_covered_cases"] == list(required.cases)
        assert node["research_implementation_fingerprint"] == bindings[key]["research_implementation_fingerprint"]
        assert node["trading_implementation_fingerprint"] == bindings[key]["trading_implementation_fingerprint"]
        cases = {row["case_id"]: row for row in node["cases"]}
        assert len(cases) == len(node["cases"]) == len(required.cases) and cases.keys() == set(required.cases)
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
