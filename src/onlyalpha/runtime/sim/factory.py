"""SIM Runtime composition through realtime DataSource and simulated Broker SPI."""

from __future__ import annotations

import hashlib
import json
import logging
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import timedelta
from pathlib import Path

from onlyalpha.broker.inbound import OnlyBoundedBrokerInboundQueue
from onlyalpha.cache.historical import OnlyHistoricalCacheService, OnlyParquetHistoricalCacheStore
from onlyalpha.config import OnlyRuntimeAssemblyPlan
from onlyalpha.config.persistence import OnlyRuntimePersistenceBackend
from onlyalpha.core.clock import OnlyLiveClock
from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.data.models import OnlyMarketDataSubscriptionRequest
from onlyalpha.data.queue import OnlyMarketDataInboundQueue
from onlyalpha.domain.enums import OnlyAggregationSource, OnlyRuntimeMode
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.event.model import OnlyEventScope
from onlyalpha.fee.reconciliation_policy import OnlyFeeReconciliationPolicy
from onlyalpha.market.product import OnlyResolvedMarketProductBinding
from onlyalpha.market.runtime_rules import OnlyMarketRuleEngine
from onlyalpha.market.session_clock import OnlyMarketSessionResolver
from onlyalpha.observation import (
    OnlyConsoleObservationSink,
    OnlyJsonLinesObservationSink,
    OnlyObservationSink,
)
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.plugin.broker import OnlyBrokerComponent, OnlyBrokerCreateRequest
from onlyalpha.plugin.capabilities import (
    OnlyBrokerPluginCapabilities,
    OnlyDataSourceCapabilities,
    OnlyPluginValidationIssue,
)
from onlyalpha.plugin.data_source import OnlyDataSource, OnlyDataSourceCreateRequest
from onlyalpha.plugin.errors import OnlyPluginError
from onlyalpha.plugin.lifecycle import OnlyPluginResource
from onlyalpha.runtime.assembler import OnlyComponentFactoryRegistries
from onlyalpha.runtime.factory import OnlyRuntimeBuildRequest, OnlyRuntimeBuildResult
from onlyalpha.runtime.persistence.factory import OnlyRuntimePersistenceStoreCreateRequest
from onlyalpha.runtime.persistence.lease import OnlyRuntimeStateLease
from onlyalpha.runtime.persistence.store import OnlyRuntimePersistenceStorePort
from onlyalpha.runtime.planning import OnlyRuntimePlan
from onlyalpha.runtime.runtime import OnlyRuntimeAssemblyConfig
from onlyalpha.runtime.sim.runtime import OnlySimRuntime
from onlyalpha.runtime.streaming.config import OnlyStreamingRuntimeConfig
from onlyalpha.runtime.streaming.execution import OnlyExecutionSubmissionCapability

_LOGGER = logging.getLogger(__name__)


