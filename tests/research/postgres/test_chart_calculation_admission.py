from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier

import psycopg
import pytest

from onlyalpha.application.chart_calculation import OnlyChartCalculationAdmissionService
from onlyalpha.application.product_command_authority import OnlyProductCommandConflictError
from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandAdmissionV1,
    OnlyProductCommandId,
    OnlyProductCommandKind,
)
from onlyalpha.persistence.postgres.chart_calculation_store import OnlyPostgresChartCalculationAdmissionStore
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.persistence.postgres.product_command_authority import OnlyPostgresProductCommandAuthority
from tests.application.test_chart_calculation_admission import COMMAND, NOW, request, witness
from tests.research.postgres.migration_support import copy_migrations_through

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]


def store(dsn: str) -> OnlyPostgresChartCalculationAdmissionStore:
    OnlyPostgresMigrationAuthority(dsn).migrate()
    return OnlyPostgresChartCalculationAdmissionStore(dsn)


def admit(adapter: OnlyPostgresChartCalculationAdmissionStore, params: object = None):
    return adapter.admit_or_replay(OnlyProductCommandId(COMMAND), request(params), witness(), accepted_at=NOW)


def test_committed_chart_run_reservation_blocks_later_unrelated_research_run_insert(postgres_dsn: str) -> None:
    from onlyalpha.persistence.postgres.research_run_store import OnlyPostgresResearchRunStore, _insert_run_query
    from tests.research.postgres.test_postgres_authority import _queued

    operation = admit(store(postgres_dsn)).operation
    run = _queued(operation.reserved_run_id.value)
    # Fresh writer after T1 commit: direct/legacy SQL must obey the same exclusion.
    with pytest.raises(psycopg.errors.UniqueViolation, match="RESEARCH_RUN_ID_RESERVED"):
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(_insert_run_query(), OnlyPostgresResearchRunStore._values(run))


@pytest.mark.parametrize(
    "first,second", [({}, {"period": 20, "price_field": "CLOSE"}), ({"period": 20, "price_field": "close"}, {})]
)
def test_atomic_admission_and_restart_replay_without_current_catalog(
    postgres_dsn: str, first: object, second: object
) -> None:
    adapter = store(postgres_dsn)
    initial = admit(adapter, first)
    assert not initial.reused
    operation = initial.operation
    assert operation.reserved_run_id.value != COMMAND
    binding = OnlyPostgresProductCommandAuthority(postgres_dsn).verify_binding(OnlyProductCommandId(COMMAND))
    assert binding.receipt.outcome_ref.outcome_id == COMMAND
    assert binding.receipt.command_fingerprint == operation.command_fingerprint
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM research_run").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM chart_calculation_operation").fetchone()[0] == 1
        assert connection.execute(
            "SELECT run_id::text, owner_kind, owner_id::text, reserved_at, schema_version FROM research_run_id_reservation"
        ).fetchall() == [(operation.reserved_run_id.value, "CHART_CALCULATION", COMMAND, NOW, 1)]

    def forbidden_catalog():
        raise AssertionError("replay accessed current Catalog")

    service = OnlyChartCalculationAdmissionService(
        OnlyPostgresChartCalculationAdmissionStore(postgres_dsn), forbidden_catalog
    )
    replay = service.admit(OnlyProductCommandId(COMMAND), request(second), accepted_at=NOW + timedelta(days=1))
    assert replay.reused and replay.operation == operation
    with pytest.raises(OnlyProductCommandConflictError):
        service.admit(OnlyProductCommandId(COMMAND), request({"period": 21}), accepted_at=NOW)


def test_global_different_command_kind_conflicts_before_catalog(postgres_dsn: str) -> None:
    adapter = store(postgres_dsn)
    authority = OnlyPostgresProductCommandAuthority(postgres_dsn)
    authority.admit_exact(
        OnlyProductCommandAdmissionV1(
            OnlyProductCommandId(COMMAND), OnlyProductCommandKind.CREATE_RESEARCH_RUN, "a" * 64
        )
    )

    def forbidden():
        raise AssertionError("current Catalog access")

    with pytest.raises(OnlyProductCommandConflictError):
        OnlyChartCalculationAdmissionService(adapter, forbidden).admit(
            OnlyProductCommandId(COMMAND), request(), accepted_at=NOW
        )


