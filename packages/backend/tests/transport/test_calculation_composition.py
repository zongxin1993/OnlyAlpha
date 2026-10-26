"""Historical installed-object reference composition; no native Product admission."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.calculation.definition import OnlyCalculationKind
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.fee.broker_contract import OnlyBrokerFeeContractRegistry
from onlyalpha.market.product import OnlyMarketProductFactoryRegistry
from onlyalpha.plugin.discovery import OnlyPluginDiscoveryReport, only_discover_plugins
from onlyalpha.quant_assets.catalog import OnlyQuantAssetCatalogGeneration, only_discover_quant_asset_providers
from tests.support import calculation_reference_composition as composition


def configure() -> composition.OnlyProductCalculationComposition:
    return composition.only_configure_product_registries(
        OnlyCalculationRegistry(),
        OnlyDataSourceFactoryRegistry(),
        OnlyBrokerFactoryRegistry(),
        OnlyBrokerFeeContractRegistry(),
        OnlyMarketProductFactoryRegistry(),
    )


def test_installed_discovery_is_once_and_catalog_registrations_are_actual_product_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[OnlyQuantAssetCatalogGeneration] = []
    discover = only_discover_quant_asset_providers
    plugins = only_discover_plugins

    def captured_discovery() -> OnlyQuantAssetCatalogGeneration:
        catalog = discover()
        calls.append(catalog)
        return catalog

    def captured_plugins(*args: Any, **kwargs: Any) -> OnlyPluginDiscoveryReport:
        assert kwargs["excluded_calculation_distributions"] == frozenset(
            provider.manifest.distribution_name for provider in calls[0].providers
        )
        return plugins(*args, **kwargs)

    monkeypatch.setattr(composition, "only_discover_quant_asset_providers", captured_discovery)
    monkeypatch.setattr(composition, "only_discover_plugins", captured_plugins)
    result = configure()
    assert len(calls) == 1
    assert result.catalog is calls[0]
    assert result.chart_study_unavailable is None
    assert result.chart_study is not None
    assert result.chart_study.admissions
    assert all(admission.catalog is result.catalog for admission in result.chart_study.admissions)
    assert result.chart_study._registry is result.registry
    for provider in result.catalog.providers:
        for registration in provider.calculation_registrations:
            definition = registration.type_definition
            assert (
                result.registry.resolve(
                    definition.kind, definition.type_id, definition.semantic_version, registration.backend
                )
                is registration
            )
    assert any(
        item.type_definition.kind is OnlyCalculationKind.PREDICATE for item in result.registry.backend_registrations()
    )
    assert all(
        item.type_definition.kind is not OnlyCalculationKind.PREDICATE
        for provider in result.catalog.providers
        for item in provider.calculation_registrations
    )


def test_detached_description_catalog_never_becomes_installed_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    actual = only_discover_quant_asset_providers()
    detached = replace(actual)
    assert detached.generation_fingerprint == actual.generation_fingerprint
    assert detached._installed_origins == ()
    monkeypatch.setattr(composition, "only_discover_quant_asset_providers", lambda: detached)
    result = configure()
    assert result.chart_study is None
    assert result.chart_study_unavailable == "CHART_STUDY_UNAVAILABLE"
    assert result.registry.backend_registrations()


def test_discovery_failure_issues_no_partial_composition(monkeypatch: pytest.MonkeyPatch) -> None:
    emitted: list[composition.OnlyProductCalculationComposition] = []

    def failed() -> OnlyQuantAssetCatalogGeneration:
        raise ValueError("injected missing installed Provider")

    monkeypatch.setattr(composition, "only_discover_quant_asset_providers", failed)
    with pytest.raises(ValueError, match="injected missing"):
        emitted.append(configure())
    assert emitted == []


def test_catalog_duplicate_provider_versions_and_registration_owners_are_rejected() -> None:
    actual = only_discover_quant_asset_providers()
    provider = actual.providers[0]
    with pytest.raises(ValueError, match="QUANT_ASSET_PROVIDER_VERSION_DUPLICATE"):
        OnlyQuantAssetCatalogGeneration((provider, provider))
    with pytest.raises(ValueError, match="duplicate calculation backend"):
        OnlyQuantAssetCatalogGeneration(
            (provider, replace(provider, manifest=replace(provider.manifest, provider_version="999")))
        )
