"""Trusted local composition root for built-in factories."""

from dataclasses import dataclass, field

from onlyalpha.application.run import OnlyEngineRunService
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.broker.virtual.factory import OnlyVirtualBrokerFactory
from onlyalpha.cluster.factory import OnlyClusterFactory
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.data.synthetic.factory import OnlySyntheticDataSourceFactory
from onlyalpha.factor.factory import OnlyFactorFactory
from onlyalpha.indicator import only_default_indicator_factories
from onlyalpha.output import OnlyRuntimeResultExporter
from onlyalpha.plugin.descriptor import OnlyPluginOrigin, OnlyPluginOriginType
from onlyalpha.plugin.discovery import OnlyPluginDiscoveryReport, only_discover_plugins
from onlyalpha.runtime.assembler import OnlyComponentFactoryRegistries, OnlyEngineRunAssembler
from onlyalpha.runtime.backtest.factory import OnlyBacktestRuntimeFactory
from onlyalpha.runtime.factory import OnlyRuntimeFactoryRegistry
from onlyalpha.runtime.live.factory import OnlyLiveRuntimeFactory
from onlyalpha.runtime.paper.factory import OnlyPaperRuntimeFactory
from onlyalpha.runtime.research.factory import OnlyResearchRuntimeFactory
from onlyalpha.runtime.shadow.factory import OnlyShadowRuntimeFactory
from onlyalpha.strategy.factory import OnlyStrategyFactory


@dataclass(frozen=True, slots=True)
class OnlyEngineServices:
    assembler: OnlyEngineRunAssembler
    data_sources: OnlyDataSourceFactoryRegistry = field(default_factory=OnlyDataSourceFactoryRegistry)
    brokers: OnlyBrokerFactoryRegistry = field(default_factory=OnlyBrokerFactoryRegistry)
    plugin_discovery: OnlyPluginDiscoveryReport = field(default_factory=lambda: OnlyPluginDiscoveryReport((), ()))


def only_default_engine_services(*, fail_fast: bool = True) -> OnlyEngineServices:
    data_sources = OnlyDataSourceFactoryRegistry()
    builtin = OnlyPluginOrigin(OnlyPluginOriginType.BUILTIN, "onlyalpha")
    data_sources.register(OnlySyntheticDataSourceFactory(), origin=builtin)
    brokers = OnlyBrokerFactoryRegistry()
    brokers.register(OnlyVirtualBrokerFactory(), origin=builtin)
    discovery = only_discover_plugins(data_sources, brokers, fail_fast=fail_fast)
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
    assembler = OnlyEngineRunAssembler(
        runtimes,
        OnlyComponentFactoryRegistries(data_sources, brokers, clusters),
    )
    return OnlyEngineServices(assembler, data_sources, brokers, discovery)


def only_default_run_service() -> OnlyEngineRunService:
    """Deprecated compatibility entry for legacy Runtime-level tests."""

    return OnlyEngineRunService(only_default_engine_services().assembler, OnlyRuntimeResultExporter())
