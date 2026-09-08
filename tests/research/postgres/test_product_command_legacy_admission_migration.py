from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest

from onlyalpha.application.product_command_authority import OnlyProductCommandConflictError
from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandAdmissionV1,
    OnlyProductCommandId,
    OnlyProductCommandKind,
)
from onlyalpha.backtest.errors import OnlyBacktestError
from onlyalpha.persistence.postgres import (
    OnlyPostgresProductCommandAuthority,
    OnlyPostgresResearchDeploymentStore,
)
from onlyalpha.persistence.postgres.backtest_store import OnlyPostgresBacktestStore
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.persistence.postgres.research_run_store import OnlyPostgresResearchRunStore
from onlyalpha.persistence.postgres.strategy_product_store import OnlyPostgresStrategyProductStore
from onlyalpha.persistence.postgres.strategy_store import OnlyPostgresStrategyStore
from onlyalpha.research.operations.deployment import OnlyResearchSemanticStoreId
from onlyalpha.research.run.errors import OnlyPostgresMigrationIntegrityError
from tests.research.postgres.migration_support import copy_migrations_through
from tests.research.postgres.test_backtest_execution_authority import (
    _queued as _backtest_queued,
)
from tests.research.postgres.test_backtest_execution_authority import (
    _receipt as _backtest_receipt,
)
from tests.research.postgres.test_postgres_authority import _queued

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]

M20 = "0020_strategy_qualification_authority"
M21 = "0021_product_command_admission_authority"
M22 = "0022_product_command_legacy_admission_closure"
NOW = datetime(2026, 9, 8, 1, 2, 3, tzinfo=UTC)
NAMESPACE = OnlyResearchSemanticStoreId("00000000-0000-4000-8000-000000000971")
RESEARCH_RUN_ID = "00000000-0000-4000-8000-000000000972"
STRATEGY_FINGERPRINT = "a" * 64


def _migrate_through(postgres_dsn: str, root: Path, migration_id: str) -> tuple[str, ...]:
    copy_migrations_through(root, migration_id)
    return OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=root).migrate()


def _seed_prerequisites(postgres_dsn: str) -> None:
    OnlyPostgresResearchDeploymentStore(postgres_dsn).initialize(NAMESPACE)
    OnlyPostgresStrategyStore(postgres_dsn, NAMESPACE).ensure_strategy(STRATEGY_FINGERPRINT, 1)
    OnlyPostgresResearchRunStore(postgres_dsn).create_queued(_queued(RESEARCH_RUN_ID))


def _insert_freeze(
    connection: psycopg.Connection[object],
    command_id: str,
    fingerprint: str,
    *,
    completed: bool = False,
) -> None:
    if completed:
        connection.execute(
            """INSERT INTO strategy_freeze_command_admission
            (command_id, command_fingerprint, research_run_id, candidate_fingerprint, actor, comment,
             state, strategy_fingerprint, freeze_relation_fingerprint, prepared_at, published_at,
             completed_at, schema_version)
            VALUES (%s, %s, %s, %s, 'operator', NULL, 'COMPLETED', %s, %s, %s, %s, %s, 1)""",
            (
                command_id,
                fingerprint,
                RESEARCH_RUN_ID,
                "b" * 64,
                STRATEGY_FINGERPRINT,
                "c" * 64,
                NOW,
                NOW,
                NOW,
            ),
        )
        return
    connection.execute(
        """INSERT INTO strategy_freeze_command_admission
        (command_id, command_fingerprint, research_run_id, candidate_fingerprint, actor, comment,
         state, prepared_at, schema_version)
        VALUES (%s, %s, %s, %s, 'operator', NULL, 'PREPARED', %s, 1)""",
        (command_id, fingerprint, RESEARCH_RUN_ID, "b" * 64, NOW),
    )


def _insert_qualification(
    connection: psycopg.Connection[object],
    command_id: str,
    fingerprint: str,
    *,
    completed: bool = False,
) -> None:
    if completed:
        connection.execute(
            """INSERT INTO qualification_command_admission
            (command_id, command_fingerprint, subject_strategy_fingerprint, policy_id, policy_version,
             evidence_payload, state, decision_fingerprint, prepared_at, completed_at, schema_version)
            VALUES (%s, %s, %s, 'policy', '1', '[]'::jsonb, 'COMPLETED', %s, %s, %s, 1)""",
            (command_id, fingerprint, STRATEGY_FINGERPRINT, "d" * 64, NOW, NOW),
        )
        return
    connection.execute(
        """INSERT INTO qualification_command_admission
        (command_id, command_fingerprint, subject_strategy_fingerprint, policy_id, policy_version,
         evidence_payload, state, prepared_at, schema_version)
        VALUES (%s, %s, %s, 'policy', '1', '[]'::jsonb, 'PREPARED', %s, 1)""",
        (command_id, fingerprint, STRATEGY_FINGERPRINT, NOW),
    )


