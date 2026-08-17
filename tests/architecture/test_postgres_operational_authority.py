from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture


def test_postgres_schema_is_minimal_operational_authority_not_semantic_store() -> None:
    sql = Path("database/postgres/migrations/0001_research_run_operational_authority.sql").read_text()
    tables = re.findall(r"CREATE TABLE ([a-z_]+)", sql)
    assert tables == ["onlyalpha_schema_migration", "research_run"]
    for forbidden in (
        "dataset_row",
        "calculation_row",
        "factor_value",
        "statistics_row",
        "research_result_content",
        "artifact_content BYTEA",
        "research_run_attempt",
        "worker",
        "lease",
        "heartbeat",
    ):
        assert forbidden not in sql
    assert "UNIQUE(specification_fingerprint)" not in sql


def test_application_startup_cannot_migrate_or_repair_postgres() -> None:
    for root in (Path("src/onlyalpha/application"), Path("src/onlyalpha/engine"), Path("src/onlyalpha/runtime")):
        if root.exists():
            source = "\n".join(path.read_text() for path in root.rglob("*.py"))
            assert "OnlyPostgresMigrationAuthority" not in source
            assert "database migrate" not in source
    operator = Path("scripts/database.py").read_text()
    assert 'if args.command == "migrate"' in operator
    assert "pg_dump" in operator and "pg_restore" in operator
    assert "--target-dsn-env" in operator


def test_migrations_are_repository_local_forward_only_and_checksummed() -> None:
    migration = Path("src/onlyalpha/persistence/postgres/migration.py").read_text()
    assert "sha256(path.read_bytes())" in migration
    assert "pg_advisory_lock" in migration
    assert "unknown database migrations" in migration
    assert "checksum mismatch" in migration
    for forbidden in (" downgrade(", " rollback(", "repair(", "arbitrary.sql"):
        assert forbidden not in migration
