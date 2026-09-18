from dataclasses import replace

import pytest
from onlyalpha_plugin_indicators.provider import quant_asset_provider as indicator_provider
from onlyalpha_plugin_operators.provider import quant_asset_provider as operator_provider
from onlyalpha_test_factor_provider.provider import quant_asset_provider as factor_provider

from onlyalpha.calculation import OnlyCalculationBackendKind, OnlyCalculationKind
from onlyalpha.quant_assets import (
    OnlyQuantAssetCatalogGeneration,
    OnlyQuantAssetCatalogManager,
    OnlyQuantAssetKind,
    OnlyQuantAssetProvider,
    only_discover_quant_asset_providers,
)


def _generation() -> OnlyQuantAssetCatalogGeneration:
    return only_discover_quant_asset_providers(
        (operator_provider(), indicator_provider(), factor_provider()),
        include_installed=False,
    )


def test_public_calculation_kinds_form_one_content_addressed_catalog_generation() -> None:
    generation = _generation()
    assert set(OnlyQuantAssetKind) == {
        OnlyQuantAssetKind.OPERATOR,
        OnlyQuantAssetKind.INDICATOR,
        OnlyQuantAssetKind.FACTOR,
        OnlyQuantAssetKind.STRATEGY,
    }
    assert {provider.manifest.kind for provider in generation.providers} == {
        OnlyQuantAssetKind.OPERATOR,
        OnlyQuantAssetKind.INDICATOR,
        OnlyQuantAssetKind.FACTOR,
    }
    assert len(generation.generation_fingerprint) == 64
    registry = generation.calculation_registry()
    assert registry.resolve(
        OnlyCalculationKind.INDICATOR,
        "onlyalpha.operator.rolling_mean",
        "1",
        OnlyCalculationBackendKind.RESEARCH,
    )
    assert registry.resolve(
        OnlyCalculationKind.FACTOR,
        "example.factor.momentum",
        "1",
        OnlyCalculationBackendKind.TRADING,
    )
    descriptor = generation.descriptor()
    assert descriptor["generation_fingerprint"] == generation.generation_fingerprint


def test_installed_quant_asset_entry_points_discover_public_calculation_kinds() -> None:
    generation = only_discover_quant_asset_providers()
    assert {provider.manifest.kind for provider in generation.providers} >= {
        OnlyQuantAssetKind.OPERATOR,
        OnlyQuantAssetKind.INDICATOR,
        OnlyQuantAssetKind.FACTOR,
    }
    assert OnlyQuantAssetKind.STRATEGY not in {provider.manifest.kind for provider in generation.providers}
    assert {provider.manifest.provider_id for provider in generation.providers} >= {
        "onlyalpha.operator.library",
        "onlyalpha.indicator.library",
        "example.factor.library",
    }


def test_refresh_is_atomic_and_rejects_same_version_content_drift() -> None:
    initial = _generation()
    manager = OnlyQuantAssetCatalogManager(initial)
    old_snapshot = manager.snapshot()
    factor = factor_provider()
    original = factor.calculation_registrations[0]
    assert original.implementation_manifest is not None
    changed_manifest = replace(
        original.implementation_manifest,
        resources=(replace(original.implementation_manifest.resources[0], byte_sha256="f" * 64),)
        + original.implementation_manifest.resources[1:],
    )
    changed_registration = replace(original, implementation_manifest=changed_manifest)
    drifted = replace(
        factor,
        calculation_registrations=(changed_registration,) + factor.calculation_registrations[1:],
    )
    candidate = OnlyQuantAssetCatalogGeneration(
        tuple(
            drifted if item.manifest.provider_id == factor.manifest.provider_id else item for item in initial.providers
        )
    )
    with pytest.raises(ValueError, match="CONTENT_DRIFT"):
        manager.refresh(lambda: candidate)
    assert manager.snapshot() is old_snapshot
    assert manager.generation(old_snapshot.generation_fingerprint) is old_snapshot


def test_new_provider_version_switches_only_new_catalog_snapshot() -> None:
    initial = _generation()
    manager = OnlyQuantAssetCatalogManager(initial)
    factor = factor_provider()
    version_two = OnlyQuantAssetProvider(
        replace(factor.manifest, provider_version="2"),
        calculation_registrations=factor.calculation_registrations,
    )
    candidate = OnlyQuantAssetCatalogGeneration(
        tuple(
            version_two if item.manifest.provider_id == factor.manifest.provider_id else item
            for item in initial.providers
        )
    )
    current = manager.refresh(lambda: candidate)
    assert current.generation_fingerprint != initial.generation_fingerprint
    assert manager.snapshot() is current
    assert manager.generation(initial.generation_fingerprint) is initial


def test_distribution_rebuild_changes_generation_without_false_content_drift() -> None:
    initial = _generation()
    manager = OnlyQuantAssetCatalogManager(initial)
    factor = factor_provider()
    repackaged = replace(
        factor,
        manifest=replace(
            factor.manifest,
            source=replace(factor.manifest.source, distribution_version="0.9.10"),
        ),
    )
    assert repackaged.content_fingerprint == factor.content_fingerprint
    candidate = OnlyQuantAssetCatalogGeneration(
        tuple(
            repackaged if item.manifest.provider_id == factor.manifest.provider_id else item
            for item in initial.providers
        )
    )

    assert candidate.generation_fingerprint != initial.generation_fingerprint
    assert manager.refresh(lambda: candidate) is candidate


def test_duplicate_calculation_identity_across_providers_fails_closed() -> None:
    operator = operator_provider()
    duplicate = replace(
        operator,
        manifest=replace(operator.manifest, provider_id="private.operator.library"),
    )
    with pytest.raises(ValueError, match="duplicate calculation backend registration"):
        OnlyQuantAssetCatalogGeneration((operator, duplicate))
