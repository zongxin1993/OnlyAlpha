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
    OnlyPostgresResearchExecutionStore,
    OnlyPostgresResearchRunStore,
    OnlyPostgresSchemaVerdict,
)
from onlyalpha.research.command import OnlyResearchRunPageCursor, OnlyResearchSubmissionKey
from onlyalpha.research.execution import (
    OnlyResearchRunAttemptId,
    OnlyResearchWorkerInstanceId,
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
    OnlyResearchRunStateConflictError,
    only_research_admission_resolution_fingerprint,
)
from onlyalpha.research.specification import OnlyResearchSpecificationResolver
from scripts.database import _backup, _restore_test
from scripts.database import main as database_main
from tests.research.specification.support import registry, specification

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]
NOW = datetime(2026, 8, 17, 1, 2, 3, tzinfo=UTC)
M1 = "0001_research_run_operational_authority"
M2 = "0002_research_run_authority_hardening"
M3 = "0003_research_run_attempt_authority"
M4 = "0004_research_run_submission_and_read_projection"


def _copy_migrations(target: Path, *migration_ids: str) -> None:
    for migration_id in migration_ids:
        source = DEFAULT_MIGRATION_ROOT / f"{migration_id}.sql"
        (target / source.name).write_bytes(source.read_bytes())


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
    assert tuple(item.migration_id for item in authority.plan()) == (M1, M2, M3, M4)
    with pytest.raises(OnlyPostgresSchemaIncompatibleError):
        authority.assert_compatible()

    assert authority.migrate() == (M1, M2, M3, M4)
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


@pytest.mark.parametrize("tampered_id", [M1, M2, M3, M4])
def test_migration_checksum_tamper_fails_closed(postgres_dsn: str, tmp_path: Path, tampered_id: str) -> None:
    authority = OnlyPostgresMigrationAuthority(postgres_dsn)
    authority.migrate()
    _copy_migrations(tmp_path, M1, M2, M3, M4)
    copied = tmp_path / f"{tampered_id}.sql"
    copied.write_bytes(copied.read_bytes() + b"\n-- tampered\n")
    tampered = OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=tmp_path)
    assert tampered.status().verdict is OnlyPostgresSchemaVerdict.CHECKSUM_MISMATCH
    with pytest.raises(OnlyPostgresMigrationIntegrityError):
        tampered.plan()


def test_unknown_database_history_is_ahead(postgres_dsn: str) -> None:
    authority = OnlyPostgresMigrationAuthority(postgres_dsn)
    authority.migrate()
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("INSERT INTO onlyalpha_schema_migration VALUES (%s, %s)", ("9999_unknown", "f" * 64))
    assert authority.status().verdict is OnlyPostgresSchemaVerdict.AHEAD


def test_existing_m1_database_plans_and_applies_exact_forward_suffix(postgres_dsn: str, tmp_path: Path) -> None:
    _copy_migrations(tmp_path, M1)
    assert OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=tmp_path).migrate() == (M1,)
    run = OnlyPostgresResearchRunStore(postgres_dsn).create_queued(_queued("00000000-0000-4000-8000-000000000020"))

    authority = OnlyPostgresMigrationAuthority(postgres_dsn)
    assert authority.status().verdict is OnlyPostgresSchemaVerdict.BEHIND
    assert tuple(item.migration_id for item in authority.plan()) == (M2, M3, M4)
    assert authority.migrate() == (M2, M3, M4)
    assert authority.status().verdict is OnlyPostgresSchemaVerdict.COMPATIBLE
    assert OnlyPostgresResearchRunStore(postgres_dsn).load(run.run_id) == run


def test_invalid_existing_m1_fact_blocks_m2_without_repair(postgres_dsn: str, tmp_path: Path) -> None:
    _copy_migrations(tmp_path, M1)
    OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=tmp_path).migrate()
    run = OnlyPostgresResearchRunStore(postgres_dsn).create_queued(_queued("00000000-0000-4000-8000-000000000021"))
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE research_run SET state = 'RUNNING', started_at = %s, cancel_requested_at = %s WHERE run_id = %s",
            (NOW + timedelta(seconds=1), NOW + timedelta(seconds=2), run.run_id.value),
        )

    with pytest.raises(OnlyPostgresMigrationIntegrityError):
        OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute(
            "SELECT migration_id FROM onlyalpha_schema_migration ORDER BY migration_id"
        ).fetchall() == [(M1,)]
        assert connection.execute(
            "SELECT state, started_at, cancel_requested_at FROM research_run WHERE run_id = %s", (run.run_id.value,)
        ).fetchone() == ("RUNNING", NOW + timedelta(seconds=1), NOW + timedelta(seconds=2))


def test_known_non_prefix_histories_diverge_and_cannot_change_database(postgres_dsn: str) -> None:
    authority = OnlyPostgresMigrationAuthority(postgres_dsn)
    authority.migrate()
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("DELETE FROM onlyalpha_schema_migration WHERE migration_id = %s", (M1,))
    before = authority.status()
    assert before.verdict is OnlyPostgresSchemaVerdict.HISTORY_DIVERGED
    assert before.applied_migrations == (M2, M3, M4)
    assert before.pending_migrations == ()
    with pytest.raises(OnlyPostgresMigrationIntegrityError):
        authority.plan()
    with pytest.raises(OnlyPostgresMigrationIntegrityError):
        authority.migrate()
    with pytest.raises(OnlyPostgresSchemaIncompatibleError):
        authority.assert_compatible()
    assert authority.status() == before


