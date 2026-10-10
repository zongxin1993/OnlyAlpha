"""Actual installed-generation portable publication, not Chart Work dispatch."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from importlib import metadata
from pathlib import Path

import psycopg
import pytest
from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry

from onlyalpha.distribution import (
    OnlyArtifactSourceProvenanceAuthority,
    OnlyDistributionArtifactRole,
)
from onlyalpha.research.artifact import OnlyParquetResearchCalculationArtifactStoreV2
from tests.runtime_support.chart_execution_host import exact_host_environment as exact_host_environment
from tests.runtime_support.chart_execution_host import materialize_exact_host_environment
from tests.runtime_support.market_fact_reference import save_reference_facts
from tests.runtime_support.native_calculation_publication import PUBLISH as _PUBLISH
from tests.runtime_support.native_calculation_publication import provision_native_publication_roots
from tests.support.runtime_distribution_wheels import installed_distribution_wheel, plain_artifact

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def _provision_schema_reference(python):
    # Owning PostgreSQL readers require the unchanged canonical migration
    # reference alongside this isolated test installation. Do not bypass the
    # verifier, mutate SQL or change the installed Core/provider distributions.
    target = Path(
        subprocess.check_output(
            [
                str(python),
                "-I",
                "-c",
                "from onlyalpha.persistence.postgres.migration import DEFAULT_MIGRATION_ROOT; print(DEFAULT_MIGRATION_ROOT)",
            ],
            text=True,
        ).strip()
    )
    source = Path(__file__).resolve().parents[3] / "database" / "postgres" / "migrations"
    if target.exists():
        assert {p.name: p.read_bytes() for p in target.glob("*.sql")} == {
            p.name: p.read_bytes() for p in source.glob("*.sql")
        }
    else:
        shutil.copytree(source, target)


@pytest.fixture
def native_publication_case(exact_host_environment, postgres_dsn, tmp_path, monkeypatch, request):
    from dataclasses import replace

    from onlyalpha_runtime_generation_manager.catalog_context import OnlyRuntimeGenerationExactCatalogDescriptorReader

    from onlyalpha.application.catalog_context import OnlyExactCatalogContextQueryService
    from onlyalpha.application.chart_calculation import OnlyChartCalculationCatalogWitnessV1
    from onlyalpha.application.chart_calculation_compilation import OnlyChartCalculationCompilationService
    from onlyalpha.application.integration_configuration import OnlyIntegrationId
    from onlyalpha.domain.value import OnlyQuantity
    from onlyalpha.persistence.postgres.chart_calculation_compilation_store import (
        OnlyPostgresChartCalculationCompilationStore,
    )
    from onlyalpha.persistence.postgres.integration_store import OnlyPostgresIntegrationStore
    from onlyalpha.persistence.postgres.market_data_catalog import OnlyPostgresMarketDataCatalog
    from onlyalpha.plugin.integration import OnlyIntegrationTypeId
    from onlyalpha.research.run.generation import OnlyResearchHostedRuntimeGenerationResolver
    from tests.application.test_market_data_product import _FakeSource
    from tests.research.postgres.test_chart_calculation_preparation import WORKER, prepared_system

    period = getattr(request, "param", 3)
    original_update = _FakeSource._update

    def recorded_update(source, start_ns, bar_type):
        update = original_update(source, start_ns, bar_type)
        # Deterministic provider facts pass through normal original ingress/WAL,
        # revision/sealing/materialization. Never rewrite a Snapshot or execution.
        volume = (0, 0, 2, 5, 0, 1)[(start_ns // (15 * 60_000_000_000)) % 6]
        return replace(
            update,
            payload=replace(update.payload, bar=replace(update.payload.bar, volume=OnlyQuantity(Decimal(volume), 5))),
        )

    monkeypatch.setattr(_FakeSource, "_update", recorded_update)

    builder, built, host_type, template = exact_host_environment
    registry = OnlyRuntimeGenerationRegistry(tmp_path / "registry")
    now = datetime(2026, 10, 9, tzinfo=UTC)
    generation = built.manifest.runtime_generation_fingerprint
    registry.prepare(built.manifest, actor="fixture", occurred_at=now)
    registry.admit_ready(built.validation_evidence, actor="fixture", occurred_at=now)
    registry.activate_for_new_work(expected_current=None, target=generation, actor="fixture", occurred_at=now)
    reader = OnlyRuntimeGenerationExactCatalogDescriptorReader(registry, builder, tmp_path / "chart-catalog")
    query = OnlyExactCatalogContextQueryService(reader, reader, reader, reader, readiness=reader)
    catalog_id = built.manifest.catalog_generation_fingerprint
    witness = OnlyChartCalculationCatalogWitnessV1.from_projections(
        query.get_exact_catalog_context(catalog_id), query.get_exact_catalog_readiness(catalog_id)
    )
    system = prepared_system(
        postgres_dsn,
        tmp_path / "chart-input",
        monkeypatch,
        period=period,
        price_field="VOLUME",
        catalog_witness=witness,
    )
    system.service._runtime = registry
    ready = system.service.prepare(
        system.operation, worker_id=WORKER, runtime_generation_fingerprint=generation, occurred_at=now
    )
    assert ready.state == "INPUT_READY"
    materialize_exact_host_environment(template, generation, tmp_path / "hosts")
    host = host_type(registry=registry, builder=builder, cache_root=tmp_path / "hosts")
    compilations = OnlyPostgresChartCalculationCompilationStore(postgres_dsn)
    try:
        compiled = OnlyChartCalculationCompilationService(
            preparations=system.adapter,
            datasets=system.dataset,
            materializations=system.dataset,
            runtime_generations=registry,
            resolver=OnlyResearchHostedRuntimeGenerationResolver(
                execution=host, dataset_store_root=str(tmp_path / "chart-input" / "dataset")
            ),
            compilations=compilations,
        ).compile(system.operation)
    finally:
        host.close()
    from onlyalpha.persistence.postgres.research_chart_calculation_run_admission_store import (
        OnlyPostgresChartCalculationRunAdmissionStore,
    )

    system.run = OnlyPostgresChartCalculationRunAdmissionStore(
        postgres_dsn, runtime_generations=registry
    ).commit_or_replay(system.operation, compiled, queued_at=system.operation.accepted_at)
    assert system.run.state.value == "QUEUED"
    # Persist original Source metadata through its formal PostgreSQL owner and
    # original physical rows in the controlled cross-process reference store.
    pin = ready.input_pin
    revision, seal = system.market.catalog.load_sealed_revision(pin.revision_id)
    ids = tuple(item[0] for item in revision.segment_refs)
    segments = system.market.catalog.load_durable_segments(ids)
    proofs = system.market.catalog.load_physical_proofs(ids)
    catalog = OnlyPostgresMarketDataCatalog(postgres_dsn)
    catalog.commit_durable_segments(segments, proofs)
    catalog.commit_revision(
        segments, system.market.catalog.load_coverage_manifest(revision.manifest_id), revision, seal
    )
    integrations = OnlyPostgresIntegrationStore(postgres_dsn)
    integration_revision = system.market.state.load_revision(system.market.revision_fingerprint)
    integrations.create_integration(
        OnlyIntegrationId(system.market.state.integration.integration_id.value),
        OnlyIntegrationTypeId(integration_revision.type_id),
        "native source",
    )
    integrations.insert_revision(integration_revision, ())
    save_reference_facts(tmp_path / "original-facts.json", system.market.service._facts)
    frozen = tmp_path / "frozen.json"
    frozen.write_text(json.dumps(compiled.resolution.to_dict()))
    (tmp_path / "artifact-store-root.txt").write_text(str(builder.artifact_store.root))
    (tmp_path / "input-owner.json").write_text(
        json.dumps(
            {
                "dsn": postgres_dsn,
                "operation_id": system.operation.operation_id.value,
                "reader": str(Path(__file__).resolve().parents[2] / "runtime_support" / "chart_publication_input.py"),
            }
        )
    )
    (tmp_path / "semantic").mkdir()
    _provision_schema_reference(builder.artifact_store.root.parent / "built" / "bin" / "python")
    return system, compiled, registry, builder.artifact_store.root.parent / "built" / "bin" / "python", frozen


_ARTIFACT = r"""
import json, sys, runpy
from pathlib import Path
from datetime import UTC, datetime
from onlyalpha_runtime_generation_manager.registry import OnlyRuntimeGenerationRegistry
from onlyalpha_runtime_generation_manager.artifact_store import OnlyLocalImmutableArtifactStore
from onlyalpha_runtime_generation_manager.native_publication import only_publish_native_calculation_artifact
from onlyalpha.research.run.calculation_resolution import OnlyResearchCalculationRuntimeResolutionV1
from onlyalpha.research.calculation.execution import OnlyResearchCalculationExecutor
def forbidden(*args, **kwargs):
    raise AssertionError('Artifact projection reexecuted numeric backend')
