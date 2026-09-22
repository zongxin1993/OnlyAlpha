"""Trusted local composition root for built-in factories."""

from collections.abc import Callable
from dataclasses import dataclass

from onlyalpha.application.integration_runtime import OnlyIntegrationRuntimeResolver
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.cluster.factory import OnlyClusterFactory
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.data.synthetic.factory import OnlySyntheticDataSourceFactory
from onlyalpha.domain.value import OnlyCurrency
from onlyalpha.fee.basis import only_default_fee_basis_provider_registry
from onlyalpha.fee.broker_contract import OnlyBrokerFeeContractRegistry
from onlyalpha.fee.reconciliation_policy import (
    OnlyFeeReconciliationPolicyRegistry,
    only_standard_fee_reconciliation_policy,
)
from onlyalpha.indicator.registry import OnlyIndicatorFactoryRegistry
from onlyalpha.market.product import OnlyMarketProductFactoryRegistry, OnlyMarketProductResourceResolver
from onlyalpha.plugin.descriptor import OnlyPluginOrigin, OnlyPluginOriginType
from onlyalpha.plugin.discovery import OnlyPluginDiscoveryReport, only_discover_plugins
from onlyalpha.quant_assets import OnlyDistributionProviderSource, OnlyQuantAssetCatalogGeneration
from onlyalpha.research.calculation.predicate import only_register_research_predicate_primitives
from onlyalpha.runtime.assembler import OnlyComponentFactoryRegistries, OnlyEngineRunAssembler
from onlyalpha.runtime.backtest.factory import OnlyBacktestRuntimeFactory
from onlyalpha.runtime.factory import OnlyRuntimeFactoryRegistry
from onlyalpha.runtime.live.factory import OnlyLiveRuntimeFactory
from onlyalpha.runtime.persistence.factory import (
    OnlyDefaultRuntimePersistenceStoreFactory,
    OnlyRuntimePersistenceStoreFactory,
)
from onlyalpha.runtime.research.factory import OnlyResearchRuntimeFactory
from onlyalpha.runtime.sim.factory import OnlySimRuntimeFactory
from onlyalpha.runtime.trading.predicate import only_register_trading_predicate_primitives


@dataclass(frozen=True, slots=True)
class OnlyEngineServices:
    assembler: OnlyEngineRunAssembler
    plugin_discovery: OnlyPluginDiscoveryReport = OnlyPluginDiscoveryReport((), ())


def only_default_engine_services(
    *,
    fail_fast: bool = True,
    runtime_persistence_store_factory: OnlyRuntimePersistenceStoreFactory | None = None,
    market_product_resources: OnlyMarketProductResourceResolver | None = None,
    calculation_catalog_generation: OnlyQuantAssetCatalogGeneration | None = None,
    authoring_generation_fingerprint: str | None = None,
    integration_runtime_resolver: OnlyIntegrationRuntimeResolver | None = None,
    integration_runtime_resolver_factory: (
        Callable[[OnlyDataSourceFactoryRegistry, OnlyBrokerFactoryRegistry], OnlyIntegrationRuntimeResolver] | None
    ) = None,
) -> OnlyEngineServices:
    data_sources = OnlyDataSourceFactoryRegistry()
    builtin = OnlyPluginOrigin(OnlyPluginOriginType.BUILTIN, "onlyalpha")
    data_sources.register(OnlySyntheticDataSourceFactory(), origin=builtin)
    brokers = OnlyBrokerFactoryRegistry()
    broker_contracts = OnlyBrokerFeeContractRegistry()
    market_products = OnlyMarketProductFactoryRegistry()
    calculations = (
        OnlyCalculationRegistry()
        if calculation_catalog_generation is None
        else calculation_catalog_generation.calculation_registry()
    )
    indicators = OnlyIndicatorFactoryRegistry(calculations)
    discovery = only_discover_plugins(
        data_sources,
        brokers,
        broker_contracts,
        market_products,
        calculations,
        fail_fast=fail_fast,
        excluded_calculation_distributions=(
            frozenset()
            if calculation_catalog_generation is None
            else frozenset(
                provider.manifest.source.distribution_name
                for provider in calculation_catalog_generation.providers
                if isinstance(provider.manifest.source, OnlyDistributionProviderSource)
            )
        ),
    )
    only_register_research_predicate_primitives(calculations)
    only_register_trading_predicate_primitives(calculations)
    if integration_runtime_resolver is not None and integration_runtime_resolver_factory is not None:
        raise ValueError("INTEGRATION_RUNTIME_COMPOSITION_CONFLICT")
    resolver = integration_runtime_resolver
    if resolver is None and integration_runtime_resolver_factory is not None:
        resolver = integration_runtime_resolver_factory(data_sources, brokers)
    clusters = OnlyClusterFactory(
        calculations,
        indicators,
    )
    runtimes = OnlyRuntimeFactoryRegistry()
    runtimes.register(OnlyBacktestRuntimeFactory())
    runtimes.register(OnlySimRuntimeFactory())
    runtimes.register(OnlyLiveRuntimeFactory())
    runtimes.register(OnlyResearchRuntimeFactory())
    reconciliation_policies = OnlyFeeReconciliationPolicyRegistry()
    reconciliation_policies.register(only_standard_fee_reconciliation_policy(OnlyCurrency("CNY", 2)))
    assembler = OnlyEngineRunAssembler(
        runtimes,
        OnlyComponentFactoryRegistries(
            calculations,
            data_sources,
            brokers,
            market_products,
            clusters,
            broker_contracts,
            only_default_fee_basis_provider_registry(),
            reconciliation_policies,
            runtime_persistence_store_factory or OnlyDefaultRuntimePersistenceStoreFactory(),
            market_product_resources,
            authoring_generation_fingerprint,
            resolver,
        ),
    )
    return OnlyEngineServices(assembler, discovery)
