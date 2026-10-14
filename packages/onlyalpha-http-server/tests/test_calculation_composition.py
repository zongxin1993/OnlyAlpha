"""Real installed objects retained by the Product startup composition."""

from __future__ import annotations

from dataclasses import replace

import pytest
from onlyalpha_http_server import composition

from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.calculation.definition import OnlyCalculationKind
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.fee.broker_contract import OnlyBrokerFeeContractRegistry
from onlyalpha.market.product import OnlyMarketProductFactoryRegistry
from onlyalpha.quant_assets.catalog import OnlyQuantAssetCatalogGeneration


def configure():
    return composition.only_configure_product_registries(
        OnlyCalculationRegistry(),
        OnlyDataSourceFactoryRegistry(),
        OnlyBrokerFactoryRegistry(),
        OnlyBrokerFeeContractRegistry(),
        OnlyMarketProductFactoryRegistry(),
    )


def test_installed_discovery_is_once_and_catalog_registrations_are_actual_product_objects(monkeypatch):
    calls = []
    discover = composition.only_discover_quant_asset_providers
    plugins = composition.only_discover_plugins

    def captured_discovery():
        catalog = discover()
        calls.append(catalog)
        return catalog

    def captured_plugins(*args, **kwargs):
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
    assert result.chart_study.admission.catalog is result.catalog
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


def test_detached_description_catalog_never_becomes_installed_capability(monkeypatch):
    actual = composition.only_discover_quant_asset_providers()
    detached = replace(actual)
    assert detached.generation_fingerprint == actual.generation_fingerprint
    assert detached._installed_origins == ()
    monkeypatch.setattr(composition, "only_discover_quant_asset_providers", lambda: detached)
    result = configure()
    assert result.chart_study is None
    assert result.chart_study_unavailable == "CHART_STUDY_UNAVAILABLE"
    assert result.registry.backend_registrations()


def test_discovery_failure_issues_no_partial_composition(monkeypatch):
    emitted = []

    def failed():
        raise ValueError("injected missing installed Provider")

    monkeypatch.setattr(composition, "only_discover_quant_asset_providers", failed)
    with pytest.raises(ValueError, match="injected missing"):
        emitted.append(configure())
    assert emitted == []


def test_catalog_duplicate_provider_versions_and_registration_owners_are_rejected():
    actual = composition.only_discover_quant_asset_providers()
    provider = actual.providers[0]
    with pytest.raises(ValueError, match="QUANT_ASSET_PROVIDER_VERSION_DUPLICATE"):
        OnlyQuantAssetCatalogGeneration((provider, provider))
    with pytest.raises(ValueError, match="duplicate calculation backend"):
        OnlyQuantAssetCatalogGeneration(
            (provider, replace(provider, manifest=replace(provider.manifest, provider_version="999")))
        )
