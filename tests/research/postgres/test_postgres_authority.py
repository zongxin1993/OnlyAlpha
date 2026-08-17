from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import psycopg
import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.persistence.postgres import (
    DEFAULT_MIGRATION_ROOT,
    OnlyPostgresConfig,
    OnlyPostgresMigrationAuthority,
    OnlyPostgresResearchRunStore,
    OnlyPostgresSchemaVerdict,
)
from onlyalpha.research.run import (
    OnlyPostgresMigrationIntegrityError,
    OnlyPostgresSchemaIncompatibleError,
    OnlyResearchRun,
    OnlyResearchRunAdmissionError,
    OnlyResearchRunAdmissionService,
    OnlyResearchRunId,
    OnlyResearchRunIntegrityError,
    OnlyResearchRunRevisionConflictError,
    OnlyResearchRunState,
    only_research_admission_resolution_fingerprint,
)
from onlyalpha.research.specification import OnlyResearchSpecificationResolver
from scripts.database import _backup, _restore_test
from scripts.database import main as database_main
from tests.research.specification.support import registry, specification

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]
NOW = datetime(2026, 8, 17, 1, 2, 3, tzinfo=UTC)


def _queued(run_id: str) -> OnlyResearchRun:
    spec = specification()
    resolution = OnlyResearchSpecificationResolver(registry()).resolve(spec)
    return OnlyResearchRun.queued(
        run_id=OnlyResearchRunId(run_id),
        specification=spec,
        canonical_specification_payload=only_canonical_json(spec.to_dict()),
        admission_resolution_fingerprint=only_research_admission_resolution_fingerprint(resolution),
        queued_at=NOW,
    )


def test_fresh_plan_migrate_noop_and_startup_compatibility_are_exact(postgres_dsn: str) -> None:
    authority = OnlyPostgresMigrationAuthority(postgres_dsn)
    before = authority.status()
    assert before.verdict is OnlyPostgresSchemaVerdict.LEDGER_MISSING
    assert tuple(item.migration_id for item in authority.plan()) == ("0001_research_run_operational_authority",)
    with pytest.raises(OnlyPostgresSchemaIncompatibleError):
        authority.assert_compatible()

    assert authority.migrate() == ("0001_research_run_operational_authority",)
    assert authority.status().verdict is OnlyPostgresSchemaVerdict.COMPATIBLE
    assert authority.migrate() == ()


def test_operator_status_plan_and_migrate_are_explicit_and_secret_safe(
    postgres_dsn: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ONLYALPHA_POSTGRES_DSN", postgres_dsn)
    assert "onlyalpha_test" not in repr(OnlyPostgresConfig.from_environment())
    monkeypatch.setattr("sys.argv", ["database.py", "status"])
    assert database_main() == 2
    assert "onlyalpha_test" not in capsys.readouterr().out
    monkeypatch.setattr("sys.argv", ["database.py", "plan"])
    assert database_main() == 0
    assert OnlyPostgresMigrationAuthority(postgres_dsn).status().verdict is OnlyPostgresSchemaVerdict.LEDGER_MISSING
    monkeypatch.setattr("sys.argv", ["database.py", "migrate"])
    assert database_main() == 0
    assert OnlyPostgresMigrationAuthority(postgres_dsn).status().compatible


def test_migration_checksum_tamper_and_unknown_database_history_fail_closed(postgres_dsn: str, tmp_path: Path) -> None:
    authority = OnlyPostgresMigrationAuthority(postgres_dsn)
    authority.migrate()
    migration = next(DEFAULT_MIGRATION_ROOT.glob("0001_*.sql"))
    copied = tmp_path / migration.name
    copied.write_bytes(migration.read_bytes() + b"\n-- tampered\n")
    tampered = OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=tmp_path)
    assert tampered.status().verdict is OnlyPostgresSchemaVerdict.CHECKSUM_MISMATCH
    with pytest.raises(OnlyPostgresMigrationIntegrityError):
        tampered.plan()

    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("INSERT INTO onlyalpha_schema_migration VALUES (%s, %s)", ("9999_unknown", "f" * 64))
    assert authority.status().verdict is OnlyPostgresSchemaVerdict.AHEAD


