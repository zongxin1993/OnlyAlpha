"""Paper Runtime composition through the standard Engine assembler."""

from __future__ import annotations

import hashlib
import json
import logging
import tempfile
from datetime import timedelta
from pathlib import Path

from onlyalpha.cache.historical import OnlyHistoricalCacheService, OnlyParquetHistoricalCacheStore
from onlyalpha.config import OnlyRuntimeAssemblyPlan
from onlyalpha.core.clock import OnlyLiveClock
from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.data.models import OnlyMarketDataSubscriptionRequest
from onlyalpha.data.queue import OnlyMarketDataInboundQueue
from onlyalpha.domain.enums import OnlyAggregationSource, OnlyRuntimeMode
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.event.model import OnlyEventScope
from onlyalpha.fee.models import OnlyFeeConfigurationMode
from onlyalpha.fee.resolver import OnlyFeeResolverConfig
from onlyalpha.market.runtime_rules import OnlyMarketRuleEngine, only_instrument_reference
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.plugin.capabilities import OnlyDataSourceCapabilities
from onlyalpha.plugin.data_source import OnlyDataSource, OnlyDataSourceCreateRequest
from onlyalpha.runtime.assembler import OnlyComponentFactoryRegistries
from onlyalpha.runtime.factory import OnlyRuntimeBuildRequest, OnlyRuntimeBuildResult
from onlyalpha.runtime.paper.runtime import OnlyPaperRuntime
from onlyalpha.runtime.persistence.factory import OnlyRuntimePersistenceStoreCreateRequest
from onlyalpha.runtime.runtime import OnlyRuntimeAssemblyConfig
from onlyalpha.runtime.streaming.config import OnlyStreamingRuntimeConfig
from onlyalpha.runtime.streaming.execution import (
    OnlyExecutionSubmissionCapability,
    OnlyShadowExecutionService,
)

_LOGGER = logging.getLogger(__name__)