OnlyResearchCalculationExecutor._execute_verified_v2 = forbidden
root = Path(sys.argv[1])
frozen = OnlyResearchCalculationRuntimeResolutionV1.from_dict(json.loads((root / 'frozen.json').read_text()))
owner = json.loads((root / 'input-owner.json').read_text())
registry = OnlyRuntimeGenerationRegistry(root / 'registry')
verified_input = runpy.run_path(owner['reader'])['export_input'](
    owner['dsn'], owner['operation_id'], root / 'chart-input' / 'dataset', root / 'original-facts.json', registry)
artifact = only_publish_native_calculation_artifact(
    generations=registry, frozen=frozen, verified_input=verified_input,
    distribution_artifact_store=OnlyLocalImmutableArtifactStore(Path((root / 'artifact-store-root.txt').read_text())),
    dataset_store_root=root / 'chart-input' / 'dataset', calculation_result_root=root / 'calculation-results',
    execution_evidence_root=root / 'semantic', research_result_root=root / 'research-results',
    research_artifact_root=root / 'artifacts', audit_time=lambda: datetime(2026, 10, 9, tzinfo=UTC),
)
print(json.dumps(artifact.manifest.to_dict()))
"""


def test_two_installed_generations_publish_same_result_and_distinct_portable_artifacts(
    native_publication_case,
    exact_host_environment,
    tmp_path,
):
    from onlyalpha_plugin_indicators.provider import quant_asset_provider

    from onlyalpha.quant_assets import OnlyQuantAssetCatalogGeneration

    chart, compilation, registry, first_python, _ = native_publication_case
    builder, built, _, _ = exact_host_environment
    original_registry = {path: path.read_bytes() for path in registry.root.rglob("*") if path.is_file()}
    original_dataset = {path: path.read_bytes() for path in chart.dataset._root.rglob("*") if path.is_file()}
    owner = json.loads((tmp_path / "input-owner.json").read_text())
    from onlyalpha.persistence.postgres.research_run_store import OnlyPostgresResearchRunStore

    runs = OnlyPostgresResearchRunStore(owner["dsn"])
    provision_native_publication_roots(tmp_path)
    first_result = json.loads(
        subprocess.check_output([str(first_python), "-I", "-c", _PUBLISH, str(tmp_path), "execute"], text=True)
    )
    first_artifact = json.loads(
        subprocess.check_output([str(first_python), "-I", "-c", _ARTIFACT, str(tmp_path)], text=True)
    )
    assert (
        json.loads(subprocess.check_output([str(first_python), "-I", "-c", _ARTIFACT, str(tmp_path)], text=True))
        == first_artifact
    )

    # Different SUPPORT bytes create an independent installed generation, with no
    # change to scientific inputs or the selected Calculation implementation.
    wheel = installed_distribution_wheel("packaging", tmp_path / "independent-support-wheel")
    raw = wheel.read_bytes()
    support = plain_artifact(
        wheel,
        role=OnlyDistributionArtifactRole.SUPPORT,
        authority=OnlyArtifactSourceProvenanceAuthority.EXTERNAL_RELEASE,
        repository="PyPA-packaging",
        revision="release-" + metadata.version("packaging"),
    )
    builder.artifact_store.put_once(support, raw)
    artifacts = tuple(builder.artifact_store.fetch_exact(identity)[0] for identity in built.manifest.artifact_sha256s)
    second = builder.build_validated(
        artifacts=(*artifacts, support),
        expected_catalog=OnlyQuantAssetCatalogGeneration((quant_asset_provider(),)),
        environment_root=tmp_path / "independent-generation",
    )
    assert second.manifest.runtime_generation_fingerprint != built.manifest.runtime_generation_fingerprint
    other = tmp_path / "independent-publication"
    other.mkdir()
    other_registry = OnlyRuntimeGenerationRegistry(other / "registry")
    now = datetime(2026, 10, 9, tzinfo=UTC)
    other_registry.prepare(second.manifest, actor="fixture", occurred_at=now)
    other_registry.admit_ready(second.validation_evidence, actor="fixture", occurred_at=now)
    other_registry.activate_for_new_work(
        expected_current=None, target=second.manifest.runtime_generation_fingerprint, actor="fixture", occurred_at=now
    )
    shutil.copytree(tmp_path / "chart-input", other / "chart-input")
    (other / "semantic").mkdir()
    provision_native_publication_roots(other)
    (other / "artifact-store-root.txt").write_text(str(builder.artifact_store.root))
    second_python = builder._environment_python(tmp_path / "independent-generation")
    _provision_schema_reference(second_python)
    # Admit a separate T1/T2/D2 occurrence. Never rebind the original Work or
    # substitute an independently compiled DTO for its owning Compilation.
    from onlyalpha.application.chart_calculation_compilation import OnlyChartCalculationCompilationService
    from onlyalpha.application.product_command_receipt import OnlyProductCommandId
    from onlyalpha.persistence.postgres.chart_calculation_compilation_store import (
        OnlyPostgresChartCalculationCompilationStore,
    )
    from onlyalpha.persistence.postgres.chart_calculation_store import OnlyPostgresChartCalculationAdmissionStore
    from onlyalpha.research.run.generation import OnlyResearchHostedRuntimeGenerationResolver
    from tests.research.postgres.test_chart_calculation_preparation import WORKER

    owner = json.loads((tmp_path / "input-owner.json").read_text())
    second_operation = (
        OnlyPostgresChartCalculationAdmissionStore(owner["dsn"])
        .admit_or_replay(
            OnlyProductCommandId("00000000-0000-4000-8000-000000000723"),
            chart.operation.intent,
            chart.operation.catalog_witness,
            accepted_at=chart.operation.accepted_at,
        )
        .operation
    )
    chart.service._runtime = other_registry
    ready = chart.service.prepare(
        second_operation,
        worker_id=WORKER,
        runtime_generation_fingerprint=second.manifest.runtime_generation_fingerprint,
        occurred_at=now,
    )
    host = exact_host_environment[2](registry=other_registry, builder=builder, cache_root=other / "hosts")
    try:
        frozen_compilation = OnlyChartCalculationCompilationService(
            preparations=chart.adapter,
            datasets=chart.dataset,
            materializations=chart.dataset,
            runtime_generations=other_registry,
            resolver=OnlyResearchHostedRuntimeGenerationResolver(
                execution=host, dataset_store_root=str(chart.dataset._root)
            ),
            compilations=OnlyPostgresChartCalculationCompilationStore(owner["dsn"]),
        ).compile(second_operation)
    finally:
        host.close()
    assert ready.dataset_snapshot_fingerprint == compilation.dataset_snapshot_fingerprint
    (other / "frozen.json").write_text(json.dumps(frozen_compilation.resolution.to_dict()))
    owner["operation_id"] = second_operation.operation_id.value
    (other / "input-owner.json").write_text(json.dumps(owner))
    shutil.copyfile(tmp_path / "original-facts.json", other / "original-facts.json")
    second_result = json.loads(
        subprocess.check_output([str(second_python), "-I", "-c", _PUBLISH, str(other), "execute"], text=True)
    )
    second_artifact = json.loads(
        subprocess.check_output([str(second_python), "-I", "-c", _ARTIFACT, str(other)], text=True)
    )
    assert first_result["result"] == second_result["result"]
    assert first_artifact["artifact_content_fingerprint"] != second_artifact["artifact_content_fingerprint"]
    assert first_artifact["selected_evidence"] != second_artifact["selected_evidence"]
    assert original_registry == {path: path.read_bytes() for path in registry.root.rglob("*") if path.is_file()}
    assert original_dataset == {path: path.read_bytes() for path in chart.dataset._root.rglob("*") if path.is_file()}
    assert runs.load(chart.run.run_id) == chart.run
    with psycopg.connect(owner["dsn"]) as connection:
        assert connection.execute("SELECT count(*) FROM research_run_attempt").fetchone() == (0,)
    assert (
        json.loads((tmp_path / "frozen.json").read_text())["runtime_generation_fingerprint"]
        == compilation.resolution.runtime_generation_fingerprint
    )

    portable = tmp_path / "portable"
    shutil.copytree(tmp_path / "artifacts", portable)
    shutil.copytree(other / "artifacts", portable, dirs_exist_ok=True)
    for artifact in (first_artifact, second_artifact):
        loaded = OnlyParquetResearchCalculationArtifactStoreV2(portable).load_verified(
            artifact["artifact_content_fingerprint"],
            research_result_fingerprint=artifact["result"]["research_result_fingerprint"],
        )
        calculation = next(iter(loaded.calculations.values()))
        values = calculation.outputs[0].table["value"].to_pylist()
        readiness = calculation.readiness[0].table.to_pylist()
        assert len(set(loaded.dataset_table["volume"].to_pylist())) > 1
        assert values == [
            Decimal(value) for value in ("0", "0", "0.666666666667", "2.333333333333", "2.333333333333", "2")
        ]
        assert readiness[0]["readiness"] == "PARTIAL"
        assert readiness[1]["reason"] == "WARMUP_INCOMPLETE"
        assert readiness[2]["readiness"] == "READY"
        assert readiness[2]["reason"] == "NONE"
    shutil.rmtree(tmp_path / "calculation-results")
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.check_output(
            [str(first_python), "-I", "-c", _ARTIFACT, str(tmp_path)], text=True, stderr=subprocess.PIPE
        )
    assert not (tmp_path / "calculation-results").exists()
    assert OnlyParquetResearchCalculationArtifactStoreV2(portable).load_verified(
        first_artifact["artifact_content_fingerprint"],
        research_result_fingerprint=first_artifact["result"]["research_result_fingerprint"],
    )
    offline = r"""
