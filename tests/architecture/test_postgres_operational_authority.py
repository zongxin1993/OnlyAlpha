from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture


def test_postgres_schema_is_control_catalog_authority_not_high_volume_semantic_store() -> None:
    migrations = tuple(sorted(Path("database/postgres/migrations").glob("*.sql")))
    sql = "\n".join(path.read_text() for path in migrations)
    tables = re.findall(r"CREATE TABLE ([a-z_]+)", sql)
    assert tables == [
        "onlyalpha_schema_migration",
        "research_run",
        "research_run_attempt",
        "research_run_submission",
        "research_worker_presence",
        "research_deployment_semantic_store_binding",
        "strategy_catalog",
        "strategy_freeze_record",
        "strategy_promotion_record",
        "product_command_receipt",
        "market_source",
        "market_capture_session",
        "market_ingest_segment",
        "market_segment_state_event",
        "market_coverage_manifest",
        "market_coverage_manifest_segment",
        "market_data_revision",
        "market_revision_segment",
        "market_revision_seal",
        "market_recovery_event",
        "market_acquisition_intent",
        "strategy_freeze_command_admission",
        "backtest_run",
        "backtest_run_attempt",
        "backtest_worker_presence",
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


def test_published_migration_0004_and_0005_bytes_are_immutable() -> None:
    import hashlib

    expected = {
        "0004_research_run_submission_and_read_projection.sql": "ab7f9efc66e247659f8febde24a48eaaed98293285157d96affed1858d45af83",
        "0005_research_specification_v2_admission.sql": "90c8e44943f552ece5e89babaf290775e61244ae6a37c7129b25f48f6e33a96f",
    }
    for name, checksum in expected.items():
        assert hashlib.sha256((Path("database/postgres/migrations") / name).read_bytes()).hexdigest() == checksum


def test_published_migration_0007_bytes_are_immutable() -> None:
    import hashlib

    payload = Path("database/postgres/migrations/0007_research_deployment_semantic_store_binding.sql").read_bytes()
    assert hashlib.sha256(payload).hexdigest() == "de0e2f549c5f8ca54531ebf07a1a62811a6750ea02a625b5ed279b58878b6233"


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


def test_specification_v2_migration_only_expands_existing_version_admission() -> None:
    sql = Path("database/postgres/migrations/0005_research_specification_v2_admission.sql").read_text()
    assert "specification_schema_version IN (1, 2)" in sql
    assert "CREATE TABLE" not in sql
    assert "ADD COLUMN" not in sql
    assert "UPDATE research_run" not in sql


def test_research_authoring_provenance_migration_is_forward_only_and_legacy_compatible() -> None:
    sql = Path("database/postgres/migrations/0019_research_authoring_provenance.sql").read_text()
    assert "ADD COLUMN authoring_provenance JSONB NULL" in sql
    assert "research_run_authoring_provenance_object" in sql
    assert "jsonb_typeof(authoring_provenance) = 'object'" in sql
    assert "UPDATE research_run" not in sql


def test_worker_presence_migration_is_minimal_and_diagnostic_only() -> None:
    sql = Path("database/postgres/migrations/0006_research_worker_presence.sql").read_text()
    for required in ("worker_instance_id", "started_at", "last_seen_at", "service_version", "draining_since"):
        assert required in sql
    for forbidden in ("run_id", "attempt_id", "specification", "dataset", "result", "artifact", "ownership"):
        assert forbidden not in sql


def test_deployment_binding_is_narrow_operational_compatibility_not_semantic_content() -> None:
    sql = Path("database/postgres/migrations/0007_research_deployment_semantic_store_binding.sql").read_text()
    assert "semantic_store_id UUID NOT NULL" in sql
    assert "singleton BOOLEAN PRIMARY KEY" in sql
    for forbidden in (
        "dataset",
        "calculation",
        "statistics",
        "research_result",
        "artifact_content",
        "specification",
        "key TEXT",
        "value TEXT",
    ):
        assert forbidden not in sql


def test_strategy_catalog_contains_only_namespace_catalog_and_append_only_evidence() -> None:
    sql = Path("database/postgres/migrations/0008_strategy_revision_promotion_foundation.sql").read_text()
    for table in ("strategy_catalog", "strategy_freeze_record", "strategy_promotion_record"):
        assert f"CREATE TABLE {table}" in sql
    assert "semantic_namespace_id UUID NOT NULL REFERENCES" in sql
    assert "research_deployment_semantic_store_binding (semantic_store_id)" in sql
    assert "UNIQUE (candidate_fingerprint, research_result_fingerprint, strategy_fingerprint)" in sql
    assert "previous_record_fingerprint" in sql
    for forbidden in ("strategy_json", "decision_graph JSON", "mutable_status", "UPDATE strategy_"):
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
    assert 'ONLYALPHA_POSTGRES_CLIENT_BIN_DIR_ENV = "ONLYALPHA_POSTGRES_CLIENT_BIN_DIR"' in operator
    assert "shutil.which" not in operator


def test_migrations_are_repository_local_forward_only_and_checksummed() -> None:
    migration = Path("src/onlyalpha/persistence/postgres/migration.py").read_text()
    assert "sha256(path.read_bytes())" in migration
    assert "pg_advisory_lock" in migration
    assert "unknown database migrations" in migration
    assert "checksum mismatch" in migration
    for forbidden in (" downgrade(", " rollback(", "repair(", "arbitrary.sql"):
        assert forbidden not in migration