def test_parallel_same_key_has_one_reservation(postgres_dsn: str) -> None:
    adapter = store(postgres_dsn)
    barrier = Barrier(2)

    def submit(_: int):
        barrier.wait()
        return admit(adapter)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(submit, range(2)))
    assert sorted(item.reused for item in outcomes) == [False, True]
    assert outcomes[0].operation == outcomes[1].operation


@pytest.mark.parametrize(
    "table",
    [
        "product_command_admission",
        "product_command_receipt",
        "chart_calculation_operation",
        "research_run_id_reservation",
    ],
)
def test_partial_t1_fails_closed_without_repair(postgres_dsn: str, table: str) -> None:
    from psycopg import sql

    adapter = store(postgres_dsn)
    admit(adapter)
    with psycopg.connect(postgres_dsn) as connection:
        # Deliberate physical corruption, bypassing immutable-history protection only in this isolated fixture.
        connection.execute(sql.SQL("ALTER TABLE {} DISABLE TRIGGER ALL").format(sql.Identifier(table)))
        connection.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier(table)))
    with pytest.raises(ValueError, match="CHART_OPERATION_RELATION_CORRUPT"):
        adapter.load_verified(OnlyProductCommandId(COMMAND))
    with pytest.raises(ValueError, match="CHART_OPERATION_RELATION_CORRUPT"):
        admit(adapter)


def test_reserved_run_collisions_regenerate_and_command_id_is_not_run_identity(
    postgres_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from onlyalpha.research.run.model import OnlyResearchRunId
    from tests.research.postgres.test_postgres_authority import _queued
    from tests.support.research_run_seeder import OnlyPostgresResearchRunSeeder

    adapter = store(postgres_dsn)
    # Existing Run with the client command UUID is unrelated to the new operation.
    run = _queued(COMMAND)
    OnlyPostgresResearchRunSeeder(postgres_dsn).seed_queued(run)
    choices = iter([OnlyResearchRunId(COMMAND), OnlyResearchRunId("00000000-0000-4000-8000-000000000703")])
    monkeypatch.setattr(OnlyResearchRunId, "new", classmethod(lambda cls: next(choices)))
    first = admit(adapter)
    assert first.operation.reserved_run_id.value.endswith("703")
    next_command = OnlyProductCommandId("00000000-0000-4000-8000-000000000704")
    choices = iter([first.operation.reserved_run_id, OnlyResearchRunId("00000000-0000-4000-8000-000000000705")])
    second = adapter.admit_or_replay(next_command, request(), witness(), accepted_at=NOW)
    assert second.operation.reserved_run_id.value.endswith("705")


def test_atomic_rollback_when_receipt_write_fails(postgres_dsn: str, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = store(postgres_dsn)

    def fail(*args: object) -> None:
        raise RuntimeError("injected Receipt failure")

    monkeypatch.setattr(OnlyPostgresProductCommandAuthority, "insert_verified_receipt", fail)
    with pytest.raises(RuntimeError, match="injected"):
        admit(adapter)
    with psycopg.connect(postgres_dsn) as connection:
        for table in (
            "product_command_admission",
            "product_command_receipt",
            "chart_calculation_operation",
            "research_run_id_reservation",
        ):
            from psycopg import sql

            assert (
                connection.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))).fetchone()[0] == 0
            )


@pytest.mark.parametrize(
    "column,value",
    [
        ("intent_fingerprint", "f" * 64),
        ("catalog_witness_fingerprint", "f" * 64),
        ("operation_fingerprint", "f" * 64),
        ("reserved_run_id", "00000000-0000-4000-8000-000000000709"),
        ("accepted_at", NOW + timedelta(seconds=1)),
    ],
)
def test_operation_integrity_mutations_reject(postgres_dsn: str, column: str, value: object) -> None:
    from psycopg import sql

    adapter = store(postgres_dsn)
    admit(adapter)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("ALTER TABLE chart_calculation_operation DISABLE TRIGGER ALL")
        connection.execute(
            sql.SQL("UPDATE chart_calculation_operation SET {} = %s").format(sql.Identifier(column)), (value,)
        )
    with pytest.raises(ValueError, match="CHART_OPERATION_RELATION_CORRUPT"):
        adapter.load_verified(OnlyProductCommandId(COMMAND))