import importlib.abc, sys
class NoExecutableAuthority(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('onlyalpha.runtime', 'onlyalpha.application', 'onlyalpha_runtime_generation_manager',
                                'onlyalpha.quant_assets.private_factor_execution')):
            raise AssertionError('portable read imported executable Authority: ' + fullname)
sys.meta_path.insert(0, NoExecutableAuthority())
from pathlib import Path
from importlib import metadata
from onlyalpha.research.artifact import OnlyParquetResearchCalculationArtifactStoreV2
from onlyalpha.research.dataset.parquet_store import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.calculation.execution import OnlyResearchCalculationExecutor
from onlyalpha.research.calculation import execution_provenance
def fail(*args, **kwargs):
    raise AssertionError('portable read attempted upstream access, discovery or execution')
metadata.entry_points = fail
OnlyParquetResearchDatasetSnapshotStore.load_verified_table = fail
OnlyParquetResearchDatasetSnapshotStore.acknowledge_exact = fail
OnlyResearchCalculationExecutor._execute_verified_v2 = fail
execution_provenance._only_issue_research_runtime_execution_context = fail
store = OnlyParquetResearchCalculationArtifactStoreV2(Path(sys.argv[1]))
first, second = (store.load_verified(identity, research_result_fingerprint=sys.argv[2]) for identity in sys.argv[3:])
assert first.manifest.result == second.manifest.result
assert first.manifest.artifact_content_fingerprint != second.manifest.artifact_content_fingerprint
print(first.manifest.artifact_content_fingerprint, second.manifest.artifact_content_fingerprint)
"""
    identities = [item["artifact_content_fingerprint"] for item in (first_artifact, second_artifact)]
    # Only portable bytes survive. No offline read may discover original source,
    # Snapshot, Result, Evidence, Registry or Calculation stores from fixture paths.
    for path in ("chart-input", "semantic", "research-results", "registry", "artifacts", "independent-publication"):
        shutil.rmtree(tmp_path / path)
    (tmp_path / "original-facts.json").unlink()
    (tmp_path / "input-owner.json").unlink()
    assert (
        subprocess.check_output(
            [
                sys.executable,
                "-c",
                offline,
                str(portable),
                first_artifact["result"]["research_result_fingerprint"],
                *identities,
            ],
            text=True,
        ).split()
        == identities
    )


@pytest.mark.parametrize("native_publication_case", (1,), indirect=True)
def test_native_period_one_preserves_exact_zero_as_ready(native_publication_case, tmp_path):
    chart, compiled, registry, python, _ = native_publication_case
    provision_native_publication_roots(tmp_path)
    subprocess.check_output([str(python), "-I", "-c", _PUBLISH, str(tmp_path), "execute"], text=True)
    manifest = json.loads(subprocess.check_output([str(python), "-I", "-c", _ARTIFACT, str(tmp_path)], text=True))
    artifact = OnlyParquetResearchCalculationArtifactStoreV2(tmp_path / "artifacts").load_verified(
        manifest["artifact_content_fingerprint"],
        research_result_fingerprint=manifest["result"]["research_result_fingerprint"],
    )
    calculation = next(iter(artifact.calculations.values()))
    values = calculation.outputs[0].table["value"].to_pylist()
    assert values == artifact.dataset_table["volume"].to_pylist()
    assert values[:2] == [Decimal(0), Decimal(0)] and len(set(values)) > 1
    assert all(
        row["readiness"] == "READY" and row["reason"] == "NONE" for row in calculation.readiness[0].table.to_pylist()
    )


def test_installed_native_result_reentry_refuses_an_artifact_only_survivor(native_publication_case, tmp_path):
    _, _, _, python, _ = native_publication_case
    provision_native_publication_roots(tmp_path)
    first = json.loads(
        subprocess.check_output([str(python), "-I", "-c", _PUBLISH, str(tmp_path), "execute"], text=True)
    )
    published = json.loads(subprocess.check_output([str(python), "-I", "-c", _ARTIFACT, str(tmp_path)], text=True))
    calculation = first["evidence"]["calculation_fingerprint"]
    evidence = first["evidence"]["evidence_fingerprint"]
    plan = first["result"]["research_result_plan_fingerprint"]
    paths = (
        tmp_path / "calculation-results" / "v2" / "sha256" / calculation[:2] / calculation,
        tmp_path / "semantic" / "calculation-execution-evidence" / "v2" / "sha256" / evidence[:2] / evidence,
        tmp_path / "research-results" / "sha256" / plan[:2] / plan,
    )
    for index, path in enumerate(paths):
        path.rename(tmp_path / f"unavailable-prefix-{index}")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    attempt = subprocess.run(
        [str(python), "-I", "-c", _PUBLISH, str(tmp_path), "execute"], capture_output=True, text=True
    )
    assert attempt.returncode != 0
    assert "RESEARCH_RESULT_NOT_FOUND" in attempt.stderr
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert all(not path.exists() for path in paths)
    from onlyalpha.research.artifact.calculation_v2_store import OnlyParquetResearchCalculationArtifactStoreV2

    retained = OnlyParquetResearchCalculationArtifactStoreV2(tmp_path / "artifacts").load_verified(
        published["artifact_content_fingerprint"],
        research_result_fingerprint=published["result"]["research_result_fingerprint"],
    )
    assert retained.manifest.artifact_content_fingerprint == published["artifact_content_fingerprint"]
