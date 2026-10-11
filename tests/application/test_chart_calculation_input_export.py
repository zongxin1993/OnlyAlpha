"""Reader issuance and original physical input closure; no operational writes."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from onlyalpha.application.chart_calculation import OnlyChartCalculationError
from onlyalpha.application.chart_calculation_compilation import (
    OnlyChartCalculationCompilationService,
    OnlyChartCalculationInputVerifier,
)
from onlyalpha.application.chart_calculation_input_export import OnlyChartCalculationInputExportService
from onlyalpha.research.dataset.publication_input import _only_require_verified_sealed_chart_publication_input
from onlyalpha.research.dataset.sealed_input_evidence import OnlyRetainedSealedChartInputEvidenceV1
from tests.support.chart_calculation_compilation import prepared_input

pytestmark = pytest.mark.contract


def export_case(tmp_path):
    chart = prepared_input(tmp_path)
    compilation = OnlyChartCalculationCompilationService(
        preparations=chart.preparations,
        datasets=chart.dataset,
        materializations=chart.dataset,
        runtime_generations=chart.runtime,
        resolver=chart.resolver,
        compilations=chart.compilations,
    ).compile(chart.operation)
    chart.compilations.load_verified.return_value = compilation
    operations = SimpleNamespace(load_verified=lambda _: chart.operation)
    exporter = OnlyChartCalculationInputExportService(
        operations=operations,
        preparations=chart.preparations,
        compilations=chart.compilations,
        inputs=OnlyChartCalculationInputVerifier(
            datasets=chart.dataset, materializations=chart.dataset, runtime_generations=chart.runtime
        ),
        integrations=chart.market.state,
        catalog=chart.market.catalog,
        facts=chart.market.service._facts,
        materializations=chart.dataset,
    )
    return chart, compilation, exporter


def test_export_revalidates_exact_source_and_never_mutates_owning_facts(tmp_path):
    chart, compilation, exporter = export_case(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    writes = chart.market.service._facts.writes
    provider_calls = vars(chart.market.provider).copy()
    issued = exporter.export(chart.operation.operation_id)
    assert OnlyRetainedSealedChartInputEvidenceV1.from_dict(issued.retained.to_dict()) == issued.retained
    assert (
        _only_require_verified_sealed_chart_publication_input(
            issued,
            compilation.result_plan_fingerprint,
            compilation.graph_fingerprint,
            compilation.runtime_generation_fingerprint,
        )
        == issued.retained
    )
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert chart.market.service._facts.writes == writes
    assert vars(chart.market.provider) == provider_calls


def test_export_uses_historical_integration_revision_without_admission_secrets_or_provider(tmp_path, monkeypatch):
    from onlyalpha.application.integration_configuration import OnlyIntegrationLifecycleState

    chart, _, exporter = export_case(tmp_path)
    chart.market.state.integrations = tuple(
        replace(item, lifecycle_state=OnlyIntegrationLifecycleState.DISABLED)
        for item in chart.market.state.integrations
    )

    def forbidden(*args, **kwargs):
        pytest.fail("historical export attempted admission, credentials, latest selection or acquisition")

    monkeypatch.setattr(chart.market.service, "plan_selection", forbidden)
    monkeypatch.setattr(chart.market.service, "acquire_bars", forbidden)
    monkeypatch.setattr(chart.market.catalog, "latest_sealed_revision", forbidden)
    monkeypatch.setattr(chart.market.service._resolver._credentials, "read_secret", forbidden)
    assert exporter.export(chart.operation.operation_id)


@pytest.mark.parametrize("forgery", ("copy", "dto", "mutate", "wrong_plan"))
def test_portable_parse_cannot_issue_publication_input(tmp_path, forgery):
    chart, compilation, exporter = export_case(tmp_path)
    issued = exporter.export(chart.operation.operation_id)
    candidate = issued
    plan = compilation.result_plan_fingerprint
    if forgery == "copy":
        candidate = replace(issued)
    elif forgery == "dto":
        candidate = OnlyRetainedSealedChartInputEvidenceV1.from_dict(issued.retained.to_dict())
    elif forgery == "mutate":
        object.__setattr__(issued, "graph_fingerprint", "f" * 64)
    else:
        plan = "f" * 64
    with pytest.raises(ValueError, match="issued sealed input"):
        _only_require_verified_sealed_chart_publication_input(
            candidate,
            plan,
            compilation.graph_fingerprint,
            compilation.runtime_generation_fingerprint,
        )


def test_export_fails_if_original_physical_source_becomes_unavailable(tmp_path):
    chart, compilation, exporter = export_case(tmp_path)
    issued = exporter.export(chart.operation.operation_id)
    chart.market.faults.fact_read = OSError("original source unavailable")
    with pytest.raises(OSError, match="original source unavailable"):
        _only_require_verified_sealed_chart_publication_input(
            issued,
            compilation.result_plan_fingerprint,
            compilation.graph_fingerprint,
            compilation.runtime_generation_fingerprint,
        )


def test_readonly_verification_never_issues_publication_input(tmp_path, monkeypatch):
    import onlyalpha.application.chart_calculation_input_export as module

    chart, compilation, exporter = export_case(tmp_path)
    expected = exporter.export(chart.operation.operation_id).retained
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    writes = chart.market.service._facts.writes
    provider_calls = vars(chart.market.provider).copy()

    def forbidden(*args, **kwargs):
        pytest.fail("read-only Source verification issued a publication capability")

    monkeypatch.setattr(module, "_only_issue_verified_sealed_chart_publication_input", forbidden)
    monkeypatch.setattr(exporter, "export", forbidden)
    verified = exporter.verify_frozen(chart.operation.operation_id, compilation)
    assert verified == expected
    with pytest.raises(ValueError, match="reader-issued sealed input required"):
        _only_require_verified_sealed_chart_publication_input(
            verified,
            compilation.result_plan_fingerprint,
            compilation.graph_fingerprint,
            compilation.runtime_generation_fingerprint,
        )
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert chart.market.service._facts.writes == writes
    assert vars(chart.market.provider) == provider_calls


@pytest.mark.parametrize(
    "dimension",
    (
        "operation_id",
        "intent_fingerprint",
        "catalog_witness_fingerprint",
        "input_preparation_revision",
        "input_selection_fingerprint",
        "dataset_materialization_id",
        "runtime_binding_reference",
    ),
)
def test_readonly_verification_compares_whole_stored_compilation(tmp_path, dimension):
    from onlyalpha.application.product_command_receipt import OnlyProductCommandId

    chart, compilation, exporter = export_case(tmp_path)
    value = (
        OnlyProductCommandId("00000000-0000-4000-8000-000000000723")
        if dimension == "operation_id"
        else compilation.input_preparation_revision + 1
        if dimension == "input_preparation_revision"
        else "dataset-materialization:" + "f" * 64
        if dimension == "dataset_materialization_id"
        else replace(compilation.runtime_binding_reference, binding_event_fingerprint="f" * 64)
        if dimension == "runtime_binding_reference"
        else "f" * 64
    )
    different = replace(compilation, **{dimension: value})
    assert (
        different.result_plan_fingerprint,
        different.graph_fingerprint,
        different.runtime_generation_fingerprint,
    ) == (
        compilation.result_plan_fingerprint,
        compilation.graph_fingerprint,
        compilation.runtime_generation_fingerprint,
    )
    with pytest.raises(OnlyChartCalculationError, match="CHART_COMPILATION_RELATION_CORRUPT"):
        exporter.verify_frozen(chart.operation.operation_id, different)


@pytest.mark.parametrize("missing", ("operation", "preparation", "compilation", "physical_source"))
def test_readonly_verification_missing_owner_is_not_absence(tmp_path, missing):
    chart, compilation, exporter = export_case(tmp_path)
    if missing == "operation":
        exporter._operations.load_verified = lambda _: None
    elif missing == "preparation":
        chart.preparations.load_verified.return_value = None
    elif missing == "compilation":
        chart.compilations.load_verified.return_value = None
    else:
        chart.market.faults.fact_read = OSError("original source unavailable")
    with pytest.raises((OnlyChartCalculationError, OSError)):
        exporter.verify_frozen(chart.operation.operation_id, compilation)
