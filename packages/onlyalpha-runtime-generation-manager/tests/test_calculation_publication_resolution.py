from __future__ import annotations

import sys
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

import pytest

from tests.runtime_support.chart_execution_host import compile_chart_in_exact_host
from tests.support.runtime_distribution_wheels import build_wheel, installed_distribution_wheel, plain_artifact


def test_hosted_worker_advertises_separate_calculation_publication_resolution():
    from onlyalpha_runtime_generation_manager.search_worker import _CAPABILITIES

    from onlyalpha.application.search_generation_execution import OnlySearchGenerationOperationV1

    operation = OnlySearchGenerationOperationV1("RESOLVE_RESEARCH_CALCULATION_PUBLICATION")
    assert operation in _CAPABILITIES


def test_exact_installed_generation_resolves_after_retirement_without_current_registry(tmp_path, monkeypatch):
    from onlyalpha_plugin_indicators.provider import quant_asset_provider
    from onlyalpha_runtime_generation_manager import (
        OnlyHistoricalGenerationHostManager,
        OnlyLocalImmutableArtifactStore,
        OnlyRuntimeGenerationBuilder,
        OnlyRuntimeGenerationRegistry,
    )

    from onlyalpha.quant_assets import OnlyQuantAssetCatalogGeneration, only_quant_asset_distribution_artifact_manifest
    from onlyalpha.research.dataset.parquet_store import OnlyParquetResearchDatasetSnapshotStore
    from onlyalpha.research.run.errors import OnlyResearchRunAdmissionError
    from onlyalpha.research.run.generation import OnlyResearchHostedRuntimeGenerationResolver
    from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver
    from onlyalpha.runtime.generation import (
        OnlyArtifactSourceProvenanceAuthority,
        OnlyCoreExecutionIdentity,
        OnlyDistributionArtifactRole,
    )
    from tests.research.calculation.support import snapshot
    from tests.research.specification.test_calculation_publication import publication_specification
    from tests.runtime_support.generation_support import only_ready_test_generation

    repository = Path(__file__).resolve().parents[3]
    wheels = [
        build_wheel(repository, tmp_path / "core"),
        build_wheel(repository / "packages/onlyalpha-runtime-generation-manager", tmp_path / "manager"),
        build_wheel(repository / "plugs/onlyalpha-plugin-indicators", tmp_path / "indicators"),
        installed_distribution_wheel("pyarrow", tmp_path / "arrow"),
    ]
    core = plain_artifact(
        wheels[0],
        role=OnlyDistributionArtifactRole.CORE,
        authority=OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
        repository="OnlyAlpha",
        revision="1" * 40,
    )
    identity = OnlyCoreExecutionIdentity(core.distribution_name, core.distribution_version, core.artifact_sha256)
    provider = quant_asset_provider()
    indicator = only_quant_asset_distribution_artifact_manifest(
        source_repository="OnlyAlpha",
        source_revision="2" * 40,
        artifact_logical_name=wheels[2].name,
        artifact_bytes=wheels[2].read_bytes(),
        tested_core_execution_fingerprint=identity.fingerprint,
        provider=provider,
    )
    manager = plain_artifact(
        wheels[1],
        role=OnlyDistributionArtifactRole.SUPPORT,
        authority=OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
        repository="OnlyAlpha",
        revision="3" * 40,
    )
    arrow = plain_artifact(
        wheels[3],
        role=OnlyDistributionArtifactRole.SUPPORT,
        authority=OnlyArtifactSourceProvenanceAuthority.EXTERNAL_RELEASE,
        repository="Apache-Arrow",
        revision="release-" + metadata.version("pyarrow"),
    )
    artifacts = (core, manager, indicator, arrow)
    store = OnlyLocalImmutableArtifactStore(tmp_path / "artifacts")
    for artifact, wheel in zip(artifacts, wheels, strict=True):
        store.put_once(artifact, wheel.read_bytes())
    builder = OnlyRuntimeGenerationBuilder(store, Path(sys.executable))
    built = builder.build_validated(
        artifacts=artifacts,
        expected_catalog=OnlyQuantAssetCatalogGeneration((provider,)),
        environment_root=tmp_path / "built",
    )
    registry = OnlyRuntimeGenerationRegistry(tmp_path / "registry")
    now = datetime(2026, 10, 7, tzinfo=UTC)
    generation = built.manifest.runtime_generation_fingerprint
    registry.prepare(built.manifest, actor="test", occurred_at=now)
    registry.admit_ready(built.validation_evidence, actor="test", occurred_at=now)
    registry.activate_for_new_work(expected_current=None, target=generation, actor="test", occurred_at=now)
    dataset_root = tmp_path / "datasets"
    candidate, partitions = snapshot()
    dataset = OnlyParquetResearchDatasetSnapshotStore(dataset_root).commit(candidate, partitions)
    spec = publication_specification(dataset.snapshot_fingerprint)
    host = OnlyHistoricalGenerationHostManager(registry=registry, builder=builder, cache_root=tmp_path / "hosts")
    resolver = OnlyResearchHostedRuntimeGenerationResolver(execution=host, dataset_store_root=str(dataset_root))

    def no_current(*args, **kwargs):
        raise AssertionError("historical resolution touched current server resolver")

    monkeypatch.setattr(OnlyResearchSpecificationResolver, "resolve", no_current)
    try:
        chart, chart_service, chart_compilation = compile_chart_in_exact_host(
            tmp_path, registry, builder, generation, host
        )
        from onlyalpha.application.chart_calculation_run_admission import (
            OnlyChartCalculationRunAdmissionService,
            only_chart_calculation_queued_run,
        )

        class AdmissionPort:
            """Queue contract fake; actual atomic PostgreSQL behavior is proved in its owning lane."""

            admitted = None

            def load_verified(self, operation):
                return self.admitted

            def commit_or_replay(self, operation, frozen, *, queued_at):
                assert frozen == chart_compilation
                self.admitted = only_chart_calculation_queued_run(frozen, queued_at=queued_at)
                return self.admitted

        admission = OnlyChartCalculationRunAdmissionService(
            preparations=chart.preparations,
            compilations=chart.compilations,
            datasets=chart.dataset,
            materializations=chart.dataset,
            runtime_generations=registry,
            runs=AdmissionPort(),
        )
        chart_run = admission.admit(chart.operation, queued_at=chart.operation.accepted_at)
        assert chart_run.state.value == "QUEUED" and chart_run.origin_kind.value == "CHART_CALCULATION"
        assert chart_run.admission_resolution_fingerprint == chart_compilation.compilation_fingerprint
        registry.release_work(chart.operation.reserved_run_id.value, actor="test", occurred_at=now)
        other = only_ready_test_generation(registry, "e", now)
        registry.activate_for_new_work(expected_current=generation, target=other, actor="test", occurred_at=now)
        registry.retire(generation, actor="test", occurred_at=now)
        chart_service._resolver = object()  # Verified replay cannot call an unavailable host.
        assert chart_service.compile(chart.operation) == chart_compilation
        assert admission.admit(chart.operation, queued_at=chart.operation.accepted_at) == chart_run
        resolved = resolver.resolve_calculation_publication(generation, spec)
        assert resolved.runtime_generation_fingerprint == generation
        assert resolved.specification == spec and resolved.result_plan.schema_version == 4
        assert (
            resolved.implementation_manifest.implementation_fingerprint
            == resolved.research_implementation_bindings[0].research_implementation_fingerprint
        )
        assert resolver.resolve_calculation_publication(generation, spec) == resolved
        from onlyalpha.application.search_generation_execution import (
            OnlyHistoricalGenerationUnavailable,
            OnlySearchGenerationExecutionRequestV1,
            OnlySearchGenerationOperationV1,
        )

        with pytest.raises(OnlyHistoricalGenerationUnavailable):
            host.acquire(generation)
        with pytest.raises(OnlyHistoricalGenerationUnavailable):
            host.execute(
                OnlySearchGenerationExecutionRequestV1(
                    generation, OnlySearchGenerationOperationV1.RESOLVE_RESEARCH_ADMISSION, {}
                )
            )
        with pytest.raises(OnlyResearchRunAdmissionError) as failure:
            resolver.resolve(generation, spec)
        assert failure.value.code == "RESEARCH_ADMISSION_SPECIFICATION_VERSION_UNSUPPORTED"
    finally:
        host.close()