def _insert_receipt(
    connection: psycopg.Connection[object],
    command_id: str,
    kind: str,
    fingerprint: str,
    outcome_kind: str,
    outcome_id: str,
) -> None:
    connection.execute(
        """INSERT INTO product_command_receipt
        (command_id, command_kind, command_fingerprint, outcome_kind, outcome_id, accepted_at, schema_version)
        VALUES (%s, %s, %s, %s, %s, %s, 1)""",
        (command_id, kind, fingerprint, outcome_kind, outcome_id, NOW),
    )


def _assert_legacy_conflict(error: pytest.ExceptionInfo[OnlyPostgresMigrationIntegrityError]) -> None:
    assert isinstance(error.value.__cause__, psycopg.errors.CheckViolation)
    assert "Product Command legacy Admission conflict" in str(error.value.__cause__)


def test_0022_from_0020_preserves_prepared_workflows_recovers_and_blocks_reuse(
    postgres_dsn: str,
    tmp_path: Path,
) -> None:
    _migrate_through(postgres_dsn, tmp_path, M20)
    _seed_prerequisites(postgres_dsn)
    freeze_id = "00000000-0000-4000-8000-000000000973"
    qualification_id = "00000000-0000-4000-8000-000000000974"
    with psycopg.connect(postgres_dsn) as connection:
        _insert_freeze(connection, freeze_id, "e" * 64)
        _insert_qualification(connection, qualification_id, "f" * 64)
        freeze_before = connection.execute(
            "SELECT * FROM strategy_freeze_command_admission WHERE command_id = %s", (freeze_id,)
        ).fetchone()
        qualification_before = connection.execute(
            "SELECT * FROM qualification_command_admission WHERE command_id = %s", (qualification_id,)
        ).fetchone()

    assert _migrate_through(postgres_dsn, tmp_path, M22) == (M21, M22)
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute(
            """SELECT command_id::text, command_kind, command_fingerprint, schema_version
            FROM product_command_admission ORDER BY command_id"""
        ).fetchall() == [
            (freeze_id, "FREEZE_STRATEGY", "e" * 64, 1),
            (qualification_id, "EVALUATE_QUALIFICATION", "f" * 64, 1),
        ]
        assert (
            connection.execute(
                "SELECT * FROM strategy_freeze_command_admission WHERE command_id = %s", (freeze_id,)
            ).fetchone()
            == freeze_before
        )
        assert (
            connection.execute(
                "SELECT * FROM qualification_command_admission WHERE command_id = %s", (qualification_id,)
            ).fetchone()
            == qualification_before
        )
        assert connection.execute("SELECT count(*) FROM product_command_receipt").fetchone() == (0,)

    restarted = OnlyPostgresStrategyProductStore(postgres_dsn, NAMESPACE)
    assert restarted.load_freeze_admission(OnlyProductCommandId(freeze_id)).state.value == "PREPARED"
    assert restarted.load_qualification_admission(OnlyProductCommandId(qualification_id)).state.value == "PREPARED"

    conflicting = OnlyProductCommandAdmissionV1(
        OnlyProductCommandId(freeze_id),
        OnlyProductCommandKind.CREATE_RESEARCH_RUN,
        "9" * 64,
    )
    with pytest.raises(OnlyProductCommandConflictError):
        OnlyPostgresProductCommandAuthority(postgres_dsn).admit_exact(conflicting)

    backtest = _backtest_queued()
    with pytest.raises(OnlyBacktestError, match="PRODUCT_COMMAND_CONFLICT"):
        OnlyPostgresBacktestStore(postgres_dsn).create_queued_with_receipt(
            backtest,
            _backtest_receipt(backtest, freeze_id, "9" * 64),
        )
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM backtest_run").fetchone() == (0,)


def test_0022_completed_receipts_and_receipt_only_binding_converge_exactly(
    postgres_dsn: str,
    tmp_path: Path,
) -> None:
    _migrate_through(postgres_dsn, tmp_path, M20)
    _seed_prerequisites(postgres_dsn)
    freeze_id = "00000000-0000-4000-8000-000000000975"
    qualification_id = "00000000-0000-4000-8000-000000000976"
    receipt_only_id = "00000000-0000-4000-8000-000000000977"
    with psycopg.connect(postgres_dsn) as connection:
        _insert_freeze(connection, freeze_id, "1" * 64, completed=True)
        _insert_qualification(connection, qualification_id, "2" * 64, completed=True)
        _insert_receipt(
            connection,
            freeze_id,
            "FREEZE_STRATEGY",
            "1" * 64,
            "STRATEGY",
            STRATEGY_FINGERPRINT,
        )
        _insert_receipt(
            connection,
            qualification_id,
            "EVALUATE_QUALIFICATION",
            "2" * 64,
            "QUALIFICATION_DECISION",
            "d" * 64,
        )
        _insert_receipt(
            connection,
            receipt_only_id,
            "CREATE_RESEARCH_RUN",
            "3" * 64,
            "RESEARCH_RUN",
            RESEARCH_RUN_ID,
        )
        sources_before = (
            connection.execute("SELECT * FROM strategy_freeze_command_admission").fetchall(),
            connection.execute("SELECT * FROM qualification_command_admission").fetchall(),
            connection.execute("SELECT * FROM product_command_receipt ORDER BY command_id").fetchall(),
        )

    _migrate_through(postgres_dsn, tmp_path, M22)
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute(
            "SELECT command_id::text, command_kind, command_fingerprint FROM product_command_admission ORDER BY command_id"
        ).fetchall() == [
            (freeze_id, "FREEZE_STRATEGY", "1" * 64),
            (qualification_id, "EVALUATE_QUALIFICATION", "2" * 64),
            (receipt_only_id, "CREATE_RESEARCH_RUN", "3" * 64),
        ]
        assert (
            connection.execute("SELECT * FROM strategy_freeze_command_admission").fetchall(),
            connection.execute("SELECT * FROM qualification_command_admission").fetchall(),
            connection.execute("SELECT * FROM product_command_receipt ORDER BY command_id").fetchall(),
        ) == sources_before


