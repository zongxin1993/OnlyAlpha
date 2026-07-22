"""Backtest Runtime assembly through DataSource and Broker plugin SPI."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from onlyalpha.broker.inbound import OnlyBoundedBrokerInboundQueue
from onlyalpha.broker.ports import OnlyBrokerGateway
from onlyalpha.cache.historical import OnlyHistoricalCacheService, OnlyParquetHistoricalCacheStore
from onlyalpha.config import OnlyRuntimeAssemblyPlan
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.data.models import OnlyHistoricalBarRequest, OnlyHistoricalDataRange
from onlyalpha.domain.enums import OnlyRuntimeMode
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.event.model import OnlyEventScope
from onlyalpha.fee.models import OnlyBrokerFeeReportingMode, OnlyFeeConfigurationMode
from onlyalpha.fee.resolver import OnlyFeeResolverConfig
from onlyalpha.market.runtime_rules import OnlyMarketRuleEngine, only_instrument_reference
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.plugin.broker import OnlyBrokerComponent, OnlyBrokerCreateRequest, OnlyBrokerGatewayFactory
from onlyalpha.plugin.capabilities import (
    OnlyBrokerPluginCapabilities,
    OnlyDataSourceCapabilities,
    OnlyPluginValidationIssue,
)
from onlyalpha.plugin.data_source import OnlyDataSource, OnlyDataSourceCreateRequest, OnlyDataSourceFactory
from onlyalpha.plugin.errors import OnlyPluginError
from onlyalpha.plugin.lifecycle import OnlyPluginResource
from onlyalpha.runtime.assembler import OnlyComponentFactoryRegistries
from onlyalpha.runtime.backtest.config import OnlyBacktestRuntimeExtensionConfig
from onlyalpha.runtime.backtest.run_plan import OnlyBacktestRunPlan
from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime
from onlyalpha.runtime.factory import OnlyRuntimeBuildRequest, OnlyRuntimeBuildResult
from onlyalpha.runtime.runtime import OnlyRuntimeAssemblyConfig

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _OnlyBacktestPluginPlan:
    runtime_config: OnlyRuntimeAssemblyConfig
    clock: OnlyBacktestClock
    event_bus: OnlyEventBus
    broker_queue: OnlyBoundedBrokerInboundQueue
    data_factory: OnlyDataSourceFactory
    data_request: OnlyDataSourceCreateRequest
    broker_factory: OnlyBrokerGatewayFactory
    broker_request: OnlyBrokerCreateRequest


class OnlyBacktestRuntimeFactory:
    @property
    def runtime_type(self) -> str:
        return "BACKTEST"

    def validate(self, request: OnlyRuntimeBuildRequest) -> OnlyRuntimeBuildResult:
        try:
            plan = self._plugin_plan(request)
            plan.clock.close()
            plan.event_bus.close()
        except Exception as exc:
            return self._failure(exc)
        return OnlyRuntimeBuildResult()

    def create(self, request: OnlyRuntimeBuildRequest) -> OnlyRuntimeBuildResult:
        try:
            plan = self._plugin_plan(request)
        except Exception as exc:
            return self._failure(exc)
        components = request.components
        if not isinstance(components, OnlyComponentFactoryRegistries):
            return OnlyRuntimeBuildResult(
                failure_code="RUNTIME_ASSEMBLY_FAILED",
                failure_message="Backtest factory requires OnlyComponentFactoryRegistries",
            )
        source: OnlyDataSource | None = None
        gateway: OnlyBrokerGateway | None = None
        broker_resource: OnlyPluginResource | None = None
        try:
            try:
                source = plan.data_factory.create(plan.data_request)
            except Exception as exc:
                raise OnlyPluginError(
                    "PLUGIN_CREATE_FAILED",
                    str(exc),
                    plugin_id=plan.data_factory.descriptor.plugin_id,
                    resource_id=str(plan.data_request.source_id),
                ) from exc
            try:
                broker_component: OnlyBrokerComponent = plan.broker_factory.create(plan.broker_request)
                gateway = broker_component.gateway
                broker_resource = broker_component.resource
                if broker_component.deterministic_driver is None:
                    raise ValueError("simulated_execution Broker must provide a deterministic driver")
            except Exception as exc:
                raise OnlyPluginError(
                    "PLUGIN_CREATE_FAILED",
                    str(exc),
                    plugin_id=plan.broker_factory.descriptor.plugin_id,
                    resource_id=str(plan.broker_request.gateway_id),
                ) from exc
            config = request.config
            clusters = tuple(components.clusters.create(item, config) for item in config.clusters if item.enabled)
            if not clusters:
                raise ValueError("product Backtest requires at least one enabled Cluster")
            bar_types = frozenset(
                bar_type
                for cluster in clusters
                if cluster.config.subscription is not None
                for bar_type in cluster.config.subscription.bar_types
            )
            source_common = next(item for item in config.data_sources if item.enabled)
            request_model = OnlyHistoricalBarRequest(
                f"{config.runtime_id}-historical-bars",
                frozenset(item.instrument_id for item in bar_types),
                bar_types,
                OnlyHistoricalDataRange(config.start_time, config.end_time),  # type: ignore[arg-type]
                source_common.data_version,
                batch_size=source_common.batch_size,
            )
            run_plan = OnlyBacktestRunPlan(config, source, request_model, clusters)
            runtime = OnlyBacktestRuntime(
                plan.runtime_config,
                config.reference_data.calendars[0],
                config.start_time,
                run_plan=run_plan,
                owned_clock=plan.clock,
                owned_event_bus=plan.event_bus,
                broker_gateway=gateway,
                deterministic_broker_driver=broker_component.deterministic_driver,
                broker_inbound_queue=plan.broker_queue,
                plugin_resources=(source, broker_resource),
            )
            for instrument in config.reference_data.instruments:
                runtime.register_instrument(instrument)
            for cluster in clusters:
                runtime.add_cluster(config.engine_id, cluster)
            return OnlyRuntimeBuildResult(runtime=runtime)
        except Exception as exc:
            if broker_resource is not None:
                broker_resource.stop()
                broker_resource.close()
            if source is not None:
                source.stop()
                source.close()
            plan.event_bus.close()
            plan.clock.close()
            return self._failure(exc)

    def _plugin_plan(self, request: OnlyRuntimeBuildRequest) -> _OnlyBacktestPluginPlan:
        config = request.config
        OnlyBacktestRuntimeExtensionConfig.from_mapping(config.runtime.extensions)
        if config.start_time is None or config.end_time is None:
            raise ValueError("BACKTEST requires runtime.start_time and runtime.end_time")
        components = request.components
        if not isinstance(components, OnlyComponentFactoryRegistries):
            raise TypeError("Backtest factory requires OnlyComponentFactoryRegistries")
        sources = tuple(item for item in config.data_sources if item.enabled)
        brokers = tuple(item for item in config.brokers if item.enabled)
        if len(config.accounts) != 1 or len(brokers) != 1 or len(sources) != 1:
            raise ValueError("first-phase Backtest requires one enabled Account, Broker and DataSource")
        account = config.accounts[0]
        broker_common = brokers[0]
        source_common = sources[0]
        calendar = config.reference_data.calendars[0]

        def advance_trading_day(day: OnlyTradingDay, lag: int) -> OnlyTradingDay:
            from datetime import timedelta

            candidate = day.value
            remaining = lag
            while remaining > 0:
                candidate += timedelta(days=1)
                if calendar.is_trading_day(candidate):
                    remaining -= 1
            return OnlyTradingDay(candidate)

        references = {
            str(instrument.instrument_id): only_instrument_reference(
                instrument,
                profile_id=config.market.profile.value,
                board=(
                    None
                    if config.reference_data.instrument_attributes.get(str(instrument.instrument_id), {}).get("board")
                    is None
                    else str(config.reference_data.instrument_attributes[str(instrument.instrument_id)]["board"])
                ),
                st_status=bool(
                    config.reference_data.instrument_attributes.get(str(instrument.instrument_id), {}).get(
                        "st_status", False
                    )
                ),
            )
            for instrument in config.reference_data.instruments
        }
        market_rule_engine = OnlyMarketRuleEngine(
            registry=components.market_profiles,
            compiler=components.market_rule_compiler,
            request=config.market.to_request(),
            runtime_mode=OnlyRuntimeMode.BACKTEST,
            references=references,
            advance_trading_day=advance_trading_day,
        )
        fee_resolver_config = OnlyFeeResolverConfig(
            market_mode=config.market.fees.mode,
            market_schedule_id=config.market.fees.schedule_id,
            broker_mode=broker_common.fees.mode,
            broker_schedule_id=broker_common.fees.schedule_id,
            broker_id=str(broker_common.gateway_id),
            broker_reporting_mode=broker_common.fees.reporting_mode or OnlyBrokerFeeReportingMode.NONE,
        )
        self._validate_fee_schedules(
            config,
            components,
            market_rule_engine,
            fee_resolver_config,
            calendar.trading_day_at(OnlyTimestamp.from_datetime(config.start_time)),
        )
        runtime_config = OnlyRuntimeAssemblyConfig(
            config.engine_id,
            config.runtime_id,
            OnlyRuntimeMode.BACKTEST,
            default_account_id=account.account_id,
            strategy_initial_capital=account.initial_cash.amount,
            strategy_base_currency=config.runtime.base_currency,
            broker_gateway_id=broker_common.gateway_id,
            account_initial_cash=account.initial_cash,
            market_rule_engine=market_rule_engine,
            fee_resolver_config=fee_resolver_config,
            market_fee_schedules=components.market_fee_schedules,
            broker_fee_schedules=components.broker_fee_schedules,
        )
        clock = OnlyBacktestClock(config.start_time)
        event_bus = OnlyEventBus(
            runtime_config.event_capacity,
            scope=OnlyEventScope(config.engine_id, config.runtime_id),
            queue_policy=runtime_config.event_queue_policy,
        )
        queue = OnlyBoundedBrokerInboundQueue(runtime_config.event_capacity)
        bar_types = self._configured_bar_types(config)
        data_factory = components.data_sources.resolve(source_common.plugin_id)
        data_plugin_config = data_factory.parse_config(source_common.extensions)
        data_request = OnlyDataSourceCreateRequest(
            source_common.source_id,
            data_plugin_config,
            config.runtime.runtime_type,
            OnlyDataSourceCapabilities(historical_bars=True),
            clock,
            event_bus,
            config.reference_data.instrument_by_id,
            bar_types,
            config.reference_data.calendar_by_id,
            config.universes,
            source_common.coverage,
            config.runtime_id,
            source_common.data_version,
            source_common.batch_size,
            config.source_path.parent,
            _LOGGER,
            historical_cache_service=(
                OnlyHistoricalCacheService(
                    OnlyParquetHistoricalCacheStore(
                        OnlyUserDataLayout(request.user_data_root).historical_market_data_cache_root
                    )
                )
                if request.user_data_root is not None
                else None
            ),
        )
        self._raise_issues(
            data_factory.descriptor.plugin_id, str(source_common.source_id), data_factory.validate_request(data_request)
        )
        broker_factory = components.brokers.resolve(broker_common.plugin_id)
        broker_plugin_config = broker_factory.parse_config(broker_common.extensions)
        broker_request = OnlyBrokerCreateRequest(
            broker_common.gateway_id,
            broker_plugin_config,
            config.runtime.runtime_type,
            OnlyBrokerPluginCapabilities(simulated_execution=True),
            clock,
            event_bus,
            queue,
            config.runtime_id,
            account.account_id,
            account.initial_cash,
            _LOGGER,
        )
        self._raise_issues(
            broker_factory.descriptor.plugin_id,
            str(broker_common.gateway_id),
            broker_factory.validate_request(broker_request),
        )
        return _OnlyBacktestPluginPlan(
            runtime_config,
            clock,
            event_bus,
            queue,
            data_factory,
            data_request,
            broker_factory,
            broker_request,
        )

    @staticmethod
    def _validate_fee_schedules(
        config: OnlyRuntimeAssemblyPlan,
        components: OnlyComponentFactoryRegistries,
        market_rules: OnlyMarketRuleEngine,
        fee_config: OnlyFeeResolverConfig,
        trading_day: OnlyTradingDay,
    ) -> None:
        if fee_config.market_mode is not OnlyFeeConfigurationMode.NONE:
            for instrument in config.reference_data.instruments:
                schedule_id = fee_config.market_schedule_id
                if fee_config.market_mode is OnlyFeeConfigurationMode.DEFAULT:
                    schedule_id = market_rules.compiled_rules(
                        str(instrument.instrument_id), trading_day
                    ).market_fee_schedule_id
                if schedule_id is None:
                    raise ValueError("market fee configuration requires a schedule")
                components.market_fee_schedules.resolve(schedule_id, trading_day.value)
        if fee_config.broker_mode is OnlyFeeConfigurationMode.DEFAULT:
            raise ValueError("broker fees must explicitly select NONE, MODEL, or REPORTED")
        if fee_config.broker_mode is OnlyFeeConfigurationMode.MODEL:
            if fee_config.broker_schedule_id is None:
                raise ValueError("broker MODEL fee configuration requires a schedule")
            components.broker_fee_schedules.resolve(fee_config.broker_schedule_id, trading_day.value)

    @staticmethod
    def _configured_bar_types(config: OnlyRuntimeAssemblyPlan) -> dict[OnlyInstrumentId, OnlyBarType]:
        clusters = config.clusters
        result: dict[OnlyInstrumentId, OnlyBarType] = {}
        for cluster in clusters:
            for factor in cluster.factors:
                for instrument_subscription in factor.subscriptions.instrument_bars:
                    result[instrument_subscription.instrument_id] = (
                        instrument_subscription.bar_specification.to_bar_type(instrument_subscription.instrument_id)
                    )
                for universe_subscription in factor.subscriptions.universe_bars:
                    universe = next(
                        item for item in config.universes if item.universe_id == universe_subscription.universe_id
                    )
                    for instrument_id in universe.instrument_ids:
                        result[instrument_id] = universe_subscription.bar_specification.to_bar_type(instrument_id)
        return result

    @staticmethod
    def _raise_issues(
        plugin_id: str,
        resource_id: str,
        issues: Sequence[OnlyPluginValidationIssue],
    ) -> None:
        values = tuple(issues)
        if values:
            issue = values[0]
            raise OnlyPluginError(
                issue.code,
                issue.message,
                plugin_id=plugin_id,
                resource_id=resource_id,
            )

    @staticmethod
    def _failure(exc: Exception) -> OnlyRuntimeBuildResult:
        code = exc.code if isinstance(exc, OnlyPluginError) else "RUNTIME_ASSEMBLY_FAILED"
        return OnlyRuntimeBuildResult(failure_code=code, failure_message=str(exc))
