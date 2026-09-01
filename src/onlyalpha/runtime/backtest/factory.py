"""Backtest Runtime assembly through DataSource and Broker plugin SPI."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from onlyalpha.account.enums import OnlyAccountType
from onlyalpha.broker.inbound import OnlyBoundedBrokerInboundQueue
from onlyalpha.broker.ports import OnlyBrokerGateway
from onlyalpha.cache.historical import OnlyHistoricalCacheService, OnlyParquetHistoricalCacheStore
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.data.historical.models import OnlyHistoricalFactRequest
from onlyalpha.data.models import OnlyHistoricalBarRequest, OnlyHistoricalDataRange
from onlyalpha.domain.enums import OnlyRuntimeMode
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBarType
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.event.model import OnlyEventScope
from onlyalpha.market.economics import OnlyEconomicModel
from onlyalpha.market.runtime_rules import OnlyMarketRuleEngine
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.plugin.broker import OnlyBrokerComponent, OnlyBrokerCreateRequest, OnlyBrokerGatewayFactory
from onlyalpha.plugin.capabilities import (
    OnlyBrokerPluginCapabilities,
    OnlyCheckpointCapability,
    OnlyDataSourceCapabilities,
    OnlyPluginValidationIssue,
)
from onlyalpha.plugin.data_source import OnlyDataSource, OnlyDataSourceCreateRequest, OnlyDataSourceFactory
from onlyalpha.plugin.errors import OnlyPluginError
from onlyalpha.plugin.lifecycle import OnlyPluginResource
from onlyalpha.runtime.assembler import OnlyComponentFactoryRegistries
from onlyalpha.runtime.backtest.config import OnlyBacktestRuntimeExtensionConfig
from onlyalpha.runtime.backtest.driver import OnlyBacktestDriver
from onlyalpha.runtime.backtest.input_requirements import only_kernel_economic_input_requirements
from onlyalpha.runtime.backtest.run_plan import OnlyBacktestRunPlan
from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime
from onlyalpha.runtime.factory import OnlyRuntimeBuildRequest, OnlyRuntimeBuildResult
from onlyalpha.runtime.persistence.factory import (
    OnlyRuntimePersistenceStoreCreateRequest,
)
from onlyalpha.runtime.persistence.store import OnlyRuntimePersistenceStorePort
from onlyalpha.runtime.planning import OnlyRuntimePlan
from onlyalpha.runtime.runtime import OnlyRuntimeAssemblyConfig
from onlyalpha.strategy.execution import OnlyStrategyExecutionResolver
from onlyalpha.strategy.store import OnlyFrozenStrategyRevisionStore

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
    broker_checkpoint_schema_version: int | None
    economic_requests: tuple[OnlyHistoricalFactRequest, ...]


class OnlyBacktestRuntimeFactory:
    @property
    def runtime_type(self) -> str:
        return "BACKTEST"

    def validate(self, request: OnlyRuntimeBuildRequest) -> OnlyRuntimeBuildResult:
        try:
            plan = self._plugin_plan(request)
            components = request.components
            if not isinstance(components, OnlyComponentFactoryRegistries):
                raise TypeError("Backtest factory requires OnlyComponentFactoryRegistries")
            components.runtime_persistence_stores.validate(request.config.runtime.persistence)
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
        persistence_store: OnlyRuntimePersistenceStorePort | None = None
        try:
            try:
                source = plan.data_factory.create(plan.data_request)
                if plan.economic_requests and not callable(getattr(source, "load_facts", None)):
                    raise ValueError("KERNEL_ECONOMIC_FACT_SOURCE_UNAVAILABLE")
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
            if request.user_data_root is None and config.runtime.persistence.backend.value == "SQLITE":
                raise ValueError("SQLite Runtime persistence requires user_data_root")
            state_root = (
                OnlyUserDataLayout(request.user_data_root).runtime_state_root(config.engine_id, config.runtime_id)
                if request.user_data_root is not None
                else Path(".")
            )
            persistence_store = components.runtime_persistence_stores.create(
                OnlyRuntimePersistenceStoreCreateRequest(
                    config.engine_id,
                    config.runtime_id,
                    OnlyRuntimeMode.BACKTEST,
                    config.runtime.persistence,
                    state_root,
                    self._config_fingerprint(request),
                    None,
                    config.runtime.base_currency.code,
                    config.accounts[0].account_id,
                    request.market_product.composition_identity.fingerprint,
                )
            )
            if request.user_data_root is None:
                raise ValueError("STRATEGY_SEMANTIC_ROOT_REQUIRED")
            semantic_root = OnlyUserDataLayout(request.user_data_root).research_root
            clusters = tuple(
                components.clusters.create(item, config, semantic_root) for item in config.clusters if item.enabled
            )
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
            run_plan = OnlyBacktestRunPlan(config, source, request_model, clusters, plan.economic_requests)
            if config.start_time is None:
                raise ValueError("BACKTEST requires runtime.start_time")
            runtime = OnlyBacktestRuntime(
                plan.runtime_config,
                config.reference_data.calendars[0],
                config.start_time,
                run_plan=OnlyBacktestDriver(run_plan),
                owned_clock=plan.clock,
                owned_event_bus=plan.event_bus,
                broker_gateway=gateway,
                deterministic_broker_driver=broker_component.deterministic_driver,
                broker_inbound_queue=plan.broker_queue,
                runtime_persistence_store=persistence_store,
                persistence_config=config.runtime.persistence,
                config_fingerprint=self._config_fingerprint(request),
                replay_source_id=source.source_id,
                replay_data_version=source_common.data_version,
                recovery_source=source,
                recovery_request=request_model,
                recovery_economic_requests=plan.economic_requests,
                plugin_resources=(source, broker_resource),
            )
            for instrument in config.reference_data.instruments:
                runtime.register_instrument(instrument)
            for cluster in clusters:
                runtime.add_cluster(config.engine_id, cluster)
            persistence_store = None
            return OnlyRuntimeBuildResult(runtime=runtime)
        except Exception as exc:
            if persistence_store is not None:
                persistence_store.close()
            if broker_resource is not None:
                broker_resource.stop()
                broker_resource.close()
            if source is not None:
                source.stop()
                source.close()
            plan.event_bus.close()
            plan.clock.close()
            return self._failure(exc)

    @staticmethod
    def _config_fingerprint(request: OnlyRuntimeBuildRequest) -> str:
        if not isinstance(request.plan, OnlyRuntimePlan):
            raise TypeError("Backtest factory requires OnlyRuntimePlan")
        payloads = [
            dict(config.normalized_payload)
            for config in sorted(request.plan.cluster_configs, key=lambda item: str(item.cluster_id))
        ]
        payload = json.dumps(payloads, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

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

        market_rule_engine = OnlyMarketRuleEngine(
            binding=request.market_product,
            advance_trading_day=advance_trading_day,
        )
        assert config.start_time is not None
        initial_trading_day = calendar.trading_day_at(config.start_time)
        policies = {
            instrument.instrument_id: market_rule_engine.compiled_rules(
                str(instrument.instrument_id),
                initial_trading_day,
                as_of=config.start_time,
            )
            for instrument in config.reference_data.instruments
        }
        economic_models = {policy.economic_model for policy in policies.values()}
        if len(economic_models) != 1:
            raise ValueError("one Backtest Account cannot mix cash and margined economic models")
        account_type = (
            OnlyAccountType.MARGIN
            if economic_models == {OnlyEconomicModel.MARGINED_DERIVATIVE}
            else OnlyAccountType.CASH
        )
        market_fee_pack = request.market_product.market_fee_pack
        broker_fee_contract = components.broker_fee_contracts.require(
            account.broker_fee_contract.contract_id,
            account.broker_fee_contract.contract_version,
        )
        broker_fee_contract.validate_compatibility(
            broker_id=broker_common.plugin_id,
            account_id=account.account_id,
        )
        reconciliation_policy = components.fee_reconciliation_policies.require(
            account.fee_reconciliation_policy.policy_id,
            account.fee_reconciliation_policy.policy_version,
            account.initial_cash.currency,
        )
        runtime_config = OnlyRuntimeAssemblyConfig(
            config.engine_id,
            config.runtime_id,
            OnlyRuntimeMode.BACKTEST,
            default_account_id=account.account_id,
            strategy_base_currency=config.runtime.base_currency,
            strategy_capitals={
                cluster.cluster_id: account.initial_cash if cluster.capital is None else cluster.capital.amount
                for cluster in config.clusters
            },
            broker_gateway_id=broker_common.gateway_id,
            account_initial_cash=account.initial_cash,
            account_type=account_type,
            market_rule_engine=market_rule_engine,
            market_fee_pack=market_fee_pack,
            broker_fee_contract=broker_fee_contract,
            broker_fee_authority_id=broker_common.plugin_id,
            fee_basis_providers=components.fee_basis_providers,
            fee_reconciliation_policy=reconciliation_policy,
        )
        clock = OnlyBacktestClock(config.start_time)
        event_bus = OnlyEventBus(
            runtime_config.event_capacity,
            scope=OnlyEventScope(config.engine_id, config.runtime_id),
            queue_policy=runtime_config.event_queue_policy,
        )
        queue = OnlyBoundedBrokerInboundQueue(runtime_config.event_capacity)
        bar_types = self._configured_bar_types(request)
        data_factory = components.data_sources.resolve(source_common.plugin_id)
        if config.runtime.persistence.checkpoint.enabled:
            data_checkpoint = self._require_checkpoint_capability(data_factory.descriptor.capabilities, "DataSource")
            if data_checkpoint is not OnlyCheckpointCapability.STATELESS:
                raise ValueError("Backtest Historical DataSource checkpoint capability must be STATELESS")
        data_plugin_config = data_factory.parse_config(source_common.extensions)
        economic_requests = tuple(
            OnlyHistoricalFactRequest(
                instrument_id,
                requirement.fact_family,
                OnlyTimeRange(config.start_time, config.end_time),
                source_common.data_version,
                requirement.reference_price_kind,
                source_common.batch_size,
            )
            for instrument_id, policy in sorted(policies.items(), key=lambda item: str(item[0]))
            for requirement in only_kernel_economic_input_requirements(policy)
        )
        required_families = frozenset(item.fact_family for item in economic_requests)
        data_request = OnlyDataSourceCreateRequest(
            source_common.source_id,
            data_plugin_config,
            config.runtime.runtime_type,
            OnlyDataSourceCapabilities(
                historical_bars=True,
                historical_reference_prices=OnlyMarketDataType.REFERENCE_PRICE in required_families,
                historical_funding_rates=OnlyMarketDataType.FUNDING_RATE in required_families,
                historical_settlements=OnlyMarketDataType.SETTLEMENT in required_families,
            ),
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
            kernel_economic_requests=economic_requests,
        )
        self._raise_issues(
            data_factory.descriptor.plugin_id, str(source_common.source_id), data_factory.validate_request(data_request)
        )
        broker_factory = components.brokers.resolve(broker_common.plugin_id)
        broker_checkpoint_version: int | None = None
        if config.runtime.persistence.checkpoint.enabled:
            broker_checkpoint = self._require_checkpoint_capability(broker_factory.descriptor.capabilities, "Broker")
            if broker_checkpoint is not OnlyCheckpointCapability.CHECKPOINTABLE:
                raise ValueError("checkpoint-enabled Backtest Broker must be CHECKPOINTABLE")
            broker_checkpoint_version = getattr(
                broker_factory.descriptor.capabilities,
                "checkpoint_schema_version",
                None,
            )
            if not isinstance(broker_checkpoint_version, int) or broker_checkpoint_version < 1:
                raise ValueError("Backtest Broker checkpoint schema version must be positive")
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
            broker_checkpoint_version,
            economic_requests,
        )

    @staticmethod
    def _require_checkpoint_capability(capabilities: object, component_type: str) -> OnlyCheckpointCapability:
        capability = getattr(capabilities, "supports_runtime_checkpoint", None)
        if not isinstance(capability, OnlyCheckpointCapability):
            raise ValueError(f"SQLite checkpoint requires explicit {component_type} checkpoint capability")
        return capability

    @staticmethod
    def _configured_bar_types(request: OnlyRuntimeBuildRequest) -> dict[OnlyInstrumentId, OnlyBarType]:
        config = request.config
        components = request.components
        if not isinstance(components, OnlyComponentFactoryRegistries):
            raise TypeError("Backtest factory requires OnlyComponentFactoryRegistries")
        if request.user_data_root is None:
            raise ValueError("STRATEGY_SEMANTIC_ROOT_REQUIRED")
        resolver = OnlyStrategyExecutionResolver(
            OnlyFrozenStrategyRevisionStore(OnlyUserDataLayout(request.user_data_root).research_root),
            components.calculations,
        )
        result: dict[OnlyInstrumentId, OnlyBarType] = {}
        for cluster in config.clusters:
            if not cluster.enabled:
                continue
            revision = resolver.resolve(cluster.strategy.fingerprint).revision
            contract = revision.market_input_contract
            for instrument_id in revision.universe.instruments:
                bar_type = OnlyBarType(instrument_id, contract.bar_specification, contract.aggregation_source)
                existing = result.get(instrument_id)
                if existing is not None and existing != bar_type:
                    raise ValueError("Strategy Market Input Contracts conflict for one instrument")
                result[instrument_id] = bar_type
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
