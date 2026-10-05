from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from onlyalpha_plugin_operators.provider import quant_asset_provider as operator_provider
from onlyalpha_runtime_generation_manager import (
    OnlyRuntimeGenerationBuilder,
    OnlyRuntimeGenerationRegistry,
)
from onlyalpha_runtime_generation_manager.catalog_context import OnlyRuntimeGenerationExactCatalogDescriptorReader
from onlyalpha_test_factor_provider.provider import quant_asset_provider as factor_provider

from onlyalpha.application.catalog_context import (
    OnlyExactCatalogContextCorrupt,
    OnlyExactCatalogContextNotFound,
    OnlyExactCatalogContextProjectionMismatch,
    OnlyExactCatalogContextQueryService,
    OnlyExactCatalogContextUnavailable,
)
from onlyalpha.quant_assets import OnlyQuantAssetCatalogGeneration
from onlyalpha.runtime.generation import (
    OnlyCoreExecutionIdentity,
    OnlyRuntimeGenerationManifest,
    OnlyRuntimeGenerationValidationEvidence,
    OnlyRuntimeProviderBinding,
)

NOW = datetime(2026, 9, 8, tzinfo=UTC)


def _manifest(seed: str, catalog: OnlyQuantAssetCatalogGeneration) -> OnlyRuntimeGenerationManifest:
    provider = catalog.providers[0]
    return OnlyRuntimeGenerationManifest(
        core_execution=OnlyCoreExecutionIdentity("onlyalpha", f"0.9.{seed}", seed * 64),
        artifact_manifest_fingerprints=(seed * 64,),
        artifact_sha256s=(seed * 64,),
        providers=(
            OnlyRuntimeProviderBinding(
                provider.manifest.provider_id,
                provider.manifest.provider_version,
                provider.content_fingerprint,
                seed * 64,
            ),
        ),
        catalog_generation_fingerprint=catalog.generation_fingerprint,
        implementations=(),
    )


def _ready(
    registry: OnlyRuntimeGenerationRegistry,
    manifest: OnlyRuntimeGenerationManifest,
    offset: int,
) -> str:
    registry.prepare(manifest, actor="operator", occurred_at=NOW + timedelta(seconds=offset))
    registry.admit_ready(
        OnlyRuntimeGenerationValidationEvidence.from_manifest(manifest),
        actor="validator",
        occurred_at=NOW + timedelta(seconds=offset + 1),
    )
    return manifest.runtime_generation_fingerprint


class _Builder:
    def __init__(self, descriptors: dict[str, dict[str, object]], unavailable: set[str] | None = None) -> None:
        self.descriptors = descriptors
        self.unavailable = unavailable or set()
        self.calls: list[str] = []

    def rebuild_catalog_context_bundle(
        self,
        *,
        expected_manifest: OnlyRuntimeGenerationManifest,
        environment_root: Path,
    ) -> dict[str, object]:
        assert not environment_root.exists()
        fingerprint = expected_manifest.runtime_generation_fingerprint
        self.calls.append(fingerprint)
        if fingerprint in self.unavailable:
            raise ValueError("RUNTIME_GENERATION_ARTIFACT_MISMATCH")
        return {
            "catalog": self.descriptors[fingerprint],
            "dataset_fields": [],
            "registered_universes": [],
            "statistics": [],
        }

    def verify_exact_artifacts(self, expected_manifest: OnlyRuntimeGenerationManifest) -> None:
        del expected_manifest


def _reader(
    registry: OnlyRuntimeGenerationRegistry,
    builder: _Builder,
    root: Path,
) -> OnlyRuntimeGenerationExactCatalogDescriptorReader:
    return OnlyRuntimeGenerationExactCatalogDescriptorReader(
        registry,
        cast(OnlyRuntimeGenerationBuilder, builder),
        root,
    )