def test_failed_migration_rolls_back_schema_and_ledger_atomically(postgres_dsn: str, tmp_path: Path) -> None:
    migration = next(DEFAULT_MIGRATION_ROOT.glob("0001_*.sql"))
    (tmp_path / migration.name).write_bytes(migration.read_bytes())
    (tmp_path / "0002_intentional_failure.sql").write_text(
        "CREATE TABLE must_rollback (value INTEGER); SELECT 1 / 0;\n", encoding="utf-8"
    )
    with pytest.raises(OnlyPostgresMigrationIntegrityError):
        OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=tmp_path).migrate()
    status = OnlyPostgresMigrationAuthority(postgres_dsn).status()
    assert status.verdict is OnlyPostgresSchemaVerdict.LEDGER_MISSING
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT to_regclass('public.must_rollback')").fetchone() == (None,)


def test_migration_advisory_lock_serializes_two_operator_processes(postgres_dsn: str) -> None:
    barrier = Barrier(2)

    def migrate() -> tuple[str, ...]:
        barrier.wait()
        return OnlyPostgresMigrationAuthority(postgres_dsn).migrate()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(item.result() for item in (executor.submit(migrate), executor.submit(migrate)))
    assert sorted(outcomes) == [(), ("0001_research_run_operational_authority",)]
    assert OnlyPostgresMigrationAuthority(postgres_dsn).status().compatible


def test_create_reload_same_spec_multiple_runs_and_canonical_integrity(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    store = OnlyPostgresResearchRunStore(postgres_dsn)
    first = store.create_queued(_queued("00000000-0000-4000-8000-000000000011"))
    second = store.create_queued(_queued("00000000-0000-4000-8000-000000000012"))

    reloaded = OnlyPostgresResearchRunStore(postgres_dsn).load(first.run_id)
    assert reloaded == first
    assert first.run_id != second.run_id
    assert first.specification_fingerprint == second.specification_fingerprint

    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE research_run SET specification_fingerprint = %s WHERE run_id = %s",
            ("e" * 64, first.run_id.value),
        )
    with pytest.raises(OnlyResearchRunIntegrityError):
        store.load(first.run_id)