class _OnlySimCompositionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class OnlySimRuntimeFactory:
    """Compose realtime simulated trading through shared Streaming and Trading kernels."""

    @property
    def runtime_type(self) -> str:
        return "SIM"

    def validate(self, request: OnlyRuntimeBuildRequest) -> OnlyRuntimeBuildResult:
        try:
            components, _, _ = self._validate(request)
            components.runtime_persistence_stores.validate(request.config.runtime.persistence)
            self._validate_durable_root(request)
        except Exception as exc:
            return self._failure(exc)
        return OnlyRuntimeBuildResult()

    def create(self, request: OnlyRuntimeBuildRequest) -> OnlyRuntimeBuildResult:
        source: OnlyDataSource | None = None
        broker_resource: OnlyPluginResource | None = None
        persistence: OnlyRuntimePersistenceStorePort | None = None
        lease: OnlyRuntimeStateLease | None = None
        clock: OnlyLiveClock | None = None
        event_bus: OnlyEventBus | None = None
        try:
            components, streaming, reconciliation_policy = self._validate(request)
            config = request.config
            source_common = next(item for item in config.data_sources if item.enabled)
            broker_common = next(item for item in config.brokers if item.enabled)
            account = config.accounts[0]
            calendar = config.reference_data.calendars[0]

            clock = OnlyLiveClock()
            event_bus = OnlyEventBus(
                streaming.inbound_queue_capacity,
                scope=OnlyEventScope(config.engine_id, config.runtime_id),
            )
            market_inbound = OnlyMarketDataInboundQueue(streaming.inbound_queue_capacity)
            broker_inbound = OnlyBoundedBrokerInboundQueue(streaming.inbound_queue_capacity)

            if request.user_data_root is None:
                raise _OnlySimCompositionError(
                    "STRATEGY_SEMANTIC_ROOT_REQUIRED",
                    "SIM Strategy resolution requires the shared semantic root",
                )
            semantic_root = OnlyUserDataLayout(request.user_data_root).research_root
            clusters = tuple(
                components.clusters.create(item, config, semantic_root) for item in config.clusters if item.enabled
            )
            if not clusters:
                raise _OnlySimCompositionError(
                    "SIM_CLUSTER_REQUIRED",
                    "SIM requires at least one enabled Cluster",
                )
            all_bar_types = frozenset(
                bar_type
                for cluster in clusters
                if cluster.config.subscription is not None
                for bar_type in cluster.config.subscription.bar_types
            )
            base_bar_types = frozenset(
                item for item in all_bar_types if item.aggregation_source is OnlyAggregationSource.EXTERNAL
            )
            if not base_bar_types:
                raise _OnlySimCompositionError(
                    "SIM_EXTERNAL_BAR_SUBSCRIPTION_REQUIRED",
                    "SIM requires an external base Bar subscription",
                )

            state_root = (
                OnlyUserDataLayout(request.user_data_root).runtime_state_root(config.engine_id, config.runtime_id)
                if request.user_data_root is not None
                else Path(tempfile.gettempdir()) / "onlyalpha" / "runtime_state" / str(config.runtime_id)
            )
            lease = OnlyRuntimeStateLease(state_root, config.runtime_id)
            by_instrument = {item.instrument_id: item for item in base_bar_types}
            data_factory = components.data_sources.resolve(source_common.plugin_id)
            data_request = OnlyDataSourceCreateRequest(
                source_common.source_id,
                data_factory.parse_config(source_common.extensions),
                config.runtime.runtime_type,
                OnlyDataSourceCapabilities(historical_bars=True, live_bars=True, live_reconnect=True),
                clock,
                event_bus,
                config.reference_data.instrument_by_id,
                by_instrument,
                config.reference_data.calendar_by_id,
                config.universes,
                source_common.coverage,
                config.runtime_id,
                source_common.data_version,
                source_common.batch_size,
                config.source_path.parent,
                _LOGGER,
                market_data_sink=market_inbound.put,
                historical_cache_service=(
                    OnlyHistoricalCacheService(
                        OnlyParquetHistoricalCacheStore(
                            OnlyUserDataLayout(request.user_data_root).historical_market_data_cache_root
                        )
                    )
                    if request.user_data_root is not None
                    else None
                ),
                runtime_state_root=state_root,
            )
            self._raise_issues(
                data_factory.descriptor.plugin_id,
                str(source_common.source_id),
                data_factory.validate_request(data_request),
            )
            try:
                source = data_factory.create(data_request)
            except Exception as exc:
                raise OnlyPluginError(
                    "PLUGIN_CREATE_FAILED",
                    str(exc),
                    plugin_id=data_factory.descriptor.plugin_id,
                    resource_id=str(source_common.source_id),
                ) from exc

            market_rules = self._market_rules(config, request.market_product, clock)
            broker_fee_contract = components.broker_fee_contracts.require(
                account.broker_fee_contract.contract_id,
                account.broker_fee_contract.contract_version,
            )
            broker_fee_contract.validate_compatibility(
                broker_id=broker_common.plugin_id,
                account_id=account.account_id,
            )
            runtime_config = OnlyRuntimeAssemblyConfig(
                config.engine_id,
                config.runtime_id,
                OnlyRuntimeMode.SIM,
                event_capacity=streaming.inbound_queue_capacity,
                default_account_id=account.account_id,
                strategy_base_currency=config.runtime.base_currency,
                strategy_capitals={
                    cluster.cluster_id: account.initial_cash if cluster.capital is None else cluster.capital.amount
                    for cluster in config.clusters
                },
                broker_gateway_id=broker_common.gateway_id,
                account_initial_cash=account.initial_cash,
                market_rule_engine=market_rules,
                market_fee_pack=request.market_product.market_fee_pack,
                broker_fee_contract=broker_fee_contract,
                broker_fee_authority_id=broker_common.plugin_id,
                fee_basis_providers=components.fee_basis_providers,
                fee_reconciliation_policy=reconciliation_policy,
            )
            persistence = components.runtime_persistence_stores.create(
                OnlyRuntimePersistenceStoreCreateRequest(
                    config.engine_id,
                    config.runtime_id,
                    OnlyRuntimeMode.SIM,
                    config.runtime.persistence,
                    state_root,
                    self._fingerprint(request),
                    None,
                    config.runtime.base_currency.code,
                    account.account_id,
                    request.market_product.composition_identity.fingerprint,
                )
            )

            broker_factory = components.brokers.resolve(broker_common.plugin_id)
            broker_request = OnlyBrokerCreateRequest(
                broker_common.gateway_id,
                broker_factory.parse_config(broker_common.extensions),
                config.runtime.runtime_type,
                OnlyBrokerPluginCapabilities(
                    submit_order=True,
                    cancel_order=True,
                    query_orders=True,
                    query_trades=True,
                    simulated_execution=True,
                ),
                clock,
                event_bus,
                broker_inbound,
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
            try:
                broker_component: OnlyBrokerComponent = broker_factory.create(broker_request)
            except Exception as exc:
                raise OnlyPluginError(
                    "PLUGIN_CREATE_FAILED",
                    str(exc),
                    plugin_id=broker_factory.descriptor.plugin_id,
                    resource_id=str(broker_common.gateway_id),
                ) from exc
            broker_resource = broker_component.resource
            if broker_component.deterministic_driver is None:
                raise _OnlySimCompositionError(
                    "SIM_DETERMINISTIC_BROKER_DRIVER_REQUIRED",
                    "operational SIM Broker must provide a deterministic driver",
                )

            subscription = OnlyMarketDataSubscriptionRequest(
                f"sim-{config.runtime_id}",
                source_common.source_id,
                frozenset(by_instrument),
                frozenset({OnlyMarketDataType.BAR}),
                base_bar_types,
            )
            runtime = OnlySimRuntime(
                runtime_config,
                calendar,
                clock=clock,
                event_bus=event_bus,
                data_source=source,
                inbound_queue=market_inbound,
                broker_gateway=broker_component.gateway,
                broker_inbound_queue=broker_inbound,
                deterministic_broker_driver=broker_component.deterministic_driver,
                broker_resource=broker_resource,
                persistence_store=persistence,
                persistence_config=config.runtime.persistence,
                config_fingerprint=self._fingerprint(request),
                subscription=subscription,
                data_version=source_common.data_version,
                bootstrap_bars=streaming.bootstrap_bars,
                historical_compatibility_profile=streaming.historical_compatibility_profile,
                historical_timeout_seconds=streaming.historical_timeout_seconds,
                warmup_alignment_steps=tuple(
                    item.specification.step
                    for item in all_bar_types
                    if item.aggregation_source is OnlyAggregationSource.INTERNAL
                ),
                stale_after_seconds=streaming.stale_after_seconds,
                observation_sinks=self._observation_sinks(config, request.user_data_root),
                observation_queue_capacity=streaming.observation_queue_capacity,
            )
            runtime._bind_runtime_state_lease(lease)
            for instrument in config.reference_data.instruments:
                runtime.register_instrument(instrument)
            for cluster in clusters:
                runtime.add_cluster(config.engine_id, cluster)

            source = None
            broker_resource = None
            persistence = None
            lease = None
            clock = None
            event_bus = None
            return OnlyRuntimeBuildResult(runtime=runtime)
        except Exception as exc:
            self._rollback(persistence, lease, broker_resource, source, event_bus, clock)
            return self._failure(exc)

    @staticmethod
    def _rollback(
        persistence: OnlyRuntimePersistenceStorePort | None,
        lease: OnlyRuntimeStateLease | None,
        broker_resource: OnlyPluginResource | None,
        source: OnlyDataSource | None,
        event_bus: OnlyEventBus | None,
        clock: OnlyLiveClock | None,
    ) -> None:
        operations: list[tuple[str, Callable[[], object]]] = []
        if persistence is not None:
            operations.append(("persistence.close", persistence.close))
        if lease is not None:
            operations.append(("runtime_state_lease.close", lease.close))
        if broker_resource is not None:
            operations.extend(
                (
                    ("broker.stop", broker_resource.stop),
                    ("broker.close", broker_resource.close),
                )
            )
        if source is not None:
            operations.extend((("data_source.stop", source.stop), ("data_source.close", source.close)))
        if event_bus is not None:
            operations.append(("event_bus.close", event_bus.close))
        if clock is not None:
            operations.append(("clock.close", clock.close))
        for name, operation in operations:
            try:
                operation()
            except Exception:
                _LOGGER.exception("SIM Factory rollback failed during %s", name)

    @staticmethod
    def _validate(
        request: OnlyRuntimeBuildRequest,
    ) -> tuple[
        OnlyComponentFactoryRegistries,
        OnlyStreamingRuntimeConfig,
        OnlyFeeReconciliationPolicy,
    ]:
        components = request.components
        if not isinstance(components, OnlyComponentFactoryRegistries):
            raise TypeError("Sim factory requires OnlyComponentFactoryRegistries")

        config = request.config
        if config.runtime.runtime_type != "SIM":
            raise _OnlySimCompositionError(
                "SIM_RUNTIME_TYPE_REQUIRED",
                "Sim factory requires runtime.type=SIM",
            )

        streaming = OnlyStreamingRuntimeConfig.from_mapping(config.runtime.extensions)
        if streaming.execution_capability is not OnlyExecutionSubmissionCapability.SIMULATED:
            raise _OnlySimCompositionError(
                "SIM_EXECUTION_CAPABILITY_REQUIRED",
                "SIM requires explicit SIMULATED execution capability",
            )
        if config.start_time is not None or config.end_time is not None:
            raise _OnlySimCompositionError(
                "SIM_FINITE_RANGE_NOT_SUPPORTED",
                "SIM does not support runtime.start_time or runtime.end_time",
            )
        OnlySimRuntimeFactory._validate_durable_root(request)

        sources = tuple(item for item in config.data_sources if item.enabled)
        if len(sources) != 1:
            raise _OnlySimCompositionError(
                "SIM_DATA_SOURCE_COUNT_INVALID",
                "SIM requires exactly one enabled realtime DataSource",
            )
        source_factory = components.data_sources.resolve(sources[0].plugin_id)
        source_capabilities = source_factory.descriptor.capabilities
        required_source_capabilities = OnlyDataSourceCapabilities(
            historical_bars=True,
            live_bars=True,
            live_reconnect=True,
        )
        if not isinstance(source_capabilities, OnlyDataSourceCapabilities):
            raise _OnlySimCompositionError(
                "SIM_DATA_SOURCE_CAPABILITY_REQUIRED",
                "SIM DataSource must declare historical_bars, live_bars, and live_reconnect capabilities",
            )
        missing_source_capabilities = source_capabilities.missing(required_source_capabilities)
        if missing_source_capabilities:
            code = (
                "SIM_DATA_SOURCE_RECONNECT_CAPABILITY_REQUIRED"
                if missing_source_capabilities == ("live_reconnect",)
                else "SIM_DATA_SOURCE_CAPABILITY_REQUIRED"
            )
            raise _OnlySimCompositionError(
                code,
                f"SIM DataSource is missing required capabilities: {', '.join(missing_source_capabilities)}",
            )

        if len(config.accounts) != 1:
            raise _OnlySimCompositionError(
                "SIM_ACCOUNT_COUNT_INVALID",
                "SIM requires exactly one Account",
            )
        brokers = tuple(item for item in config.brokers if item.enabled)
        if len(brokers) != 1:
            raise _OnlySimCompositionError(
                "SIM_BROKER_COUNT_INVALID",
                "SIM requires exactly one enabled Broker",
            )
        broker_factory = components.brokers.resolve(brokers[0].plugin_id)
        broker_capabilities = broker_factory.descriptor.capabilities
        if (
            not isinstance(broker_capabilities, OnlyBrokerPluginCapabilities)
            or not broker_capabilities.simulated_execution
        ):
            raise _OnlySimCompositionError(
                "SIM_SIMULATED_BROKER_REQUIRED",
                "SIM Broker must explicitly support simulated_execution",
            )
        required_broker_capabilities = OnlyBrokerPluginCapabilities(
            submit_order=True,
            cancel_order=True,
            query_orders=True,
            query_trades=True,
        )
        missing_broker_capabilities = broker_capabilities.missing(required_broker_capabilities)
        if missing_broker_capabilities:
            raise _OnlySimCompositionError(
                "SIM_BROKER_CAPABILITY_REQUIRED",
                f"SIM Broker is missing required capabilities: {', '.join(missing_broker_capabilities)}",
            )

        account = config.accounts[0]
        reconciliation_policy = components.fee_reconciliation_policies.require(
            account.fee_reconciliation_policy.policy_id,
            account.fee_reconciliation_policy.policy_version,
            account.initial_cash.currency,
        )
        return components, streaming, reconciliation_policy

    @staticmethod
    def _validate_durable_root(request: OnlyRuntimeBuildRequest) -> None:
        persistence = request.config.runtime.persistence
        if not persistence.checkpoint.enabled:
            return
        if persistence.backend is not OnlyRuntimePersistenceBackend.SQLITE:
            raise _OnlySimCompositionError(
                "SIM_DURABLE_PERSISTENCE_REQUIRED",
                "checkpoint-enabled SIM requires SQLITE Runtime persistence",
            )
        if request.user_data_root is None:
            raise _OnlySimCompositionError(
                "SIM_DURABLE_STATE_ROOT_REQUIRED",
                "checkpoint-enabled SIM requires a stable user_data state root",
            )

    @staticmethod
    def _market_rules(
        config: OnlyRuntimeAssemblyPlan,
        market_product: OnlyResolvedMarketProductBinding,
        clock: OnlyLiveClock,
    ) -> OnlyMarketRuleEngine:
        calendar = config.reference_data.calendars[0]

        def advance(day: OnlyTradingDay, lag: int) -> OnlyTradingDay:
            candidate = day.value
            remaining = lag
            while remaining:
                candidate += timedelta(days=1)
                if calendar.is_trading_day(candidate):
                    remaining -= 1
            return OnlyTradingDay(candidate)

        engine = OnlyMarketRuleEngine(binding=market_product, advance_trading_day=advance)
        startup = OnlyMarketSessionResolver(calendar).resolve(OnlyTimestamp.from_datetime(clock.now_utc()))
        validation_day = startup.current_trading_day or startup.next_trading_day
        for instrument in config.reference_data.instruments:
            engine.compiled_rules(str(instrument.instrument_id), validation_day)
        return engine

    @staticmethod
    def _observation_sinks(
        config: OnlyRuntimeAssemblyPlan,
        user_data_root: Path | None,
    ) -> tuple[OnlyObservationSink, ...]:
        raw = config.runtime.extensions.get("observation", {})
        if not isinstance(raw, Mapping):
            raise ValueError("runtime.extensions.observation must be an object")
        sinks: list[OnlyObservationSink] = []
        if bool(raw.get("console", False)):
            sinks.append(OnlyConsoleObservationSink())
        if bool(raw.get("jsonl", False)):
            selected = Path(str(raw.get("jsonl_path", "observations/latest.jsonl")))
            if not selected.is_absolute():
                selected = (user_data_root or config.source_path.parent) / selected
            sinks.append(OnlyJsonLinesObservationSink(selected))
        return tuple(sinks)

    @staticmethod
    def _fingerprint(request: OnlyRuntimeBuildRequest) -> str:
        if not isinstance(request.plan, OnlyRuntimePlan):
            raise TypeError("SIM factory requires OnlyRuntimePlan")
        payload = json.dumps(
            [dict(item.normalized_payload) for item in request.plan.cluster_configs],
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()

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
        if isinstance(exc, (_OnlySimCompositionError, OnlyPluginError)):
            code = exc.code
        else:
            code = "RUNTIME_ASSEMBLY_FAILED"
        return OnlyRuntimeBuildResult(failure_code=code, failure_message=str(exc))
