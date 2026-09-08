from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import psycopg
import pytest

from onlyalpha.application.product_command_authority import (
    OnlyProductCommandBindingState,
    OnlyProductCommandConflictError,
    OnlyProductCommandPutDisposition,
    OnlyProductCommandReceiptCorruptError,
)
from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandAdmissionV1,
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandOutcomeRef,
    OnlyProductCommandReceipt,
)
from onlyalpha.backtest.errors import OnlyBacktestError
from onlyalpha.persistence.postgres import OnlyPostgresProductCommandAuthority
from onlyalpha.persistence.postgres.backtest_store import OnlyPostgresBacktestStore
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.persistence.postgres.research_run_store import OnlyPostgresResearchRunStore
from onlyalpha.research.run.errors import OnlyResearchRunStoreUnavailableError
from tests.research.postgres.migration_support import copy_migrations_through
from tests.research.postgres.test_backtest_execution_authority import (
    _queued as _backtest_queued,
)
from tests.research.postgres.test_backtest_execution_authority import (
    _receipt as _backtest_receipt,
)
from tests.research.postgres.test_postgres_authority import _create_receipt, _queued

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]

NOW = datetime(2026, 9, 8, 1, 2, 3, tzinfo=UTC)
COMMAND_ID = OnlyProductCommandId("00000000-0000-4000-8000-000000000901")


def _admission(
    kind: OnlyProductCommandKind = OnlyProductCommandKind.CREATE_RESEARCH_RUN,
    fingerprint: str = "a" * 64,
) -> OnlyProductCommandAdmissionV1:
    return OnlyProductCommandAdmissionV1(COMMAND_ID, kind, fingerprint)


def _receipt(outcome_id: str = "00000000-0000-4000-8000-000000000902") -> OnlyProductCommandReceipt:
    return OnlyProductCommandReceipt(
        COMMAND_ID,
        OnlyProductCommandKind.CREATE_RESEARCH_RUN,
        "a" * 64,
        OnlyProductCommandOutcomeRef(OnlyProductCommandOutcomeKind.RESEARCH_RUN, outcome_id),
        NOW,
    )


def test_admission_put_once_binding_and_receipt_verification(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    authority = OnlyPostgresProductCommandAuthority(postgres_dsn)

    assert authority.verify_binding(COMMAND_ID).state is OnlyProductCommandBindingState.NONE
    assert authority.admit_exact(_admission()) is OnlyProductCommandPutDisposition.CREATED
    assert authority.admit_exact(_admission()) is OnlyProductCommandPutDisposition.REUSED
    assert authority.verify_binding(COMMAND_ID).state is OnlyProductCommandBindingState.ADMITTED_NO_OUTCOME
    with pytest.raises(OnlyProductCommandConflictError):
        authority.admit_exact(_admission(OnlyProductCommandKind.CREATE_BACKTEST_RUN))
    with pytest.raises(OnlyProductCommandConflictError):
        authority.admit_exact(_admission(fingerprint="b" * 64))

    receipt = _receipt()
    assert authority.put_verified_receipt(receipt) is OnlyProductCommandPutDisposition.CREATED
    assert authority.put_verified_receipt(receipt) is OnlyProductCommandPutDisposition.REUSED
    verified = authority.verify_binding(COMMAND_ID)
    assert verified.state is OnlyProductCommandBindingState.VERIFIED_ACCEPTED
    assert verified.receipt == receipt
    with pytest.raises(OnlyProductCommandConflictError):
        authority.put_verified_receipt(_receipt("00000000-0000-4000-8000-000000000903"))


def test_receipt_without_admission_and_mismatched_integrity_fail_closed(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    authority = OnlyPostgresProductCommandAuthority(postgres_dsn)
    receipt = _receipt()
    with pytest.raises(OnlyProductCommandReceiptCorruptError):
        authority.put_verified_receipt(receipt)

    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            """INSERT INTO product_command_receipt
            (command_id, command_kind, command_fingerprint, outcome_kind, outcome_id, accepted_at, schema_version)
            VALUES (%s, %s, %s, %s, %s, %s, 1)""",
            (
                receipt.command_id.value,
                receipt.command_kind.value,
                receipt.command_fingerprint,
                receipt.outcome_ref.kind.value,
                receipt.outcome_ref.outcome_id,
                receipt.accepted_at,
            ),
        )
    with pytest.raises(OnlyProductCommandReceiptCorruptError):
        authority.load_verified_receipt(COMMAND_ID)
    with pytest.raises(OnlyProductCommandReceiptCorruptError):
        authority.admit_exact(_admission())

    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            """INSERT INTO product_command_admission
            (command_id, command_kind, command_fingerprint, schema_version)
            VALUES (%s, 'CREATE_BACKTEST_RUN', %s, 1)""",
            (COMMAND_ID.value, "b" * 64),
        )
    with pytest.raises(OnlyProductCommandReceiptCorruptError):
        authority.load_verified_receipt(COMMAND_ID)