def test_unknown_commit_response_reloads_exact_convergence(postgres_dsn: str, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = store(postgres_dsn)
    connect = psycopg.connect
    lost = False

    class LostResponse:
        def __init__(self, connection):
            self.connection = connection
            self.wrote = False

        def execute(self, query, *args):
            if isinstance(query, str) and "INSERT INTO chart_calculation_operation" in query:
                self.wrote = True
            return self.connection.execute(query, *args)

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, *args):
            nonlocal lost
            result = self.connection.__exit__(*args)
            if not lost and self.wrote and args[0] is None:
                lost = True
                raise psycopg.OperationalError("injected lost commit response")
            return result

    def wrapped(*args, **kwargs):
        return LostResponse(connect(*args, **kwargs))

    monkeypatch.setattr(psycopg, "connect", wrapped)
    outcome = admit(adapter)
    assert lost and outcome.reused
    assert adapter.load_verified(OnlyProductCommandId(COMMAND)) == outcome.operation


def test_operation_is_immutable_at_database_boundary(postgres_dsn: str) -> None:
    adapter = store(postgres_dsn)
    admit(adapter)
    for query in (
        "UPDATE chart_calculation_operation SET preparation_revision = 0",
        "DELETE FROM chart_calculation_operation",
        "TRUNCATE chart_calculation_operation CASCADE",
    ):
        with pytest.raises(psycopg.errors.RaiseException):
            with psycopg.connect(postgres_dsn) as connection:
                connection.execute(query)
    assert adapter.load_verified(OnlyProductCommandId(COMMAND)) is not None