class OnlyPaperRuntimeFactory:
    @property
    def runtime_type(self) -> str:
        return "PAPER"

    def validate(self, request: OnlyRuntimeBuildRequest) -> OnlyRuntimeBuildResult:
        try:
            self._validate(request)
        except Exception as exc:
            return self._failure(exc)
        return OnlyRuntimeBuildResult()

    def create(self, request: OnlyRuntimeBuildRequest) -> OnlyRuntimeBuildResult:
        source: OnlyDataSource | None = None
        persistence = None
        clock: OnlyLiveClock | None = None
        event_bus: OnlyEventBus | None = None
        try:
            components, streaming = self._validate(request)
            config = request.config
            source_common = next(item for item in config.data_sources if item.enabled)
            account = config.accounts[0]
            calendar = config.reference_data.calendars[0]
            clock = OnlyLiveClock()
            event_bus = OnlyEventBus(
                streaming.inbound_queue_capacity,
                scope=OnlyEventScope(config.engine_id, config.runtime_id),
            )
            inbound = OnlyMarketDataInboundQueue(streaming.inbound_queue_capacity)
            clusters = tuple(components.clusters.create(item, config) for item in config.clusters if item.enabled)
            if not clusters:
                raise ValueError("product Paper Runtime requires at least one enabled Cluster")
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
                raise ValueError("Paper Runtime requires an external base Bar subscription")
            state_root = (
                OnlyUserDataLayout(request.user_data_root).runtime_state_root(config.engine_id, config.runtime_id)
                if request.user_data_root is not None
                else Path(tempfile.gettempdir()) / "onlyalpha" / "runtime_state" / str(config.runtime_id)
            )
            by_instrument = {item.instrument_id: item for item in base_bar_types}
            data_factory = components.data_sources.resolve(source_common.plugin_id)
            data_request = OnlyDataSourceCreateRequest(
                source_common.source_id,
                data_factory.parse_config(source_common.extensions),
                config.runtime.runtime_type,
                OnlyDataSourceCapabilities(historical_bars=True, live_bars=True),
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
                market_data_sink=inbound.put,
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
            issues = tuple(data_factory.validate_request(data_request))
            if issues:
                raise ValueError(f"{issues[0].code}: {issues[0].message}")
            source = data_factory.create(data_request)
            market_rules = self._market_rules(config, components, clock)
            runtime_config = OnlyRuntimeAssemblyConfig(
                config.engine_id,
                config.runtime_id,
                OnlyRuntimeMode.PAPER,
                event_capacity=streaming.inbound_queue_capacity,
                default_account_id=account.account_id,
                strategy_base_currency=config.runtime.base_currency,
                strategy_capitals={
                    cluster.cluster_id: account.initial_cash if cluster.capital is None else cluster.capital.amount
                    for cluster in config.clusters
                },
                broker_gateway_id=None,
                account_initial_cash=account.initial_cash,
                market_rule_engine=market_rules,
                fee_resolver_config=OnlyFeeResolverConfig(
                    market_mode=OnlyFeeConfigurationMode.NONE,
                    broker_mode=OnlyFeeConfigurationMode.NONE,
                    broker_id="paper-shadow",
                ),
                market_fee_schedules=components.market_fee_schedules,
                broker_fee_schedules=components.broker_fee_schedules,
            )
            persistence = components.runtime_persistence_stores.create(
                OnlyRuntimePersistenceStoreCreateRequest(
                    config.engine_id,
                    config.runtime_id,
                    OnlyRuntimeMode.PAPER,
                    config.runtime.persistence,
                    state_root,
                    self._fingerprint(request),
                    None,
                    config.runtime.base_currency.code,
                    account.account_id,
                    config.market.profile.value,
                )
            )
            subscription = OnlyMarketDataSubscriptionRequest(
                f"paper-{config.runtime_id}",
                source_common.source_id,
                frozenset(by_instrument),
                frozenset({OnlyMarketDataType.BAR}),
                base_bar_types,
            )
            runtime = OnlyPaperRuntime(
                runtime_config,
                calendar,
                clock=clock,
                event_bus=event_bus,
                data_source=source,
                inbound_queue=inbound,
                execution_service=OnlyShadowExecutionService(),
                persistence_store=persistence,
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
            )
            for instrument in config.reference_data.instruments:
                runtime.register_instrument(instrument)
            for cluster in clusters:
                runtime.add_cluster(config.engine_id, cluster)
            source = None
            persistence = None
            clock = None
            event_bus = None
            return OnlyRuntimeBuildResult(runtime=runtime)
        except Exception as exc:
            if persistence is not None:
                persistence.close()
            if source is not None:
                source.stop()
                source.close()
            if event_bus is not None:
                event_bus.close()
            if clock is not None:
                clock.close()
            return self._failure(exc)

    @staticmethod
    def _validate(
        request: OnlyRuntimeBuildRequest,
    ) -> tuple[OnlyComponentFactoryRegistries, OnlyStreamingRuntimeConfig]:
        components = request.components
        if not isinstance(components, OnlyComponentFactoryRegistries):
            raise TypeError("Paper factory requires OnlyComponentFactoryRegistries")
        config = request.config
        streaming = OnlyStreamingRuntimeConfig.from_mapping(config.runtime.extensions)
        if streaming.execution_capability is not OnlyExecutionSubmissionCapability.SHADOW:
            raise ValueError("PAPER requires SHADOW execution capability")
        if config.runtime.persistence.checkpoint.enabled:
            raise ValueError("Paper checkpoint/restart is not supported in PR5.1")
        if len(tuple(item for item in config.data_sources if item.enabled)) != 1:
            raise ValueError("Paper requires exactly one enabled live DataSource")
        if len(config.accounts) != 1:
            raise ValueError("current schema requires one read-only Shadow authority Account")
        if any(item.enabled for item in config.brokers):
            raise ValueError("PAPER + SHADOW forbids enabled Broker adapters")
        return components, streaming

    @staticmethod
    def _market_rules(
        config: OnlyRuntimeAssemblyPlan,
        components: OnlyComponentFactoryRegistries,
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

        references = {
            str(instrument.instrument_id): only_instrument_reference(
                instrument,
                profile_id=config.market.profile.value,
            )
            for instrument in config.reference_data.instruments
        }
        engine = OnlyMarketRuleEngine(
            registry=components.market_profiles,
            compiler=components.market_rule_compiler,
            request=config.market.to_request(),
            runtime_mode=OnlyRuntimeMode.PAPER,
            references=references,
            advance_trading_day=advance,
        )
        for instrument in config.reference_data.instruments:
            engine.compiled_rules(
                str(instrument.instrument_id),
                calendar.trading_day_at(OnlyTimestamp.from_datetime(clock.now_utc())),
            )
        return engine

    @staticmethod
    def _fingerprint(request: OnlyRuntimeBuildRequest) -> str:
        payload = json.dumps(
            [dict(item.normalized_payload) for item in request.plan.cluster_configs],
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    def _failure(exc: Exception) -> OnlyRuntimeBuildResult:
        return OnlyRuntimeBuildResult(
            failure_code="RUNTIME_ASSEMBLY_FAILED",
            failure_message=f"{type(exc).__name__}: {exc}",
        )
