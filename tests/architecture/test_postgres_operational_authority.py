from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture


def test_postgres_schema_is_minimal_operational_authority_not_semantic_store() -> None:
    migrations = tuple(sorted(Path("database/postgres/migrations").glob("*.sql")))
    sql = "\n".join(path.read_text() for path in migrations)
    tables = re.findall(r"CREATE TABLE ([a-z_]+)", sql)
    assert tables == [
        "onlyalpha_schema_migration",
        "research_run",
        "research_run_attempt",
        "research_run_submission",
    ]
    for forbidden in (
        "dataset_row",
        "calculation_row",
        "factor_value",
        "statistics_row",
        "research_result_content",
        "artifact_content BYTEA",
        "semantic_checkpoint",
        "partial_result",
        "calculation_progress",
    ):
        assert forbidden not in sql
    assert "UNIQUE(specification_fingerprint)" not in sql


def test_published_migration_0001_bytes_are_immutable() -> None:
    import hashlib

    payload = Path("database/postgres/migrations/0001_research_run_operational_authority.sql").read_bytes()
    assert hashlib.sha256(payload).hexdigest() == "3e7d6564dc83a062ea2954f7eb23255065c39b3f6398115cde3e2719954062b0"


def test_published_migration_0002_bytes_are_immutable() -> None:
    import hashlib

    payload = Path("database/postgres/migrations/0002_research_run_authority_hardening.sql").read_bytes()
    assert hashlib.sha256(payload).hexdigest() == "05dd03d41d1418046e705b98e00c51a0041f9acd07122ca0331d9f786980bd6a"


def test_published_migration_0003_bytes_are_immutable() -> None:
    import hashlib

    payload = Path("database/postgres/migrations/0003_research_run_attempt_authority.sql").read_bytes()
    assert hashlib.sha256(payload).hexdigest() == "b5c9cbb93a3fea8231a9b9ab4f76b2e0b5cd2abede475aa41eb913cdd98fa19d"


def test_forward_hardening_migration_mirrors_domain_fact_boundaries() -> None:
    sql = Path("database/postgres/migrations/0002_research_run_authority_hardening.sql").read_text()
    for constraint in (
        "research_run_time_order",
        "research_run_running_has_no_cancel_request",
        "research_run_execution_required",
        "research_run_cancelled_lifecycle",
        "research_run_artifact_requires_result",
    ):
        assert f"ADD CONSTRAINT {constraint}" in sql
    assert "UPDATE research_run" not in sql


def test_attempt_migration_contains_only_operational_ownership_facts() -> None:
    sql = Path("database/postgres/migrations/0003_research_run_attempt_authority.sql").read_text()
    assert "research_run_attempt_one_active" in sql
    assert "UNIQUE (run_id, attempt_number)" in sql
    assert "clock_timestamp" not in sql
    for forbidden in ("dataset", "calculation", "statistics", "result_content", "artifact_content"):
        assert forbidden not in sql


def test_command_migration_contains_only_submission_identity_and_read_index() -> None:
    sql = Path("database/postgres/migrations/0004_research_run_submission_and_read_projection.sql").read_text()
    assert "submission_key UUID PRIMARY KEY" in sql
    assert "command_fingerprint" in sql
    assert "run_id UUID NOT NULL UNIQUE REFERENCES research_run(run_id)" in sql
    assert "research_run_recent_order" in sql
    assert "queued_at DESC, run_id DESC" in sql
    for forbidden in ("attempt", "lease", "dataset", "statistics", "result_content", "artifact_content BYTEA"):
        assert forbidden not in sql


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
