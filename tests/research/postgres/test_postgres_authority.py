from __future__ import annotations

import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace
from urllib.request import urlopen

import psycopg
import pytest
from psycopg import sql

import onlyalpha.persistence.postgres.research_operations_store as research_operations_store_module
from onlyalpha.canonical import only_canonical_json
from onlyalpha.cli import main as onlyalpha_main
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.persistence.postgres import (
    DEFAULT_MIGRATION_ROOT,
    OnlyPostgresConfig,
    OnlyPostgresMigrationAuthority,
    OnlyPostgresOperationalConnectionOptions,
    OnlyPostgresResearchDeploymentStore,
    OnlyPostgresResearchExecutionStore,
    OnlyPostgresResearchOperationsStore,
    OnlyPostgresResearchRunStore,
    OnlyPostgresSchemaVerdict,
)
from onlyalpha.research.command import OnlyResearchRunPageCursor, OnlyResearchSubmissionKey
from onlyalpha.research.execution import (
    OnlyResearchExecutionClaim,
    OnlyResearchExecutionOwnershipLostError,
    OnlyResearchRunAttemptId,
    OnlyResearchWorkerInstanceId,
)
from onlyalpha.research.operations.deployment import (
    OnlyResearchDeploymentError,
    OnlyResearchDeploymentErrorCode,
    OnlyResearchSemanticStoreId,
)
from onlyalpha.research.operations.diagnostics import (
    OnlyResearchDiagnosticPolicy,
    OnlyResearchOperationalDiagnosticService,
)
from onlyalpha.research.operations.model import OnlyResearchOperationalDiagnosisCode
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
    OnlyResearchRunStoreUnavailableError,
    only_research_admission_resolution_fingerprint,
)
from onlyalpha.research.specification import (
    RESEARCH_SPECIFICATION_SCIENTIFIC_SCHEMA_VERSION,
    OnlyResearchScientificEvidenceSpec,
    OnlyResearchSeriesSelector,
    OnlyResearchSignalEvidenceSpec,
    OnlyResearchSpecification,
    OnlyResearchSpecificationResolver,
)
from scripts.database import _assert_client_major, _backup, _initialize_deployment, _restore_test
from scripts.database import main as database_main
from tests.research.specification.support import registry, specification

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]
NOW = datetime(2026, 8, 17, 1, 2, 3, tzinfo=UTC)
M1 = "0001_research_run_operational_authority"
M2 = "0002_research_run_authority_hardening"
M3 = "0003_research_run_attempt_authority"
M4 = "0004_research_run_submission_and_read_projection"
M5 = "0005_research_specification_v2_admission"
M6 = "0006_research_worker_presence"
M7 = "0007_research_deployment_semantic_store_binding"