def test_independent_reserved_id_collision_with_existing_research_run_regenerates(
    postgres_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from onlyalpha.research.run.model import OnlyResearchRunId
    from tests.research.postgres.test_postgres_authority import _queued
    from tests.support.research_run_seeder import OnlyPostgresResearchRunSeeder

    adapter = store(postgres_dsn)
    existing_id = "00000000-0000-4000-8000-000000000710"
    OnlyPostgresResearchRunSeeder(postgres_dsn).seed_queued(_queued(existing_id))
    choices = iter([OnlyResearchRunId(existing_id), OnlyResearchRunId("00000000-0000-4000-8000-000000000711")])
    monkeypatch.setattr(OnlyResearchRunId, "new", classmethod(lambda cls: next(choices)))
    assert admit(adapter).operation.reserved_run_id.value.endswith("711")


@pytest.mark.parametrize(
    "mutation",
    ["whole_context", "provider", "implementation", "source", "nested_readiness", "duplicate", "wrong_family"],
)
def test_structural_witness_corruption_cannot_be_replayed(postgres_dsn: str, mutation: str) -> None:
    from onlyalpha.canonical import only_canonical_json

    adapter = store(postgres_dsn)
    operation = admit(adapter).operation
    encoded = operation.catalog_witness.to_dict()
    context = encoded["context"]
    if mutation == "whole_context":
        del encoded["context"]
    elif mutation == "provider":
        context["ordered_providers"] = []
    elif mutation == "source":
        del context["ordered_providers"][0]["provider_source"]
    elif mutation == "implementation":
        context["ordered_calculation_capabilities"][0]["implementation_fingerprint"] = "f" * 64
    elif mutation == "nested_readiness":
        del encoded["readiness"]["ordered_calculation_readiness_capabilities"]
    elif mutation == "duplicate":
        context["ordered_calculation_capabilities"].append(context["ordered_calculation_capabilities"][0])
    else:
        context["ordered_calculation_capabilities"][0]["kind"] = "TARGET"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("ALTER TABLE chart_calculation_operation DISABLE TRIGGER ALL")
        connection.execute(
            "UPDATE chart_calculation_operation SET catalog_witness_json = %s", (only_canonical_json(encoded),)
        )
    with pytest.raises(ValueError, match="CHART_OPERATION_RELATION_CORRUPT"):
        adapter.load_verified(OnlyProductCommandId(COMMAND))


def test_t1_service_has_zero_market_runtime_run_or_execution_calls(postgres_dsn: str) -> None:
    import sys

    from onlyalpha.application.catalog_context import OnlyExactCatalogContextV1, OnlyExactCatalogReadinessProjectionV1

    adapter = store(postgres_dsn)
    encoded = witness().to_dict()
    pair = (
        OnlyExactCatalogContextV1.from_dict(encoded["context"]),
        OnlyExactCatalogReadinessProjectionV1.from_dict(encoded["readiness"]),
    )
    catalog_calls = 0

    def catalog():
        nonlocal catalog_calls
        catalog_calls += 1
        return pair

    forbidden_calls = []
    prefixes = (
        "onlyalpha.market_data",
        "onlyalpha.dataset",
        "onlyalpha.runtime",
        "onlyalpha.research.execution",
        "onlyalpha.research.command",
        "onlyalpha.research.calculation",
        "onlyalpha.research.result",
        "onlyalpha.research.artifact",
        "onlyalpha_plugin_binance",
    )

    def trace(frame, event, arg):
        module = frame.f_globals.get("__name__", "")
        if event == "call" and module.startswith(prefixes):
            forbidden_calls.append((module, frame.f_code.co_name))

    previous = sys.getprofile()
    try:
        sys.setprofile(trace)
        service = OnlyChartCalculationAdmissionService(adapter, catalog)
        first = service.admit(OnlyProductCommandId(COMMAND), request(), accepted_at=NOW)
        second = service.admit(OnlyProductCommandId(COMMAND), request({"period": 20}), accepted_at=NOW)
    finally:
        sys.setprofile(previous)
    assert second.operation == first.operation and second.reused
    assert catalog_calls == 1 and forbidden_calls == []
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM research_run").fetchone()[0] == 0


def test_reservation_excludes_concurrent_research_insert_until_t1_commit(
    postgres_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from threading import Event

    adapter = store(postgres_dsn)
    reserved = Event()
    release = Event()
    reserve = adapter._reserve_run_id

    def hold(connection, command_id):
        candidate = reserve(connection, command_id)
        reserved.set()
        assert release.wait(30), "test barrier was not released"
        return candidate

    monkeypatch.setattr(adapter, "_reserve_run_id", hold)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(admit, adapter)
        assert reserved.wait(30), "T1 did not reach reservation barrier"
        try:
            # Research insertion needs RowExclusive. NOWAIT deterministically proves
            # another writer cannot occupy the reservation before chart T1 commits.
            with pytest.raises(psycopg.errors.LockNotAvailable):
                with psycopg.connect(postgres_dsn) as connection:
                    connection.execute("LOCK TABLE research_run IN ROW EXCLUSIVE MODE NOWAIT")
        finally:
            release.set()
        assert pending.result(timeout=30).operation.reserved_run_id.value != COMMAND


@pytest.mark.parametrize("isolation", ["read committed", "repeatable read", "serializable"])
def test_established_snapshot_cannot_steal_later_committed_reservation(postgres_dsn: str, isolation: str) -> None:
    from psycopg import sql

    from onlyalpha.persistence.postgres.research_run_store import OnlyPostgresResearchRunStore, _insert_run_query
    from tests.research.postgres.test_postgres_authority import _queued

    adapter = store(postgres_dsn)
    with psycopg.connect(postgres_dsn) as writer:
        writer.execute(sql.SQL("SET TRANSACTION ISOLATION LEVEL {}").format(sql.SQL(isolation)))
        assert writer.execute("SELECT count(*) FROM research_run_id_reservation").fetchone() == (0,)
        operation = admit(adapter).operation
        run = _queued(operation.reserved_run_id.value)
        # Snapshot writers may reject with serialization failure; they must never steal the ID.
        with pytest.raises((psycopg.errors.UniqueViolation, psycopg.errors.SerializationFailure)):
            writer.execute(_insert_run_query(), OnlyPostgresResearchRunStore._values(run))
        writer.rollback()
    assert (
        OnlyPostgresChartCalculationAdmissionStore(postgres_dsn).load_verified(OnlyProductCommandId(COMMAND))
        == operation
    )


@pytest.mark.parametrize("isolation", ["read committed", "repeatable read", "serializable"])
@pytest.mark.parametrize("immediate", [False, True])
def test_unreserved_run_insert_preserves_writer_isolation_and_constraint_modes(
    postgres_dsn: str, isolation: str, immediate: bool
) -> None:
    from psycopg import sql

    from onlyalpha.persistence.postgres.research_run_store import OnlyPostgresResearchRunStore, _insert_run_query
    from tests.research.postgres.test_postgres_authority import _queued

    adapter = store(postgres_dsn)
    operation = admit(adapter).operation
    # Run UUID equal to an unrelated operation UUID is legal; only the reserved Run UUID is excluded.
    run = _queued(COMMAND)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("SET TRANSACTION ISOLATION LEVEL {}").format(sql.SQL(isolation)))
        if immediate:
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        connection.execute(_insert_run_query(), OnlyPostgresResearchRunStore._values(run))
    assert OnlyPostgresResearchRunStore(postgres_dsn).load(run.run_id) == run
    assert adapter.load_verified(OnlyProductCommandId(COMMAND)) == operation
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM research_run_id_reservation").fetchone() == (1,)


@pytest.mark.parametrize(
    "column,value",
    [
        ("owner_id", "00000000-0000-4000-8000-000000000719"),
        ("run_id", "00000000-0000-4000-8000-000000000718"),
        ("reserved_at", NOW + timedelta(seconds=1)),
    ],
)
def test_reservation_relation_mutation_fails_closed_without_repair(
    postgres_dsn: str, column: str, value: object
) -> None:
    from psycopg import sql

    adapter = store(postgres_dsn)
    operation = admit(adapter).operation
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("ALTER TABLE research_run_id_reservation DISABLE TRIGGER ALL")
        connection.execute(
            sql.SQL("UPDATE research_run_id_reservation SET {} = %s").format(sql.Identifier(column)), (value,)
        )
    for read in (
        lambda: adapter.load_verified(OnlyProductCommandId(COMMAND)),
        lambda: admit(adapter),
    ):
        with pytest.raises(ValueError, match="CHART_OPERATION_RELATION_CORRUPT"):
            read()
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM research_run_id_reservation").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM research_run").fetchone() == (0,)
    assert operation.reserved_run_id.value != COMMAND


