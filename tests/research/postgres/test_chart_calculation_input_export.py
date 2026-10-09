"""Real T1/T2/D2 owning reads issue input proof without Run or Source mutation."""

from types import SimpleNamespace

import pytest

from onlyalpha.application.chart_calculation_compilation import (
    OnlyChartCalculationCompilationService,
    OnlyChartCalculationInputVerifier,
)
from onlyalpha.application.chart_calculation_input_export import OnlyChartCalculationInputExportService
from onlyalpha.persistence.postgres.chart_calculation_compilation_store import (
    OnlyPostgresChartCalculationCompilationStore,
)
from onlyalpha.persistence.postgres.chart_calculation_preparation_store import (
    OnlyPostgresChartCalculationPreparationStore,
)
from onlyalpha.persistence.postgres.chart_calculation_store import OnlyPostgresChartCalculationAdmissionStore
from onlyalpha.research.dataset.publication_input import _only_require_verified_sealed_chart_publication_input
from tests.application.test_chart_calculation_admission import NOW
from tests.research.postgres.test_chart_calculation_compilation import authority_facts
from tests.research.postgres.test_chart_calculation_preparation import (
    WORKER,
    chart_runtime_registry,
    prepared_system,
    publish_revision,
)
from tests.support.chart_calculation_compilation import resolve_publication

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.fixture
def owning_input_export(postgres_dsn, tmp_path, monkeypatch):
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch, period=3)
    registry, generation, _ = chart_runtime_registry(system, tmp_path / "runtime")
    system.service._runtime = registry
    ready = system.service.prepare(
        system.operation,
        worker_id=WORKER,
        runtime_generation_fingerprint=generation,
        occurred_at=NOW,
    )
    compilations = OnlyPostgresChartCalculationCompilationStore(postgres_dsn)
    # Only the registered compiler is a deterministic fake here. T1, T2, D2,
    # Runtime Work, Dataset/Materialization and original physical reads are real.
    compiled = OnlyChartCalculationCompilationService(
        preparations=system.adapter,
        datasets=system.dataset,
        materializations=system.dataset,
        runtime_generations=registry,
        resolver=SimpleNamespace(resolve_calculation_publication=resolve_publication),
        compilations=compilations,
    ).compile(system.operation)
    exporter = OnlyChartCalculationInputExportService(
        operations=OnlyPostgresChartCalculationAdmissionStore(postgres_dsn),
        preparations=OnlyPostgresChartCalculationPreparationStore(postgres_dsn),
        compilations=compilations,
        inputs=OnlyChartCalculationInputVerifier(
            datasets=system.dataset, materializations=system.dataset, runtime_generations=registry
        ),
        integrations=system.market.state,
        catalog=system.market.catalog,
        facts=system.market.service._facts,
        materializations=system.dataset,
    )
    return system, ready, compiled, exporter, registry


def test_postgres_owning_export_and_revalidation_preserve_authorities(owning_input_export, postgres_dsn, tmp_path):
    system, _, compiled, exporter, registry = owning_input_export
    before = authority_facts(postgres_dsn)
    files = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    issued = exporter.export(system.operation.operation_id)
    assert (
        _only_require_verified_sealed_chart_publication_input(
            issued,
            compiled.result_plan_fingerprint,
            compiled.graph_fingerprint,
            compiled.runtime_generation_fingerprint,
        )
        == issued.retained
    )
    assert authority_facts(postgres_dsn) == before
    assert files == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    registry.release_work(system.operation.reserved_run_id.value, actor="owner", occurred_at=NOW)
    assert exporter.export(system.operation.operation_id).retained == issued.retained


def test_later_source_revision_does_not_reselect_historical_input(owning_input_export):
    system, ready, _, exporter, _ = owning_input_export
    original = exporter.export(system.operation.operation_id).retained
    newer = publish_revision(system, ready.input_pin.revision_id)
    assert newer.revision_id != ready.input_pin.revision_id
    assert exporter.export(system.operation.operation_id).retained == original


def test_original_source_unavailable_cannot_become_absence_or_reissued_input(owning_input_export, postgres_dsn):
    system, _, compiled, exporter, _ = owning_input_export
    issued = exporter.export(system.operation.operation_id)
    before = authority_facts(postgres_dsn)
    system.market.faults.fact_read = OSError("original physical source unavailable")
    with pytest.raises(OSError, match="original physical source unavailable"):
        _only_require_verified_sealed_chart_publication_input(
            issued,
            compiled.result_plan_fingerprint,
            compiled.graph_fingerprint,
            compiled.runtime_generation_fingerprint,
        )
    assert authority_facts(postgres_dsn) == before
