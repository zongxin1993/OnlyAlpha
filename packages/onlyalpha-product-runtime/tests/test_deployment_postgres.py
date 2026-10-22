"""Read-only existing namespace pairing; technical evidence, not node/UI readiness."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority

from .support.integration import call

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.timeout(120)]
ID = "550e8400-e29b-41d4-a716-446655440000"
OTHER = "550e8400-e29b-41d4-a716-446655440001"


@pytest.fixture
def deployment_db(postgres_dsn: str) -> str:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    return postgres_dsn


def check(probe: Path, local: str = ID, *, lost_connection: bool = False) -> dict[str, object]:
    return call(
        probe,
        {
            "op": "deployment-lost-connection" if lost_connection else "deployment",
            "command_id": str(uuid4()),
            "local_id": local,
        },
    )


def facts(dsn: str) -> list[tuple[object, ...]]:
    with psycopg.connect(dsn) as connection:
        return list(
            connection.execute(
                "SELECT singleton,semantic_store_id::text,bound_at FROM research_deployment_semantic_store_binding ORDER BY singleton,semantic_store_id::text"
            ).fetchall()
        )


def bind(dsn: str, identity: str = ID) -> None:
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "INSERT INTO research_deployment_semantic_store_binding(singleton,semantic_store_id) VALUES(TRUE,%s)",
            (identity,),
        )


def test_missing_binding_never_initializes_it(native_probe: Path, deployment_db: str) -> None:
    before = facts(deployment_db)
    assert check(native_probe) == {"error": "DEPLOYMENT_BINDING_MISSING"}
    assert facts(deployment_db) == before == []


def test_exact_existing_pair_and_restarted_reader_do_not_change_binding(native_probe: Path, deployment_db: str) -> None:
    bind(deployment_db)
    before = facts(deployment_db)
    assert check(native_probe) == {"compatible": True}
    assert check(native_probe) == {"compatible": True}
    assert facts(deployment_db) == before
    assert check(native_probe, OTHER) == {"error": "SEMANTIC_STORE_IDENTITY_MISMATCH"}
    assert facts(deployment_db) == before
    # A new process reads the actual changed binding; an already returned verdict has no watcher.
    with psycopg.connect(deployment_db) as connection:
        connection.execute("UPDATE research_deployment_semantic_store_binding SET semantic_store_id=%s", (OTHER,))
    assert check(native_probe) == {"error": "SEMANTIC_STORE_IDENTITY_MISMATCH"}
    assert check(native_probe, OTHER) == {"compatible": True}


def test_wrong_uuid_family_is_corrupt_not_a_complete_different_namespace(
    native_probe: Path, deployment_db: str
) -> None:
    bind(deployment_db, ID.replace("41d4", "11d4"))
    before = facts(deployment_db)
    assert check(native_probe) == {"error": "SEMANTIC_STORE_IDENTITY_CORRUPT"}
    assert facts(deployment_db) == before


@pytest.mark.parametrize(
    "rows",
    [
        [(False, ID)],
        [(False, ID), (True, ID)],
        [(True, ID), (True, ID)],
        [(True, None)],
        [(None, ID)],
        [(True, "invalid")],
        [(True, ID.upper())],
        [(True, "x" * 32769)],
    ],
)
def test_corrupt_singleton_proof_is_not_filtered_into_absence_or_match(
    native_probe: Path, deployment_db: str, rows: list[tuple[bool | None, str | None]]
) -> None:
    # Deliberately damaged physical schema in the canonical isolated test DB only.
    with psycopg.connect(deployment_db) as connection:
        connection.execute("DROP TABLE research_deployment_semantic_store_binding CASCADE")
        connection.execute(
            "CREATE TABLE research_deployment_semantic_store_binding(singleton BOOLEAN,semantic_store_id TEXT,bound_at TIMESTAMPTZ DEFAULT now())"
        )
        for singleton, identity in rows:
            connection.execute(
                "INSERT INTO research_deployment_semantic_store_binding(singleton,semantic_store_id) VALUES(%s,%s)",
                (singleton, identity),
            )
    before = facts(deployment_db)
    assert check(native_probe) == {"error": "SEMANTIC_STORE_IDENTITY_CORRUPT"}
    assert facts(deployment_db) == before


@pytest.mark.parametrize("missing_table", [False, True])
def test_unavailable_read_never_certifies_binding_absence(
    native_probe: Path, deployment_db: str, missing_table: bool
) -> None:
    bind(deployment_db)
    if missing_table:
        with psycopg.connect(deployment_db) as connection:
            connection.execute("DROP TABLE research_deployment_semantic_store_binding CASCADE")
    assert check(native_probe, lost_connection=not missing_table) == {"error": "RESEARCH_RUN_STORE_UNAVAILABLE"}
    if not missing_table:
        assert len(facts(deployment_db)) == 1


def test_check_runs_in_explicit_read_only_transaction(native_probe: Path, deployment_db: str) -> None:
    # Read-only controlled view exposes the actual transaction mode without a production hook.
    with psycopg.connect(deployment_db) as connection:
        connection.execute("DROP TABLE research_deployment_semantic_store_binding CASCADE")
        connection.execute(
            f"CREATE VIEW research_deployment_semantic_store_binding AS SELECT TRUE AS singleton, CASE WHEN current_setting('transaction_read_only')='on' THEN '{ID}'::uuid ELSE '{OTHER}'::uuid END AS semantic_store_id"
        )
    assert check(native_probe) == {"compatible": True}


@pytest.mark.parametrize(
    ("canonical", "shadow", "expected"),
    [
        ("MISSING_RELATION", ID, {"error": "RESEARCH_RUN_STORE_UNAVAILABLE"}),
        (None, ID, {"error": "DEPLOYMENT_BINDING_MISSING"}),
        (OTHER, ID, {"error": "SEMANTIC_STORE_IDENTITY_MISMATCH"}),
        (ID, OTHER, {"compatible": True}),
    ],
)
def test_search_path_cannot_select_a_different_namespace_authority(
    native_probe: Path, deployment_db: str, canonical: str | None, shadow: str, expected: dict[str, object]
) -> None:
    missing_relation = canonical == "MISSING_RELATION"
    if canonical is not None and not missing_relation:
        bind(deployment_db, canonical)
    before = facts(deployment_db)
    with psycopg.connect(deployment_db) as connection:
        connection.execute("CREATE SCHEMA controlled_deployment_shadow")
        connection.execute(
            "CREATE TABLE controlled_deployment_shadow.research_deployment_semantic_store_binding (LIKE public.research_deployment_semantic_store_binding INCLUDING ALL)"
        )
        connection.execute(
            "INSERT INTO controlled_deployment_shadow.research_deployment_semantic_store_binding(singleton,semantic_store_id) VALUES(TRUE,%s)",
            (shadow,),
        )
        if missing_relation:
            connection.execute("DROP TABLE public.research_deployment_semantic_store_binding CASCADE")
    try:
        request = {
            "op": "deployment",
            "command_id": str(uuid4()),
            "local_id": ID,
            "search_path": "controlled_deployment_shadow,public",
        }
        assert call(native_probe, request) == expected
        if not missing_relation:
            assert facts(deployment_db) == before
        with psycopg.connect(deployment_db) as connection:
            assert connection.execute(
                "SELECT semantic_store_id::text FROM controlled_deployment_shadow.research_deployment_semantic_store_binding"
            ).fetchall() == [(shadow,)]
            if missing_relation:
                assert connection.execute(
                    "SELECT to_regclass('public.research_deployment_semantic_store_binding')"
                ).fetchone() == (None,)
    finally:
        with psycopg.connect(deployment_db) as connection:
            connection.execute("DROP SCHEMA controlled_deployment_shadow CASCADE")