def test_0022_applies_to_existing_0021_database_and_preserves_admission_only_rows(
    postgres_dsn: str,
    tmp_path: Path,
) -> None:
    _migrate_through(postgres_dsn, tmp_path, M20)
    _seed_prerequisites(postgres_dsn)
    freeze_id = "00000000-0000-4000-8000-000000000978"
    admission_only_id = "00000000-0000-4000-8000-000000000979"
    with psycopg.connect(postgres_dsn) as connection:
        _insert_freeze(connection, freeze_id, "4" * 64)
    assert _migrate_through(postgres_dsn, tmp_path, M21) == (M21,)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "INSERT INTO product_command_admission VALUES (%s, 'FREEZE_STRATEGY', %s, 1)",
            (freeze_id, "4" * 64),
        )
        connection.execute(
            "INSERT INTO product_command_admission VALUES (%s, 'CREATE_SYMBOLIC_SEARCH_EXPERIMENT', %s, 1)",
            (admission_only_id, "5" * 64),
        )
        before = connection.execute("SELECT * FROM product_command_admission ORDER BY command_id").fetchall()

    assert _migrate_through(postgres_dsn, tmp_path, M22) == (M22,)
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT * FROM product_command_admission ORDER BY command_id").fetchall() == before
        assert connection.execute("SELECT count(*) FROM product_command_receipt").fetchone() == (0,)


def test_0022_rejects_cross_legacy_conflict_atomically_from_0020(
    postgres_dsn: str,
    tmp_path: Path,
) -> None:
    _migrate_through(postgres_dsn, tmp_path, M20)
    _seed_prerequisites(postgres_dsn)
    conflict_id = "00000000-0000-4000-8000-000000000980"
    valid_id = "00000000-0000-4000-8000-000000000981"
    with psycopg.connect(postgres_dsn) as connection:
        _insert_freeze(connection, conflict_id, "6" * 64)
        _insert_qualification(connection, conflict_id, "7" * 64)
        _insert_freeze(connection, valid_id, "8" * 64)

    copy_migrations_through(tmp_path, M22)
    with pytest.raises(OnlyPostgresMigrationIntegrityError) as error:
        OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=tmp_path).migrate()
    _assert_legacy_conflict(error)
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT to_regclass('public.product_command_admission')").fetchone() == (None,)
        assert connection.execute(
            "SELECT migration_id FROM onlyalpha_schema_migration ORDER BY migration_id DESC LIMIT 1"
        ).fetchone() == (M20,)
        assert connection.execute("SELECT count(*) FROM strategy_freeze_command_admission").fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM qualification_command_admission").fetchone() == (1,)


def test_0022_rejects_existing_global_conflict_without_partial_backfill(
    postgres_dsn: str,
    tmp_path: Path,
) -> None:
    _migrate_through(postgres_dsn, tmp_path, M20)
    _seed_prerequisites(postgres_dsn)
    conflict_id = "00000000-0000-4000-8000-000000000982"
    valid_id = "00000000-0000-4000-8000-000000000983"
    with psycopg.connect(postgres_dsn) as connection:
        _insert_freeze(connection, conflict_id, "a" * 64)
        _insert_qualification(connection, valid_id, "b" * 64)
    _migrate_through(postgres_dsn, tmp_path, M21)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "INSERT INTO product_command_admission VALUES (%s, 'CREATE_RESEARCH_RUN', %s, 1)",
            (conflict_id, "c" * 64),
        )

    copy_migrations_through(tmp_path, M22)
    with pytest.raises(OnlyPostgresMigrationIntegrityError) as error:
        OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=tmp_path).migrate()
    _assert_legacy_conflict(error)
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute(
            "SELECT command_kind, command_fingerprint FROM product_command_admission WHERE command_id = %s",
            (conflict_id,),
        ).fetchone() == ("CREATE_RESEARCH_RUN", "c" * 64)
        assert connection.execute(
            "SELECT count(*) FROM product_command_admission WHERE command_id = %s", (valid_id,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM onlyalpha_schema_migration WHERE migration_id = %s", (M22,)
        ).fetchone() == (0,)
