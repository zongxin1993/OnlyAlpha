"""Trusted local composition root for built-in factories."""

from dataclasses import dataclass, field

from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.cluster.factory import OnlyClusterFactory
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.data.synthetic.factory import OnlySyntheticDataSourceFactory
from onlyalpha.factor.factory import OnlyFactorFactory
from onlyalpha.fee.basis import only_default_fee_basis_provider_registry
from onlyalpha.fee.broker_contract import OnlyBrokerFeeContractRegistry
from onlyalpha.fee.market_pack import OnlyMarketFeePackRegistry
from onlyalpha.fee.packs import (
    only_cn_a_share_conformance_fee_pack,
    only_generic_crypto_spot_fee_pack,
    only_generic_margin_futures_fee_pack,
    only_generic_t0_cash_fee_pack,
)
from onlyalpha.indicator import only_default_indicator_factories
from onlyalpha.market.profiles import only_builtin_market_profile_registry
from onlyalpha.market.runtime_rules import OnlyMarketRuleCompiler
from onlyalpha.plugin.descriptor import OnlyPluginOrigin, OnlyPluginOriginType
from onlyalpha.plugin.discovery import OnlyPluginDiscoveryReport, only_discover_plugins
from onlyalpha.runtime.assembler import OnlyComponentFactoryRegistries, OnlyEngineRunAssembler
from onlyalpha.runtime.backtest.factory import OnlyBacktestRuntimeFactory
from onlyalpha.runtime.factory import OnlyRuntimeFactoryRegistry
from onlyalpha.runtime.live.factory import OnlyLiveRuntimeFactory
from onlyalpha.runtime.paper.factory import OnlyPaperRuntimeFactory
from onlyalpha.runtime.persistence.factory import (
    OnlyDefaultRuntimePersistenceStoreFactory,
    OnlyRuntimePersistenceStoreFactory,
)
from onlyalpha.runtime.research.factory import OnlyResearchRuntimeFactory
from onlyalpha.runtime.shadow.factory import OnlyShadowRuntimeFactory
from onlyalpha.scenario.data_source import OnlyScenarioDataSourceFactory
from onlyalpha.strategy.factory import OnlyStrategyFactory


@dataclass(frozen=True, slots=True)
class OnlyEngineServices:
    assembler: OnlyEngineRunAssembler
    data_sources: OnlyDataSourceFactoryRegistry = field(default_factory=OnlyDataSourceFactoryRegistry)
    brokers: OnlyBrokerFactoryRegistry = field(default_factory=OnlyBrokerFactoryRegistry)
    market_fee_packs: OnlyMarketFeePackRegistry = field(default_factory=OnlyMarketFeePackRegistry)
    broker_fee_contracts: OnlyBrokerFeeContractRegistry = field(default_factory=OnlyBrokerFeeContractRegistry)
    plugin_discovery: OnlyPluginDiscoveryReport = field(default_factory=lambda: OnlyPluginDiscoveryReport((), ()))


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
    discovery = only_discover_plugins(data_sources, brokers, broker_contracts, fail_fast=fail_fast)
    clusters = OnlyClusterFactory(
        OnlyStrategyFactory(),
        OnlyFactorFactory(),
        only_default_indicator_factories(),
    )
    runtimes = OnlyRuntimeFactoryRegistry()
    runtimes.register(OnlyBacktestRuntimeFactory())
    runtimes.register(OnlyPaperRuntimeFactory())
    runtimes.register(OnlyLiveRuntimeFactory())
    runtimes.register(OnlyShadowRuntimeFactory())
    runtimes.register(OnlyResearchRuntimeFactory())
    fee_packs = OnlyMarketFeePackRegistry()
    for pack in (
        only_generic_t0_cash_fee_pack(),
        only_generic_margin_futures_fee_pack(),
        only_generic_crypto_spot_fee_pack(),
        only_cn_a_share_conformance_fee_pack(),
    ):
        fee_packs.register(pack)
    assembler = OnlyEngineRunAssembler(
        runtimes,
        OnlyComponentFactoryRegistries(
            data_sources,
            brokers,
            clusters,
            only_builtin_market_profile_registry(),
            OnlyMarketRuleCompiler(),
            fee_packs,
            broker_contracts,
            only_default_fee_basis_provider_registry(),
            runtime_persistence_store_factory or OnlyDefaultRuntimePersistenceStoreFactory(),
        ),
    )
    return OnlyEngineServices(assembler, data_sources, brokers, fee_packs, broker_contracts, discovery)
