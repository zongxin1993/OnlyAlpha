"""Native PostgreSQL migration and read-only schema admission checks."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from scripts.native_http_contract import native_executable

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.timeout(120)]


DEFAULT_MIGRATION_ROOT = Path(__file__).resolve().parents[4] / "database/postgres/migrations"


@pytest.fixture(scope="session")
def migration_backend() -> Path:
    return native_executable()


def migrate(backend: Path, dsn: str, root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(backend), "--migrate-postgres-schema", str(root)],
        env={**os.environ, "ONLYALPHA_POSTGRES_DSN": make_conninfo(dsn, sslmode="disable")},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


@pytest.fixture
def schema_db(postgres_dsn: str, migration_backend: Path) -> str:
    result = migrate(migration_backend, postgres_dsn, DEFAULT_MIGRATION_ROOT)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"applied": [item[0] for item in request()["migrations"]]}
    return postgres_dsn


def test_schema_migration_is_idempotent_and_refuses_changed_bytes(migration_backend: Path, schema_db: str) -> None:
    before = facts(schema_db)
    result = migrate(migration_backend, schema_db, DEFAULT_MIGRATION_ROOT)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"applied": []}
    with psycopg.connect(schema_db) as connection:
        connection.execute(
            "UPDATE public.onlyalpha_schema_migration SET checksum_sha256 = %s WHERE migration_id = %s",
            (hashlib.sha256(b"changed bytes").hexdigest(), before[0][0]),
        )
    tampered = facts(schema_db)
    result = migrate(migration_backend, schema_db, DEFAULT_MIGRATION_ROOT)
    assert result.returncode == 1
    assert result.stderr.strip() == "POSTGRES_MIGRATION_INTEGRITY_ERROR"
    assert facts(schema_db) == tampered


def test_native_authoring_run_rejects_incomplete_binding_before_attempt(schema_db: str) -> None:
    run = str(uuid4())
    statement = (
        "INSERT INTO research_run(run_id,revision,state,specification_schema_version,specification_fingerprint,"
        "specification_payload,admission_resolution_fingerprint,queued_at,"
        "calculation_execution_evidence_fingerprints,origin_kind) "
        "VALUES(%s,0,'QUEUED',6,%s,%s,%s,clock_timestamp(),ARRAY[]::text[],'GENERAL')"
    )
    complete = {
        "schema_version": 6,
        "kind": "TIME_SERIES_FACTOR_RESEARCH",
        "authoring_generation_fingerprint": "a" * 64,
    }
    with psycopg.connect(schema_db) as connection:
        for field in complete:
            body = {key: value for key, value in complete.items() if key != field}
            with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
                connection.execute(statement, (run, "b" * 64, json.dumps(body), "c" * 64))
        with pytest.raises(psycopg.errors.RaiseException, match="NATIVE_FACTOR_RESEARCH_RELATION_CORRUPT"):
            with connection.transaction():
                connection.execute(statement, (run, "b" * 64, json.dumps(complete), "c" * 64))
        assert connection.execute("SELECT count(*) FROM research_run_attempt WHERE run_id=%s", (run,)).fetchone() == (0,)


def test_schema_migration_respects_existing_operator_lock(migration_backend: Path, postgres_dsn: str) -> None:
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("SELECT pg_catalog.pg_advisory_lock(591487210081::bigint)")
        blocked = migrate(migration_backend, postgres_dsn, DEFAULT_MIGRATION_ROOT)
        assert blocked.returncode == 1
        assert blocked.stderr.strip() == "RESEARCH_RUN_STORE_UNAVAILABLE"
        assert connection.execute("SELECT to_regclass('public.onlyalpha_schema_migration')").fetchone() == (None,)
        assert connection.execute("SELECT pg_catalog.pg_advisory_unlock(591487210081::bigint)").fetchone() == (True,)
    result = migrate(migration_backend, postgres_dsn, DEFAULT_MIGRATION_ROOT)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"applied": [item[0] for item in request()["migrations"]]}


@pytest.mark.parametrize("failure", ["SELECT 1 / 0;", "COMMIT;"])
def test_schema_migration_rolls_back_all_pending_files(
    migration_backend: Path, postgres_dsn: str, tmp_path: Path, failure: str
) -> None:
    root = tmp_path / "migrations"
    root.mkdir(mode=0o700)
    (root / "0001_ledger.sql").write_text(
        "CREATE TABLE onlyalpha_schema_migration(migration_id text PRIMARY KEY, checksum_sha256 text NOT NULL);"
    )
    (root / "0002_invalid.sql").write_text(f"CREATE TABLE should_rollback(id integer); {failure}")
    result = migrate(migration_backend, postgres_dsn, root)
    assert result.returncode == 1
    assert result.stderr.strip() == "POSTGRES_MIGRATION_INTEGRITY_ERROR"
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute(
            "SELECT to_regclass('public.onlyalpha_schema_migration'), to_regclass('public.should_rollback')"
        ).fetchone() == (None, None)


def call(probe: Path, request: dict[str, Any]) -> dict[str, Any]:
    result = subprocess.run([str(probe)], input=json.dumps(request), text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    return cast(dict[str, Any], json.loads(result.stdout))


def request(**changes: Any) -> dict[str, Any]:
    return dict(
        {
            "op": "schema",
            "command_id": str(uuid4()),
            "migrations": [
                [p.stem, {"path": str(p)}] for p in sorted(DEFAULT_MIGRATION_ROOT.glob("[0-9][0-9][0-9][0-9]_*.sql"))
            ],
            "rows": 1024,
            "work": 1024 * 1024,
        },
        **changes,
    )


def facts(dsn: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn) as connection:
        return list(
            connection.execute("SELECT * FROM public.onlyalpha_schema_migration ORDER BY migration_id").fetchall()
        )


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("none", "COMPATIBLE"),
        ("missing", "LEDGER_MISSING"),
        ("empty", "BEHIND"),
        ("last", "BEHIND"),
        ("first", "HISTORY_DIVERGED"),
        ("checksum", "CHECKSUM_MISMATCH"),
        ("unknown", "AHEAD"),
        ("unknown-and-checksum", "AHEAD"),
        ("hole-and-checksum", "CHECKSUM_MISMATCH"),
    ],
)
def test_complete_schema_verdicts_preserve_authority_and_priority(
    native_probe: Path, schema_db: str, mutation: str, expected: str
) -> None:
    ids = [item[0] for item in request()["migrations"]]
    with psycopg.connect(schema_db) as connection:
        if mutation == "missing":
            connection.execute("DROP TABLE public.onlyalpha_schema_migration")
        elif mutation == "empty":
            connection.execute("DELETE FROM public.onlyalpha_schema_migration")
        elif mutation in {"last", "first", "hole-and-checksum"}:
            connection.execute(
                "DELETE FROM public.onlyalpha_schema_migration WHERE migration_id=%s",
                (ids[-1] if mutation == "last" else ids[0],),
            )
        if mutation in {"checksum", "unknown-and-checksum", "hole-and-checksum"}:
            connection.execute(
                "UPDATE public.onlyalpha_schema_migration SET checksum_sha256=%s WHERE migration_id=%s",
                ("0" * 64, ids[1]),
            )
        if mutation in {"unknown", "unknown-and-checksum"}:
            connection.execute(
                "INSERT INTO public.onlyalpha_schema_migration(migration_id,checksum_sha256) VALUES('9999_unknown',%s)",
                ("1" * 64,),
            )
    before = None if mutation == "missing" else facts(schema_db)
    assert call(native_probe, request()) == {"verdict": expected}
    if mutation == "missing":
        with psycopg.connect(schema_db) as connection:
            assert connection.execute("SELECT to_regclass('public.onlyalpha_schema_migration')").fetchone() == (None,)
    else:
        assert facts(schema_db) == before


def test_expected_history_hashes_exact_sql_bytes_and_sorts_identity_pairs(native_probe: Path, schema_db: str) -> None:
    command = request()
    command["migrations"].reverse()
    before = facts(schema_db)
    assert call(native_probe, command) == {"verdict": "COMPATIBLE"}
    path = Path(command["migrations"][0][1]["path"])
    command["migrations"][0][1] = path.read_bytes().decode("utf-8") + "\n-- additional source bytes\n"
    assert call(native_probe, command) == {"verdict": "CHECKSUM_MISMATCH"}
    assert facts(schema_db) == before


@pytest.mark.parametrize("mutation", ["duplicate", "null-checksum", "wrong-checksum-family", "wrong-id-family"])
def test_incomplete_or_corrupt_ledger_cannot_be_a_complete_mismatch_or_match(
    native_probe: Path, schema_db: str, mutation: str
) -> None:
    first = request()["migrations"][0][0]
    with psycopg.connect(schema_db) as connection:
        if mutation == "duplicate":
            connection.execute(
                "ALTER TABLE public.onlyalpha_schema_migration DROP CONSTRAINT onlyalpha_schema_migration_pkey"
            )
            connection.execute(
                "INSERT INTO public.onlyalpha_schema_migration SELECT * FROM public.onlyalpha_schema_migration WHERE migration_id=%s",
                (first,),
            )
        elif mutation == "null-checksum":
            connection.execute(
                "ALTER TABLE public.onlyalpha_schema_migration ALTER COLUMN checksum_sha256 DROP NOT NULL"
            )
            connection.execute(
                "UPDATE public.onlyalpha_schema_migration SET checksum_sha256=NULL WHERE migration_id=%s", (first,)
            )
        elif mutation == "wrong-checksum-family":
            connection.execute(
                "ALTER TABLE public.onlyalpha_schema_migration DROP CONSTRAINT onlyalpha_schema_migration_checksum_sha256_check"
            )
            connection.execute(
                "UPDATE public.onlyalpha_schema_migration SET checksum_sha256=%s WHERE migration_id=%s",
                ("A" * 64, first),
            )
        else:
            connection.execute(
                "UPDATE public.onlyalpha_schema_migration SET migration_id='not-migration' WHERE migration_id=%s",
                (first,),
            )
    before = facts(schema_db)
    assert call(native_probe, request()) == {"error": "POSTGRES_MIGRATION_INTEGRITY_ERROR"}
    assert facts(schema_db) == before


@pytest.mark.parametrize("rows", [0, 1, 18446744073709551615])
def test_row_budget_failure_is_not_a_schema_verdict(native_probe: Path, schema_db: str, rows: int) -> None:
    before = facts(schema_db)
    assert call(native_probe, request(rows=rows)) == {"error": "RESEARCH_RUN_STORE_UNAVAILABLE"}
    assert facts(schema_db) == before


def test_exact_row_budget_and_normal_one_unknown_are_distinct_from_overflow(native_probe: Path, schema_db: str) -> None:
    count = len(request()["migrations"])
    assert call(native_probe, request(rows=count)) == {"verdict": "COMPATIBLE"}
    with psycopg.connect(schema_db) as connection:
        connection.execute(
            "INSERT INTO public.onlyalpha_schema_migration(migration_id,checksum_sha256) VALUES('9999_unknown',%s)",
            ("1" * 64,),
        )
    before = facts(schema_db)
    assert call(native_probe, request(rows=count)) == {"error": "RESEARCH_RUN_STORE_UNAVAILABLE"}
    assert call(native_probe, request(rows=count + 1)) == {"verdict": "AHEAD"}
    assert facts(schema_db) == before


@pytest.mark.parametrize("mutation", ["empty", "duplicate", "wrong-id", "budget"])
def test_expected_source_proof_is_not_adopted_from_the_database(
    native_probe: Path, schema_db: str, mutation: str
) -> None:
    command = request()
    before = facts(schema_db)
    if mutation == "empty":
        command["migrations"] = []
    elif mutation == "duplicate":
        command["migrations"].append(command["migrations"][0])
    elif mutation == "wrong-id":
        command["migrations"][0][0] = "bad-source"
    else:
        command["work"] = 0
    assert call(native_probe, command) == {
        "error": "RESEARCH_RUN_STORE_UNAVAILABLE" if mutation == "budget" else "POSTGRES_MIGRATION_INTEGRITY_ERROR"
    }
    assert facts(schema_db) == before


def test_lost_connection_cannot_be_ledger_absence(native_probe: Path, schema_db: str) -> None:
    before = facts(schema_db)
    assert call(native_probe, request(op="schema-lost-connection")) == {"error": "RESEARCH_RUN_STORE_UNAVAILABLE"}
    assert facts(schema_db) == before


@pytest.mark.parametrize("canonical_missing", [False, True])
def test_search_path_cannot_substitute_the_canonical_ledger(
    native_probe: Path, schema_db: str, canonical_missing: bool
) -> None:
    before = facts(schema_db)
    with psycopg.connect(schema_db) as connection:
        connection.execute("CREATE SCHEMA controlled_schema_shadow")
        connection.execute(
            "CREATE TABLE controlled_schema_shadow.onlyalpha_schema_migration (LIKE public.onlyalpha_schema_migration INCLUDING ALL)"
        )
        connection.execute(
            "INSERT INTO controlled_schema_shadow.onlyalpha_schema_migration SELECT * FROM public.onlyalpha_schema_migration"
        )
        if canonical_missing:
            connection.execute("DROP TABLE public.onlyalpha_schema_migration")
        else:
            connection.execute(
                "UPDATE controlled_schema_shadow.onlyalpha_schema_migration SET checksum_sha256=%s", ("0" * 64,)
            )
    try:
        assert call(native_probe, request(search_path="controlled_schema_shadow,public")) == {
            "verdict": "LEDGER_MISSING" if canonical_missing else "COMPATIBLE"
        }
        if not canonical_missing:
            assert facts(schema_db) == before
    finally:
        with psycopg.connect(schema_db) as connection:
            connection.execute("DROP SCHEMA controlled_schema_shadow CASCADE")


@pytest.mark.parametrize(
    ("size", "expected"), [(512, {"verdict": "AHEAD"}), (513, {"error": "RESEARCH_RUN_STORE_UNAVAILABLE"})]
)
def test_ledger_identity_byte_budget_is_not_a_partial_history(
    native_probe: Path, schema_db: str, size: int, expected: dict[str, str]
) -> None:
    first = request()["migrations"][0][0]
    with psycopg.connect(schema_db) as connection:
        connection.execute(
            "UPDATE public.onlyalpha_schema_migration SET migration_id=%s WHERE migration_id=%s",
            ("0000_" + "x" * (size - 5), first),
        )
    before = facts(schema_db)
    assert call(native_probe, request()) == expected
    assert facts(schema_db) == before


@pytest.mark.parametrize("size", [63, 65])
def test_wrong_checksum_length_is_corrupt_proof(native_probe: Path, schema_db: str, size: int) -> None:
    first = request()["migrations"][0][0]
    with psycopg.connect(schema_db) as connection:
        connection.execute(
            "ALTER TABLE public.onlyalpha_schema_migration DROP CONSTRAINT onlyalpha_schema_migration_checksum_sha256_check"
        )
        connection.execute(
            "UPDATE public.onlyalpha_schema_migration SET checksum_sha256=%s WHERE migration_id=%s", ("a" * size, first)
        )
    before = facts(schema_db)
    assert call(native_probe, request()) == {"error": "POSTGRES_MIGRATION_INTEGRITY_ERROR"}
    assert facts(schema_db) == before


def test_native_research_deployment_binds_exact_namespace(
    migration_backend: Path, schema_db: str, tmp_path: Path
) -> None:
    def initialize(root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(migration_backend), "--initialize-research-deployment", str(root), str(DEFAULT_MIGRATION_ROOT)],
            env={**os.environ, "ONLYALPHA_POSTGRES_DSN": make_conninfo(schema_db, sslmode="disable")},
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    root = tmp_path / "deployment"
    root.mkdir(mode=0o700)
    with psycopg.connect(schema_db) as connection:
        connection.execute("SELECT pg_catalog.pg_advisory_lock(1329199301, 5)")
        busy = initialize(root)
        assert busy.returncode == 1 and busy.stderr.strip() == "PRODUCT_KERNEL_AUTHORITY_ALREADY_HELD"
        assert not (root / "research").exists()
        assert connection.execute("SELECT pg_catalog.pg_advisory_unlock(1329199301, 5)").fetchone() == (True,)

    first = initialize(root)
    assert first.returncode == 0, first.stderr
    identity = json.loads(first.stdout)["semantic_store_id"]
    assert json.loads((root / "research/.onlyalpha-semantic-store.json").read_text()) == {
        "schema_version": 1,
        "store_id": identity,
    }
    again = initialize(root)
    assert again.returncode == 0, again.stderr
    assert json.loads(again.stdout) == {"schema_version": 1, "semantic_store_id": identity}

    other = tmp_path / "other-deployment"
    other.mkdir(mode=0o700)
    subprocess.run(
        [str(migration_backend), "--initialize-fresh-research-namespace", str(other)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    foreign = initialize(other)
    assert foreign.returncode == 1 and foreign.stderr.strip() == "SEMANTIC_STORE_IDENTITY_MISMATCH"
    with psycopg.connect(schema_db) as connection:
        assert connection.execute(
            "SELECT semantic_store_id::text FROM public.research_deployment_semantic_store_binding"
        ).fetchall() == [(identity,)]


def test_native_research_deployment_resumes_published_identity(
    migration_backend: Path, schema_db: str, tmp_path: Path
) -> None:
    root = tmp_path / "deployment"
    root.mkdir(mode=0o700)
    published = subprocess.run(
        [str(migration_backend), "--initialize-fresh-research-namespace", str(root)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    identity = json.loads(published.stdout)["semantic_store_id"]
    metadata = root / "research/.onlyalpha-semantic-store.json"
    before = metadata.read_bytes()
    inode = metadata.stat().st_ino
    resumed = subprocess.run(
        [str(migration_backend), "--initialize-research-deployment", str(root), str(DEFAULT_MIGRATION_ROOT)],
        env={**os.environ, "ONLYALPHA_POSTGRES_DSN": make_conninfo(schema_db, sslmode="disable")},
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert resumed.returncode == 0, resumed.stderr
    assert json.loads(resumed.stdout) == {"schema_version": 1, "semantic_store_id": identity}
    assert metadata.read_bytes() == before and metadata.stat().st_ino == inode
    with psycopg.connect(schema_db) as connection:
        assert connection.execute(
            "SELECT semantic_store_id::text FROM public.research_deployment_semantic_store_binding"
        ).fetchall() == [(identity,)]
