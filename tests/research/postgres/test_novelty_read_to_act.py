from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psycopg
import pytest

from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandAdmissionV1,
    OnlyProductCommandId,
    OnlyProductCommandKind,
)
from onlyalpha.persistence.postgres import (
    OnlyPostgresProductCommandAuthority,
    OnlyPostgresResearchRunStore,
)
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.research.command.novelty_admission import (
    OnlyResearchNoveltyAdmissionV1,
    only_novelty_same_subject_guard_key,
)
from onlyalpha.research.run import OnlyResearchRunIntegrityError, OnlyResearchRunStoreUnavailableError
from tests.research.postgres.test_postgres_authority import _create_receipt, _queued

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]


def _frontier(dsn: str) -> int:
    with psycopg.connect(dsn) as connection:
        row = connection.execute(
            "SELECT last_index FROM research_source_history_frontier WHERE singleton = TRUE"
        ).fetchone()
    assert row is not None
    return int(row[0])


def _admission(command_id, command_fingerprint, run, subject="4" * 64):  # type: ignore[no-untyped-def]
    return OnlyResearchNoveltyAdmissionV1(
        command_id,
        command_fingerprint,
        "1" * 64,
        "2" * 64,
        subject,
        "5" * 64,
        "6" * 64,
        "7" * 64,
        only_novelty_same_subject_guard_key(subject),
        run.run_id.value,
        run.run_id,
    )


def _preadmit(dsn: str, command_id: OnlyProductCommandId, fingerprint: str) -> None:
    OnlyPostgresProductCommandAuthority(dsn).admit_exact(
        OnlyProductCommandAdmissionV1(
            command_id,
            OnlyProductCommandKind.CREATE_RESEARCH_RUN,
            fingerprint,
        )
    )


def test_novelty_admission_run_and_receipt_commit_atomically(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    store = OnlyPostgresResearchRunStore(postgres_dsn)
    command_id = OnlyProductCommandId("00000000-0000-4000-8000-000000000901")
    run = _queued("00000000-0000-4000-8000-000000000911")
    fingerprint = "a" * 64
    receipt = _create_receipt(command_id, run, fingerprint)
    admission = _admission(command_id, fingerprint, run)
    _preadmit(postgres_dsn, command_id, fingerprint)

    assert (
        store.create_queued_with_novelty_admission(
            run,
            receipt,
            admission,
            expected_source_frontier=_frontier(postgres_dsn),
        )
        == receipt
    )
    assert store.load_novelty_admission(command_id) == admission
    assert store.load(run.run_id) == run
    assert store.find_product_command_receipt(command_id) == receipt

    second_id = OnlyProductCommandId("00000000-0000-4000-8000-000000000903")
    second_run = _queued("00000000-0000-4000-8000-000000000914")
    second_fingerprint = "c" * 64
    _preadmit(postgres_dsn, second_id, second_fingerprint)
    with pytest.raises(OnlyResearchRunIntegrityError, match="NOVELTY_SAME_SUBJECT_IN_FLIGHT"):
        store.create_queued_with_novelty_admission(
            second_run,
            _create_receipt(second_id, second_run, second_fingerprint),
            _admission(second_id, second_fingerprint, second_run),
            expected_source_frontier=_frontier(postgres_dsn),
        )
    assert store.find_product_command_receipt(second_id) is None


def test_stale_frontier_and_same_subject_in_flight_create_zero_second_run(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    store = OnlyPostgresResearchRunStore(postgres_dsn)

    stale_id = OnlyProductCommandId("00000000-0000-4000-8000-000000000902")
    stale_run = _queued("00000000-0000-4000-8000-000000000912")
    stale_fingerprint = "b" * 64
    _preadmit(postgres_dsn, stale_id, stale_fingerprint)
    stale_frontier = _frontier(postgres_dsn)
    store.create_queued(_queued("00000000-0000-4000-8000-000000000913"))
    with pytest.raises(OnlyResearchRunIntegrityError, match="NOVELTY_DECISION_STALE"):
        store.create_queued_with_novelty_admission(
            stale_run,
            _create_receipt(stale_id, stale_run, stale_fingerprint),
            _admission(stale_id, stale_fingerprint, stale_run),
            expected_source_frontier=stale_frontier,
        )
    assert store.find_product_command_receipt(stale_id) is None

    # A legacy nonterminal Run is deliberately unclassified and therefore
    # blocks every new subject until it reaches a terminal state.
    fresh_frontier = _frontier(postgres_dsn)
    with pytest.raises(OnlyResearchRunIntegrityError, match="NOVELTY_UNCLASSIFIED_RESEARCH_IN_FLIGHT"):
        store.create_queued_with_novelty_admission(
            stale_run,
            _create_receipt(stale_id, stale_run, stale_fingerprint),
            _admission(stale_id, stale_fingerprint, stale_run),
            expected_source_frontier=fresh_frontier,
        )
    assert store.find_product_command_receipt(stale_id) is None


def test_real_concurrent_commands_same_subject_commit_at_most_one_run(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    command_ids = (
        OnlyProductCommandId("00000000-0000-4000-8000-000000000904"),
        OnlyProductCommandId("00000000-0000-4000-8000-000000000905"),
    )
    runs = (
        _queued("00000000-0000-4000-8000-000000000915"),
        _queued("00000000-0000-4000-8000-000000000916"),
    )
    fingerprints = ("d" * 64, "e" * 64)
    for command_id, fingerprint in zip(command_ids, fingerprints, strict=True):
        _preadmit(postgres_dsn, command_id, fingerprint)
    expected = _frontier(postgres_dsn)
    barrier = Barrier(2)

    def submit(index: int) -> str:
        barrier.wait()
        try:
            OnlyPostgresResearchRunStore(postgres_dsn).create_queued_with_novelty_admission(
                runs[index],
                _create_receipt(command_ids[index], runs[index], fingerprints[index]),
                _admission(command_ids[index], fingerprints[index], runs[index]),
                expected_source_frontier=expected,
            )
            return "COMMITTED"
        except OnlyResearchRunIntegrityError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(submit, range(2)))
    assert outcomes.count("COMMITTED") == 1
    assert any("NOVELTY_DECISION_STALE" in item for item in outcomes)
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM research_novelty_admission").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM research_run").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM product_command_receipt").fetchone() == (1,)


def test_receipt_insert_fault_rolls_back_run_and_admission(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    command_id = OnlyProductCommandId("00000000-0000-4000-8000-000000000906")
    run = _queued("00000000-0000-4000-8000-000000000917")
    fingerprint = "f" * 64
    _preadmit(postgres_dsn, command_id, fingerprint)
    expected = _frontier(postgres_dsn)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "CREATE FUNCTION reject_novelty_receipt() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN RAISE EXCEPTION 'injected receipt failure'; END $$"
        )
        connection.execute(
            "CREATE TRIGGER reject_novelty_receipt_trigger BEFORE INSERT ON product_command_receipt "
            "FOR EACH ROW EXECUTE FUNCTION reject_novelty_receipt()"
        )
    with pytest.raises(OnlyResearchRunStoreUnavailableError, match="Novelty-gated Research transaction failed"):
        OnlyPostgresResearchRunStore(postgres_dsn).create_queued_with_novelty_admission(
            run,
            _create_receipt(command_id, run, fingerprint),
            _admission(command_id, fingerprint, run),
            expected_source_frontier=expected,
        )
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM research_novelty_admission").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM research_run").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM product_command_receipt").fetchone() == (0,)
