"""Backtest Runtime assembly through DataSource and Broker plugin SPI."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from onlyalpha.broker.virtual.scheduler import OnlyVirtualBrokerUpdateQueue
from onlyalpha.config import OnlyRuntimeAssemblyPlan
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.data.models import OnlyHistoricalBarRequest, OnlyHistoricalDataRange
from onlyalpha.domain.enums import OnlyRuntimeMode
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBarType
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.event.model import OnlyEventScope
from onlyalpha.plugin.broker import OnlyBacktestBrokerGateway, OnlyBrokerCreateRequest, OnlyBrokerGatewayFactory
from onlyalpha.plugin.capabilities import (
    OnlyBrokerPluginCapabilities,
    OnlyDataSourceCapabilities,
    OnlyPluginValidationIssue,
)
from onlyalpha.plugin.data_source import OnlyDataSource, OnlyDataSourceCreateRequest, OnlyDataSourceFactory
from onlyalpha.plugin.errors import OnlyPluginError
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
    broker_queue: OnlyVirtualBrokerUpdateQueue
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
        gateway: OnlyBacktestBrokerGateway | None = None
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
                gateway = cast(OnlyBacktestBrokerGateway, plan.broker_factory.create(plan.broker_request))
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
                broker_inbound_queue=plan.broker_queue,
                plugin_resources=(source, gateway),
            )
            for instrument in config.reference_data.instruments:
                runtime.register_instrument(instrument)
            for cluster in clusters:
                runtime.add_cluster(config.engine_id, cluster)
            return OnlyRuntimeBuildResult(runtime=runtime)
        except Exception as exc:
            if gateway is not None:
                gateway.stop()
                gateway.close()
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
        runtime_config = OnlyRuntimeAssemblyConfig(
            config.engine_id,
            config.runtime_id,
            OnlyRuntimeMode.BACKTEST,
            default_account_id=account.account_id,
            strategy_initial_capital=account.initial_cash.amount,
            strategy_base_currency=config.runtime.base_currency,
            broker_gateway_id=broker_common.gateway_id,
            account_initial_cash=account.initial_cash,
        )
        clock = OnlyBacktestClock(config.start_time)
        event_bus = OnlyEventBus(
            runtime_config.event_capacity,
            scope=OnlyEventScope(config.engine_id, config.runtime_id),
            queue_policy=runtime_config.event_queue_policy,
        )
        queue = OnlyVirtualBrokerUpdateQueue(runtime_config.event_capacity)
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