def test_reservation_exclusion_survives_fresh_process_and_blocks_run_id_update(postgres_dsn: str) -> None:
    import os
    import subprocess
    import sys

    from tests.research.postgres.test_postgres_authority import _queued
    from tests.support.research_run_seeder import OnlyPostgresResearchRunSeeder

    operation = admit(store(postgres_dsn)).operation
    unrelated = _queued("00000000-0000-4000-8000-000000000717")
    OnlyPostgresResearchRunSeeder(postgres_dsn).seed_queued(unrelated)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os,sys,psycopg\n"
            "try:\n"
            " with psycopg.connect(os.environ['ONLYALPHA_POSTGRES_DSN']) as c:\n"
            "  c.execute('UPDATE research_run SET run_id=%s WHERE run_id=%s',sys.argv[1:])\n"
            "except psycopg.errors.UniqueViolation as e:\n"
            " assert 'RESEARCH_RUN_ID_RESERVED' in str(e)\n"
            "else:\n"
            " raise AssertionError('reserved ID was stolen')\n",
            operation.reserved_run_id.value,
            unrelated.run_id.value,
        ],
        env={**os.environ, "ONLYALPHA_POSTGRES_DSN": postgres_dsn},
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert (
        OnlyPostgresChartCalculationAdmissionStore(postgres_dsn).load_verified(OnlyProductCommandId(COMMAND))
        == operation
    )


