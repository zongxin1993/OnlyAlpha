"""DDL shape and forward migration evidence, not compilation authoring or store admission."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

import onlyalpha.persistence.postgres.migration as migration_module
import tests.research.postgres.test_chart_calculation_admission as admission_tests
from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.persistence.postgres import DEFAULT_MIGRATION_ROOT, OnlyPostgresSchemaVerdict, OnlyPostgresSchemaVerifier
from onlyalpha.persistence.postgres.chart_calculation_preparation_store import (
    OnlyPostgresChartCalculationPreparationStore,
)
from onlyalpha.persistence.postgres.chart_calculation_store import OnlyPostgresChartCalculationAdmissionStore
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.research.run.errors import (
    OnlyPostgresMigrationIntegrityError,
    OnlyPostgresSchemaIncompatibleError,
    OnlyResearchRunStoreUnavailableError,
)
from tests.research.postgres.migration_support import copy_migrations_through
from tests.research.postgres.test_chart_calculation_preparation import GENERATION, WORKER, prepare, prepared_system

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]
PREVIOUS = "0046_chart_calculation_runtime_binding_relation"
MIGRATION = "0047_chart_calculation_compilation_relation"
TABLE = "chart_calculation_compilation"
COLUMNS = {
    "operation_id": "uuid",
    "input_preparation_revision": "bigint",
    "input_preparation_fence": "bigint",
    "input_selection_fingerprint": "text",
    "dataset_snapshot_fingerprint": "text",
    "dataset_materialization_id": "text",
    "runtime_generation_fingerprint": "text",
    "runtime_work_id": "uuid",
    "runtime_binding_event_fingerprint": "text",
    "catalog_witness_fingerprint": "text",
    "catalog_implementation_fingerprint": "text",
    "specification_fingerprint": "text",
    "result_plan_fingerprint": "text",
    "graph_fingerprint": "text",
    "calculation_fingerprint": "text",
    "implementation_fingerprint": "text",
    "compilation_json": "text",
    "compilation_fingerprint": "text",
    "schema_version": "smallint",
}
SHA_COLUMNS = tuple(name for name in COLUMNS if name.endswith("fingerprint"))


def _previous_schema(dsn: str, root: Path) -> OnlyPostgresMigrationAuthority:
    root.mkdir()
    copy_migrations_through(root, PREVIOUS)
    authority = OnlyPostgresMigrationAuthority(dsn, migration_root=root)
    assert authority.migrate()[-1] == PREVIOUS
    return authority


def _history(dsn: str) -> tuple[tuple[str, str], ...]:
    with psycopg.connect(dsn) as connection:
        return tuple(
            connection.execute(
                "SELECT migration_id, checksum_sha256 FROM onlyalpha_schema_migration ORDER BY migration_id"
            ).fetchall()
        )


def _chart_bytes(dsn: str) -> dict[str, tuple[bytes, ...]]:
    # Text columns retain their original bytes, including embedded canonical JSON.
    tables = (
        "chart_calculation_operation",
        "chart_calculation_preparation_fact",
        "product_command_admission",
        "product_command_receipt",
        "research_run_id_reservation",
        "research_run",
    )
    with psycopg.connect(dsn) as connection:
        return {
            table: tuple(
                row[0].encode("utf-8")
                for row in connection.execute(
                    sql.SQL("SELECT row_to_json(t)::text FROM {} t ORDER BY row_to_json(t)::text").format(
                        sql.Identifier(table)
                    )
                ).fetchall()
            )
            for table in tables
        }


def _shape_row(operation_id: str, runtime_work_id: str) -> dict[str, object]:
    # SQL structural fixture only. An object is not proof of canonical compilation;
    # the parent task's verified adapter must reject this semantically incomplete JSON.
    return {
        **dict.fromkeys(SHA_COLUMNS, "a" * 64),
        "operation_id": operation_id,
        "input_preparation_revision": 4,
        "input_preparation_fence": 1,
        "dataset_materialization_id": "dataset-materialization:" + "b" * 64,
        "runtime_work_id": runtime_work_id,
        "compilation_json": "{}",
        "schema_version": 1,
    }


def _insert(connection: psycopg.Connection, row: dict[str, object]) -> None:
    connection.execute(
        sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            sql.Identifier(TABLE),
            sql.SQL(",").join(map(sql.Identifier, row)),
            sql.SQL(",").join(sql.Placeholder() for _ in row),
        ),
        tuple(row.values()),
    )


@pytest.fixture
def shape_row(postgres_dsn: str) -> dict[str, object]:
    operation = admission_tests.admit(admission_tests.store(postgres_dsn)).operation
    return _shape_row(operation.operation_id.value, operation.reserved_run_id.value)


def test_previous_history_is_behind_with_exact_pending_compilation_migration(postgres_dsn: str, tmp_path: Path) -> None:
    _previous_schema(postgres_dsn, tmp_path / "previous")
    before = _history(postgres_dsn)
    verifier = OnlyPostgresSchemaVerifier(postgres_dsn)
    status = verifier.status()
    assert status.verdict is OnlyPostgresSchemaVerdict.BEHIND
    assert status.applied_migrations[-1] == PREVIOUS
    assert status.pending_migrations == (MIGRATION,)
    with pytest.raises(OnlyPostgresSchemaIncompatibleError, match="BEHIND"):
        verifier.assert_compatible()
    authority = OnlyPostgresMigrationAuthority(postgres_dsn)
    assert tuple(item.migration_id for item in authority.plan()) == (MIGRATION,)
    assert _history(postgres_dsn) == before
    assert authority.migrate() == (MIGRATION,)
    assert authority.migrate() == ()
    assert verifier.status().verdict is OnlyPostgresSchemaVerdict.COMPATIBLE
    assert _history(postgres_dsn) == before + (
        (MIGRATION, hashlib.sha256((DEFAULT_MIGRATION_ROOT / f"{MIGRATION}.sql").read_bytes()).hexdigest()),
    )


@pytest.mark.parametrize("state", ["MATERIALIZING_INPUT", "INPUT_READY", "FAILED"])
def test_compilation_migration_preserves_readable_preparation_and_admission_bytes(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    previous = _previous_schema(postgres_dsn, tmp_path / "previous")
    # The fixture's normal startup migrate must not advance this historical database.
    with monkeypatch.context() as historical:
        historical.setattr(admission_tests, "OnlyPostgresMigrationAuthority", lambda _dsn: previous)
        system = prepared_system(postgres_dsn, tmp_path / "inputs", monkeypatch, period=1, acquire=state != "FAILED")
    if state == "MATERIALIZING_INPUT":
        preparation = system.adapter.claim(system.operation, WORKER, GENERATION, lease_duration=timedelta(minutes=2))
    else:
        preparation = prepare(system)
    if state == "FAILED":
        assert preparation.failure_code == "CHART_SEALED_COVERAGE_UNAVAILABLE"
        assert system.adapter.load_verified(system.operation) == preparation
    assert preparation.state == state
    old_admission = OnlyPostgresChartCalculationAdmissionStore(postgres_dsn)
    old_preparation = OnlyPostgresChartCalculationPreparationStore(postgres_dsn)
    assert old_admission.load_verified(system.operation.operation_id) == system.operation
    assert old_preparation.load_verified(system.operation) == preparation
    before = _chart_bytes(postgres_dsn)
    history = _history(postgres_dsn)
    assert before["chart_calculation_preparation_fact"]
    assert before["research_run"] == ()
    assert OnlyPostgresMigrationAuthority(postgres_dsn).migrate() == (MIGRATION,)
    assert _history(postgres_dsn)[:-1] == history
    assert _chart_bytes(postgres_dsn) == before
    assert old_admission.load_verified(system.operation.operation_id) == system.operation
    assert old_preparation.load_verified(system.operation) == preparation
    assert (
        OnlyPostgresChartCalculationAdmissionStore(postgres_dsn).load_verified(system.operation.operation_id)
        == system.operation
    )
    assert OnlyPostgresChartCalculationPreparationStore(postgres_dsn).load_verified(system.operation) == preparation
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM chart_calculation_compilation").fetchone() == (0,)


def test_compilation_ddl_and_ledger_roll_back_together_then_retry(postgres_dsn: str, tmp_path: Path) -> None:
    _previous_schema(postgres_dsn, tmp_path / "previous")
    before = _history(postgres_dsn)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "CREATE FUNCTION reject_compilation_ledger() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN IF NEW.migration_id = '0047_chart_calculation_compilation_relation' THEN "
            "RAISE EXCEPTION 'injected ledger failure'; END IF; RETURN NEW; END; $$"
        )
        connection.execute(
            "CREATE TRIGGER reject_compilation_ledger BEFORE INSERT ON onlyalpha_schema_migration "
            "FOR EACH ROW EXECUTE FUNCTION reject_compilation_ledger()"
        )
    authority = OnlyPostgresMigrationAuthority(postgres_dsn)
    with pytest.raises(OnlyPostgresMigrationIntegrityError) as error:
        authority.migrate()
    assert isinstance(error.value.__cause__, psycopg.errors.RaiseException)
    assert "injected ledger failure" in str(error.value.__cause__)
    assert _history(postgres_dsn) == before
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT to_regclass('public.chart_calculation_compilation')").fetchone() == (None,)
        connection.execute("DROP TRIGGER reject_compilation_ledger ON onlyalpha_schema_migration")
        connection.execute("DROP FUNCTION reject_compilation_ledger()")
    assert authority.migrate() == (MIGRATION,)
    assert authority.migrate() == ()
    assert _history(postgres_dsn)[:-1] == before


def test_compilation_migration_lost_postcommit_ack_reconciles_without_second_ddl(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _previous_schema(postgres_dsn, tmp_path / "previous")
    with monkeypatch.context() as fault:

        def lost_ack(_self: object) -> None:
            raise psycopg.OperationalError("injected postcommit acknowledgement loss")

        fault.setattr(migration_module._OnlyPostgresSchemaHistoryEvaluator, "assert_compatible", lost_ack)
        with pytest.raises(OnlyResearchRunStoreUnavailableError, match="migration unavailable"):
            OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    history = _history(postgres_dsn)
    assert history[-1][0] == MIGRATION
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT to_regclass('public.chart_calculation_compilation')").fetchone() == (TABLE,)
    assert OnlyPostgresSchemaVerifier(postgres_dsn).status().compatible
    assert OnlyPostgresMigrationAuthority(postgres_dsn).migrate() == ()
    assert _history(postgres_dsn) == history


def test_compilation_checksum_mismatch_fails_closed_without_repair(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE onlyalpha_schema_migration SET checksum_sha256 = %s WHERE migration_id = %s",
            ("0" * 64, MIGRATION),
        )
    before = _history(postgres_dsn)
    verifier = OnlyPostgresSchemaVerifier(postgres_dsn)
    assert verifier.status().verdict is OnlyPostgresSchemaVerdict.CHECKSUM_MISMATCH
    with pytest.raises(OnlyPostgresSchemaIncompatibleError, match="CHECKSUM_MISMATCH"):
        verifier.assert_compatible()
    authority = OnlyPostgresMigrationAuthority(postgres_dsn)
    with pytest.raises(OnlyPostgresMigrationIntegrityError, match="checksum mismatch"):
        authority.plan()
    with pytest.raises(OnlyPostgresMigrationIntegrityError, match="checksum mismatch"):
        authority.migrate()
    assert _history(postgres_dsn) == before


def test_compilation_table_has_only_frozen_nonnullable_relation_columns(
    postgres_dsn: str, shape_row: dict[str, object]
) -> None:
    with psycopg.connect(postgres_dsn) as connection:
        columns = connection.execute(
            "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position",
            (TABLE,),
        ).fetchall()
        assert columns == [(name, kind, "NO", None) for name, kind in COLUMNS.items()]
        _insert(connection, shape_row)


@pytest.mark.parametrize("column", COLUMNS)
def test_compilation_columns_reject_missing_proof(postgres_dsn: str, shape_row: dict[str, object], column: str) -> None:
    with pytest.raises(psycopg.errors.NotNullViolation):
        with psycopg.connect(postgres_dsn) as connection:
            _insert(connection, {**shape_row, column: None})


@pytest.mark.parametrize("column", SHA_COLUMNS)
@pytest.mark.parametrize("invalid", ["A" * 64, "g" * 64, "a" * 63, "a" * 65, ""])
def test_compilation_sha_references_reject_noncanonical_shape(
    postgres_dsn: str, shape_row: dict[str, object], column: str, invalid: str
) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(postgres_dsn) as connection:
            _insert(connection, {**shape_row, column: invalid})


@pytest.mark.parametrize("revision,fence", [(0, 1), (-1, 1), (4, 0), (4, -1), (4, 5)])
def test_compilation_revision_and_fence_require_positive_ordered_int64(
    postgres_dsn: str, shape_row: dict[str, object], revision: int, fence: int
) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(postgres_dsn) as connection:
            _insert(connection, {**shape_row, "input_preparation_revision": revision, "input_preparation_fence": fence})


def test_compilation_revision_and_fence_accept_full_signed_bigint_boundary(
    postgres_dsn: str, shape_row: dict[str, object]
) -> None:
    with psycopg.connect(postgres_dsn) as connection:
        _insert(
            connection, {**shape_row, "input_preparation_revision": 2**63 - 1, "input_preparation_fence": 2**63 - 1}
        )
    with pytest.raises(psycopg.errors.NumericValueOutOfRange):
        with psycopg.connect(postgres_dsn) as connection:
            _insert(connection, {**shape_row, "input_preparation_revision": 2**63})


@pytest.mark.parametrize("document", ["[]", "null", "true", "1", '"text"'])
def test_compilation_json_requires_object_not_other_json_family(
    postgres_dsn: str, shape_row: dict[str, object], document: str
) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(postgres_dsn) as connection:
            _insert(connection, {**shape_row, "compilation_json": document})


def test_compilation_json_rejects_invalid_json(postgres_dsn: str, shape_row: dict[str, object]) -> None:
    with pytest.raises(psycopg.errors.InvalidTextRepresentation):
        with psycopg.connect(postgres_dsn) as connection:
            _insert(connection, {**shape_row, "compilation_json": "{"})


@pytest.mark.parametrize("version", [0, 2, -1])
def test_compilation_schema_is_exactly_one(postgres_dsn: str, shape_row: dict[str, object], version: int) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(postgres_dsn) as connection:
            _insert(connection, {**shape_row, "schema_version": version})


@pytest.mark.parametrize("identifier", ["", " "])
def test_compilation_materialization_reference_cannot_be_empty(
    postgres_dsn: str, shape_row: dict[str, object], identifier: str
) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(postgres_dsn) as connection:
            _insert(connection, {**shape_row, "dataset_materialization_id": identifier})


def test_compilation_owner_fk_and_single_owner_identity(postgres_dsn: str, shape_row: dict[str, object]) -> None:
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with psycopg.connect(postgres_dsn) as connection:
            _insert(connection, {**shape_row, "operation_id": "00000000-0000-4000-8000-000000000799"})
    with psycopg.connect(postgres_dsn) as connection:
        _insert(connection, shape_row)
    with pytest.raises(psycopg.errors.UniqueViolation):
        with psycopg.connect(postgres_dsn) as connection:
            _insert(connection, {**shape_row, "compilation_fingerprint": "b" * 64})


def test_compilation_semantic_references_do_not_merge_distinct_operation_owners(
    postgres_dsn: str, shape_row: dict[str, object]
) -> None:
    second = (
        OnlyPostgresChartCalculationAdmissionStore(postgres_dsn)
        .admit_or_replay(
            OnlyProductCommandId("00000000-0000-4000-8000-000000000799"),
            admission_tests.request(),
            admission_tests.witness(),
            accepted_at=admission_tests.NOW,
        )
        .operation
    )
    with psycopg.connect(postgres_dsn) as connection:
        _insert(connection, shape_row)
        _insert(
            connection,
            {
                **shape_row,
                "operation_id": second.operation_id.value,
                "runtime_work_id": second.reserved_run_id.value,
                "compilation_fingerprint": "b" * 64,
            },
        )
        assert connection.execute("SELECT count(*) FROM chart_calculation_compilation").fetchone() == (2,)


@pytest.mark.parametrize("work", ["00000000-0000-1000-8000-000000000799", "00000000-0000-4000-0000-000000000799"])
def test_compilation_work_requires_canonical_uuid4_family(
    postgres_dsn: str, shape_row: dict[str, object], work: str
) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(postgres_dsn) as connection:
            _insert(connection, {**shape_row, "runtime_work_id": work})


@pytest.mark.parametrize("populated", [False, True])
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE chart_calculation_compilation SET schema_version = schema_version",
        "DELETE FROM chart_calculation_compilation",
        "TRUNCATE chart_calculation_compilation",
    ],
)
def test_compilation_relation_is_globally_immutable_even_for_empty_statements(
    postgres_dsn: str, shape_row: dict[str, object], populated: bool, statement: str
) -> None:
    with psycopg.connect(postgres_dsn) as connection:
        if populated:
            _insert(connection, shape_row)
        before = connection.execute("SELECT row_to_json(t)::text FROM chart_calculation_compilation t").fetchall()
    with pytest.raises(psycopg.errors.RaiseException, match="Research source history and cuts are immutable"):
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(statement)
    with psycopg.connect(postgres_dsn) as connection:
        assert (
            connection.execute("SELECT row_to_json(t)::text FROM chart_calculation_compilation t").fetchall() == before
        )