def test_retired_generation_is_exact_after_activation_switch_and_fresh_reader_restart(tmp_path: Path) -> None:
    first_catalog = OnlyQuantAssetCatalogGeneration((operator_provider(),))
    second_catalog = OnlyQuantAssetCatalogGeneration((factor_provider(),))
    first_manifest = _manifest("a", first_catalog)
    second_manifest = _manifest("b", second_catalog)
    registry = OnlyRuntimeGenerationRegistry(tmp_path / "authority")
    first_runtime = _ready(registry, first_manifest, 0)
    second_runtime = _ready(registry, second_manifest, 2)
    registry.activate_for_new_work(expected_current=None, target=first_runtime, actor="operator", occurred_at=NOW)
    registry.activate_for_new_work(
        expected_current=first_runtime,
        target=second_runtime,
        actor="operator",
        occurred_at=NOW + timedelta(seconds=4),
    )
    registry.retire(first_runtime, actor="operator", occurred_at=NOW + timedelta(seconds=5))
    descriptors = {
        first_runtime: first_catalog.descriptor(),
        second_runtime: second_catalog.descriptor(),
    }
    before_reader = _reader(registry, _Builder(descriptors), tmp_path / "environments-a")
    before = OnlyExactCatalogContextQueryService(
        before_reader, before_reader, before_reader, before_reader
    ).get_exact_catalog_context(first_catalog.generation_fingerprint)

    fresh_registry = OnlyRuntimeGenerationRegistry(tmp_path / "authority")
    after_reader = _reader(fresh_registry, _Builder(descriptors), tmp_path / "environments-b")
    after = OnlyExactCatalogContextQueryService(
        after_reader, after_reader, after_reader, after_reader
    ).get_exact_catalog_context(first_catalog.generation_fingerprint)

    assert before == after
    assert before.canonical_bytes() == after.canonical_bytes()
    assert before.catalog_generation_fingerprint == first_catalog.generation_fingerprint
    assert {item.provider_id for item in before.ordered_providers} == {"onlyalpha.operator.library"}


def test_multiple_runtime_generations_for_one_catalog_converge_and_ignore_runtime_identity(tmp_path: Path) -> None:
    catalog = OnlyQuantAssetCatalogGeneration((operator_provider(),))
    first = _manifest("a", catalog)
    second = _manifest("b", catalog)
    registry = OnlyRuntimeGenerationRegistry(tmp_path / "authority")
    first_runtime = _ready(registry, first, 0)
    second_runtime = _ready(registry, second, 2)
    descriptors = {
        first_runtime: catalog.descriptor(),
        second_runtime: catalog.descriptor(),
    }
    builder = _Builder(descriptors)

    context_reader = _reader(registry, builder, tmp_path / "environments")
    context = OnlyExactCatalogContextQueryService(
        context_reader, context_reader, context_reader, context_reader
    ).get_exact_catalog_context(catalog.generation_fingerprint)

    assert builder.calls == sorted((first_runtime, second_runtime))
    assert context.catalog_generation_fingerprint == catalog.generation_fingerprint
    assert "runtime_generation_fingerprint" not in context.to_dict()


def test_disagreeing_reconstructions_and_unavailable_or_unknown_generation_fail_closed(tmp_path: Path) -> None:
    catalog = OnlyQuantAssetCatalogGeneration((operator_provider(),))
    first = _manifest("a", catalog)
    second = _manifest("b", catalog)
    registry = OnlyRuntimeGenerationRegistry(tmp_path / "authority")
    first_runtime = _ready(registry, first, 0)
    second_runtime = _ready(registry, second, 2)
    changed = catalog.descriptor()
    changed["unexpected"] = True
    disagreeing = _Builder({first_runtime: catalog.descriptor(), second_runtime: changed})
    reader = _reader(registry, disagreeing, tmp_path / "disagreeing")
    with pytest.raises(OnlyExactCatalogContextProjectionMismatch):
        reader.load_verified_catalog_descriptor(catalog.generation_fingerprint)

    unavailable = _Builder(
        {first_runtime: catalog.descriptor(), second_runtime: catalog.descriptor()},
        {first_runtime, second_runtime},
    )
    with pytest.raises(OnlyExactCatalogContextUnavailable):
        _reader(registry, unavailable, tmp_path / "unavailable").load_verified_catalog_descriptor(
            catalog.generation_fingerprint
        )

    with pytest.raises(OnlyExactCatalogContextNotFound):
        reader.load_verified_catalog_descriptor("f" * 64)