def test_replay_verifies_existing_reservation_without_inserting_it(postgres_dsn: str) -> None:
    adapter = store(postgres_dsn)
    operation = admit(adapter).operation
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "CREATE FUNCTION forbid_reservation_insert() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN RAISE EXCEPTION 'reservation recreated'; END; $$"
        )
        connection.execute(
            "CREATE TRIGGER forbid_reservation_insert BEFORE INSERT ON research_run_id_reservation "
            "FOR EACH ROW EXECUTE FUNCTION forbid_reservation_insert()"
        )
    assert admit(OnlyPostgresChartCalculationAdmissionStore(postgres_dsn)).operation == operation


def test_command_id_equal_to_another_operation_reserved_run_is_a_distinct_domain(postgres_dsn: str) -> None:
    adapter = store(postgres_dsn)
    first = admit(adapter).operation
    second = adapter.admit_or_replay(
        OnlyProductCommandId(first.reserved_run_id.value), request(), witness(), accepted_at=NOW
    ).operation
    assert second.operation_id.value == first.reserved_run_id.value
    assert second.reserved_run_id not in (first.reserved_run_id, second.operation_id)
    assert adapter.load_verified(OnlyProductCommandId(COMMAND)) == first


def test_database_guard_covers_legacy_insert_only_role(postgres_dsn: str) -> None:
    from onlyalpha.persistence.postgres.research_run_store import OnlyPostgresResearchRunStore, _insert_run_query
    from tests.research.postgres.test_postgres_authority import _queued

    operation = admit(store(postgres_dsn)).operation
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("CREATE ROLE research_run_legacy_insert_writer NOLOGIN")
        connection.execute("GRANT USAGE ON SCHEMA public TO research_run_legacy_insert_writer")
        connection.execute("GRANT INSERT ON research_run TO research_run_legacy_insert_writer")
        # Existing source-history triggers require these baseline writer privileges.
        connection.execute(
            "GRANT SELECT, UPDATE ON research_source_history_frontier TO research_run_legacy_insert_writer"
        )
        connection.execute("GRANT INSERT ON research_source_history TO research_run_legacy_insert_writer")
    try:
        with pytest.raises(psycopg.errors.UniqueViolation, match="RESEARCH_RUN_ID_RESERVED"):
            with psycopg.connect(postgres_dsn) as connection:
                connection.execute("SET LOCAL ROLE research_run_legacy_insert_writer")
                connection.execute(
                    _insert_run_query(), OnlyPostgresResearchRunStore._values(_queued(operation.reserved_run_id.value))
                )
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute("SET LOCAL ROLE research_run_legacy_insert_writer")
            connection.execute(_insert_run_query(), OnlyPostgresResearchRunStore._values(_queued(COMMAND)))
    finally:
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute("REVOKE INSERT ON research_run FROM research_run_legacy_insert_writer")
            connection.execute("REVOKE USAGE ON SCHEMA public FROM research_run_legacy_insert_writer")
            connection.execute(
                "REVOKE SELECT, UPDATE ON research_source_history_frontier FROM research_run_legacy_insert_writer"
            )
            connection.execute("REVOKE INSERT ON research_source_history FROM research_run_legacy_insert_writer")
            connection.execute("DROP ROLE research_run_legacy_insert_writer")


