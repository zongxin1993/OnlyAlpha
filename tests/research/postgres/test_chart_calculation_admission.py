from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
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

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]


def store(dsn: str) -> OnlyPostgresChartCalculationAdmissionStore:
    OnlyPostgresMigrationAuthority(dsn).migrate()
    return OnlyPostgresChartCalculationAdmissionStore(dsn)


def admit(adapter: OnlyPostgresChartCalculationAdmissionStore, params: object = None):
    return adapter.admit_or_replay(OnlyProductCommandId(COMMAND), request(params), witness(), accepted_at=NOW)


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
    "table", ["product_command_admission", "product_command_receipt", "chart_calculation_operation"]
)
def test_partial_t1_fails_closed_without_repair(postgres_dsn: str, table: str) -> None:
    from psycopg import sql

    adapter = store(postgres_dsn)
    admit(adapter)
    with psycopg.connect(postgres_dsn) as connection:
        # Deliberate physical corruption, bypassing immutable-history protection only in this isolated fixture.
        connection.execute(sql.SQL("ALTER TABLE {} DISABLE TRIGGER USER").format(sql.Identifier(table)))
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
        for table in ("product_command_admission", "product_command_receipt", "chart_calculation_operation"):
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
        connection.execute("ALTER TABLE chart_calculation_operation DISABLE TRIGGER USER")
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
        "TRUNCATE chart_calculation_operation",
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
        connection.execute("ALTER TABLE chart_calculation_operation DISABLE TRIGGER USER")
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
