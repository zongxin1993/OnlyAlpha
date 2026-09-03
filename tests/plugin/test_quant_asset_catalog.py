import json
from dataclasses import replace

import pytest
from onlyalpha_example_alpha.provider import quant_asset_provider as alpha_provider
from onlyalpha_example_strategies.provider import quant_asset_provider as strategy_provider
from onlyalpha_plugin_indicators.provider import quant_asset_provider as indicator_provider
from onlyalpha_plugin_operators.provider import quant_asset_provider as operator_provider

from onlyalpha.calculation import OnlyCalculationBackendKind, OnlyCalculationKind
from onlyalpha.quant_assets import (
    OnlyQuantAssetCatalogGeneration,
    OnlyQuantAssetCatalogManager,
    OnlyQuantAssetLayer,
    OnlyQuantAssetProvider,
    OnlyStrategyAuthoringAsset,
    OnlyStrategyAuthoringResource,
    only_discover_quant_asset_providers,
)


def _generation() -> OnlyQuantAssetCatalogGeneration:
    return only_discover_quant_asset_providers(
        (operator_provider(), indicator_provider(), alpha_provider(), strategy_provider()),
        include_installed=False,
    )


def test_four_layers_form_one_content_addressed_catalog_generation() -> None:
    generation = _generation()
    assert {provider.manifest.layer for provider in generation.providers} == set(OnlyQuantAssetLayer)
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
    strategy = generation.resolve_strategy_asset(
        "example.strategy.library",
        "1",
        "example.strategy.simple_momentum",
        "1",
    )
    payload = json.loads(strategy.resource_bytes("research-definition.json"))
    assert payload["display_metadata"]["name"] == "Simple Momentum Signal"
    descriptor = generation.descriptor()
    assert descriptor["generation_fingerprint"] == generation.generation_fingerprint
    strategy_inventory = next(
        provider
        for provider in descriptor["providers"]
        if provider["manifest"]["provider_id"] == "example.strategy.library"
    )
    assert strategy_inventory["strategies"][0]["semantic_version"] == "1"
    assert len(strategy_inventory["strategies"][0]["resources"][0]["content_sha256"]) == 64


def test_installed_quant_asset_entry_points_discover_all_four_layers() -> None:
    generation = only_discover_quant_asset_providers()
    assert {provider.manifest.layer for provider in generation.providers} >= set(OnlyQuantAssetLayer)
    assert {provider.manifest.provider_id for provider in generation.providers} >= {
        "onlyalpha.operator.library",
        "onlyalpha.indicator.library",
        "example.alpha.library",
        "example.strategy.library",
    }


def test_refresh_is_atomic_and_rejects_same_version_content_drift() -> None:
    initial = _generation()
    manager = OnlyQuantAssetCatalogManager(initial)
    old_snapshot = manager.snapshot()
    strategy = strategy_provider()
    original = strategy.strategy_assets[0]
    changed = OnlyStrategyAuthoringAsset(
        original.asset_id,
        original.semantic_version,
        tuple(
            replace(resource, content=resource.content + b"\n")
            if resource.relative_path == "metadata.json"
            else resource
            for resource in original.resources
        ),
    )
    drifted = OnlyQuantAssetProvider(strategy.manifest, strategy_assets=(changed,))
    candidate = OnlyQuantAssetCatalogGeneration(
        tuple(
            drifted if item.manifest.provider_id == strategy.manifest.provider_id else item
            for item in initial.providers
        )
    )
    with pytest.raises(ValueError, match="CONTENT_DRIFT"):
        manager.refresh(lambda: candidate)
    assert manager.snapshot() is old_snapshot
    assert manager.generation(old_snapshot.generation_fingerprint) is old_snapshot


def test_new_provider_version_switches_only_new_catalog_snapshot() -> None:
    initial = _generation()
    manager = OnlyQuantAssetCatalogManager(initial)
    strategy = strategy_provider()
    version_two = OnlyQuantAssetProvider(
        replace(strategy.manifest, provider_version="2"),
        strategy_assets=(
            replace(
                strategy.strategy_assets[0],
                semantic_version="2",
                resources=strategy.strategy_assets[0].resources
                + (OnlyStrategyAuthoringResource("notes/v2.txt", b"new version"),),
            ),
        ),
    )
    candidate = OnlyQuantAssetCatalogGeneration(
        tuple(
            version_two if item.manifest.provider_id == strategy.manifest.provider_id else item
            for item in initial.providers
        )
    )
    current = manager.refresh(lambda: candidate)
    assert current.generation_fingerprint != initial.generation_fingerprint
    assert manager.snapshot() is current
    assert manager.generation(initial.generation_fingerprint) is initial
    with pytest.raises(KeyError):
        initial.resolve_strategy_asset("example.strategy.library", "2", "example.strategy.simple_momentum", "2")


def test_distribution_rebuild_changes_generation_without_false_content_drift() -> None:
    initial = _generation()
    manager = OnlyQuantAssetCatalogManager(initial)
    strategy = strategy_provider()
    repackaged = replace(
        strategy,
        manifest=replace(strategy.manifest, distribution_version="0.9.10"),
    )
    assert repackaged.content_fingerprint == strategy.content_fingerprint
    candidate = OnlyQuantAssetCatalogGeneration(
        tuple(
            repackaged if item.manifest.provider_id == strategy.manifest.provider_id else item
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
