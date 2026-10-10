"""Real, offline wheel-backed host fixture shared by Contract and PostgreSQL tests."""

from __future__ import annotations

import shutil
import stat
import sys
from importlib import metadata
from pathlib import Path

import pytest

from tests.support.runtime_distribution_wheels import build_wheel, installed_distribution_wheel, plain_artifact


@pytest.fixture(scope="module")
def exact_host_environment(tmp_path_factory):
    from onlyalpha_plugin_indicators.provider import quant_asset_provider
    from onlyalpha_runtime_generation_manager import (
        OnlyHistoricalGenerationHostManager,
        OnlyLocalImmutableArtifactStore,
        OnlyRuntimeGenerationBuilder,
    )

    from onlyalpha.quant_assets import OnlyQuantAssetCatalogGeneration, only_quant_asset_distribution_artifact_manifest
    from onlyalpha.runtime.generation import (
        OnlyArtifactSourceProvenanceAuthority,
        OnlyCoreExecutionIdentity,
        OnlyDistributionArtifactRole,
    )

    root = tmp_path_factory.mktemp("exact-chart-host")
    repository = Path(__file__).resolve().parents[2]
    postgres_dependencies = ("psycopg", "psycopg-binary", "typing-extensions", "cryptography", "cffi", "pycparser")
    wheels = [
        build_wheel(repository, root / "core"),
        build_wheel(repository / "packages/onlyalpha-runtime-generation-manager", root / "manager"),
        build_wheel(repository / "plugs/onlyalpha-plugin-indicators", root / "indicators"),
        installed_distribution_wheel("pyarrow", root / "arrow"),
        installed_distribution_wheel("pyyaml", root / "yaml"),
        *(installed_distribution_wheel(name, root / name) for name in postgres_dependencies),
    ]
    authority = OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT
    core = plain_artifact(
        wheels[0],
        role=OnlyDistributionArtifactRole.CORE,
        authority=authority,
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
        authority=authority,
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
    yaml = plain_artifact(
        wheels[4],
        role=OnlyDistributionArtifactRole.SUPPORT,
        authority=OnlyArtifactSourceProvenanceAuthority.EXTERNAL_RELEASE,
        repository="PyYAML",
        revision="release-" + metadata.version("pyyaml"),
    )
    postgres_support = tuple(
        plain_artifact(
            wheel,
            role=OnlyDistributionArtifactRole.SUPPORT,
            authority=OnlyArtifactSourceProvenanceAuthority.EXTERNAL_RELEASE,
            repository="Python-package-" + name,
            revision="release-" + metadata.version(name),
        )
        for name, wheel in zip(postgres_dependencies, wheels[5:], strict=True)
    )
    artifacts = (core, manager, indicator, arrow, yaml, *postgres_support)
    store = OnlyLocalImmutableArtifactStore(root / "artifacts")
    for artifact, wheel in zip(artifacts, wheels, strict=True):
        store.put_once(artifact, wheel.read_bytes())
    builder = OnlyRuntimeGenerationBuilder(store, Path(sys.executable))
    built = builder.build_validated(
        artifacts=artifacts,
        expected_catalog=OnlyQuantAssetCatalogGeneration((provider,)),
        environment_root=root / "built",
    )
    # Freeze only installed code, before a publication case provisions its own
    # schema reference in `built`. No registry, Work, process or database is here.
    template = root / "host-template" / built.manifest.runtime_generation_fingerprint
    try:
        shutil.copytree(root / "built", template, symlinks=True)
        _require_environment_symlinks(template)
        for entry in (template, *template.rglob("*")):
            if not entry.is_symlink():
                entry.chmod(entry.stat().st_mode & ~0o222)
        yield builder, built, OnlyHistoricalGenerationHostManager, template
    finally:
        # Only this fixture's copy is restored for pytest cleanup, including
        # failures before yield. Never chmod a base-interpreter symlink target.
        _make_environment_directories_writable(template)


def _require_environment_symlinks(root: Path) -> None:
    interpreter = Path(sys.executable).resolve()
    for entry in root.rglob("*"):
        if entry.is_symlink():
            target = entry.resolve(strict=True)
            assert target.is_relative_to(root.resolve()) or target == interpreter, "external template symlink"


def _make_environment_directories_writable(root: Path) -> None:
    if root.exists():
        for entry in (root, *root.rglob("*")):
            if not entry.is_symlink() and entry.is_dir():
                entry.chmod(entry.stat().st_mode | stat.S_IWUSR)


def materialize_exact_host_environment(template: Path, generation_fingerprint: str, cache_root: Path) -> Path:
    """Copy immutable code into a new case cache; this grants no host Authority."""
    assert template.is_dir() and template.name == generation_fingerprint, "exact host template required"
    _require_environment_symlinks(template)
    assert all(entry.is_symlink() or not entry.stat().st_mode & 0o222 for entry in (template, *template.rglob("*")))
    target = cache_root / generation_fingerprint
    try:
        shutil.copytree(template, target, symlinks=True)
    except FileExistsError:
        # A preexisting destination is not ours to merge, sanitize or chmod.
        raise
    except OSError:
        _make_environment_directories_writable(target)
        raise
    _make_environment_directories_writable(target)
    # The real manager still exact-loads the owning manifest/evidence, starts a
    # fresh interpreter, and verifies installed seal/RECORD/handshake. A copied
    # directory, matching name, or template permission is never admission proof.
    return target


def compile_chart_in_exact_host(tmp_path, registry, builder, generation, host, *, period=3, price_field="VOLUME"):
    from dataclasses import replace

    from onlyalpha_runtime_generation_manager.catalog_context import OnlyRuntimeGenerationExactCatalogDescriptorReader

    from onlyalpha.application.catalog_context import OnlyExactCatalogContextQueryService
    from onlyalpha.application.chart_calculation import OnlyChartCalculationCatalogWitnessV1
    from onlyalpha.application.chart_calculation_compilation import OnlyChartCalculationCompilationService
    from onlyalpha.application.chart_calculation_preparation import (
        OnlyChartCalculationInputPinV1,
        OnlyChartCalculationRuntimeBindingReferenceV1,
    )
    from onlyalpha.canonical import only_canonical_json
    from onlyalpha.research.run.generation import OnlyResearchHostedRuntimeGenerationResolver
    from tests.application.test_chart_calculation_admission import NOW
    from tests.support.chart_calculation_compilation import prepared_input

    chart = prepared_input(tmp_path / "chart-input", period=period, price_field=price_field)
    reader = OnlyRuntimeGenerationExactCatalogDescriptorReader(registry, builder, tmp_path / "chart-catalog")
    query = OnlyExactCatalogContextQueryService(reader, reader, reader, reader, readiness=reader)
    catalog = registry.load_manifest(generation).catalog_generation_fingerprint
    witness = OnlyChartCalculationCatalogWitnessV1.from_projections(
        query.get_exact_catalog_context(catalog), query.get_exact_catalog_readiness(catalog)
    )
    chart.operation = replace(chart.operation, catalog_witness=witness)
    registry.bind_new_work_exact(
        chart.operation.reserved_run_id.value,
        generation,
        owner="CHART_CALCULATION_INPUT",
        actor="chart-test",
        occurred_at=NOW,
    )
    evidence = registry.require_work_binding_evidence(chart.operation.reserved_run_id.value)
    pin = dict(chart.preparation.input_pin.to_dict())
    pin["runtime_generation_fingerprint"] = generation
    chart.preparation = replace(
        chart.preparation,
        runtime_generation_fingerprint=generation,
        input_pin=OnlyChartCalculationInputPinV1(only_canonical_json(pin)),
        runtime_binding_reference=OnlyChartCalculationRuntimeBindingReferenceV1.from_evidence(evidence),
    )
    chart.preparations.load_verified.return_value = chart.preparation
    resolver = OnlyResearchHostedRuntimeGenerationResolver(
        execution=host, dataset_store_root=str(tmp_path / "chart-input" / "dataset")
    )
    service = OnlyChartCalculationCompilationService(
        preparations=chart.preparations,
        datasets=chart.dataset,
        materializations=chart.dataset,
        runtime_generations=registry,
        resolver=resolver,
        compilations=chart.compilations,
    )
    compiled = service.compile(chart.operation)
    chart.compilations.load_verified.return_value = compiled
    assert compiled.specification.calculations[0].graph_template.nodes[0].input_bindings == ()
    assert (
        compiled.resolution.implementation_manifest.implementation_fingerprint
        == witness.capability.implementation_fingerprint
    )
    assert service.compile(chart.operation) == compiled
    return chart, service, compiled
