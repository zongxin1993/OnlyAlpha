"""Transactional source-owned history, including pre-migration baseline and later revisions."""

from __future__ import annotations

import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from threading import Event, Thread

import psycopg
import pytest

from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandAdmissionV1,
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandOutcomeRef,
    OnlyProductCommandReceipt,
)
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.persistence.postgres.product_command_authority import OnlyPostgresProductCommandAuthority
from onlyalpha.persistence.postgres.research_execution_store import OnlyPostgresResearchExecutionStore
from onlyalpha.persistence.postgres.research_run_store import OnlyPostgresResearchRunStore
from onlyalpha.persistence.postgres.research_source_cut import OnlyPostgresResearchSourceCutAuthority
from onlyalpha.research.execution import OnlyResearchRunAttemptId, OnlyResearchWorkerInstanceId
from onlyalpha.research.source_cut import OnlySourceCutError
from tests.research.postgres.migration_support import copy_migrations_through
from tests.research.postgres.test_postgres_authority import NOW, _queued


def test_transactional_run_cut_preserves_baseline_and_later_revision(postgres_dsn: str, tmp_path: Path) -> None:
    copy_migrations_through(tmp_path, "0022_product_command_legacy_admission_closure")
    OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=tmp_path).migrate()
    run = _queued("00000000-0000-4000-8000-000000000901")
    store = OnlyPostgresResearchRunStore(postgres_dsn)
    store.create_queued(run)

    copy_migrations_through(tmp_path, "0023_research_source_closed_cut")
    assert OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=tmp_path).migrate() == (
        "0023_research_source_closed_cut",
    )
    source = OnlyPostgresResearchSourceCutAuthority(postgres_dsn)
    old = source.capture_closed_cut("RESEARCH_RUN")
    assert old == source.capture_closed_cut("RESEARCH_RUN")
    assert old.cut_boundary == "JOURNAL_INDEX:1"
    assert len(old.entries) == 1

    # The ordinary official writer and even a direct SQL update are covered by
    # the database trigger; no process-local hook can be bypassed.
    cancelled = run.transition(run.state.CANCELLED, at=run.queued_at)
    store.commit_transition(run, cancelled)
    newer = source.capture_closed_cut("RESEARCH_RUN")
    assert len(newer.entries) == 2
    assert source.load_closed_cut_verified(old.cut_fingerprint, "RESEARCH_RUN") == old
    assert source.load_closed_cut_verified(newer.cut_fingerprint, "RESEARCH_RUN") == newer

    program = (
        "import sys\n"
        "from onlyalpha.persistence.postgres.research_source_cut import OnlyPostgresResearchSourceCutAuthority\n"
        "cut = OnlyPostgresResearchSourceCutAuthority(sys.argv[1]).load_closed_cut_verified(sys.argv[2], 'RESEARCH_RUN')\n"
        "print(cut.cut_fingerprint)\n"
    )
    assert (
        subprocess.check_output([sys.executable, "-c", program, postgres_dsn, old.cut_fingerprint], text=True).strip()
        == old.cut_fingerprint
    )

    with psycopg.connect(postgres_dsn) as connection:
        rows = connection.execute(
            "SELECT event_index, operation, source_row ->> 'revision' FROM research_source_history ORDER BY event_index"
        ).fetchall()
        assert rows == [(1, "BASELINE", "0"), (2, "UPDATE", "1")]
        with pytest.raises(psycopg.Error):
            connection.execute("DELETE FROM research_source_history WHERE event_index = 1")