def test_concurrent_admission_converges_and_conflict_has_one_winner(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    barrier = Barrier(2)

    def admit(admission: OnlyProductCommandAdmissionV1) -> str:
        barrier.wait()
        try:
            return OnlyPostgresProductCommandAuthority(postgres_dsn).admit_exact(admission).value
        except OnlyProductCommandConflictError:
            return "CONFLICT"

    with ThreadPoolExecutor(max_workers=2) as pool:
        same = tuple(pool.map(admit, (_admission(), _admission())))
    assert sorted(same) == ["CREATED", "REUSED"]

    other_id = OnlyProductCommandId("00000000-0000-4000-8000-000000000911")
    barrier = Barrier(2)
    first = OnlyProductCommandAdmissionV1(other_id, OnlyProductCommandKind.CREATE_RESEARCH_RUN, "c" * 64)
    second = OnlyProductCommandAdmissionV1(other_id, OnlyProductCommandKind.CREATE_BACKTEST_RUN, "d" * 64)
    with ThreadPoolExecutor(max_workers=2) as pool:
        conflicting = tuple(pool.map(admit, (first, second)))
    assert sorted(conflicting) == ["CONFLICT", "CREATED"]


def test_global_command_id_conflicts_before_real_cross_subsystem_effect(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    authority = OnlyPostgresProductCommandAuthority(postgres_dsn)
    assert authority.admit_exact(_admission()) is OnlyProductCommandPutDisposition.CREATED
    backtest = _backtest_queued()
    with pytest.raises(OnlyBacktestError, match="PRODUCT_COMMAND_CONFLICT"):
        OnlyPostgresBacktestStore(postgres_dsn).create_queued_with_receipt(
            backtest,
            _backtest_receipt(backtest, COMMAND_ID.value, "b" * 64),
        )
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM backtest_run").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM product_command_admission").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM product_command_receipt").fetchone() == (0,)


def test_research_admission_effect_receipt_transaction_rolls_back_on_injected_effect_failure(
    postgres_dsn: str,
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    run = _queued("00000000-0000-4000-8000-000000000931")
    command_id = OnlyProductCommandId("00000000-0000-4000-8000-000000000932")
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            """CREATE FUNCTION reject_research_run_insert() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'INJECTED_AFTER_ADMISSION'; END $$"""
        )
        connection.execute(
            """CREATE TRIGGER reject_research_run_insert
            BEFORE INSERT ON research_run FOR EACH ROW EXECUTE FUNCTION reject_research_run_insert()"""
        )
    with pytest.raises(OnlyResearchRunStoreUnavailableError, match="transaction failed"):
        OnlyPostgresResearchRunStore(postgres_dsn).create_queued_with_receipt(
            run,
            _create_receipt(command_id, run, "9" * 64),
        )
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM product_command_admission").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM research_run").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM product_command_receipt").fetchone() == (0,)


def test_0021_backfills_receipts_preserves_rows_and_extends_search_checks(postgres_dsn: str, tmp_path) -> None:  # type: ignore[no-untyped-def]
    copy_migrations_through(tmp_path, "0020_strategy_qualification_authority")
    OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=tmp_path).migrate()
    receipt = _receipt()
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            """INSERT INTO product_command_receipt
            (command_id, command_kind, command_fingerprint, outcome_kind, outcome_id, accepted_at, schema_version)
            VALUES (%s, %s, %s, %s, %s, %s, 1)""",
            (
                receipt.command_id.value,
                receipt.command_kind.value,
                receipt.command_fingerprint,
                receipt.outcome_ref.kind.value,
                receipt.outcome_ref.outcome_id,
                receipt.accepted_at,
            ),
        )
        before = connection.execute("SELECT * FROM product_command_receipt").fetchall()

    source = copy_migrations_through(tmp_path, "0021_product_command_admission_authority")
    assert source[-1] == "0021_product_command_admission_authority"
    assert OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=tmp_path).migrate() == (
        "0021_product_command_admission_authority",
    )
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT * FROM product_command_receipt").fetchall() == before
        assert connection.execute("SELECT count(*) FROM product_command_admission").fetchone() == (1,)
        search_id = "00000000-0000-4000-8000-000000000921"
        connection.execute(
            """INSERT INTO product_command_admission VALUES
            (%s, 'CREATE_SYMBOLIC_SEARCH_EXPERIMENT', %s, 1)""",
            (search_id, "e" * 64),
        )
        connection.execute(
            """INSERT INTO product_command_receipt VALUES
            (%s, 'CREATE_SYMBOLIC_SEARCH_EXPERIMENT', %s, 'SEARCH_EXPERIMENT', %s, %s, 1)""",
            (search_id, "e" * 64, "f" * 64, NOW),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                connection.execute(
                    """INSERT INTO product_command_receipt VALUES
                    (%s, 'CREATE_PARAMETER_SEARCH_EXPERIMENT', %s, 'SEARCH_EXPERIMENT', %s, %s, 1)""",
                    (
                        "00000000-0000-4000-8000-000000000922",
                        "a" * 64,
                        COMMAND_ID.value,
                        NOW,
                    ),
                )
        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                connection.execute(
                    """INSERT INTO product_command_receipt VALUES
                    (%s, 'ADVANCE_SEARCH_EXPERIMENT', %s, 'SEARCH_EXPERIMENT', %s, %s, 1)""",
                    (
                        "00000000-0000-4000-8000-000000000923",
                        "a" * 64,
                        "G" * 64,
                        NOW,
                    ),
                )
