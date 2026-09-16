from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
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
    OnlyResearchNoveltyAdmissionSubjectV1,
    OnlyResearchNoveltyAdmissionV1,
    OnlyResearchNoveltyAdmissionV2,
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


def _aggregate_admission(command_id, command_fingerprint, run, subjects):  # type: ignore[no-untyped-def]
    ordered = tuple(sorted(subjects))
    members = tuple(
        OnlyResearchNoveltyAdmissionSubjectV1(
            index,
            subject,
            f"{index + 1:x}" * 64,
            "2" * 64,
            "5" * 64,
            "6" * 64,
            only_novelty_same_subject_guard_key(subject),
        )
        for index, subject in enumerate(ordered)
    )
    return OnlyResearchNoveltyAdmissionV2(
        command_id,
        command_fingerprint,
        "8" * 64,
        "9" * 64,
        "7" * 64,
        run.run_id.value,
        run.run_id,
        members,
    )


def _preadmit(dsn: str, command_id: OnlyProductCommandId, fingerprint: str) -> None:
    OnlyPostgresProductCommandAuthority(dsn).admit_exact(
        OnlyProductCommandAdmissionV1(
            command_id,
            OnlyProductCommandKind.CREATE_RESEARCH_RUN,
            fingerprint,
        )
    )


@pytest.mark.parametrize("forgery", ("group", "member", "proof"))
def test_caller_authored_admission_forgery_has_no_public_persistence_path(postgres_dsn: str, forgery: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    store = OnlyPostgresResearchRunStore(postgres_dsn)
    command_id = OnlyProductCommandId("00000000-0000-4000-8000-000000000920")
    run = _queued("00000000-0000-4000-8000-000000000930")
    admission = _aggregate_admission(command_id, "a" * 64, run, ("b" * 64, "c" * 64))
    if forgery == "group":
        admission = replace(admission, decision_group_fingerprint="f" * 64)
    elif forgery == "member":
        admission = replace(
            admission,
            members=(replace(admission.members[0], novelty_decision_fingerprint="e" * 64), *admission.members[1:]),
        )
    else:
        admission = replace(
            admission,
            members=(replace(admission.members[0], action_time_proof_fingerprint="d" * 64), *admission.members[1:]),
        )
    assert admission.admission_fingerprint
    assert not hasattr(store, "create_queued_with_novelty_admission")
    with pytest.raises(AttributeError):
        _ = store.create_queued_with_novelty_admission  # type: ignore[attr-defined]
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM research_novelty_admission").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM research_run").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM product_command_receipt").fetchone() == (0,)


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
        store._create_queued_with_verified_novelty_admission(
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
        store._create_queued_with_verified_novelty_admission(
            second_run,
            _create_receipt(second_id, second_run, second_fingerprint),
            _admission(second_id, second_fingerprint, second_run),
            expected_source_frontier=_frontier(postgres_dsn),
        )
    assert store.find_product_command_receipt(second_id) is None


def test_aggregate_parent_all_members_run_and_receipt_commit_atomically(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    store = OnlyPostgresResearchRunStore(postgres_dsn)
    command_id = OnlyProductCommandId("00000000-0000-4000-8000-000000000921")
    run = _queued("00000000-0000-4000-8000-000000000931")
    fingerprint = "a" * 64
    admission = _aggregate_admission(command_id, fingerprint, run, ("b" * 64, "a" * 64))
    receipt = _create_receipt(command_id, run, fingerprint)
    _preadmit(postgres_dsn, command_id, fingerprint)

    assert (
        store._create_queued_with_verified_novelty_admission(
            run, receipt, admission, expected_source_frontier=_frontier(postgres_dsn)
        )
        == receipt
    )
    assert store.load_novelty_admission(command_id) == admission
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM research_novelty_admission").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM research_novelty_admission_subject").fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM research_run").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM product_command_receipt").fetchone() == (1,)


