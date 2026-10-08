"""Owning PostgreSQL facts remain unchanged through real isolated numeric execution."""

from __future__ import annotations

from decimal import Decimal
from threading import Event

import pytest

from onlyalpha.application.chart_calculation import OnlyChartCalculationError
from onlyalpha.application.chart_calculation_execution import OnlyChartCalculationExecutionService
from onlyalpha.application.search_generation_execution import (
    OnlyHistoricalGenerationWorkerUnavailable,
    OnlySearchGenerationOperationV1,
)
from onlyalpha.research.run.model import OnlyResearchRunState
from tests.runtime_support.chart_execution_host import exact_host_environment as exact_host_environment

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.parametrize(
    "fault", ["none", "swapped_response", "release", "host_loss", "cancel_request", "contended_run"]
)
def test_postgres_owning_chain_through_real_isolated_host_is_readonly(
    exact_host_environment, postgres_dsn, tmp_path, monkeypatch, fault
):
    import psycopg
    from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry
    from onlyalpha_runtime_generation_manager.catalog_context import OnlyRuntimeGenerationExactCatalogDescriptorReader
    from psycopg import sql

    from onlyalpha.application.catalog_context import OnlyExactCatalogContextQueryService
    from onlyalpha.application.chart_calculation import OnlyChartCalculationCatalogWitnessV1
    from onlyalpha.application.chart_calculation_compilation import OnlyChartCalculationCompilationService
    from onlyalpha.application.chart_calculation_run_admission import OnlyChartCalculationRunAdmissionService
    from onlyalpha.persistence.postgres.chart_calculation_compilation_store import (
        OnlyPostgresChartCalculationCompilationStore,
    )
    from onlyalpha.persistence.postgres.chart_calculation_store import OnlyPostgresChartCalculationAdmissionStore
    from onlyalpha.persistence.postgres.research_chart_calculation_run_admission_store import (
        OnlyPostgresChartCalculationRunAdmissionStore,
    )
    from onlyalpha.persistence.postgres.research_run_store import OnlyPostgresResearchRunStore
    from onlyalpha.research.run.generation import OnlyResearchHostedRuntimeGenerationResolver
    from tests.application.test_chart_calculation_admission import NOW
    from tests.research.postgres import test_chart_calculation_preparation as preparation_fixtures

    builder, built, manager_type = exact_host_environment
    registry = OnlyRuntimeGenerationRegistry(tmp_path / "runtime")
    generation = built.manifest.runtime_generation_fingerprint
    registry.prepare(built.manifest, actor="fixture", occurred_at=NOW)
    registry.admit_ready(built.validation_evidence, actor="fixture", occurred_at=NOW)
    registry.activate_for_new_work(expected_current=None, target=generation, actor="fixture", occurred_at=NOW)
    reader = OnlyRuntimeGenerationExactCatalogDescriptorReader(registry, builder, tmp_path / "catalog")
    query = OnlyExactCatalogContextQueryService(reader, reader, reader, reader, readiness=reader)
    catalog = built.manifest.catalog_generation_fingerprint
    witness = OnlyChartCalculationCatalogWitnessV1.from_projections(
        query.get_exact_catalog_context(catalog), query.get_exact_catalog_readiness(catalog)
    )
    monkeypatch.setattr(preparation_fixtures, "witness", lambda: witness)
    system = preparation_fixtures.prepared_system(postgres_dsn, tmp_path, monkeypatch, period=3)
    system.service._runtime = registry
    ready = system.service.prepare(
        system.operation,
        worker_id=preparation_fixtures.WORKER,
        runtime_generation_fingerprint=generation,
        occurred_at=NOW,
    )
    assert ready.state == "INPUT_READY"
    host = manager_type(registry=registry, builder=builder, cache_root=tmp_path / "hosts")
    compilations = OnlyPostgresChartCalculationCompilationStore(postgres_dsn)
    runs = OnlyPostgresChartCalculationRunAdmissionStore(postgres_dsn, runtime_generations=registry)
    try:
        frozen = OnlyChartCalculationCompilationService(
            preparations=system.adapter,
            datasets=system.dataset,
            materializations=system.dataset,
            runtime_generations=registry,
            resolver=OnlyResearchHostedRuntimeGenerationResolver(
                execution=host, dataset_store_root=str(tmp_path / "dataset")
            ),
            compilations=compilations,
        ).compile(system.operation)
        run = OnlyChartCalculationRunAdmissionService(
            preparations=system.adapter,
            compilations=compilations,
            datasets=system.dataset,
            materializations=system.dataset,
            runtime_generations=registry,
            runs=runs,
        ).admit(system.operation, queued_at=NOW)
        service = OnlyChartCalculationExecutionService(
            operations=OnlyPostgresChartCalculationAdmissionStore(postgres_dsn),
            preparations=system.adapter,
            compilations=compilations,
            datasets=system.dataset,
            materializations=system.dataset,
            runtime_generations=registry,
            runs=runs,
            host=host,
            dataset_store_root=str(tmp_path / "dataset"),
        )

        def facts():
            with psycopg.connect(postgres_dsn) as connection:
                return {
                    table: connection.execute(
                        sql.SQL("SELECT row_to_json(t)::text FROM {} t ORDER BY row_to_json(t)::text").format(
                            sql.Identifier(table)
                        )
                    ).fetchall()
                    for table in (
                        "product_command_admission",
                        "product_command_receipt",
                        "chart_calculation_operation",
                        "chart_calculation_preparation_fact",
                        "chart_calculation_compilation",
                        "chart_calculation_run_admission",
                        "research_run_id_reservation",
                        "research_run",
                        "research_run_attempt",
                        "research_source_history",
                    )
                }

        before = facts()
        dataset = {path: path.read_bytes() for path in system.dataset._root.rglob("*") if path.is_file()}
        cancellation = Event()
        exchange = host._exchange_chart

        def injected(process, request, cancel, **kwargs):
            if "dispatch_guard" in kwargs:
                from contextlib import contextmanager

                original_guard = kwargs["dispatch_guard"]

                @contextmanager
                def checked_guard():
                    with original_guard:
                        # A concurrent cancellation update cannot commit until the
                        # complete request is sent, without any global command lock.
                        with psycopg.connect(postgres_dsn) as other:
                            with pytest.raises(psycopg.errors.LockNotAvailable):
                                other.execute(
                                    "SELECT run_id FROM research_run WHERE run_id=%s FOR UPDATE NOWAIT",
                                    (run.run_id.value,),
                                )
                        yield

                kwargs["dispatch_guard"] = checked_guard()
            response = exchange(process, request, cancel, **kwargs)
            # The same owning row is not held while waiting for/after output.
            with psycopg.connect(postgres_dsn) as other:
                other.execute("SELECT run_id FROM research_run WHERE run_id=%s FOR UPDATE NOWAIT", (run.run_id.value,))
            if fault == "swapped_response":
                from onlyalpha.application.search_generation_execution import OnlySearchGenerationExecutionResponseV1

                response["result_payload"]["operation_id"] = "00000000-0000-4000-8000-000000000998"
                return OnlySearchGenerationExecutionResponseV1(
                    response["runtime_generation_fingerprint"],
                    OnlySearchGenerationOperationV1(response["operation_kind"]),
                    response["result_payload"],
                ).to_dict()
            if fault == "release":
                registry.release_work(run.run_id.value, actor="fixture", occurred_at=NOW)
            elif fault == "host_loss":
                host._terminate(process)
            elif fault == "cancel_request":
                cancellation.set()
            return response

        monkeypatch.setattr(host, "_exchange_chart", injected)
        if fault == "none":
            result = service.execute(system.operation.operation_id, cancellation=cancellation)
            assert result.values.column("value").to_pylist() == [Decimal("101")] * 6
            assert result.readiness.column("readiness").to_pylist() == [
                "PARTIAL",
                "PARTIAL",
                "READY",
                "READY",
                "READY",
                "READY",
            ]
            assert result.readiness.column("reason").to_pylist() == [
                "WARMUP_INCOMPLETE",
                "WARMUP_INCOMPLETE",
                "NONE",
                "NONE",
                "NONE",
                "NONE",
            ]
            assert result.request.compilation == frozen
        elif fault == "contended_run":
            from onlyalpha.application.product_command_authority import OnlyProductCommandAuthorityUnavailableError

            with psycopg.connect(postgres_dsn) as cancellation_writer:
                cancellation_writer.execute(
                    "SELECT run_id FROM research_run WHERE run_id=%s FOR UPDATE", (run.run_id.value,)
                )
                with pytest.raises(OnlyProductCommandAuthorityUnavailableError):
                    service.execute(system.operation.operation_id, cancellation=cancellation)
        else:
            with pytest.raises((OnlyChartCalculationError, OnlyHistoricalGenerationWorkerUnavailable)):
                service.execute(system.operation.operation_id, cancellation=cancellation)
        assert facts() == before
        assert before["research_run_attempt"] == []
        assert OnlyPostgresResearchRunStore(postgres_dsn).load(run.run_id) == run
        assert run.state is OnlyResearchRunState.QUEUED and run.revision == 0
        assert run.research_result_fingerprint is None and run.artifact_content_fingerprint is None
        assert run.calculation_execution_evidence_fingerprints == ()
        assert {path: path.read_bytes() for path in system.dataset._root.rglob("*") if path.is_file()} == dataset
    finally:
        host.close()
