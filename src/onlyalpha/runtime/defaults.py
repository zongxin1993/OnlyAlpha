"""Trusted local composition root for built-in factories."""

from onlyalpha.application.run import OnlyEngineRunService
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.broker.virtual.factory import OnlyVirtualBrokerFactory
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.data.synthetic.factory import OnlySyntheticDataSourceFactory
from onlyalpha.output import OnlyRuntimeResultExporter
from onlyalpha.runtime.assembler import OnlyComponentFactoryRegistries, OnlyEngineRunAssembler
from onlyalpha.runtime.backtest.factory import OnlyBacktestRuntimeFactory
from onlyalpha.runtime.factory import OnlyRuntimeFactoryRegistry
from onlyalpha.runtime.live.factory import OnlyLiveRuntimeFactory
from onlyalpha.runtime.paper.factory import OnlyPaperRuntimeFactory
from onlyalpha.runtime.research.factory import OnlyResearchRuntimeFactory
from onlyalpha.runtime.shadow.factory import OnlyShadowRuntimeFactory
from onlyalpha.strategy.factory import OnlyStrategyFactoryRegistry
from onlyalpha.strategy.macd import OnlyMacdStrategyFactory


def only_default_run_service() -> OnlyEngineRunService:
    data_sources = OnlyDataSourceFactoryRegistry()
    data_sources.register(OnlySyntheticDataSourceFactory())
    brokers = OnlyBrokerFactoryRegistry()
    brokers.register(OnlyVirtualBrokerFactory())
    strategies = OnlyStrategyFactoryRegistry()
    strategies.register(OnlyMacdStrategyFactory())
    runtimes = OnlyRuntimeFactoryRegistry()
    runtimes.register(OnlyBacktestRuntimeFactory())
    runtimes.register(OnlyPaperRuntimeFactory())
    runtimes.register(OnlyLiveRuntimeFactory())
    runtimes.register(OnlyShadowRuntimeFactory())
    runtimes.register(OnlyResearchRuntimeFactory())
    assembler = OnlyEngineRunAssembler(
        runtimes,
        OnlyComponentFactoryRegistries(data_sources, brokers, strategies),
    )
    return OnlyEngineRunService(assembler, OnlyRuntimeResultExporter())