def test_two_independent_connections_cannot_lose_same_revision_update(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    first_store = OnlyPostgresResearchRunStore(postgres_dsn)
    second_store = OnlyPostgresResearchRunStore(postgres_dsn)
    queued = first_store.create_queued(_queued("00000000-0000-4000-8000-000000000013"))
    running = queued.transition(OnlyResearchRunState.RUNNING, at=NOW + timedelta(seconds=1))
    first_store.commit_transition(queued, running)
    first_actor = first_store.load(running.run_id)
    second_actor = second_store.load(running.run_id)
    cancelled = first_actor.transition(OnlyResearchRunState.CANCEL_REQUESTED, at=NOW + timedelta(seconds=2))
    completed = second_actor.transition(
        OnlyResearchRunState.COMPLETED,
        at=NOW + timedelta(seconds=2),
        research_result_fingerprint="b" * 64,
        artifact_content_fingerprint="c" * 64,
    )

    barrier = Barrier(2)

    def commit(store: OnlyPostgresResearchRunStore, previous: OnlyResearchRun, target: OnlyResearchRun) -> object:
        barrier.wait()
        try:
            return store.commit_transition(previous, target)
        except OnlyResearchRunRevisionConflictError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(
            item.result()
            for item in (
                executor.submit(commit, first_store, first_actor, cancelled),
                executor.submit(commit, second_store, second_actor, completed),
            )
        )
    assert sum(isinstance(item, OnlyResearchRunRevisionConflictError) for item in outcomes) == 1
    assert sum(isinstance(item, OnlyResearchRun) for item in outcomes) == 1
    assert first_store.load(running.run_id) in (cancelled, completed)


def test_database_constraints_reject_invalid_state_and_incomplete_completion(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    run = OnlyPostgresResearchRunStore(postgres_dsn).create_queued(_queued("00000000-0000-4000-8000-000000000014"))
    with psycopg.connect(postgres_dsn) as connection, pytest.raises(psycopg.errors.CheckViolation):
        connection.execute("UPDATE research_run SET state = 'UNKNOWN' WHERE run_id = %s", (run.run_id.value,))
    with psycopg.connect(postgres_dsn) as connection, pytest.raises(psycopg.errors.CheckViolation):
        connection.execute(
            "UPDATE research_run SET state = 'COMPLETED', finished_at = %s WHERE run_id = %s",
            (NOW, run.run_id.value),
        )
    with psycopg.connect(postgres_dsn) as connection, pytest.raises(psycopg.errors.CheckViolation):
        connection.execute(
            "UPDATE research_run SET state = 'FAILED', finished_at = %s WHERE run_id = %s",
            (NOW, run.run_id.value),
        )
    with psycopg.connect(postgres_dsn) as connection, pytest.raises(psycopg.errors.CheckViolation):
        connection.execute("UPDATE research_run SET state = 'RUNNING' WHERE run_id = %s", (run.run_id.value,))


def test_admission_commit_restart_reload_and_reresolution_are_exact(postgres_dsn: str) -> None:
    class _VerifiedDatasetStore:
        def load_verified_table(self, fingerprint: str) -> object:
            assert fingerprint == "a" * 64
            return object()

    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    run_id = OnlyResearchRunId("00000000-0000-4000-8000-000000000015")
    first_process = OnlyResearchRunAdmissionService(
        resolver=OnlyResearchSpecificationResolver(registry()),
        dataset_store=_VerifiedDatasetStore(),  # type: ignore[arg-type]
        run_store=OnlyPostgresResearchRunStore(postgres_dsn),
        now_utc=lambda: NOW,
        run_id_factory=lambda: run_id,
    )
    admitted = first_process.submit(specification())

    second_process_store = OnlyPostgresResearchRunStore(postgres_dsn)
    reloaded = second_process_store.load(run_id)
    second_process = OnlyResearchRunAdmissionService(
        resolver=OnlyResearchSpecificationResolver(registry()),
        dataset_store=_VerifiedDatasetStore(),  # type: ignore[arg-type]
        run_store=second_process_store,
        now_utc=lambda: NOW,
    )
    second_process.verify_resolution(reloaded)
    assert reloaded == admitted
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE research_run SET admission_resolution_fingerprint = %s WHERE run_id = %s",
            ("d" * 64, run_id.value),
        )
    with pytest.raises(OnlyResearchRunAdmissionError, match="evidence mismatch"):
        second_process.verify_resolution(second_process_store.load(run_id))


def test_backup_restore_to_isolated_database_preserves_exact_run_and_source(postgres_dsn: str, tmp_path: Path) -> None:
    authority = OnlyPostgresMigrationAuthority(postgres_dsn)
    authority.migrate()
    run = OnlyPostgresResearchRunStore(postgres_dsn).create_queued(_queued("00000000-0000-4000-8000-000000000016"))
    backup = tmp_path / "onlyalpha.dump"
    target_dsn = postgres_dsn.rsplit("/", 1)[0] + "/onlyalpha_restore_test"
    admin_dsn = postgres_dsn.rsplit("/", 1)[0] + "/postgres"
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute("DROP DATABASE IF EXISTS onlyalpha_restore_test")
        connection.execute("CREATE DATABASE onlyalpha_restore_test")
    try:
        _backup(postgres_dsn, backup)
        _restore_test(postgres_dsn, target_dsn, backup, run.run_id.value)
        assert OnlyPostgresResearchRunStore(target_dsn).load(run.run_id) == run
        assert OnlyPostgresResearchRunStore(postgres_dsn).load(run.run_id) == run
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'onlyalpha_restore_test'"
            )
            connection.execute("DROP DATABASE IF EXISTS onlyalpha_restore_test")