@pytest.mark.parametrize("occupied", [False, True])
def test_reservation_migration_backfills_previous_chart_operations_or_fails_closed(
    postgres_dsn: str, occupied: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from onlyalpha.persistence.postgres.research_run_store import OnlyPostgresResearchRunStore, _insert_run_query
    from tests.research.postgres.test_postgres_authority import _queued

    # This reconstruction removes the historical 0044–0048 DDL below; do not
    # install later migrations and leave a non-prefix ledger behind.
    reference = tmp_path / "handoff-reference"
    reference.mkdir()
    copy_migrations_through(reference, "0048_chart_calculation_run_admission")
    historical = OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=reference)
    with monkeypatch.context() as context:
        context.setattr(
            "tests.research.postgres.test_chart_calculation_admission.OnlyPostgresMigrationAuthority",
            lambda dsn: historical,
        )
        operation = admit(store(postgres_dsn)).operation
    # Reconstruct exactly the preceding additive schema, retaining all audited 0043 facts.
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("DROP TRIGGER chart_run_admission_run_guard ON research_run")
        connection.execute("DROP TRIGGER chart_run_admission_reservation_guard ON research_run_id_reservation")
        connection.execute("DROP TABLE chart_calculation_run_admission")
        connection.execute("DROP FUNCTION chart_calculation_run_admission_guard()")
        connection.execute("ALTER TABLE research_run DROP CONSTRAINT research_run_chart_capability_check")
        connection.execute("ALTER TABLE research_run DROP CONSTRAINT research_run_origin_kind_check")
        connection.execute("ALTER TABLE research_run DROP CONSTRAINT research_run_origin_composition_check")
        connection.execute("ALTER TABLE research_run DROP CONSTRAINT research_run_specification_schema_version_check")
        connection.execute(
            "ALTER TABLE research_run ADD CONSTRAINT research_run_origin_kind_check CHECK (origin_kind IN ('GENERAL', 'PRIVATE_STRATEGY'))"
        )
        connection.execute(
            "ALTER TABLE research_run ADD CONSTRAINT research_run_origin_composition_check CHECK ((origin_kind = 'GENERAL' AND strategy_research_composition_fingerprint IS NULL) OR (origin_kind = 'PRIVATE_STRATEGY' AND strategy_research_composition_fingerprint IS NOT NULL))"
        )
        connection.execute(
            "ALTER TABLE research_run ADD CONSTRAINT research_run_specification_schema_version_check CHECK (specification_schema_version IN (1,2))"
        )
        connection.execute(
            "DELETE FROM onlyalpha_schema_migration WHERE migration_id = '0048_chart_calculation_run_admission'"
        )
        connection.execute("DROP TABLE chart_calculation_compilation")
        connection.execute(
            "DELETE FROM onlyalpha_schema_migration WHERE migration_id = '0047_chart_calculation_compilation_relation'"
        )
        connection.execute("DROP TABLE chart_calculation_preparation_fact")
        connection.execute(
            "DELETE FROM onlyalpha_schema_migration WHERE migration_id = '0046_chart_calculation_runtime_binding_relation'"
        )
        connection.execute(
            "DELETE FROM onlyalpha_schema_migration WHERE migration_id = '0045_chart_calculation_input_preparation'"
        )
        connection.execute("DROP TRIGGER research_run_reserved_id_insert ON research_run")
        connection.execute("DROP TRIGGER research_run_reserved_id_update ON research_run")
        connection.execute("DROP FUNCTION research_run_reserved_id_guard()")
        connection.execute("DROP TABLE research_run_id_reservation")
        connection.execute(
            "ALTER TABLE chart_calculation_operation DROP CONSTRAINT chart_calculation_operation_reservation_identity"
        )
        connection.execute(
            "DELETE FROM onlyalpha_schema_migration WHERE migration_id = '0044_research_run_id_reservation'"
        )
        if occupied:
            connection.execute(
                _insert_run_query(), OnlyPostgresResearchRunStore._values(_queued(operation.reserved_run_id.value))
            )
    if occupied:
        from onlyalpha.research.run.errors import OnlyPostgresMigrationIntegrityError

        with pytest.raises(OnlyPostgresMigrationIntegrityError):
            OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
        with psycopg.connect(postgres_dsn) as connection:
            assert connection.execute("SELECT to_regclass('public.research_run_id_reservation')").fetchone() == (None,)
            assert connection.execute("SELECT count(*) FROM chart_calculation_operation").fetchone() == (1,)
    else:
        assert OnlyPostgresMigrationAuthority(postgres_dsn).migrate() == (
            "0044_research_run_id_reservation",
            "0045_chart_calculation_input_preparation",
            "0046_chart_calculation_runtime_binding_relation",
            "0047_chart_calculation_compilation_relation",
            "0048_chart_calculation_run_admission",
            "0049_chart_native_publication_permissions",
        )
        assert (
            OnlyPostgresChartCalculationAdmissionStore(postgres_dsn).load_verified(OnlyProductCommandId(COMMAND))
            == operation
        )
        assert OnlyPostgresMigrationAuthority(postgres_dsn).migrate() == ()