class _ReadinessBuilder(_Builder):
    def __init__(self, catalog: OnlyQuantAssetCatalogGeneration, descriptors: dict[str, dict[str, object]]) -> None:
        super().__init__(descriptors)
        self.sidecars: dict[str, object] = {}
        rows = [
            {
                "provider_id": provider.manifest.provider_id,
                "provider_version": provider.manifest.provider_version,
                "provider_kind": provider.manifest.kind.value,
                "kind": registration.type_definition.kind.value,
                "type_id": registration.type_definition.type_id,
                "semantic_version": registration.type_definition.semantic_version,
                "backend": registration.backend.value,
                "implementation_fingerprint": registration.implementation_manifest.implementation_fingerprint,
                "readiness_contract_versions": list(registration.readiness_contract_versions),
            }
            for provider in catalog.providers
            for registration in provider.calculation_registrations
            if registration.implementation_manifest is not None
        ]
        rows.sort(
            key=lambda item: tuple(
                item[name]
                for name in (
                    "provider_kind",
                    "provider_id",
                    "provider_version",
                    "kind",
                    "type_id",
                    "semantic_version",
                    "backend",
                )
            )
        )
        for fingerprint in descriptors:
            self.sidecars[fingerprint] = rows

    def rebuild_catalog_context_bundle(
        self, *, expected_manifest: OnlyRuntimeGenerationManifest, environment_root: Path
    ) -> dict[str, object]:
        bundle = super().rebuild_catalog_context_bundle(
            expected_manifest=expected_manifest, environment_root=environment_root
        )
        bundle["calculation_readiness"] = self.sidecars[expected_manifest.runtime_generation_fingerprint]
        return bundle


def test_multiple_exact_runtime_generations_converge_on_complete_readiness(tmp_path: Path) -> None:
    catalog = OnlyQuantAssetCatalogGeneration((operator_provider(),))
    registry = OnlyRuntimeGenerationRegistry(tmp_path / "authority")
    runtimes = (_ready(registry, _manifest("a", catalog), 0), _ready(registry, _manifest("b", catalog), 2))
    builder = _ReadinessBuilder(catalog, {runtime: catalog.descriptor() for runtime in runtimes})
    reader = _reader(registry, builder, tmp_path / "environments")
    rows = reader.load_exact_calculation_readiness_capabilities(catalog.generation_fingerprint)
    assert len(rows) == sum(len(provider.calculation_registrations) for provider in catalog.providers)
    assert all(item.readiness_contract_versions == () for item in rows)
    assert all(item.catalog_generation_fingerprint == catalog.generation_fingerprint for item in rows)
    assert builder.calls == sorted(runtimes)


@pytest.mark.parametrize("sidecar", (None, "malformed", [{}]))
def test_exact_runtime_generation_malformed_readiness_sidecar_fails_closed(tmp_path: Path, sidecar: object) -> None:
    catalog = OnlyQuantAssetCatalogGeneration((operator_provider(),))
    registry = OnlyRuntimeGenerationRegistry(tmp_path / "authority")
    runtime = _ready(registry, _manifest("a", catalog), 0)
    builder = _ReadinessBuilder(catalog, {runtime: catalog.descriptor()})
    builder.sidecars[runtime] = sidecar
    with pytest.raises(OnlyExactCatalogContextCorrupt):
        _reader(registry, builder, tmp_path / "environments").load_exact_calculation_readiness_capabilities(
            catalog.generation_fingerprint
        )


def test_exact_runtime_generation_missing_readiness_sidecar_is_not_unsupported(tmp_path: Path) -> None:
    catalog = OnlyQuantAssetCatalogGeneration((operator_provider(),))
    registry = OnlyRuntimeGenerationRegistry(tmp_path / "authority")
    runtime = _ready(registry, _manifest("a", catalog), 0)
    reader = _reader(registry, _Builder({runtime: catalog.descriptor()}), tmp_path / "environments")
    with pytest.raises(OnlyExactCatalogContextCorrupt):
        reader.load_exact_calculation_readiness_capabilities(catalog.generation_fingerprint)


