"""Backtest Runtime assembly through DataSource and Broker plugin SPI."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from onlyalpha.broker.inbound import OnlyBoundedBrokerInboundQueue
from onlyalpha.broker.ports import OnlyBrokerGateway
from onlyalpha.cache.historical import OnlyHistoricalCacheService, OnlyParquetHistoricalCacheStore
from onlyalpha.config import OnlyRuntimeAssemblyPlan
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.data.models import OnlyHistoricalBarRequest, OnlyHistoricalDataRange
from onlyalpha.domain.enums import OnlyRuntimeMode
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBarType
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.event.model import OnlyEventScope
from onlyalpha.fee.reconciliation_policy import (
    OnlyFeeReconciliationPolicyRegistry,
    only_standard_fee_reconciliation_policy,
)
from onlyalpha.market.models import OnlyInstrumentReferenceSnapshot
from onlyalpha.market.runtime_rules import (
    OnlyMarketRuleEngine,
    OnlyReferenceProvider,
    only_ashare_instrument_reference,
    only_instrument_reference,
)
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
from onlyalpha.runtime.backtest.run_plan import OnlyBacktestRunPlan
from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime
from onlyalpha.runtime.factory import OnlyRuntimeBuildRequest, OnlyRuntimeBuildResult
from onlyalpha.runtime.persistence.factory import (
    OnlyRuntimePersistenceStoreCreateRequest,
)
from onlyalpha.runtime.persistence.store import OnlyRuntimePersistenceStorePort
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
                    config.market.profile.value,
                )
            )
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
            if config.start_time is None:
                raise ValueError("BACKTEST requires runtime.start_time")
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
                runtime_persistence_store=persistence_store,
                persistence_config=config.runtime.persistence,
                config_fingerprint=self._config_fingerprint(request),
                replay_source_id=source.source_id,
                replay_data_version=source_common.data_version,
                recovery_source=source,
                recovery_request=request_model,
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

        ashare_query = config.reference_data.ashare_registry
        references: Mapping[str, OnlyInstrumentReferenceSnapshot] | OnlyReferenceProvider
        if config.market.profile.value == "CN_A_SHARE_CASH":
            instruments = config.reference_data.instrument_by_id

            def resolve_reference(instrument_id: str, trading_day: OnlyTradingDay) -> OnlyInstrumentReferenceSnapshot:
                identity = OnlyInstrumentId.parse(instrument_id)
                record = ashare_query.resolve(identity, trading_day).require_snapshot()
                return only_ashare_instrument_reference(
                    instruments[identity], record, profile_id=config.market.profile.value
                )

            references = resolve_reference

        else:
            references = {
                str(instrument.instrument_id): only_instrument_reference(
                    instrument,
                    profile_id=config.market.profile.value,
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
            reference_registry_fingerprint=(
                config.reference_data.reference_registry_fingerprint
                if config.market.profile.value == "CN_A_SHARE_CASH"
                else None
            ),
        )
        market_fee_pack = components.market_fee_packs.require(
            config.market.fee_pack.pack_id,
            config.market.fee_pack.pack_version,
        )
        market_fee_pack.validate_compatibility(config.market.profile.value)
        broker_fee_contract = components.broker_fee_contracts.require(
            account.broker_fee_contract.contract_id,
            account.broker_fee_contract.contract_version,
        )
        broker_fee_contract.validate_compatibility(
            broker_id=broker_common.plugin_id,
            account_id=account.account_id,
        )
        reconciliation_policies = OnlyFeeReconciliationPolicyRegistry()
        reconciliation_policies.register(only_standard_fee_reconciliation_policy(account.initial_cash.currency))
        reconciliation_policy = reconciliation_policies.require(
            account.fee_reconciliation_policy.policy_id,
            account.fee_reconciliation_policy.policy_version,
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
        bar_types = self._configured_bar_types(config)
        data_factory = components.data_sources.resolve(source_common.plugin_id)
        if config.runtime.persistence.checkpoint.enabled:
            data_checkpoint = self._require_checkpoint_capability(data_factory.descriptor.capabilities, "DataSource")
            if data_checkpoint is not OnlyCheckpointCapability.STATELESS:
                raise ValueError("Backtest Historical DataSource checkpoint capability must be STATELESS")
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
        )

    @staticmethod
    def _require_checkpoint_capability(capabilities: object, component_type: str) -> OnlyCheckpointCapability:
        capability = getattr(capabilities, "supports_runtime_checkpoint", None)
        if not isinstance(capability, OnlyCheckpointCapability):
            raise ValueError(f"SQLite checkpoint requires explicit {component_type} checkpoint capability")
        return capability

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
