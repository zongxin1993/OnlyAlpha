"""Shared Product semantic registry composition used by HTTP startup and certification."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.application.chart_study_numeric import OnlyChartStudySmaInvocation
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.fee.broker_contract import OnlyBrokerFeeContractRegistry
from onlyalpha.market.product import OnlyMarketProductFactoryRegistry
from onlyalpha.plugin.discovery import only_discover_plugins
from onlyalpha.quant_assets.catalog import OnlyQuantAssetCatalogGeneration, only_discover_quant_asset_providers
from onlyalpha.research.calculation.predicate import only_register_research_predicate_primitives


@dataclass(frozen=True, slots=True)
class OnlyProductCalculationComposition:
    registry: OnlyCalculationRegistry
    catalog: OnlyQuantAssetCatalogGeneration
    chart_study: OnlyChartStudySmaInvocation | None
    chart_study_unavailable: str | None


def only_configure_product_registries(
    calculations: OnlyCalculationRegistry,
    data_sources: OnlyDataSourceFactoryRegistry,
    brokers: OnlyBrokerFactoryRegistry,
    broker_fees: OnlyBrokerFeeContractRegistry,
    market_products: OnlyMarketProductFactoryRegistry,
) -> OnlyProductCalculationComposition:
    catalog = only_discover_quant_asset_providers()
    for provider in catalog.providers:
        for registration in provider.calculation_registrations:
            calculations.register(registration)
    only_discover_plugins(
        data_sources,
        brokers,
        broker_fees,
        market_products,
        calculations,
        fail_fast=True,
        excluded_calculation_distributions=frozenset(
            provider.manifest.distribution_name for provider in catalog.providers
        ),
    )
    only_register_research_predicate_primitives(calculations)
    try:
        invocation = OnlyChartStudySmaInvocation(calculations, catalog)
    except ValueError as error:
        return OnlyProductCalculationComposition(calculations, catalog, None, str(error))
    return OnlyProductCalculationComposition(calculations, catalog, invocation, None)


__all__ = ["OnlyProductCalculationComposition", "only_configure_product_registries"]
