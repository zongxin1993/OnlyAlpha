"""Actual read-only Node storage preconditions, not READY or Shipping acceptance."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, cast

import psycopg
import pytest

from onlyalpha.persistence.postgres.migration import DEFAULT_MIGRATION_ROOT, OnlyPostgresMigrationAuthority
from tests.support.postgres_link import CommitAckCut

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.timeout(120)]
NAMESPACE = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


def files(root: Path, namespace: str = NAMESPACE) -> Path:
    data = root / "data"
    for path in [
        "research/artifacts",
        "backtest/evidence",
        "research/datasets",
        "research/dataset-economic-bindings",
        "secrets",
    ]:
        (data / path).mkdir(parents=True, mode=0o700)
    (data / "secrets/dev-master-key").write_bytes(bytes([1]) * 32)
    (data / "secrets/dev-master-key").chmod(0o600)
    (data / "research/.onlyalpha-semantic-store.json").write_text(
        json.dumps({"schema_version": 1, "store_id": namespace})
    )
    return data


@pytest.fixture
def startup_db(postgres_dsn: str) -> str:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "INSERT INTO public.research_deployment_semantic_store_binding(singleton,semantic_store_id) VALUES(TRUE,%s)",
            (NAMESPACE,),
        )
    return postgres_dsn


def call(probe: Path, data: Path, **changes: object) -> dict[str, Any]:
    request: dict[str, object] = {
        "op": "startup-storage",
        "root": str(data),
        "schema_source": str(DEFAULT_MIGRATION_ROOT),
        "rows": 1024,
        "work": 2 * 1024 * 1024,
        **changes,
    }
    result = subprocess.run([str(probe)], input=json.dumps(request), text=True, capture_output=True, timeout=25)
    assert result.returncode == 0, result.stderr
    return cast(dict[str, Any], json.loads(result.stdout))


def facts(dsn: str) -> tuple[object, object]:
    with psycopg.connect(dsn) as connection:
        present = connection.execute(
            "SELECT pg_catalog.to_regclass('public.onlyalpha_schema_migration') IS NOT NULL"
        ).fetchone()
        schema = (
            connection.execute("SELECT * FROM public.onlyalpha_schema_migration ORDER BY migration_id").fetchall()
            if present == (True,)
            else None
        )
        binding = connection.execute(
            "SELECT * FROM public.research_deployment_semantic_store_binding ORDER BY singleton"
        ).fetchall()
    return schema, binding


def test_storage_verification_and_fresh_process_preserve_existing_namespace_and_schema(
    integration_http_probe: Path, startup_db: str, tmp_path: Path
) -> None:
    data = files(tmp_path)
    before = facts(startup_db)
    assert call(integration_http_probe, data) == {"verified": True, "namespace": NAMESPACE}
    assert call(integration_http_probe, data) == {"verified": True, "namespace": NAMESPACE}
    assert facts(startup_db) == before


@pytest.mark.parametrize("mutation", ["last", "first", "checksum", "unknown", "missing"])
def test_only_exact_compatible_schema_reaches_namespace_validation(
    integration_http_probe: Path, startup_db: str, tmp_path: Path, mutation: str
) -> None:
    data = files(tmp_path)
    with psycopg.connect(startup_db) as connection:
        ids = [
            row[0]
            for row in connection.execute(
                "SELECT migration_id FROM public.onlyalpha_schema_migration ORDER BY migration_id"
            ).fetchall()
        ]
        if mutation in {"last", "first"}:
            connection.execute(
                "DELETE FROM public.onlyalpha_schema_migration WHERE migration_id=%s",
                (ids[-1] if mutation == "last" else ids[0],),
            )
        elif mutation == "checksum":
            connection.execute(
                "UPDATE public.onlyalpha_schema_migration SET checksum_sha256=%s WHERE migration_id=%s",
                ("0" * 64, ids[0]),
            )
        elif mutation == "unknown":
            connection.execute(
                "INSERT INTO public.onlyalpha_schema_migration(migration_id,checksum_sha256) VALUES('9999_future',%s)",
                ("a" * 64,),
            )
        else:
            connection.execute("DROP TABLE public.onlyalpha_schema_migration")
        # Schema rejection must precede the separately missing binding.
        connection.execute("DELETE FROM public.research_deployment_semantic_store_binding")
    before = facts(startup_db)
    assert call(integration_http_probe, data)["error"] == "SCHEMA_INCOMPATIBLE"
    assert facts(startup_db) == before


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("missing", "DEPLOYMENT_BINDING_MISSING"),
        ("different", "SEMANTIC_STORE_IDENTITY_MISMATCH"),
        ("wrong-family", "SEMANTIC_STORE_IDENTITY_CORRUPT"),
    ],
)
def test_exact_loaded_namespace_is_required_after_schema_compatibility(
    integration_http_probe: Path, startup_db: str, tmp_path: Path, mutation: str, expected: str
) -> None:
    data = files(tmp_path)
    with psycopg.connect(startup_db) as connection:
        if mutation == "missing":
            connection.execute("DELETE FROM public.research_deployment_semantic_store_binding")
        else:
            identity = OTHER if mutation == "different" else NAMESPACE.replace("4111", "1111")
            connection.execute(
                "UPDATE public.research_deployment_semantic_store_binding SET semantic_store_id=%s", (identity,)
            )
    before = facts(startup_db)
    assert call(integration_http_probe, data)["error"] == expected
    assert facts(startup_db) == before


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ({"rows": 0}, "RESEARCH_RUN_STORE_UNAVAILABLE"),
        ({"work": 1}, "RESEARCH_RUN_STORE_UNAVAILABLE"),
        ({"lost_connection": True}, "RESEARCH_RUN_STORE_UNAVAILABLE"),
    ],
)
def test_resource_exhaustion_and_unavailable_connection_are_never_storage_success(
    integration_http_probe: Path, startup_db: str, tmp_path: Path, options: dict[str, object], expected: str
) -> None:
    data = files(tmp_path)
    before = facts(startup_db)
    assert call(integration_http_probe, data, **options)["error"] == expected
    assert facts(startup_db) == before


def test_readonly_commit_ack_loss_is_unavailable_and_does_not_mutate_facts(
    integration_http_probe: Path, startup_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = files(tmp_path)
    before = facts(startup_db)
    with CommitAckCut(startup_db) as link:
        monkeypatch.setenv("ONLYALPHA_POSTGRES_DSN", link.dsn)
        assert call(integration_http_probe, data)["error"] == "RESEARCH_RUN_STORE_UNAVAILABLE"
        assert link.done.wait(20)
    assert facts(startup_db) == before


def test_cancelled_verification_produces_no_success_and_preserves_facts(
    integration_http_probe: Path, startup_db: str, tmp_path: Path
) -> None:
    data = files(tmp_path)
    before = facts(startup_db)
    assert call(integration_http_probe, data, cancel_verify=True) == {"cancelled": True}
    assert facts(startup_db) == before
    assert call(integration_http_probe, data)["verified"] is True


def test_path_replacement_after_root_selection_does_not_change_the_verified_namespace(
    integration_http_probe: Path, startup_db: str, tmp_path: Path
) -> None:
    data = files(tmp_path)
    replacement = files(tmp_path / "replacement", OTHER)
    request = {
        "op": "startup-storage",
        "root": str(data),
        "schema_source": str(DEFAULT_MIGRATION_ROOT),
        "rows": 1024,
        "work": 2 * 1024 * 1024,
        "storage_barrier": True,
    }
    before = facts(startup_db)
    with subprocess.Popen(
        [str(integration_http_probe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    ) as child:
        assert child.stdin is not None and child.stdout is not None and child.stderr is not None
        try:
            child.stdin.write(json.dumps(request) + "\n")
            child.stdin.flush()
            assert json.loads(child.stdout.readline()) == {"storage_selected": True}
            data.rename(tmp_path / "retained")
            replacement.rename(data)
            child.stdin.write("verify\n")
            child.stdin.flush()
            child.stdin.close()
            output = json.loads(child.stdout.read())
            assert child.wait(timeout=20) == 0, child.stderr.read()
            assert output == {"verified": True, "namespace": NAMESPACE}
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=20)
    assert call(integration_http_probe, data)["error"] == "SEMANTIC_STORE_IDENTITY_MISMATCH"
    assert facts(startup_db) == before