@pytest.mark.parametrize(
    ("left", "right", "expected_commits"),
    (
        (("a" * 64, "b" * 64), ("b" * 64, "c" * 64), 1),
        (("a" * 64, "b" * 64), ("c" * 64, "d" * 64), 2),
    ),
)
def test_aggregate_partial_overlap_serializes_while_disjoint_sets_both_commit(
    postgres_dsn: str,
    left: tuple[str, ...],
    right: tuple[str, ...],
    expected_commits: int,
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    command_ids = (
        OnlyProductCommandId("00000000-0000-4000-8000-000000000922"),
        OnlyProductCommandId("00000000-0000-4000-8000-000000000923"),
    )
    runs = (
        _queued("00000000-0000-4000-8000-000000000932"),
        _queued("00000000-0000-4000-8000-000000000933"),
    )
    fingerprints = ("c" * 64, "d" * 64)
    subject_sets = (left, right)
    for command_id, fingerprint in zip(command_ids, fingerprints, strict=True):
        _preadmit(postgres_dsn, command_id, fingerprint)
    expected = _frontier(postgres_dsn)
    barrier = Barrier(2)

    def submit(index: int) -> str:
        barrier.wait()
        try:
            OnlyPostgresResearchRunStore(postgres_dsn)._create_queued_with_verified_novelty_admission(
                runs[index],
                _create_receipt(command_ids[index], runs[index], fingerprints[index]),
                _aggregate_admission(command_ids[index], fingerprints[index], runs[index], subject_sets[index]),
                expected_source_frontier=expected,
            )
            return "COMMITTED"
        except OnlyResearchRunIntegrityError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(submit, range(2)))
    assert outcomes.count("COMMITTED") == expected_commits
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM research_novelty_admission").fetchone() == (expected_commits,)
        assert connection.execute("SELECT count(*) FROM research_run").fetchone() == (expected_commits,)
        assert connection.execute("SELECT count(*) FROM product_command_receipt").fetchone() == (expected_commits,)


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
        store._create_queued_with_verified_novelty_admission(
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
        store._create_queued_with_verified_novelty_admission(
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
            OnlyPostgresResearchRunStore(postgres_dsn)._create_queued_with_verified_novelty_admission(
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
        OnlyPostgresResearchRunStore(postgres_dsn)._create_queued_with_verified_novelty_admission(
            run,
            _create_receipt(command_id, run, fingerprint),
            _admission(command_id, fingerprint, run),
            expected_source_frontier=expected,
        )
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM research_novelty_admission").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM research_run").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM product_command_receipt").fetchone() == (0,)


def test_member_insert_fault_rolls_back_aggregate_parent_run_and_receipt(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    command_id = OnlyProductCommandId("00000000-0000-4000-8000-000000000924")
    run = _queued("00000000-0000-4000-8000-000000000934")
    fingerprint = "e" * 64
    _preadmit(postgres_dsn, command_id, fingerprint)
    expected = _frontier(postgres_dsn)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "CREATE FUNCTION reject_second_novelty_member() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN IF NEW.ordinal = 1 THEN RAISE EXCEPTION 'injected member failure'; END IF; RETURN NEW; END $$"
        )
        connection.execute(
            "CREATE TRIGGER reject_second_novelty_member_trigger BEFORE INSERT "
            "ON research_novelty_admission_subject FOR EACH ROW EXECUTE FUNCTION reject_second_novelty_member()"
        )
    with pytest.raises(OnlyResearchRunStoreUnavailableError, match="Novelty-gated Research transaction failed"):
        OnlyPostgresResearchRunStore(postgres_dsn)._create_queued_with_verified_novelty_admission(
            run,
            _create_receipt(command_id, run, fingerprint),
            _aggregate_admission(command_id, fingerprint, run, ("a" * 64, "b" * 64)),
            expected_source_frontier=expected,
        )
    with psycopg.connect(postgres_dsn) as connection:
        for table in (
            "research_novelty_admission_subject",
            "research_novelty_admission",
            "research_run",
            "product_command_receipt",
        ):
            assert connection.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)  # noqa: S608
