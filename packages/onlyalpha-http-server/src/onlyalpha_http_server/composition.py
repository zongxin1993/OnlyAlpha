"""Shared Product semantic registry composition used by HTTP startup and certification."""

from __future__ import annotations

from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.fee.broker_contract import OnlyBrokerFeeContractRegistry
from onlyalpha.market.product import OnlyMarketProductFactoryRegistry
from onlyalpha.plugin.discovery import only_discover_plugins
from onlyalpha.research.calculation.predicate import only_register_research_predicate_primitives


def only_configure_product_registries(
    calculations: OnlyCalculationRegistry,
    data_sources: OnlyDataSourceFactoryRegistry,
    brokers: OnlyBrokerFactoryRegistry,
    broker_fees: OnlyBrokerFeeContractRegistry,
    market_products: OnlyMarketProductFactoryRegistry,
) -> None:
    only_discover_plugins(
        data_sources,
        brokers,
        broker_fees,
        market_products,
        calculations,
        fail_fast=True,
    )
    only_register_research_predicate_primitives(calculations)


__all__ = ["only_configure_product_registries"]
