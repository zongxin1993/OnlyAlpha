"""Trusted local composition root for built-in factories."""

from dataclasses import dataclass

from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.cluster.factory import OnlyClusterFactory
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.data.synthetic.factory import OnlySyntheticDataSourceFactory
from onlyalpha.domain.value import OnlyCurrency
from onlyalpha.factor.factory import OnlyFactorFactory
from onlyalpha.fee.basis import only_default_fee_basis_provider_registry
from onlyalpha.fee.broker_contract import OnlyBrokerFeeContractRegistry
from onlyalpha.fee.reconciliation_policy import (
    OnlyFeeReconciliationPolicyRegistry,
    only_standard_fee_reconciliation_policy,
)
from onlyalpha.indicator import only_default_indicator_factories
from onlyalpha.market.product import OnlyMarketProductFactoryRegistry
from onlyalpha.plugin.descriptor import OnlyPluginOrigin, OnlyPluginOriginType
from onlyalpha.plugin.discovery import OnlyPluginDiscoveryReport, only_discover_plugins
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
from onlyalpha.scenario.data_source import OnlyScenarioDataSourceFactory
from onlyalpha.strategy.factory import OnlyStrategyFactory


@dataclass(frozen=True, slots=True)
class OnlyEngineServices:
    assembler: OnlyEngineRunAssembler
    plugin_discovery: OnlyPluginDiscoveryReport = OnlyPluginDiscoveryReport((), ())


def only_default_engine_services(
    *,
    fail_fast: bool = True,
    runtime_persistence_store_factory: OnlyRuntimePersistenceStoreFactory | None = None,
) -> OnlyEngineServices:
    data_sources = OnlyDataSourceFactoryRegistry()
    builtin = OnlyPluginOrigin(OnlyPluginOriginType.BUILTIN, "onlyalpha")
    data_sources.register(OnlySyntheticDataSourceFactory(), origin=builtin)
    data_sources.register(OnlyScenarioDataSourceFactory(), origin=builtin)
    brokers = OnlyBrokerFactoryRegistry()
    broker_contracts = OnlyBrokerFeeContractRegistry()
    market_products = OnlyMarketProductFactoryRegistry()
    discovery = only_discover_plugins(
        data_sources,
        brokers,
        broker_contracts,
        market_products,
        fail_fast=fail_fast,
    )
    clusters = OnlyClusterFactory(
        OnlyStrategyFactory(),
        OnlyFactorFactory(),
        only_default_indicator_factories(),
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
            data_sources,
            brokers,
            market_products,
            clusters,
            broker_contracts,
            only_default_fee_basis_provider_registry(),
            reconciliation_policies,
            runtime_persistence_store_factory or OnlyDefaultRuntimePersistenceStoreFactory(),
        ),
    )
    return OnlyEngineServices(assembler, discovery)
