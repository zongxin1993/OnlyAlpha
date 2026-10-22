"""Native canonical migration history startup admission, not migration or UI acceptance."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from onlyalpha.persistence.postgres.migration import DEFAULT_MIGRATION_ROOT, OnlyPostgresMigrationAuthority

from .support.integration import call

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.timeout(120)]


@pytest.fixture
def schema_db(postgres_dsn: str) -> str:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    return postgres_dsn


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
