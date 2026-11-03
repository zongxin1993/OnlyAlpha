"""Test database fencing follows the same parsed identity as psycopg."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from psycopg.conninfo import conninfo_to_dict

from scripts import compose_test
from scripts.database_guard import assert_test_database


@pytest.mark.parametrize(
    ("dsn", "name"),
    [
        ("postgresql://host/onlyalpha_test", "onlyalpha_test"),
        ("postgresql://host/declared_test?dbname=actual_test", "actual_test"),
        ("postgresql://host/encoded%5Ftest", "encoded_test"),
        ("host=host dbname=keyword_test", "keyword_test"),
    ],
)
def test_guard_checks_the_effective_explicit_database(dsn: str, name: str) -> None:
    assert assert_test_database(dsn) == name


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://host/declared_test?dbname=production",
        "postgresql://host/production",
        "postgresql://host/",
        "host=host user=service_test",
        "",
        "password='do-not-leak' invalid_parameter=x",
    ],
)
def test_guard_refuses_missing_non_test_or_invalid_database_without_secret_output(dsn: str) -> None:
    with pytest.raises(RuntimeError, match="^POSTGRES_INTEGRATION_TEST_DATABASE_REQUIRED$"):
        assert_test_database(dsn)


def test_restore_guard_requires_the_effective_restore_database() -> None:
    assert assert_test_database("host=host dbname=onlyalpha_restore_test", restore=True) == "onlyalpha_restore_test"
    for dsn in [
        "postgresql://host/onlyalpha_test",
        "postgresql://host/declared_restore_test?dbname=production",
    ]:
        with pytest.raises(RuntimeError, match="^POSTGRES_RESTORE_TEST_DATABASE_REQUIRED$"):
            assert_test_database(dsn, restore=True)


def test_compose_refuses_query_override_before_any_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONLYALPHA_POSTGRES_DSN", "postgresql://host/declared_test?dbname=production")
    monkeypatch.setattr(sys, "argv", ["compose_test.py", "true"])
    monkeypatch.setattr(compose_test.psycopg, "connect", lambda *a, **k: pytest.fail("unsafe connection attempted"))
    with pytest.raises(RuntimeError, match="POSTGRES_INTEGRATION_TEST_DATABASE_REQUIRED"):
        compose_test.main()


def test_compose_uses_the_parsed_database_and_quotes_its_identifier(monkeypatch: pytest.MonkeyPatch) -> None:
    name = 'quoted"name_test'
    dsn = "postgresql://host/declared_test?dbname=quoted%22name_test&user=operator"
    statements: list[tuple[str, object]] = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, statement, parameters=None):
            rendered = statement if isinstance(statement, str) else statement.as_string()
            statements.append((rendered, parameters))
            return SimpleNamespace(fetchone=lambda: None)

    def connect(admin_dsn, **kwargs):
        assert conninfo_to_dict(admin_dsn) == {"host": "host", "dbname": "postgres", "user": "operator"}
        assert kwargs == {"autocommit": True}
        return Connection()

    monkeypatch.setenv("ONLYALPHA_POSTGRES_DSN", dsn)
    monkeypatch.delenv("ONLYALPHA_DEV_VERIFICATION_LOCK_FD", raising=False)
    monkeypatch.setattr(sys, "argv", ["compose_test.py", "true"])
    monkeypatch.setattr(compose_test.psycopg, "connect", connect)
    monkeypatch.setattr(compose_test.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 0))
    assert compose_test.main() == 0
    assert statements == [
        ("SELECT 1 FROM pg_database WHERE datname = %s", (name,)),
        ('CREATE DATABASE "quoted""name_test"', None),
    ]


def test_compose_direct_script_rejects_unsafe_database_without_workspace_import_path(tmp_path: Path) -> None:
    environment = dict(os.environ, ONLYALPHA_POSTGRES_DSN="postgresql://host/declared_test?dbname=production")
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, str(Path(compose_test.__file__).resolve()), "true"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "POSTGRES_INTEGRATION_TEST_DATABASE_REQUIRED" in result.stderr
    assert "ModuleNotFoundError" not in result.stderr


@pytest.mark.parametrize(
    ("source", "target", "code"),
    [
        ("user=operator", "host=postgres dbname=shared_restore_test", "POSTGRES_RESTORE_SOURCE_DATABASE_REQUIRED"),
        (
            "host=alias_a dbname=shared_restore_test",
            "host=alias_b dbname=shared_restore_test",
            "isolated from the source database",
        ),
        (
            "password='do-not-leak' invalid_parameter=x",
            "host=postgres dbname=target_restore_test",
            "POSTGRES_RESTORE_SOURCE_DATABASE_REQUIRED",
        ),
    ],
)
def test_restore_cannot_infer_source_identity_or_isolation_from_host_spelling(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, source: str, target: str, code: str
) -> None:
    from scripts import database

    monkeypatch.setenv("PGDATABASE", "shared_restore_test")
    monkeypatch.setenv("PGHOST", "postgres")
    monkeypatch.setattr(
        database.psycopg, "connect", lambda *a, **k: pytest.fail("unproved restore isolation connected")
    )
    with pytest.raises(RuntimeError, match=code):
        database._restore_test(source, target, tmp_path / "unused-backup", None)


def test_independent_history_reader_loads_the_engineering_guard_before_input_or_connection() -> None:
    environment = dict(os.environ, ONLYALPHA_POSTGRES_DSN="postgresql://host/declared_test?dbname=production")
    result = subprocess.run(
        [sys.executable, "-m", "tests.runtime_support.storage_history_reader"],
        cwd=Path(compose_test.__file__).resolve().parents[1],
        env=environment,
        input="",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "POSTGRES_INTEGRATION_TEST_DATABASE_REQUIRED" in result.stderr
    assert "ImportError" not in result.stderr
