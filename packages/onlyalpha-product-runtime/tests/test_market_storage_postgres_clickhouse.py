"""Native PG/CH storage capability, controlled technical fixtures only; no UI claim."""

from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import threading
import tomllib
import urllib.request
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

import psycopg
import pytest

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_payload
from onlyalpha.data.models import OnlyMarketDataInboundUpdate
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
    OnlyClickHouseMigrationAuthority,
    only_assert_clickhouse_test_database,
)
from onlyalpha.persistence.clickhouse.market_data_store import _physical_row_sql, _quote
from onlyalpha.persistence.postgres.market_data_catalog import OnlyPostgresMarketDataCatalog, _scope_payload
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from tests.market_data_durable.conftest import bar_update, reference_update, trade_update

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.clickhouse, pytest.mark.timeout(120)]
AT = datetime(2026, 10, 22, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")
def market_probe() -> Path:
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
            "--target",
            target,
            "-j1",
            "-p",
            "onlyalpha-product-runtime",
            "--example",
            "command-postgres-probe",
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )
    return output / target / "debug/examples/command-postgres-probe"


@pytest.fixture
def database(postgres_dsn: str) -> Iterator[OnlyClickHouseClient]:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    name = "onlyalpha_test_native_market_storage"
    only_assert_clickhouse_test_database(name)
    config = OnlyClickHouseConfig(
        os.environ["ONLYALPHA_TEST_CLICKHOUSE_URL"],
        database=name,
        user=os.environ.get("ONLYALPHA_TEST_CLICKHOUSE_USER", "default"),
        password=os.environ.get("ONLYALPHA_TEST_CLICKHOUSE_PASSWORD", ""),
        storage_policy=os.environ.get("ONLYALPHA_TEST_CLICKHOUSE_STORAGE_POLICY", "hot_cold"),
    )
    client = OnlyClickHouseClient(config)
    client.execute(f"DROP DATABASE IF EXISTS {name} SYNC", database="default")
    OnlyClickHouseMigrationAuthority(client).migrate()
    try:
        yield client
    finally:
        client.execute(f"DROP DATABASE IF EXISTS {name} SYNC", database="default")


def probe(binary: Path, client: OnlyClickHouseClient, op: str, **values: Any) -> dict[str, Any]:
    request = {"op": op, "at": AT.isoformat(), "database": client.config.database, "url": client.config.url, **values}
    env = dict(os.environ)
    env.update(ONLYALPHA_CLICKHOUSE_USER=client.config.user, ONLYALPHA_CLICKHOUSE_PASSWORD=client.config.password)
    result = subprocess.run(
        [str(binary)],
        input=json.dumps({"op": "market-storage", "request": request}),
        text=True,
        capture_output=True,
        timeout=30,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return cast(dict[str, Any], json.loads(result.stdout))


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
    result = probe(market_probe, database, "range", scope=scope, intervals=intervals)
    if case == "conflict":
        assert result == {"error": "MARKET_DATA_IDENTITY_CONFLICT"}
    elif case in {"timestamp", "payload"}:
        assert result == {"error": "MARKET_DATA_EVIDENCE_UNPROVABLE"}
    else:
        assert result["status"] == "COMPLETE"
        assert result["complete_intervals"] == result["expected"] == 2
        assert result["gaps"] == result["issues"] == []
        assert {fact["canonical_fact_id"] for fact in result["facts"]} == {
            facts[index].canonical_fact_id for index in (0, 2)
        }
        assert len(result["facts"]) == 2
        assert len(result["evidence"]) == (2 if case == "duplicate" else 1)
