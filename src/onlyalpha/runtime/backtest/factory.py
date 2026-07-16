"""Backtest Runtime factory; all Backtest-specific orchestration stays here."""

from __future__ import annotations

from onlyalpha.broker.factory import OnlyBrokerBuildRequest
from onlyalpha.data.factory import OnlyDataSourceBuildRequest
from onlyalpha.data.models import OnlyHistoricalBarRequest, OnlyHistoricalDataRange
from onlyalpha.domain.enums import OnlyRuntimeMode
from onlyalpha.runtime.assembler import OnlyComponentFactoryRegistries
from onlyalpha.runtime.backtest.config import OnlyBacktestRuntimeExtensionConfig
from onlyalpha.runtime.backtest.run_plan import OnlyBacktestRunPlan
from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime
from onlyalpha.runtime.factory import OnlyRuntimeBuildRequest, OnlyRuntimeBuildResult
from onlyalpha.runtime.runtime import OnlyRuntimeAssemblyConfig
from onlyalpha.strategies.macd import OnlyMacdExampleCluster
from onlyalpha.strategy.factory import OnlyStrategyBuildRequest


class OnlyBacktestRuntimeFactory:
    @property
    def runtime_type(self) -> str:
        return "BACKTEST"

    def create(self, request: OnlyRuntimeBuildRequest) -> OnlyRuntimeBuildResult:
        config = request.config
        OnlyBacktestRuntimeExtensionConfig.from_mapping(config.runtime.extensions)
        if config.start_time is None or config.end_time is None:
            return OnlyRuntimeBuildResult(
                failure_code="INVALID_RUNTIME_CONFIG",
                failure_message="BACKTEST requires runtime.start_time and runtime.end_time",
            )
        components = request.components
        if not isinstance(components, OnlyComponentFactoryRegistries):
            raise TypeError("Backtest factory requires OnlyComponentFactoryRegistries")
        if len(config.accounts) != 1 or len(config.brokers) != 1 or len(config.data_sources) != 1:
            raise ValueError("first-phase Backtest requires one Account, Broker and DataSource")
        account = config.accounts[0]
        broker_common = config.brokers[0]
        broker = components.brokers.require(broker_common.gateway_type).create(
            OnlyBrokerBuildRequest(broker_common, account, config)
        )
        strategy_results = tuple(
            components.strategies.require(item.factory_id).create(OnlyStrategyBuildRequest(item, config))
            for item in config.strategies
            if item.common.enabled
        )
        source_common = config.data_sources[0]
        source = components.data_sources.require(source_common.source_type).create(
            OnlyDataSourceBuildRequest(source_common, config, config.runtime.runtime_id)
        )
        bar_types = frozenset(
            result.cluster.strategy_config.primary_bar_type
            for result in strategy_results
            if isinstance(result.cluster, OnlyMacdExampleCluster)
        )
        instrument_ids = frozenset(item.instrument_id for item in bar_types)
        request_model = OnlyHistoricalBarRequest(
            f"{config.runtime_id}-historical-bars",
            instrument_ids,
            bar_types,
            OnlyHistoricalDataRange(config.start_time, config.end_time),
            source_common.data_version,
            batch_size=source_common.batch_size,
        )
        strategy = strategy_results[0].cluster
        if not isinstance(strategy, OnlyMacdExampleCluster):
            raise ValueError("first-phase Backtest result builder requires MACD example strategy")
        plan = OnlyBacktestRunPlan(config, source, request_model, strategy)
        calendar = config.reference_data.calendars[0]
        runtime = OnlyBacktestRuntime(
            OnlyRuntimeAssemblyConfig(
                config.engine_id,
                config.runtime_id,
                OnlyRuntimeMode.BACKTEST,
                default_account_id=account.account_id,
                strategy_initial_capital=account.initial_cash.amount,
                strategy_base_currency=config.runtime.base_currency,
                virtual_broker_config=broker,
            ),
            calendar,
            config.start_time,
            run_plan=plan,
        )
        for instrument in config.reference_data.instruments:
            runtime.register_instrument(instrument)
        for result in strategy_results:
            for indicator in result.indicators:
                runtime.register_indicator(indicator)
            runtime.add_cluster(config.engine_id, result.cluster)
        return OnlyRuntimeBuildResult(runtime=runtime)