def test_disagreeing_complete_readiness_sidecars_fail_closed(tmp_path: Path) -> None:
    catalog = OnlyQuantAssetCatalogGeneration((operator_provider(),))
    registry = OnlyRuntimeGenerationRegistry(tmp_path / "authority")
    runtimes = (_ready(registry, _manifest("a", catalog), 0), _ready(registry, _manifest("b", catalog), 2))
    builder = _ReadinessBuilder(catalog, {runtime: catalog.descriptor() for runtime in runtimes})
    changed = deepcopy(builder.sidecars[runtimes[1]])
    assert isinstance(changed, list)
    row = next(item for item in changed if item["backend"] == "RESEARCH")
    row["readiness_contract_versions"] = [2]
    builder.sidecars[runtimes[1]] = changed
    reader = _reader(registry, builder, tmp_path / "environments")
    assert reader.load_verified_catalog_descriptor(catalog.generation_fingerprint) == catalog.descriptor()
    with pytest.raises(OnlyExactCatalogContextProjectionMismatch):
        reader.load_exact_calculation_readiness_capabilities(catalog.generation_fingerprint)


@pytest.mark.parametrize("sidecar", ([], [{}], None))
def test_one_complete_and_one_incomplete_readiness_bundle_is_corrupt(tmp_path: Path, sidecar: object) -> None:
    catalog = OnlyQuantAssetCatalogGeneration((operator_provider(),))
    registry = OnlyRuntimeGenerationRegistry(tmp_path / "authority")
    runtimes = (_ready(registry, _manifest("a", catalog), 0), _ready(registry, _manifest("b", catalog), 2))
    builder = _ReadinessBuilder(catalog, {runtime: catalog.descriptor() for runtime in runtimes})
    builder.sidecars[runtimes[1]] = sidecar
    reader = _reader(registry, builder, tmp_path / "environments")
    assert reader.load_verified_catalog_descriptor(catalog.generation_fingerprint) == catalog.descriptor()
    with pytest.raises(OnlyExactCatalogContextCorrupt):
        reader.load_exact_calculation_readiness_capabilities(catalog.generation_fingerprint)


def test_retired_generation_readiness_is_exact_after_fresh_reader_restart(tmp_path: Path) -> None:
    catalog = OnlyQuantAssetCatalogGeneration((operator_provider(),))
    registry = OnlyRuntimeGenerationRegistry(tmp_path / "authority")
    runtime = _ready(registry, _manifest("a", catalog), 0)
    newer_catalog = OnlyQuantAssetCatalogGeneration((factor_provider(),))
    newer_runtime = _ready(registry, _manifest("b", newer_catalog), 2)
    registry.activate_for_new_work(expected_current=None, target=runtime, actor="operator", occurred_at=NOW)
    registry.activate_for_new_work(
        expected_current=runtime, target=newer_runtime, actor="operator", occurred_at=NOW + timedelta(seconds=4)
    )
    registry.retire(runtime, actor="operator", occurred_at=NOW + timedelta(seconds=5))
    builder = _ReadinessBuilder(catalog, {runtime: catalog.descriptor()})
    before_reader = _reader(registry, builder, tmp_path / "before")
    before = OnlyExactCatalogContextQueryService(
        before_reader,
        before_reader,
        before_reader,
        before_reader,
        before_reader,
    ).get_exact_catalog_readiness(catalog.generation_fingerprint)
    fresh_reader = _reader(OnlyRuntimeGenerationRegistry(tmp_path / "authority"), builder, tmp_path / "after")
    after = OnlyExactCatalogContextQueryService(
        fresh_reader,
        fresh_reader,
        fresh_reader,
        fresh_reader,
        fresh_reader,
    ).get_exact_catalog_readiness(catalog.generation_fingerprint)
    assert before.to_dict() == after.to_dict()
    assert before.projection_fingerprint == after.projection_fingerprint