def test_known_history_hole_diverges(postgres_dsn: str, tmp_path: Path) -> None:
    _copy_migrations(tmp_path, M1, M2)
    (tmp_path / "0003_known.sql").write_text("SELECT 1;\n", encoding="utf-8")
    authority = OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=tmp_path)
    authority.migrate()
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("DELETE FROM onlyalpha_schema_migration WHERE migration_id = %s", (M2,))
    assert authority.status().verdict is OnlyPostgresSchemaVerdict.HISTORY_DIVERGED


def test_repository_prepend_before_applied_history_diverges(postgres_dsn: str, tmp_path: Path) -> None:
    m1_root = tmp_path / "m1"
    changed_root = tmp_path / "changed"
    m1_root.mkdir()
    changed_root.mkdir()
    _copy_migrations(m1_root, M1)
    OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=m1_root).migrate()
    (changed_root / "0000_illegal_prepend.sql").write_text("SELECT 1;\n", encoding="utf-8")
    _copy_migrations(changed_root, M1)
    assert (
        OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=changed_root).status().verdict
        is OnlyPostgresSchemaVerdict.HISTORY_DIVERGED
    )


def test_failed_migration_rolls_back_schema_and_ledger_atomically(postgres_dsn: str, tmp_path: Path) -> None:
    _copy_migrations(tmp_path, M1, M2)
    (tmp_path / "0003_intentional_failure.sql").write_text(
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
    assert sorted(outcomes) == [(), (M1, M2, M3, M4)]
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


def test_submission_transaction_is_atomic_concurrent_and_restart_safe(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    key = OnlyResearchSubmissionKey("00000000-0000-4000-8000-000000000401")
    command_fingerprint = "d" * 64
    barrier = Barrier(2)

    def submit(run_id: str):  # type: ignore[no-untyped-def]
        barrier.wait()
        return OnlyPostgresResearchRunStore(postgres_dsn).create_queued_submission(
            _queued(run_id), key, command_fingerprint
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(
            item.result()
            for item in (
                executor.submit(submit, "00000000-0000-4000-8000-000000000411"),
                executor.submit(submit, "00000000-0000-4000-8000-000000000412"),
            )
        )

    assert outcomes[0] == outcomes[1]
    restarted = OnlyPostgresResearchRunStore(postgres_dsn)
    assert restarted.find_submission(key) == outcomes[0]
    assert restarted.load(outcomes[0].run_id).state is OnlyResearchRunState.QUEUED
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM research_run_submission").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM research_run").fetchone() == (1,)


def test_submission_identity_does_not_deduplicate_specification(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    store = OnlyPostgresResearchRunStore(postgres_dsn)
    first = store.create_queued_submission(
        _queued("00000000-0000-4000-8000-000000000421"),
        OnlyResearchSubmissionKey("00000000-0000-4000-8000-000000000401"),
        "d" * 64,
    )
    second = store.create_queued_submission(
        _queued("00000000-0000-4000-8000-000000000422"),
        OnlyResearchSubmissionKey("00000000-0000-4000-8000-000000000402"),
        "d" * 64,
    )
    assert first.run_id != second.run_id
    assert store.load(first.run_id).specification_fingerprint == store.load(second.run_id).specification_fingerprint


def test_submission_and_recent_read_adapter_reject_invalid_calls_without_partial_facts(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    store = OnlyPostgresResearchRunStore(postgres_dsn)
    key = OnlyResearchSubmissionKey("00000000-0000-4000-8000-000000000403")
    assert store.find_submission(key) is None
    with pytest.raises(ValueError, match="positive"):
        store.list_recent(limit=0)

    queued = store.create_queued(_queued("00000000-0000-4000-8000-000000000423"))
    running = queued.transition(OnlyResearchRunState.RUNNING, at=NOW + timedelta(seconds=1))
    with pytest.raises(OnlyResearchRunStateConflictError, match="revision-zero"):
        store.create_queued_submission(running, key, "d" * 64)
    with pytest.raises(OnlyResearchRunIntegrityError, match="identity already exists"):
        store.create_queued_submission(queued, key, "d" * 64)
    assert store.find_submission(key) is None


def test_recent_keyset_order_is_stable_and_new_rows_do_not_duplicate_existing_cursor(
    postgres_dsn: str,
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    store = OnlyPostgresResearchRunStore(postgres_dsn)
    for value in range(431, 436):
        store.create_queued(_queued(f"00000000-0000-4000-8000-{value:012d}"))
    first = store.list_recent(limit=3)
    assert [item.run_id.value for item in first] == sorted([item.run_id.value for item in first], reverse=True)
    cursor = OnlyResearchRunPageCursor(first[-1].queued_at, first[-1].run_id)
    inserted = _queued("00000000-0000-4000-8000-000000000499")
    store.create_queued(inserted)
    second = store.list_recent(limit=3, after=cursor)
    assert inserted not in second
    assert not set(item.run_id for item in first) & set(item.run_id for item in second)


def test_two_independent_connections_cannot_lose_same_revision_update(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    first_store = OnlyPostgresResearchRunStore(postgres_dsn)
    second_store = OnlyPostgresResearchRunStore(postgres_dsn)
    queued = first_store.create_queued(_queued("00000000-0000-4000-8000-000000000013"))
    claim = OnlyPostgresResearchExecutionStore(postgres_dsn).claim_next(
        worker_instance_id=OnlyResearchWorkerInstanceId("00000000-0000-4000-8000-000000000091"),
        attempt_id=OnlyResearchRunAttemptId("00000000-0000-4000-8000-000000000092"),
        lease_duration=timedelta(minutes=2),
        max_attempts=3,
        run_started_at=NOW + timedelta(seconds=1),
    )
    assert claim is not None
    running = first_store.load(queued.run_id)
    first_actor = first_store.load(running.run_id)
    second_actor = second_store.load(running.run_id)
    cancelled = first_actor.transition(OnlyResearchRunState.CANCEL_REQUESTED, at=NOW + timedelta(seconds=2))
    competing_cancel = second_actor.transition(OnlyResearchRunState.CANCEL_REQUESTED, at=NOW + timedelta(seconds=3))

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
                executor.submit(commit, second_store, second_actor, competing_cancel),
            )
        )
    assert sum(isinstance(item, OnlyResearchRunRevisionConflictError) for item in outcomes) == 1
    assert sum(isinstance(item, OnlyResearchRun) for item in outcomes) == 1
    assert first_store.load(running.run_id) in (cancelled, competing_cancel)


def test_general_run_store_cannot_bypass_attempt_fencing(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    run_store = OnlyPostgresResearchRunStore(postgres_dsn)
    run_store.create_queued(_queued("00000000-0000-4000-8000-000000000023"))
    claim = OnlyPostgresResearchExecutionStore(postgres_dsn).claim_next(
        worker_instance_id=OnlyResearchWorkerInstanceId("00000000-0000-4000-8000-000000000093"),
        attempt_id=OnlyResearchRunAttemptId("00000000-0000-4000-8000-000000000094"),
        lease_duration=timedelta(minutes=2),
        max_attempts=3,
        run_started_at=NOW + timedelta(seconds=1),
    )
    assert claim is not None
    running = run_store.load(claim.attempt.run_id)
    completed = running.transition(
        OnlyResearchRunState.COMPLETED,
        at=NOW + timedelta(seconds=2),
        research_result_fingerprint="b" * 64,
        artifact_content_fingerprint="c" * 64,
    )
    with pytest.raises(OnlyResearchRunStateConflictError, match="fenced Research Execution Store"):
        run_store.commit_transition(running, completed)


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


@pytest.mark.parametrize(
    ("assignments", "parameters"),
    [
        (
            "state = 'COMPLETED', finished_at = %s, research_result_fingerprint = %s, "
            "artifact_content_fingerprint = %s",
            (NOW + timedelta(seconds=2), "b" * 64, "c" * 64),
        ),
        (
            "state = 'FAILED', finished_at = %s, failure_phase = 'EXECUTION', "
            "failure_code = 'FAILED', failure_detail = 'detail'",
            (NOW + timedelta(seconds=2),),
        ),
        (
            "state = 'RUNNING', started_at = %s, cancel_requested_at = %s",
            (NOW + timedelta(seconds=1), NOW + timedelta(seconds=2)),
        ),
        (
            "state = 'CANCEL_REQUESTED', started_at = %s, cancel_requested_at = %s",
            (NOW + timedelta(seconds=2), NOW + timedelta(seconds=1)),
        ),
        (
            "state = 'COMPLETED', started_at = %s, finished_at = %s, research_result_fingerprint = %s, "
            "artifact_content_fingerprint = %s",
            (NOW + timedelta(seconds=2), NOW + timedelta(seconds=1), "b" * 64, "c" * 64),
        ),
        (
            "state = 'CANCELLED', started_at = %s, cancel_requested_at = %s, finished_at = %s",
            (NOW + timedelta(seconds=1), NOW + timedelta(seconds=3), NOW + timedelta(seconds=2)),
        ),
        (
            "state = 'RUNNING', started_at = %s, artifact_content_fingerprint = %s",
            (NOW + timedelta(seconds=1), "c" * 64),
        ),
    ],
)
def test_hardened_database_constraints_reject_impossible_operational_facts(
    postgres_dsn: str, assignments: str, parameters: tuple[object, ...]
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    run = OnlyPostgresResearchRunStore(postgres_dsn).create_queued(_queued("00000000-0000-4000-8000-000000000022"))
    with psycopg.connect(postgres_dsn) as connection, pytest.raises(psycopg.errors.CheckViolation):
        connection.execute(
            f"UPDATE research_run SET {assignments} WHERE run_id = %s",  # noqa: S608 - fixed test-owned SQL fragments
            (*parameters, run.run_id.value),
        )


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