def test_deployment_binding_is_singleton_idempotent_and_cannot_rebind(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    store = OnlyPostgresResearchDeploymentStore(postgres_dsn)
    expected = OnlyResearchSemanticStoreId("00000000-0000-4000-8000-000000000001")

    with pytest.raises(OnlyResearchDeploymentError) as missing:
        store.load_semantic_store_id()
    assert missing.value.code is OnlyResearchDeploymentErrorCode.DEPLOYMENT_BINDING_MISSING
    assert store.initialize(expected) == expected
    assert store.initialize(expected) == expected
    assert store.load_semantic_store_id() == expected

    with pytest.raises(OnlyResearchDeploymentError) as mismatch:
        store.initialize(OnlyResearchSemanticStoreId("00000000-0000-4000-8000-000000000002"))
    assert mismatch.value.code is OnlyResearchDeploymentErrorCode.SEMANTIC_STORE_IDENTITY_MISMATCH

    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute(
            "SELECT count(*), min(semantic_store_id::text), max(semantic_store_id::text) "
            "FROM research_deployment_semantic_store_binding"
        ).fetchone() == (1, str(expected), str(expected))


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


def _queued_v2(run_id: str) -> OnlyResearchRun:
    v1 = specification()
    spec = OnlyResearchSpecification(
        v1.dataset_snapshot_fingerprint,
        v1.calculations,
        v1.statistics,
        OnlyResearchScientificEvidenceSpec(
            "feature",
            (OnlyResearchSeriesSelector("feature", "momentum", "factor_value"),),
            OnlyResearchSignalEvidenceSpec(),
        ),
        RESEARCH_SPECIFICATION_SCIENTIFIC_SCHEMA_VERSION,
    )
    resolution = OnlyResearchSpecificationResolver(registry()).resolve(spec)
    return OnlyResearchRun.queued(
        run_id=OnlyResearchRunId(run_id),
        specification=spec,
        canonical_specification_payload=only_canonical_json(spec.to_dict()),
        admission_resolution_fingerprint=only_research_admission_resolution_fingerprint(resolution),
        queued_at=NOW,
    )


def test_specification_v2_postgres_round_trip_is_canonical_exact(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    store = OnlyPostgresResearchRunStore(postgres_dsn)
    expected = _queued_v2("00000000-0000-4000-8000-000000000098")
    assert store.load(store.create_queued(expected).run_id) == expected


def test_worker_presence_and_operational_history_use_server_time_and_remain_diagnostic_only(
    postgres_dsn: str,
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    run_store = OnlyPostgresResearchRunStore(postgres_dsn)
    queued = run_store.create_queued(_queued("00000000-0000-4000-8000-000000000099"))
    execution = OnlyPostgresResearchExecutionStore(postgres_dsn)
    worker = OnlyResearchWorkerInstanceId("00000000-0000-4000-8002-000000000099")
    claim = execution.claim_next(
        worker_instance_id=worker,
        attempt_id=OnlyResearchRunAttemptId("00000000-0000-4000-8001-000000000099"),
        lease_duration=timedelta(minutes=2),
        max_attempts=3,
        run_started_at=NOW + timedelta(seconds=1),
    )
    assert claim is not None
    operations = OnlyPostgresResearchOperationsStore(postgres_dsn)
    announced = operations.announce_worker(worker, service_version="0.8.5")
    assert announced.last_seen_at >= announced.started_at
    heartbeat = operations.heartbeat_worker(worker)
    assert heartbeat.last_seen_at >= announced.last_seen_at
    draining = operations.mark_worker_draining(worker)
    assert draining.draining_since is not None

    snapshot = operations.load_operational_snapshot(run_id=queued.run_id, limit=1)
    assert snapshot.runs[0].attempts == (execution.load_attempt(claim.attempt.attempt_id),)
    diagnosis = OnlyResearchOperationalDiagnosticService(
        OnlyResearchDiagnosticPolicy(worker_stale_after=timedelta(microseconds=1))
    ).diagnose(snapshot)
    assert diagnosis[0].code is OnlyResearchOperationalDiagnosisCode.HEALTHY
    assert (
        execution.heartbeat(
            attempt_id=claim.attempt.attempt_id,
            worker_instance_id=worker,
            lease_duration=timedelta(minutes=2),
        ).state.value
        == "ACTIVE"
    )


def test_operational_snapshot_uses_one_read_only_repeatable_read_mvcc_observation(
    postgres_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    run_store = OnlyPostgresResearchRunStore(postgres_dsn)
    queued = run_store.create_queued(_queued("00000000-0000-4000-8000-000000000096"))
    run_read = Event()
    writer_committed = Event()
    original_connect = psycopg.connect

    class _CoordinatedConnection:
        def __init__(self, connection):  # type: ignore[no-untyped-def]
            object.__setattr__(self, "_connection", connection)

        def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
            return getattr(self._connection, name)

        def __setattr__(self, name: str, value: object) -> None:
            setattr(self._connection, name, value)

        def __enter__(self):  # type: ignore[no-untyped-def]
            self._connection.__enter__()
            return self

        def __exit__(self, *args: object):  # type: ignore[no-untyped-def]
            return self._connection.__exit__(*args)

        def execute(self, query, parameters=None):  # type: ignore[no-untyped-def]
            cursor = self._connection.execute(query, parameters)
            if isinstance(query, str) and query.startswith("SELECT * FROM research_run WHERE run_id"):
                with self._connection.cursor() as settings:
                    isolation = settings.execute(
                        "SELECT current_setting('transaction_isolation') AS isolation, "
                        "current_setting('transaction_read_only') AS read_only"
                    ).fetchone()
                assert isolation == {"isolation": "repeatable read", "read_only": "on"}
                run_read.set()
                assert writer_committed.wait(timeout=10), "writer did not commit during operational snapshot read"
            return cursor

    def coordinated_connect(*args, **kwargs):  # type: ignore[no-untyped-def]
        return _CoordinatedConnection(original_connect(*args, **kwargs))

    monkeypatch.setattr(
        research_operations_store_module,
        "psycopg",
        SimpleNamespace(connect=coordinated_connect, Error=psycopg.Error),
    )

    def claim_after_run_read():  # type: ignore[no-untyped-def]
        assert run_read.wait(timeout=10), "operational reader did not reach the Run observation"
        try:
            return OnlyPostgresResearchExecutionStore(postgres_dsn).claim_next(
                worker_instance_id=OnlyResearchWorkerInstanceId("00000000-0000-4000-8002-000000000096"),
                attempt_id=OnlyResearchRunAttemptId("00000000-0000-4000-8001-000000000096"),
                lease_duration=timedelta(minutes=2),
                max_attempts=3,
                run_started_at=NOW + timedelta(seconds=1),
            )
        finally:
            writer_committed.set()

    operations = OnlyPostgresResearchOperationsStore(postgres_dsn)
    with ThreadPoolExecutor(max_workers=1) as executor:
        writer = executor.submit(claim_after_run_read)
        first = operations.load_operational_snapshot(run_id=queued.run_id, limit=1)
        claim = writer.result()

    assert claim is not None
    assert first.runs[0].run.state is OnlyResearchRunState.QUEUED
    assert first.runs[0].attempts == ()

    second = operations.load_operational_snapshot(run_id=queued.run_id, limit=1)
    assert second.runs[0].run.state is OnlyResearchRunState.RUNNING
    assert second.runs[0].attempts == (claim.attempt,)


def test_operator_cli_reads_deterministic_run_attempt_audit_without_secret(
    postgres_dsn: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    run_store = OnlyPostgresResearchRunStore(postgres_dsn)
    queued = run_store.create_queued(_queued("00000000-0000-4000-8000-000000000097"))
    execution = OnlyPostgresResearchExecutionStore(postgres_dsn)
    claim = execution.claim_next(
        worker_instance_id=OnlyResearchWorkerInstanceId("00000000-0000-4000-8002-000000000097"),
        attempt_id=OnlyResearchRunAttemptId("00000000-0000-4000-8001-000000000097"),
        lease_duration=timedelta(minutes=2),
        max_attempts=3,
        run_started_at=NOW + timedelta(seconds=1),
    )
    assert claim is not None
    monkeypatch.setenv("ONLYALPHA_POSTGRES_DSN", postgres_dsn)
    assert onlyalpha_main(["operations", "run", queued.run_id.value]) == 0
    rendered = capsys.readouterr().out
    payload = json.loads(rendered)
    assert payload["runs"][0]["run_id"] == queued.run_id.value
    assert payload["runs"][0]["attempts"][0]["attempt_number"] == 1
    assert "postgresql://" not in rendered and "onlyalpha_test" not in rendered


def test_fresh_plan_migrate_noop_and_startup_compatibility_are_exact(postgres_dsn: str) -> None:
    authority = OnlyPostgresMigrationAuthority(postgres_dsn)
    before = authority.status()
    assert before.verdict is OnlyPostgresSchemaVerdict.LEDGER_MISSING
    assert tuple(item.migration_id for item in authority.plan()) == (M1, M2, M3, M4, M5, M6, M7)
    with pytest.raises(OnlyPostgresSchemaIncompatibleError):
        authority.assert_compatible()

    assert authority.migrate() == (M1, M2, M3, M4, M5, M6, M7)
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


def test_operator_explicitly_initializes_and_binds_new_semantic_store(
    postgres_dsn: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    monkeypatch.setenv("ONLYALPHA_POSTGRES_DSN", postgres_dsn)
    monkeypatch.setattr(
        "sys.argv",
        ["database.py", "initialize-deployment", "--user-data-root", str(tmp_path)],
    )

    assert database_main() == 0
    first = json.loads(capsys.readouterr().out)
    assert first["deployment"] == "BOUND"
    assert OnlyPostgresResearchDeploymentStore(postgres_dsn).load_semantic_store_id() == (
        OnlyResearchSemanticStoreId(first["semantic_store_id"])
    )
    layout = OnlyUserDataLayout(tmp_path)
    assert all(
        root.is_dir()
        for root in (
            layout.research_dataset_root,
            layout.research_calculation_result_root,
            layout.research_statistics_result_root,
            layout.research_result_root,
            layout.research_artifact_root,
        )
    )

    assert database_main() == 0
    assert json.loads(capsys.readouterr().out)["semantic_store_id"] == first["semantic_store_id"]


@pytest.mark.parametrize("tampered_id", [M1, M2, M3, M4, M5, M6, M7])
def test_migration_checksum_tamper_fails_closed(postgres_dsn: str, tmp_path: Path, tampered_id: str) -> None:
    authority = OnlyPostgresMigrationAuthority(postgres_dsn)
    authority.migrate()
    _copy_migrations(tmp_path, M1, M2, M3, M4, M5, M6, M7)
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
    assert tuple(item.migration_id for item in authority.plan()) == (M2, M3, M4, M5, M6, M7)
    assert authority.migrate() == (M2, M3, M4, M5, M6, M7)
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
    assert before.applied_migrations == (M2, M3, M4, M5, M6, M7)
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
    assert sorted(outcomes) == [(), (M1, M2, M3, M4, M5, M6, M7)]
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
    run_store = OnlyPostgresResearchRunStore(postgres_dsn)
    queued = run_store.create_queued(_queued("00000000-0000-4000-8000-000000000016"))
    claim = OnlyPostgresResearchExecutionStore(postgres_dsn).claim_next(
        worker_instance_id=OnlyResearchWorkerInstanceId("00000000-0000-4000-8002-000000000016"),
        attempt_id=OnlyResearchRunAttemptId("00000000-0000-4000-8001-000000000016"),
        lease_duration=timedelta(minutes=2),
        max_attempts=3,
        run_started_at=NOW + timedelta(seconds=1),
    )
    assert claim is not None
    run = run_store.load(queued.run_id)
    backup = tmp_path / "onlyalpha.dump"
    target_dsn = postgres_dsn.rsplit("/", 1)[0] + "/onlyalpha_restore_test"
    admin_dsn = postgres_dsn.rsplit("/", 1)[0] + "/postgres"
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute("DROP DATABASE IF EXISTS onlyalpha_restore_test")
        connection.execute("CREATE DATABASE onlyalpha_restore_test")
    try:
        metadata_path = _backup(postgres_dsn, backup)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert metadata["backup_sha256"] == hashlib.sha256(backup.read_bytes()).hexdigest()
        assert metadata["postgres_server_version"].startswith("16.")
        assert metadata["pg_dump_version"].startswith("pg_dump (PostgreSQL) 16.")
        assert [item["migration_id"] for item in metadata["migrations"]][-1] == M7
        assert "onlyalpha_test" not in metadata_path.read_text(encoding="utf-8")
        _restore_test(postgres_dsn, target_dsn, backup, run.run_id.value)
        assert OnlyPostgresResearchRunStore(target_dsn).load(run.run_id) == run
        target_snapshot = OnlyPostgresResearchOperationsStore(target_dsn).load_operational_snapshot(
            run_id=run.run_id, limit=1
        )
        assert target_snapshot.runs[0].attempts == (claim.attempt,)
        assert OnlyPostgresResearchRunStore(postgres_dsn).load(run.run_id) == run
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'onlyalpha_restore_test'"
            )
            connection.execute("DROP DATABASE IF EXISTS onlyalpha_restore_test")


def test_restore_rejects_source_target_and_nonempty_target(postgres_dsn: str, tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="isolated"):
        _restore_test(postgres_dsn, postgres_dsn, tmp_path / "missing.dump", None)
    target_dsn = postgres_dsn.rsplit("/", 1)[0] + "/onlyalpha_restore_test"
    admin_dsn = postgres_dsn.rsplit("/", 1)[0] + "/postgres"
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute("DROP DATABASE IF EXISTS onlyalpha_restore_test")
        connection.execute("CREATE DATABASE onlyalpha_restore_test")
    try:
        with psycopg.connect(target_dsn) as connection:
            connection.execute("CREATE TABLE occupied (value INTEGER)")
        with pytest.raises(RuntimeError, match="must be empty"):
            _restore_test(postgres_dsn, target_dsn, tmp_path / "missing.dump", None)
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute("DROP DATABASE IF EXISTS onlyalpha_restore_test")


def test_database_client_major_policy_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scripts.database._tool_version", lambda _name: "pg_dump (PostgreSQL) 18.6")
    with pytest.raises(RuntimeError, match="POSTGRES_CLIENT_MAJOR_UNSUPPORTED"):
        _assert_client_major("pg_dump")


def test_operational_statement_timeout_is_repository_owned_and_effective(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    options = OnlyPostgresOperationalConnectionOptions(
        connect_timeout=timedelta(seconds=1),
        statement_timeout=timedelta(milliseconds=100),
        lock_timeout=timedelta(milliseconds=50),
        tcp_user_timeout=timedelta(seconds=1),
    )
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "CREATE FUNCTION onlyalpha_test_slow_run() RETURNS trigger LANGUAGE plpgsql AS "
            "$$ BEGIN PERFORM pg_sleep(2); RETURN NEW; END $$"
        )
        connection.execute(
            "CREATE TRIGGER onlyalpha_test_slow_run BEFORE INSERT ON research_run "
            "FOR EACH ROW EXECUTE FUNCTION onlyalpha_test_slow_run()"
        )
    started = time.monotonic()
    try:
        with pytest.raises(OnlyResearchRunStoreUnavailableError, match="Research Run create transaction failed"):
            OnlyPostgresResearchRunStore(postgres_dsn, options).create_queued(
                _queued("00000000-0000-4000-8000-000000000051")
            )
        assert time.monotonic() - started < 1.5
    finally:
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute("DROP TRIGGER onlyalpha_test_slow_run ON research_run")
            connection.execute("DROP FUNCTION onlyalpha_test_slow_run()")


def test_operational_connection_policy_forces_utc_independent_of_server_default(postgres_dsn: str) -> None:
    options = OnlyPostgresOperationalConnectionOptions()
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        database = connection.info.dbname
        connection.execute(
            sql.SQL("ALTER DATABASE {} SET timezone TO 'Asia/Shanghai'").format(sql.Identifier(database))
        )
    try:
        with psycopg.connect(options.apply(postgres_dsn)) as connection:
            assert connection.execute("SHOW timezone").fetchone() == ("UTC",)
    finally:
        with psycopg.connect(postgres_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("ALTER DATABASE {} RESET timezone").format(sql.Identifier(database)))


@pytest.mark.parametrize(
    ("signum", "expected_exit_code"),
    ((signal.SIGINT, 130), (signal.SIGTERM, 143)),
)
def test_worker_process_signal_marks_draining_and_uses_application_exit_contract(
    postgres_dsn: str, tmp_path: Path, signum: signal.Signals, expected_exit_code: int
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    _initialize_deployment(postgres_dsn, tmp_path)
    environment = os.environ.copy()
    environment["ONLYALPHA_POSTGRES_DSN"] = postgres_dsn
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "onlyalpha.research.worker_main",
            "--user-data-root",
            str(tmp_path),
            "--polling-seconds",
            "0.05",
        ],
        cwd=Path(__file__).parents[3],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    operations = OnlyPostgresResearchOperationsStore(postgres_dsn)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if operations.load_operational_snapshot(limit=1).workers:
            break
        if process.poll() is not None:
            break
        time.sleep(0.05)
    assert process.poll() is None
    process.send_signal(signum)
    output, _ = process.communicate(timeout=10)
    assert process.returncode == expected_exit_code
    snapshot = operations.load_operational_snapshot(limit=1)
    assert len(snapshot.workers) == 1 and snapshot.workers[0].draining_since is not None
    assert '"event":"research.worker.draining"' in output
    assert '"event":"research.worker.stopped"' in output
    assert "postgresql://" not in output and "onlyalpha_test" not in output


def test_api_process_restart_reads_same_postgres_run_authority(postgres_dsn: str, tmp_path: Path) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    _initialize_deployment(postgres_dsn, tmp_path)
    run = OnlyPostgresResearchRunStore(postgres_dsn).create_queued(_queued("00000000-0000-4000-8000-000000000017"))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = os.environ.copy()
    environment["ONLYALPHA_POSTGRES_DSN"] = postgres_dsn

    def start() -> subprocess.Popen[str]:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "onlyalpha_api.main",
                "--user-data-root",
                str(tmp_path),
                "--port",
                str(port),
            ],
            cwd=Path(__file__).parents[3],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with urlopen(f"http://127.0.0.1:{port}/health/live", timeout=0.2) as response:  # noqa: S310
                    if response.status == 200:
                        return process
            except OSError:
                if process.poll() is not None:
                    break
                time.sleep(0.05)
        output, _ = process.communicate(timeout=2)
        raise AssertionError(f"API did not become live: {output}")

    for _ in range(2):
        process = start()
        with urlopen(f"http://127.0.0.1:{port}/api/v2/research/runs/{run.run_id}") as response:  # noqa: S310
            body = json.loads(response.read())
        assert body["run_id"] == run.run_id.value and body["state"] == "QUEUED"
        process.send_signal(signal.SIGTERM)
        output, _ = process.communicate(timeout=10)
        assert process.returncode in {0, -signal.SIGTERM}
        assert "postgresql://" not in output and "onlyalpha_test" not in output


def test_worker_process_killed_after_claim_expires_to_fresh_attempt_and_is_fenced(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    run = OnlyPostgresResearchRunStore(postgres_dsn).create_queued(_queued("00000000-0000-4000-8000-000000000018"))
    old_worker = OnlyResearchWorkerInstanceId("00000000-0000-4000-8002-000000000018")
    old_attempt = OnlyResearchRunAttemptId("00000000-0000-4000-8001-000000000018")
    script = (
        "import os,signal; from datetime import timedelta; "
        "from onlyalpha.persistence.postgres import OnlyPostgresResearchExecutionStore; "
        "from onlyalpha.research.execution.model import OnlyResearchWorkerInstanceId,OnlyResearchRunAttemptId; "
        "s=OnlyPostgresResearchExecutionStore(os.environ['ONLYALPHA_POSTGRES_DSN']); "
        f"c=s.claim_next(worker_instance_id=OnlyResearchWorkerInstanceId({old_worker.value!r}),"
        f"attempt_id=OnlyResearchRunAttemptId({old_attempt.value!r}),lease_duration=timedelta(seconds=30),"
        "max_attempts=3,run_started_at=__import__('datetime').datetime.now(__import__('datetime').UTC)); "
        "assert c is not None; os.kill(os.getpid(),signal.SIGKILL)"
    )
    environment = os.environ.copy()
    environment["ONLYALPHA_POSTGRES_DSN"] = postgres_dsn
    process = subprocess.run(
        [sys.executable, "-c", script], cwd=Path(__file__).parents[3], env=environment, check=False
    )
    assert process.returncode == -signal.SIGKILL
    store = OnlyPostgresResearchExecutionStore(postgres_dsn)
    stale_claim = OnlyResearchExecutionClaim(store.load_attempt(old_attempt))
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE research_run_attempt SET lease_expires_at = last_heartbeat_at WHERE attempt_id = %s",
            (old_attempt.value,),
        )
    assert store.expire_next(max_attempts=3, run_finished_at=NOW + timedelta(minutes=1)) is not None
    fresh = store.claim_next(
        worker_instance_id=OnlyResearchWorkerInstanceId("00000000-0000-4000-8002-000000000019"),
        attempt_id=OnlyResearchRunAttemptId("00000000-0000-4000-8001-000000000019"),
        lease_duration=timedelta(minutes=2),
        max_attempts=3,
        run_started_at=NOW + timedelta(minutes=2),
    )
    assert fresh is not None and fresh.attempt.attempt_number == 2
    with pytest.raises(OnlyResearchExecutionOwnershipLostError):
        store.complete(
            claim=stale_claim,
            run_finished_at=NOW + timedelta(minutes=3),
            research_result_fingerprint="b" * 64,
            artifact_content_fingerprint="c" * 64,
        )
    assert OnlyPostgresResearchRunStore(postgres_dsn).load(run.run_id).state is OnlyResearchRunState.RUNNING