def test_postgres_source_cut_rejects_journal_gap(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    source = OnlyPostgresResearchSourceCutAuthority(postgres_dsn)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("UPDATE research_source_history_frontier SET last_index = 2")
    with pytest.raises(OnlySourceCutError, match="SOURCE_CUT_JOURNAL_GAP"):
        source.capture_closed_cut("RESEARCH_RUN")


def test_attempt_and_product_admission_cuts_survive_later_changes(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    run = _queued("00000000-0000-4000-8000-000000000911")
    OnlyPostgresResearchRunStore(postgres_dsn).create_queued(run)
    source = OnlyPostgresResearchSourceCutAuthority(postgres_dsn)
    before = source.capture_closed_cut("RESEARCH_ATTEMPT")
    admission = OnlyProductCommandAdmissionV1(
        OnlyProductCommandId("00000000-0000-4000-8000-000000000912"),
        OnlyProductCommandKind.CREATE_RESEARCH_RUN,
        "a" * 64,
    )
    product = OnlyPostgresProductCommandAuthority(postgres_dsn)
    product.admit_exact(admission)
    admitted = source.capture_closed_cut("PRODUCT_COMMAND_ADMISSION")
    product.put_verified_receipt(
        OnlyProductCommandReceipt(
            admission.command_id,
            admission.command_kind,
            admission.command_fingerprint,
            OnlyProductCommandOutcomeRef(OnlyProductCommandOutcomeKind.RESEARCH_RUN, run.run_id.value),
            NOW,
        )
    )
    received = source.capture_closed_cut("PRODUCT_COMMAND_RECEIPT")
    assert len(received.entries) == 1
    claim = OnlyPostgresResearchExecutionStore(postgres_dsn).claim_next(
        worker_instance_id=OnlyResearchWorkerInstanceId("00000000-0000-4000-8002-000000000911"),
        attempt_id=OnlyResearchRunAttemptId("00000000-0000-4000-8001-000000000911"),
        lease_duration=timedelta(minutes=2),
        max_attempts=3,
        run_started_at=NOW + timedelta(seconds=1),
    )
    assert claim is not None
    active = source.capture_closed_cut("RESEARCH_ATTEMPT")
    assert before.entries == () and len(active.entries) == 1
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE research_run_attempt SET lease_expires_at = last_heartbeat_at WHERE attempt_id = %s",
            (claim.attempt.attempt_id.value,),
        )
    later = source.capture_closed_cut("RESEARCH_ATTEMPT")
    assert len(later.entries) == 2
    restarted = OnlyPostgresResearchSourceCutAuthority(postgres_dsn)
    assert restarted.load_closed_cut_verified(active.cut_fingerprint, "RESEARCH_ATTEMPT") == active
    assert restarted.load_closed_cut_verified(admitted.cut_fingerprint, "PRODUCT_COMMAND_ADMISSION") == admitted
    assert restarted.load_closed_cut_verified(received.cut_fingerprint, "PRODUCT_COMMAND_RECEIPT") == received


def test_postgres_capture_waits_for_uncommitted_writer(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    run = _queued("00000000-0000-4000-8000-000000000913")
    OnlyPostgresResearchRunStore(postgres_dsn).create_queued(run)
    source = OnlyPostgresResearchSourceCutAuthority(postgres_dsn)
    entered, release, done = Event(), Event(), Event()
    failures: list[Exception] = []

    def writer() -> None:
        try:
            with psycopg.connect(postgres_dsn) as connection:
                # A direct SQL writer is serialized by the source trigger.
                connection.execute(
                    "UPDATE research_run SET revision = revision + 1 WHERE run_id = %s",
                    (run.run_id.value,),
                )
                entered.set()
                assert release.wait(10)
        except Exception as exc:
            failures.append(exc)
        finally:
            done.set()

    thread = Thread(target=writer)
    thread.start()
    try:
        assert entered.wait(10)
        # The uncommitted trigger increment holds the frontier lock. Capture
        # can complete only after the writer's transaction commits.
        captured: list[object] = []
        capture = Thread(target=lambda: captured.append(source.capture_closed_cut("RESEARCH_RUN")))
        capture.start()
        release.set()
        assert done.wait(10)
        capture.join(10)
        assert not capture.is_alive() and not failures
        assert len(captured[0].entries) == 2  # type: ignore[attr-defined]
    finally:
        release.set()
        thread.join(10)
