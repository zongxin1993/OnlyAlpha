from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Protocol, cast

from onlyalpha.account.enums import OnlyAccountType
from onlyalpha.account.models import OnlyAccountConfig, OnlyAccountValuation
from onlyalpha.account.reconciliation import OnlyAccountReconciliationService
from onlyalpha.account.views import OnlyAccountQueryView
from onlyalpha.broker.execution import OnlyBrokerExecutionService
from onlyalpha.broker.identifiers import OnlyBrokerGatewayId
from onlyalpha.broker.updates import OnlyBrokerInboundUpdate, OnlyBrokerTradeUpdate
from onlyalpha.broker.virtual.gateway import OnlyVirtualBrokerGateway
from onlyalpha.broker.virtual.scheduler import OnlyVirtualBrokerUpdateQueue
from onlyalpha.cache.base import OnlyCache
from onlyalpha.cluster.base import OnlyClusterState
from onlyalpha.cluster.manager import OnlyClusterExecutionResult, OnlyClusterManager
from onlyalpha.core.clock import OnlyBacktestClock, OnlyClockView, OnlyTimerEvent, OnlyTimerHandle
from onlyalpha.core.errors import OnlyLifecycleError
from onlyalpha.data.audit import OnlyMarketDataAuditStore, OnlyMarketDataEventPublisher
from onlyalpha.data.enums import OnlyMarketDataProcessingStatus, OnlyMarketDataQualityFlag, OnlyMarketDataType
from onlyalpha.data.gateway import OnlyInMemoryMarketDataGateway
from onlyalpha.data.identifiers import (
    OnlyDataSequence,
    OnlyDataVersion,
    OnlyMarketDataGatewayId,
    OnlyMarketDataSourceId,
    OnlyMarketDataUpdateId,
)
from onlyalpha.data.models import (
    OnlyBarUpdate,
    OnlyHistoricalBarRequest,
    OnlyHistoricalDataRange,
    OnlyHistoricalReplayConfig,
    OnlyHistoricalReplayResult,
    OnlyMarketDataInboundUpdate,
    OnlyMarketDataProcessingResult,
    OnlyMarketDataQuality,
)
from onlyalpha.data.ports import OnlyHistoricalDataSource
from onlyalpha.data.processor import (
    OnlyMarketDataDeduplicator,
    OnlyMarketDataGapDetector,
    OnlyMarketDataProcessor,
    OnlyMarketDataSequenceTracker,
)
from onlyalpha.data.queue import OnlyMarketDataInboundQueue
from onlyalpha.data.registry import OnlyMarketDataSourceRegistry
from onlyalpha.data.replay import OnlyHistoricalReplayService
from onlyalpha.data.sources import OnlyInMemoryHistoricalDataSource, OnlyInMemoryReferenceDataSource
from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import OnlyRuntimeMode, OnlySessionType
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyCalendarId, OnlyClusterId, OnlyInstrumentId, OnlyVenueId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.domain.market_rules import OnlyMarketRule
from onlyalpha.domain.time import OnlyTimestamp, OnlyTimeZone, OnlyTradingDay
from onlyalpha.domain.value import OnlyMoney, OnlyMultiplier
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.event.model import OnlyEventScope
from onlyalpha.execution.invariants import OnlyExecutionInvariantChecker
from onlyalpha.execution.models import OnlyExecutionProcessingResult, OnlyExecutionProcessorConfig
from onlyalpha.execution.processor import OnlyExecutionProcessor
from onlyalpha.execution.publisher import OnlyExecutionEventPublisher
from onlyalpha.execution.state import (
    OnlyExecutionSequenceTracker,
    OnlyExecutionUpdateDeduplicator,
    OnlyInMemoryExecutionAuditStore,
    OnlyInMemoryExecutionReconciliationQueue,
)
from onlyalpha.indicator.pipeline import OnlyIndicatorPipeline
from onlyalpha.market_data.aggregation.manager import OnlyBarAggregationManager
from onlyalpha.market_data.cache import OnlyMarketDataCache
from onlyalpha.market_data.dispatcher import (
    OnlyBarDispatchResult,
    OnlyClusterBarSubscription,
    OnlyStrategyBarDispatcher,
)
from onlyalpha.market_data.pipeline import OnlyMarketDataPipeline, OnlyMarketDataUpdateResult
from onlyalpha.market_data.snapshot import OnlyMarketDataSnapshot
from onlyalpha.market_data.subscriptions import OnlyBarSubscription, OnlyBarSubscriptionId
from onlyalpha.order.execution.models import OnlyGatewayOrderFillUpdate
from onlyalpha.order.execution.placeholder import OnlyPlaceholderExecutionService
from onlyalpha.order.execution.processor import OnlyOrderUpdateProcessor
from onlyalpha.order.execution.service import OnlyExecutionService
from onlyalpha.order.id_generator import OnlySequenceClientOrderIdGenerator, OnlySequenceOrderIdGenerator
from onlyalpha.order.manager import OnlyOrderManager
from onlyalpha.order.publisher import OnlyRuntimeOrderEventPublisherAdapter
from onlyalpha.order.query import OnlyOrderQueryService
from onlyalpha.order.service import OnlyOrderService
from onlyalpha.order.views import OnlyOrderServiceView
from onlyalpha.plugin.broker import OnlyBacktestBrokerGateway, OnlyBrokerInboundQueue
from onlyalpha.plugin.lifecycle import OnlyPluginResource
from onlyalpha.position.authority import OnlyPositionAuthorityPolicy
from onlyalpha.position.enums import OnlyPositionSide
from onlyalpha.position.keys import OnlyPositionAllocationKey
from onlyalpha.position.models import OnlyPositionAllocationSnapshot, OnlyPositionTrade, OnlySettlementResult
from onlyalpha.position.reconciliation import OnlyPositionReconciliationService
from onlyalpha.position.reservations import OnlyOrderPositionReservationAdapter
from onlyalpha.position.settlement import OnlySettlementService
from onlyalpha.position.views import OnlyPositionContextView, OnlyPositionRiskView
from onlyalpha.risk.contexts import OnlyRiskStateUpdateContext
from onlyalpha.risk.factory import OnlyRiskProfileFactory
from onlyalpha.risk.identifiers import OnlyRiskProfileId, OnlyRiskRuleId
from onlyalpha.risk.profile import OnlyRiskProfile, OnlyRiskProfileConfig, OnlyRiskRuleConfig
from onlyalpha.risk.publisher import OnlyRuntimeRiskEventPublisherAdapter
from onlyalpha.risk.rules.account import OnlyAvailableBalanceRiskRule, OnlyAvailablePositionRiskRule
from onlyalpha.risk.service import OnlyRiskService
from onlyalpha.risk.views import (
    OnlyAccountManagerRiskView,
    OnlyInstrumentRiskMappingView,
    OnlyMarketRuleRiskMappingView,
    OnlyRiskSnapshotView,
)
from onlyalpha.runtime.context import (
    OnlyClusterContext,
    OnlyInstrumentView,
    OnlyMarketDataView,
    OnlyRuntimeContextError,
    OnlyRuntimeLogger,
    OnlySubscriptionService,
    OnlyTimerService,
)
from onlyalpha.runtime.runtime import (
    OnlyManagedBarDispatchExecutor,
    OnlyRuntime,
    OnlyRuntimeAccountCashReservationAdapter,
    OnlyRuntimeAccountEventPublisherAdapter,
    OnlyRuntimeAssemblyConfig,
    OnlyRuntimeBarResult,
    OnlyRuntimeCompositeCashReservationAdapter,
    OnlyRuntimeError,
    OnlyRuntimeErrorPolicy,
    OnlyRuntimePositionEventPublisherAdapter,
    OnlyRuntimeServices,
    OnlyRuntimeState,
)
from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey
from onlyalpha.strategy_ledger.models import OnlyStrategyMarkPrice
from onlyalpha.strategy_ledger.order_port import OnlyOrderStrategyCashReservationAdapter
from onlyalpha.strategy_ledger.publisher import OnlyRuntimeStrategyLedgerEventPublisherAdapter
from onlyalpha.strategy_ledger.valuation import OnlyStrategyValuationService
from onlyalpha.strategy_ledger.views import OnlyStrategyLedgerContextView, OnlyStrategyLedgerRiskView


class OnlyBacktestRunPlanPort(Protocol):
    def execute(self, runtime: OnlyBacktestRuntime) -> object: ...


_LOGGER = logging.getLogger(__name__)


class OnlyBacktestRuntime(OnlyRuntime):
    """Synchronous, single-threaded and deterministically Bar-driven Runtime."""

    def __init__(
        self,
        config: OnlyRuntimeAssemblyConfig | str,
        calendar_or_clock: OnlyTradingCalendar | OnlyBacktestClock,
        initial_time_or_event_bus: datetime | int | OnlyEventBus | None = None,
        legacy_cache: OnlyCache | None = None,
        *,
        calendar: OnlyTradingCalendar | None = None,
        engine_id: str = "engine",
        run_plan: OnlyBacktestRunPlanPort | None = None,
        owned_clock: OnlyBacktestClock | None = None,
        owned_event_bus: OnlyEventBus | None = None,
        broker_gateway: OnlyBacktestBrokerGateway | None = None,
        broker_inbound_queue: OnlyBrokerInboundQueue | None = None,
        plugin_resources: tuple[OnlyPluginResource, ...] = (),
    ) -> None:
        if isinstance(config, str):
            if not isinstance(calendar_or_clock, OnlyBacktestClock):
                raise TypeError("legacy Runtime construction requires OnlyBacktestClock")
            runtime_config = OnlyRuntimeAssemblyConfig(engine_id, config, OnlyRuntimeMode.BACKTEST)
            clock = calendar_or_clock
            event_bus = initial_time_or_event_bus if isinstance(initial_time_or_event_bus, OnlyEventBus) else None
            selected_calendar = calendar or self._compatibility_calendar()
            del legacy_cache
        else:
            if config.mode is not OnlyRuntimeMode.BACKTEST:
                raise ValueError("OnlyBacktestRuntime requires BACKTEST mode")
            if not isinstance(calendar_or_clock, OnlyTradingCalendar):
                raise TypeError("Backtest Runtime requires a TradingCalendar")
            if not isinstance(initial_time_or_event_bus, (datetime, int)) or isinstance(
                initial_time_or_event_bus, bool
            ):
                raise TypeError("Backtest Runtime requires an initial UTC time")
            runtime_config = config
            selected_calendar = calendar_or_clock
            clock = owned_clock or OnlyBacktestClock(initial_time_or_event_bus)
            event_bus = owned_event_bus
        super().__init__(runtime_config)
        self._selected_calendar = selected_calendar
        scope = OnlyEventScope(runtime_config.engine_id, runtime_config.runtime_id)  # type: ignore[arg-type]
        owned_bus = event_bus or OnlyEventBus(
            runtime_config.event_capacity,
            scope=scope,
            queue_policy=runtime_config.event_queue_policy,
        )
        execution_event_publisher = OnlyExecutionEventPublisher(owned_bus)
        event_sink = cast(OnlyEventBus, execution_event_publisher)
        self._strategy_ledger_manager.bind_publisher(
            OnlyRuntimeStrategyLedgerEventPublisherAdapter(
                runtime_config.engine_id,  # type: ignore[arg-type]
                event_sink,
            )
        )
        self._position_manager.bind_publisher(
            OnlyRuntimePositionEventPublisherAdapter(
                runtime_config.engine_id,  # type: ignore[arg-type]
                event_sink,
            )
        )
        self._account_manager.bind_publisher(
            OnlyRuntimeAccountEventPublisherAdapter(
                runtime_config.engine_id,  # type: ignore[arg-type]
                event_sink,
            )
        )
        account_initial_cash = runtime_config.account_initial_cash or (
            runtime_config.virtual_broker_config.initial_cash
            if runtime_config.virtual_broker_config is not None
            else OnlyMoney(Decimal(str(runtime_config.strategy_initial_capital)), runtime_config.strategy_base_currency)
        )
        configured_gateway_id = runtime_config.broker_gateway_id
        if configured_gateway_id is None and runtime_config.virtual_broker_config is not None:
            configured_gateway_id = runtime_config.virtual_broker_config.gateway_id
        self._account_manager.create_account(
            OnlyAccountConfig(
                runtime_config.runtime_id,  # type: ignore[arg-type]
                runtime_config.default_account_id,  # type: ignore[arg-type]
                (str(configured_gateway_id) if configured_gateway_id is not None else "placeholder"),
                OnlyAccountType.CASH,
                runtime_config.strategy_base_currency,
                account_initial_cash,
            ),
            OnlyTimestamp.from_unix_nanos(clock.timestamp_ns()),
        )
        market_cache = OnlyMarketDataCache(runtime_config.history_limit)
        aggregation = OnlyBarAggregationManager(selected_calendar, clock)
        indicators = OnlyIndicatorPipeline()
        pipeline = OnlyMarketDataPipeline(
            runtime_config.engine_id,  # type: ignore[arg-type]
            runtime_config.runtime_id,  # type: ignore[arg-type]
            clock,
            market_cache,
            aggregation,
            indicators,
        )
        self._subscriptions: dict[OnlyClusterId, OnlyClusterBarSubscription] = {}
        self._timer_handles: dict[OnlyClusterId, dict[str, OnlyTimerHandle]] = {}
        self._current_snapshots: dict[OnlyClusterId, OnlyMarketDataSnapshot] = {}
        self._timer_results: list[OnlyClusterExecutionResult] = []
        self._instruments: dict[OnlyInstrumentId, OnlyInstrument] = {}
        self._known_market_data_instruments: set[OnlyInstrumentId] = set()
        self._market_rules: dict[OnlyInstrumentId, OnlyMarketRule] = {}
        self._risk_profile_factory = OnlyRiskProfileFactory()
        manager = OnlyClusterManager(runtime_config.runtime_id, self._make_context, self._cleanup_cluster)  # type: ignore[arg-type]
        executor = OnlyManagedBarDispatchExecutor(manager, self._set_current_snapshot, self._prepare_risk_snapshot)
        dispatcher = OnlyStrategyBarDispatcher(pipeline, OnlyClockView(clock), executor)
        order_manager = OnlyOrderManager(
            runtime_config.engine_id,  # type: ignore[arg-type]
            runtime_config.runtime_id,  # type: ignore[arg-type]
            OnlySequenceOrderIdGenerator(runtime_config.runtime_id),  # type: ignore[arg-type]
            OnlySequenceClientOrderIdGenerator(runtime_config.runtime_id),  # type: ignore[arg-type]
        )
        order_publisher = OnlyRuntimeOrderEventPublisherAdapter(event_sink)
        order_query = OnlyOrderQueryService(order_manager)
        position_manager = self._position_manager
        allocation_manager = self._allocation_manager
        position_query = self._position_query
        position_reservations = self._position_reservation_manager
        order_position_reservations = OnlyOrderPositionReservationAdapter(position_reservations)
        strategy_cash_reservations = OnlyOrderStrategyCashReservationAdapter(
            self._strategy_ledger_manager,
            runtime_config.strategy_base_currency,
            self._instruments,
            lambda order: (
                self._current_snapshots[order.cluster_id].primary_bar.close
                if order.cluster_id in self._current_snapshots
                else None
            ),
        )
        account_cash_reservations = OnlyRuntimeAccountCashReservationAdapter(
            self._account_manager,
            runtime_config.strategy_base_currency,
            self._instruments,
            lambda order: (
                self._current_snapshots[order.cluster_id].primary_bar.close
                if order.cluster_id in self._current_snapshots
                else None
            ),
        )
        order_cash_reservations = OnlyRuntimeCompositeCashReservationAdapter(
            account_cash_reservations,
            strategy_cash_reservations,
        )
        self._account_cash_reservations = account_cash_reservations
        risk_service = OnlyRiskService(
            runtime_config.engine_id,  # type: ignore[arg-type]
            runtime_config.runtime_id,  # type: ignore[arg-type]
            OnlyClockView(clock),
            selected_calendar,
            OnlyInstrumentRiskMappingView(self._instruments),
            OnlyMarketRuleRiskMappingView(self._market_rules),
            order_query,
            OnlyRuntimeRiskEventPublisherAdapter(event_sink),
            account_rules=(OnlyAvailableBalanceRiskRule(), OnlyAvailablePositionRiskRule()),
            account_risk=OnlyAccountManagerRiskView(self._account_query),
            position_risk=OnlyPositionRiskView(position_query, clock.timestamp_ns),
            strategy_ledger_risk=OnlyStrategyLedgerRiskView(
                self._strategy_ledger_query, runtime_config.strategy_base_currency
            ),
        )
        broker_inbound = (
            broker_inbound_queue
            if broker_inbound_queue is not None
            else OnlyVirtualBrokerUpdateQueue(runtime_config.event_capacity)
        )
        selected_broker_gateway = broker_gateway or (
            OnlyVirtualBrokerGateway(
                runtime_config.virtual_broker_config,
                runtime_config.runtime_id,  # type: ignore[arg-type]
                clock,
                broker_inbound.put,
            )
            if runtime_config.virtual_broker_config is not None
            else None
        )
        execution_service: OnlyExecutionService = (
            OnlyBrokerExecutionService(selected_broker_gateway, clock)
            if selected_broker_gateway is not None
            else OnlyPlaceholderExecutionService()
        )
        order_service = OnlyOrderService(
            order_manager,
            execution_service,
            order_publisher,
            lambda: OnlyTimestamp.from_unix_nanos(clock.timestamp_ns()),
            risk_service,
            risk_service.make_evaluation_context,
            order_position_reservations,
            order_cash_reservations,
        )
        order_update_processor = OnlyOrderUpdateProcessor(
            runtime_config.runtime_id,  # type: ignore[arg-type]
            order_manager,
            order_publisher,
            risk_service,
            order_position_reservations,
            order_cash_reservations,
        )
        account_reconciliation = OnlyAccountReconciliationService(self._account_manager)
        position_reconciliation = OnlyPositionReconciliationService(
            runtime_config.runtime_id,  # type: ignore[arg-type]
            position_manager,
            allocation_manager,
            OnlyPositionAuthorityPolicy(runtime_config.mode),
            position_reservations,
        )
        execution_audit_store = OnlyInMemoryExecutionAuditStore()
        execution_reconciliation_queue = OnlyInMemoryExecutionReconciliationQueue()
        execution_update_deduplicator = OnlyExecutionUpdateDeduplicator()
        execution_sequence_tracker = OnlyExecutionSequenceTracker()
        execution_invariant_checker = OnlyExecutionInvariantChecker(
            position_manager,
            allocation_manager,
            self._strategy_ledger_manager,
            self._account_manager,
            position_reservations,
            risk_service,
        )
        execution_processor = OnlyExecutionProcessor(
            OnlyExecutionProcessorConfig(
                runtime_config.engine_id,  # type: ignore[arg-type]
                runtime_config.runtime_id,  # type: ignore[arg-type]
                (
                    runtime_config.broker_gateway_id
                    or (
                        runtime_config.virtual_broker_config.gateway_id
                        if runtime_config.virtual_broker_config is not None
                        else OnlyBrokerGatewayId("placeholder")
                    ),
                ),
                (runtime_config.default_account_id,),  # type: ignore[arg-type]
            ),
            clock,
            self._instruments,
            order_query,
            order_update_processor,
            position_manager,
            allocation_manager,
            self._strategy_ledger_manager,
            self._account_manager,
            risk_service,
            position_reservations,
            order_position_reservations,
            account_cash_reservations.consume,
            account_cash_reservations.release,
            position_reconciliation,
            account_reconciliation,
            execution_invariant_checker,
            execution_event_publisher,
            execution_audit_store,
            execution_reconciliation_queue,
            execution_update_deduplicator,
            execution_sequence_tracker,
            self._apply_strategy_valuation,
            self._apply_account_valuation,
            self._set_broker_connection_state,
            runtime_config.strategy_base_currency,
        )
        self._broker_results: list[object] = []
        historical_source_id = OnlyMarketDataSourceId(f"{runtime_config.runtime_id}-local-history")
        realtime_source_id = OnlyMarketDataSourceId(f"{runtime_config.runtime_id}-in-memory-live")
        market_data_source_registry = OnlyMarketDataSourceRegistry()
        historical_data_source = OnlyInMemoryHistoricalDataSource(historical_source_id)
        market_data_source_registry.register(historical_data_source, priority=0)
        market_data_inbound = OnlyMarketDataInboundQueue(runtime_config.event_capacity)
        market_data_gateway = OnlyInMemoryMarketDataGateway(
            OnlyMarketDataGatewayId(f"{runtime_config.runtime_id}-market-data"),
            realtime_source_id,
            market_data_inbound.put,
        )
        market_data_gateway.connect()
        market_data_gateway.authenticate()
        market_data_source_registry.register(market_data_gateway, priority=10)
        self._market_calendars: dict[OnlyInstrumentId, OnlyTradingCalendar] = {}
        reference_data_source = OnlyInMemoryReferenceDataSource(
            OnlyMarketDataSourceId(f"{runtime_config.runtime_id}-reference"),
            self._instruments,
            {selected_calendar.calendar_id: selected_calendar},
            self._market_rules,
        )
        market_data_audit_store = OnlyMarketDataAuditStore()
        market_data_deduplicator = OnlyMarketDataDeduplicator()
        market_data_sequence_tracker = OnlyMarketDataSequenceTracker()
        market_data_gap_detector = OnlyMarketDataGapDetector(self._market_calendars)
        market_data_event_publisher = OnlyMarketDataEventPublisher()
        self._last_market_trading_day: OnlyTradingDay | None = None

        def drain_execution_updates() -> None:
            results = execution_processor.process_many(broker_inbound.drain())
            self._broker_results.extend(results)

        def before_market_dispatch(result: OnlyMarketDataUpdateResult) -> None:
            owned_bus.publish_many(result.facts)
            trading_day = OnlyTradingDay(result.base_bar.trading_day)
            if self._last_market_trading_day is None:
                self._last_market_trading_day = trading_day
            elif trading_day != self._last_market_trading_day:
                self._services.settlement_service.settle_account(
                    runtime_config.default_account_id,  # type: ignore[arg-type]
                    self._last_market_trading_day,
                    trading_day,
                )
                self._last_market_trading_day = trading_day
            self._apply_market_valuations(result.base_bar, trading_day)
            if selected_broker_gateway is not None:
                selected_broker_gateway.on_bar(result.base_bar)
                drain_execution_updates()

        def after_market_dispatch() -> None:
            if selected_broker_gateway is not None:
                selected_broker_gateway.run_due()
                drain_execution_updates()
            owned_bus.drain()

        market_data_processor = OnlyMarketDataProcessor(
            runtime_config.runtime_id,  # type: ignore[arg-type]
            clock,
            self._known_market_data_instruments,
            market_data_source_registry,
            pipeline,
            dispatcher,
            market_data_deduplicator,
            market_data_sequence_tracker,
            market_data_gap_detector,
            market_data_audit_store,
            market_data_event_publisher,
            before_market_dispatch,
            after_market_dispatch,
        )
        historical_replay_service = OnlyHistoricalReplayService(clock, market_data_processor)
        self._services = OnlyRuntimeServices(
            clock,
            owned_bus,
            market_cache,
            aggregation,
            indicators,
            pipeline,
            dispatcher,
            manager,
            order_manager,
            order_query,
            order_service,
            order_update_processor,
            execution_service,
            risk_service,
            position_manager,
            allocation_manager,
            position_reservations,
            position_query,
            self._strategy_ledger_manager,
            self._strategy_ledger_query,
            OnlySettlementService(position_manager, allocation_manager),
            OnlyStrategyValuationService(),
            self._account_manager,
            self._account_query,
            broker_inbound,
            selected_broker_gateway,
            execution_processor,
            execution_event_publisher,
            execution_audit_store,
            execution_reconciliation_queue,
            execution_update_deduplicator,
            execution_sequence_tracker,
            market_data_source_registry,
            historical_data_source,
            reference_data_source,
            market_data_gateway,
            market_data_inbound,
            market_data_processor,
            historical_replay_service,
            market_data_audit_store,
            market_data_deduplicator,
            market_data_sequence_tracker,
            market_data_gap_detector,
        )
        self._valuation_versions: dict[OnlyStrategyLedgerKey, int] = {}
        self._account_valuation_version = 0
        self._broker_connection_state: object | None = None
        self._legacy_market_data_sequence = 0
        self._run_plan = run_plan
        resources = plugin_resources
        if not resources and selected_broker_gateway is not None:
            resources = (selected_broker_gateway,)
        if resources:
            self._bind_plugin_resources(resources)

    def run(self) -> object:
        """Execute a configured product backtest through Replay and Runtime-owned services."""

        if self._run_plan is None:
            raise OnlyRuntimeError("run() requires a Factory-provided Backtest RunPlan")
        return self._run_plan.execute(self)

    def register_instrument(
        self,
        instrument: OnlyInstrument,
        market_rule: OnlyMarketRule | None = None,
    ) -> None:
        if self._state is not OnlyRuntimeState.CREATED or self.clusters:
            raise OnlyLifecycleError("Instruments must be registered before Clusters while Runtime is CREATED")
        if instrument.instrument_id in self._instruments:
            raise ValueError(f"duplicate Runtime Instrument: {instrument.instrument_id}")
        self._instruments[instrument.instrument_id] = instrument
        self._known_market_data_instruments.add(instrument.instrument_id)
        self._market_calendars[instrument.instrument_id] = (
            self._services.reference_data_source.calendar(instrument.trading_calendar_id or OnlyCalendarId("XSHG"))
            or self._selected_calendar
        )
        if market_rule is not None:
            self._market_rules[instrument.instrument_id] = market_rule

    def process_bar(self, bar: OnlyBar) -> OnlyRuntimeBarResult:
        """Compatibility facade implemented as a one-record local historical replay."""

        if self._state is not OnlyRuntimeState.RUNNING:
            raise OnlyLifecycleError("Runtime accepts Bars only while RUNNING")
        try:
            self._legacy_market_data_sequence += 1
            source_id = self._services.historical_data_source.source_id
            data_version = OnlyDataVersion("runtime-local-v1")
            inbound = OnlyMarketDataInboundUpdate(
                OnlyMarketDataUpdateId(
                    f"MD-{self.config.runtime_id}-{self._legacy_market_data_sequence:012d}-"
                    f"{OnlyTimestamp.from_datetime(bar.ts_event).unix_nanos}"
                ),
                self.config.runtime_id,  # type: ignore[arg-type]
                source_id,
                OnlyDataSequence(self._legacy_market_data_sequence),
                data_version,
                bar.instrument_id,
                OnlyMarketDataType.BAR,
                OnlyBarUpdate(bar),
                OnlyTimestamp.from_datetime(bar.ts_event),
                OnlyTimestamp.from_datetime(bar.ts_init),
                OnlyMarketDataQuality(frozenset({OnlyMarketDataQualityFlag.UNADJUSTED})),
            )
            source = OnlyInMemoryHistoricalDataSource(source_id, (inbound,))
            request = OnlyHistoricalBarRequest(
                f"runtime-bar-{self._legacy_market_data_sequence}",
                frozenset({bar.instrument_id}),
                frozenset({bar.bar_type}),
                OnlyHistoricalDataRange(
                    bar.ts_event - timedelta(microseconds=1), bar.ts_event + timedelta(microseconds=1)
                ),
                data_version,
                batch_size=1,
            )
            stream = source.load_bars(request)
            before_events = len(self._services.event_bus.dispatch_results)
            replay = self._services.historical_replay_service.run(
                self._services.historical_replay_service.prepare(
                    OnlyHistoricalReplayConfig((stream,), source_priority=(source_id,))
                )
            )
            if not replay.events:
                raise OnlyRuntimeError("single-Bar Replay produced no processing event")
            replay_event = replay.events[-1]
            processing = replay_event.result
            if processing.status in (
                OnlyMarketDataProcessingStatus.REJECTED,
                OnlyMarketDataProcessingStatus.FAILED,
                OnlyMarketDataProcessingStatus.STALE,
            ):
                message = processing.validation.reasons or (
                    () if processing.failure is None else (processing.failure.message,)
                )
                raise OnlyRuntimeError(f"market-data processing failed: {message}")
            update = cast(OnlyMarketDataUpdateResult, processing.pipeline_result)
            dispatches = tuple(cast(OnlyBarDispatchResult, item) for item in processing.dispatches)
            dispatched = len(self._services.event_bus.dispatch_results) - before_events
            if self.config.cluster_error_policy is OnlyRuntimeErrorPolicy.FAIL_RUNTIME and any(
                item.called and not item.succeeded for item in dispatches
            ):
                self._state = OnlyRuntimeState.FAILED
                self._last_error = "Cluster callback failed under FAIL_RUNTIME policy"
            return OnlyRuntimeBarResult(replay_event.advance, update, dispatches, dispatched)
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            self._state = OnlyRuntimeState.FAILED
            raise

    def receive_market_data_update(self, update: OnlyMarketDataInboundUpdate) -> None:
        """Real-time Gateway management port; never exposed through Cluster Context."""

        if self._state is not OnlyRuntimeState.RUNNING:
            raise OnlyLifecycleError("Runtime accepts market data only while RUNNING")
        self._services.market_data_inbound.put(update)

    def drain_market_data_inbound(self) -> tuple[OnlyMarketDataProcessingResult, ...]:
        """Drain the independent market-data FIFO through the sole Processor."""

        if self._state is not OnlyRuntimeState.RUNNING:
            raise OnlyLifecycleError("Runtime accepts market data only while RUNNING")
        results: list[OnlyMarketDataProcessingResult] = []
        while (update := self._services.market_data_inbound.get()) is not None:
            results.append(self._services.market_data_processor.process(update))
        return tuple(results)

    def replay_historical_bars(
        self,
        source: OnlyHistoricalDataSource,
        request: OnlyHistoricalBarRequest,
    ) -> OnlyHistoricalReplayResult:
        """Load through HistoricalDataSource, then merge/advance/process through ReplayService."""

        if self._state is not OnlyRuntimeState.RUNNING:
            raise OnlyLifecycleError("Runtime accepts historical replay only while RUNNING")
        if not self._services.market_data_source_registry.contains(source.source_id):
            self._services.market_data_source_registry.register(source)
        stream = source.load_bars(request)
        cursor = self._services.historical_replay_service.prepare(
            OnlyHistoricalReplayConfig((stream,), source_priority=(source.source_id,))
        )
        return self._services.historical_replay_service.run(cursor)

    def drain_broker_inbound(self) -> tuple[object, ...]:
        """Drain FIFO updates through the Runtime-owned sole business processor."""

        if self._state is not OnlyRuntimeState.RUNNING:
            raise OnlyLifecycleError("Runtime accepts Broker updates only while RUNNING")
        results = list(self._services.execution_processor.process_many(self._services.broker_inbound.drain()))
        self._broker_results.extend(results)
        self._services.event_bus.drain()
        return tuple(results)

    def receive_broker_update(self, update: OnlyBrokerInboundUpdate) -> None:
        """Runtime management inbound Port used by Gateways and explicit fault adapters."""

        self._services.broker_inbound.put(update)

    @property
    def broker_results(self) -> tuple[object, ...]:
        return tuple(self._broker_results)

    def process_trade(
        self,
        update: OnlyBrokerTradeUpdate,
    ) -> OnlyExecutionProcessingResult:
        """Convenience ingress that still enforces Queue then ExecutionProcessor."""

        before = len(self._broker_results)
        self.receive_broker_update(update)
        self.drain_broker_inbound()
        result = self._broker_results[before]
        if not isinstance(result, OnlyExecutionProcessingResult):
            raise TypeError("Trade ingress did not produce an Execution processing result")
        return result

    def settle_positions(
        self,
        previous_trading_day: OnlyTradingDay,
        trading_day: OnlyTradingDay,
    ) -> tuple[OnlySettlementResult, ...]:
        """Run existing calendar-derived Position and Allocation settlement."""

        if self._state is not OnlyRuntimeState.RUNNING:
            raise OnlyLifecycleError("Runtime settles Positions only while RUNNING")
        return self._services.settlement_service.settle_account(
            self.config.default_account_id,  # type: ignore[arg-type]
            previous_trading_day,
            trading_day,
        )

    def _validate_trade(
        self,
        update: OnlyGatewayOrderFillUpdate,
        trade: OnlyPositionTrade,
        order: object,
    ) -> None:
        from onlyalpha.domain.execution import OnlyOrderSnapshot

        if not isinstance(order, OnlyOrderSnapshot):
            raise TypeError("Order query must return OnlyOrderSnapshot")
        fill = update.fill
        if trade.cluster_id is None:
            raise ValueError("Runtime strategy Trade requires cluster attribution")
        expected = (
            update.runtime_id,
            update.order_id,
            fill.trade_id,
            fill.venue_trade_id,
            fill.price,
            fill.quantity,
            fill.ts_event,
            fill.ts_init,
            order.cluster_id,
            order.account_id,
            order.instrument_id,
            order.side,
            order.offset,
        )
        actual = (
            trade.runtime_id,
            trade.order_id,
            trade.trade_id,
            trade.venue_trade_id,
            trade.price,
            trade.quantity,
            trade.ts_event,
            trade.ts_init,
            trade.cluster_id,
            trade.account_id,
            trade.instrument_id,
            trade.side,
            trade.offset,
        )
        if actual != expected:
            raise ValueError("Position Trade does not match standardized Order Fill")
        expected_fee = OnlyMoney(Decimal(0), self.config.strategy_base_currency) if fill.fee is None else fill.fee
        if trade.fee != expected_fee:
            raise ValueError("Position Trade fee does not match Order Fill")
        instrument = self._instruments.get(trade.instrument_id)
        if instrument is None or trade.multiplier != instrument.contract_multiplier:
            raise ValueError("Position Trade requires the registered Instrument multiplier")
        if trade.position_side is not OnlyPositionSide.LONG:
            raise ValueError("first-phase Runtime trade orchestration supports LONG only")

    def _allocation_snapshot(
        self,
        key: OnlyPositionAllocationKey,
    ) -> OnlyPositionAllocationSnapshot | None:
        active = self._services.allocation_manager.get_snapshot(key)
        if active is not None:
            return active
        return next(
            (item for item in reversed(self._services.allocation_manager.closed()) if item.key == key),
            None,
        )

    def _allocation_money(
        self,
        snapshot: OnlyPositionAllocationSnapshot | None,
        *,
        realized: bool,
    ) -> OnlyMoney:
        if snapshot is None:
            return OnlyMoney(Decimal(0), self.config.strategy_base_currency)
        return snapshot.realized_pnl if realized else snapshot.fees

    def _allocation_cost(
        self,
        snapshot: OnlyPositionAllocationSnapshot | None,
        trade: OnlyPositionTrade,
    ) -> OnlyMoney:
        if snapshot is None or snapshot.average_open_price is None:
            return OnlyMoney(Decimal(0), self.config.strategy_base_currency)
        quantum = Decimal(1).scaleb(-self.config.strategy_base_currency.precision)
        amount = (snapshot.average_open_price.value * snapshot.total_quantity.value * trade.multiplier.value).quantize(
            quantum
        )
        return OnlyMoney(amount, self.config.strategy_base_currency)

    def _apply_strategy_valuation(
        self,
        key: OnlyStrategyLedgerKey,
        trade: OnlyPositionTrade,
    ) -> None:
        allocations = self._services.allocation_manager.list_by_cluster(key.cluster_id)
        candidates = tuple(
            bar
            for registration in self._subscriptions.values()
            for bar_type in registration.subscription.bar_types
            if bar_type.instrument_id == trade.instrument_id
            if (bar := self._services.market_data_cache.latest_closed(bar_type)) is not None
        )
        if allocations and not candidates:
            raise ValueError("Strategy valuation requires a closed market-data mark")
        marks: tuple[OnlyStrategyMarkPrice, ...] = ()
        trading_day: OnlyTradingDay | None = None
        if candidates:
            latest = max(candidates, key=lambda item: item.ts_event)
            version = self._valuation_versions.get(key, 0) + 1
            marks = (OnlyStrategyMarkPrice(trade.instrument_id, latest.close, version, "MARKET_DATA_SNAPSHOT"),)
            trading_day = OnlyTradingDay(latest.trading_day)
        else:
            version = self._valuation_versions.get(key, 0) + 1
        self._valuation_versions[key] = version
        valuation = self._services.strategy_valuation_service.value(
            key,
            allocations,
            marks,
            {trade.instrument_id: trade.multiplier},
            trade.ts_event,
            trade.ts_init,
            version,
        )
        self._services.strategy_ledger_manager.apply_valuation(valuation, trading_day)

    def _apply_account_valuation(self, trade: OnlyPositionTrade) -> None:
        market_value = Decimal(0)
        unrealized = Decimal(0)
        for position in self._services.position_manager.list_by_account(trade.account_id):
            instrument = self._instruments[position.key.instrument_id]
            candidates = tuple(
                bar
                for registration in self._subscriptions.values()
                for bar_type in registration.subscription.bar_types
                if bar_type.instrument_id == position.key.instrument_id
                if (bar := self._services.market_data_cache.latest_closed(bar_type)) is not None
            )
            if not candidates or position.average_open_price is None:
                raise ValueError("Account valuation requires a closed mark for every open Position")
            mark = max(candidates, key=lambda item: item.ts_event).close
            multiplier = instrument.contract_multiplier.value
            market_value += mark.value * position.total_quantity.value * multiplier
            unrealized += (mark.value - position.average_open_price.value) * position.total_quantity.value * multiplier
        quantum = Decimal(1).scaleb(-self.config.strategy_base_currency.precision)
        self._account_valuation_version += 1
        self._services.account_manager.apply_valuation(
            OnlyAccountValuation(
                trade.runtime_id,
                trade.account_id,
                OnlyMoney(market_value.quantize(quantum), self.config.strategy_base_currency),
                OnlyMoney(unrealized.quantize(quantum), self.config.strategy_base_currency),
                trade.ts_init,
                self._account_valuation_version,
            )
        )

    def _apply_market_valuations(self, bar: OnlyBar, trading_day: OnlyTradingDay) -> None:
        """Mark Runtime-owned account and strategy views before Broker reconciliation and strategy callbacks."""

        timestamp = OnlyTimestamp.from_datetime(bar.ts_event)
        for ledger in self._services.strategy_ledger_manager.list_ledgers():
            allocations = self._services.allocation_manager.list_by_cluster(ledger.key.cluster_id)
            marks: list[OnlyStrategyMarkPrice] = []
            multipliers: dict[OnlyInstrumentId, OnlyMultiplier] = {}
            next_version = self._valuation_versions.get(ledger.key, 0) + 1
            for allocation in allocations:
                instrument = self._instruments[allocation.key.instrument_id]
                candidates = tuple(
                    cached
                    for registration in self._subscriptions.values()
                    for bar_type in registration.subscription.bar_types
                    if bar_type.instrument_id == allocation.key.instrument_id
                    if (cached := self._services.market_data_cache.latest_closed(bar_type)) is not None
                )
                if not candidates:
                    raise ValueError("Strategy mark-to-market requires a closed Bar for every Allocation")
                latest = max(candidates, key=lambda item: item.ts_event)
                marks.append(
                    OnlyStrategyMarkPrice(
                        allocation.key.instrument_id,
                        latest.close,
                        next_version,
                        "MARKET_DATA_SNAPSHOT",
                    )
                )
                multipliers[allocation.key.instrument_id] = instrument.contract_multiplier
            self._valuation_versions[ledger.key] = next_version
            valuation = self._services.strategy_valuation_service.value(
                ledger.key,
                allocations,
                tuple(marks),
                multipliers,
                timestamp,
                timestamp,
                next_version,
            )
            self._services.strategy_ledger_manager.apply_valuation(valuation, trading_day)

        market_value = Decimal(0)
        unrealized = Decimal(0)
        for position in self._services.position_manager.list_by_account(self.config.default_account_id):  # type: ignore[arg-type]
            instrument = self._instruments[position.key.instrument_id]
            candidates = tuple(
                cached
                for registration in self._subscriptions.values()
                for bar_type in registration.subscription.bar_types
                if bar_type.instrument_id == position.key.instrument_id
                if (cached := self._services.market_data_cache.latest_closed(bar_type)) is not None
            )
            if not candidates or position.average_open_price is None:
                raise ValueError("Account mark-to-market requires a closed Bar for every Position")
            mark = max(candidates, key=lambda item: item.ts_event).close
            multiplier = instrument.contract_multiplier.value
            market_value += mark.value * position.total_quantity.value * multiplier
            unrealized += (mark.value - position.average_open_price.value) * position.total_quantity.value * multiplier
        quantum = Decimal(1).scaleb(-self.config.strategy_base_currency.precision)
        self._account_valuation_version += 1
        self._services.account_manager.apply_valuation(
            OnlyAccountValuation(
                self.config.runtime_id,  # type: ignore[arg-type]
                self.config.default_account_id,  # type: ignore[arg-type]
                OnlyMoney(market_value.quantize(quantum), self.config.strategy_base_currency),
                OnlyMoney(unrealized.quantize(quantum), self.config.strategy_base_currency),
                timestamp,
                self._account_valuation_version,
            )
        )

    def _set_broker_connection_state(self, state: object) -> None:
        self._broker_connection_state = state

    def _make_context(self, cluster_id: OnlyClusterId) -> OnlyClusterContext:
        def allowed_bar_types() -> frozenset[OnlyBarType]:
            registration = self._subscriptions.get(cluster_id)
            return frozenset() if registration is None else frozenset(registration.subscription.bar_types)

        def latest(bar_type: OnlyBarType) -> OnlyBar | None:
            return self._services.market_data_cache.latest_closed(bar_type)

        def history(bar_type: OnlyBarType, count: int) -> tuple[OnlyBar, ...]:
            return self._services.market_data_cache.history(bar_type, count)

        def current_snapshot() -> OnlyMarketDataSnapshot | None:
            return self._current_snapshots.get(cluster_id)

        return OnlyClusterContext(
            self.config.engine_id,  # type: ignore[arg-type]
            self.config.runtime_id,  # type: ignore[arg-type]
            cluster_id,
            self.config.mode,
            OnlyClockView(self._services.clock),
            OnlyMarketDataView(allowed_bar_types, latest, history, current_snapshot),
            OnlyInstrumentView(self._instruments),
            OnlySubscriptionService(lambda subscription: self._subscribe(cluster_id, subscription)),
            OnlyTimerService(
                lambda timer_id, when_ns: self._schedule_at(cluster_id, timer_id, when_ns),
                lambda timer_id, delay_ns: self._schedule_after(cluster_id, timer_id, delay_ns),
                lambda timer_id, interval_ns, start_ns: self._schedule_every(
                    cluster_id, timer_id, interval_ns, start_ns
                ),
                lambda timer_id: self._cancel_timer(cluster_id, timer_id),
            ),
            OnlyOrderServiceView(
                cluster_id,
                self.config.default_account_id,  # type: ignore[arg-type]
                self._services.order_service,
                self._services.order_query,
                lambda: self._order_commands_enabled(cluster_id),
            ),
            OnlyPositionContextView(
                self.config.default_account_id,  # type: ignore[arg-type]
                cluster_id,
                self._services.position_query,
            ),
            OnlyAccountQueryView(
                self.config.default_account_id,  # type: ignore[arg-type]
                self._services.account_query,
            ),
            OnlyStrategyLedgerContextView(
                OnlyStrategyLedgerKey(
                    self.config.runtime_id,  # type: ignore[arg-type]
                    self.config.default_account_id,  # type: ignore[arg-type]
                    cluster_id,
                    self.config.strategy_base_currency,
                ),
                self._services.strategy_ledger_query,
            ),
            OnlyRiskSnapshotView(lambda: self._services.risk_service.get_snapshot(cluster_id)),
            OnlyRuntimeLogger(_LOGGER, self.config.runtime_id, cluster_id, self.config.mode),  # type: ignore[arg-type]
        )

    def _order_commands_enabled(self, cluster_id: OnlyClusterId) -> bool:
        return self._state in {OnlyRuntimeState.READY, OnlyRuntimeState.RUNNING} and (
            self._services.cluster_manager.state_of(cluster_id) in {OnlyClusterState.STARTING, OnlyClusterState.RUNNING}
        )

    def _subscribe(
        self,
        cluster_id: OnlyClusterId,
        subscription: OnlyBarSubscription,
    ) -> OnlyBarSubscriptionId:
        if self._services.cluster_manager.state_of(cluster_id) is not OnlyClusterState.LOADED:
            raise OnlyRuntimeContextError("Bar subscriptions are accepted only during Cluster initialization")
        if cluster_id in self._subscriptions:
            raise OnlyRuntimeContextError("first-phase Cluster supports one Bar subscription")
        cluster = next(item for item in self.clusters if item.config.cluster_id == str(cluster_id))
        registration = OnlyClusterBarSubscription(cluster, subscription)
        self._known_market_data_instruments.update(item.instrument_id for item in subscription.bar_types)
        self._services.dispatcher.register(registration)
        self._subscriptions[cluster_id] = registration
        return subscription.subscription_id

    def _timer_name(self, cluster_id: OnlyClusterId, timer_id: str) -> str:
        normalized = timer_id.strip()
        if not normalized or ":" in normalized:
            raise OnlyRuntimeContextError("timer_id must be non-empty and cannot contain ':'")
        return f"{self.config.runtime_id}:{cluster_id}:{normalized}"

    def _timer_callback(self, cluster_id: OnlyClusterId, event: OnlyTimerEvent) -> None:
        self._timer_results.append(self._services.cluster_manager.execute_timer(cluster_id, event))

    def _remember_timer(self, cluster_id: OnlyClusterId, timer_id: str, handle: OnlyTimerHandle) -> OnlyTimerHandle:
        handles = self._timer_handles.setdefault(cluster_id, {})
        if timer_id in handles:
            raise OnlyRuntimeContextError(f"duplicate Cluster timer_id: {timer_id}")
        handles[timer_id] = handle
        return handle

    def _schedule_at(self, cluster_id: OnlyClusterId, timer_id: str, when_ns: int) -> OnlyTimerHandle:
        self._require_timer_permission(cluster_id)
        handle = self._services.clock.schedule_at(
            self._timer_name(cluster_id, timer_id),
            when_ns,
            lambda event: self._timer_callback(cluster_id, event),
        )
        return self._remember_timer(cluster_id, timer_id, handle)

    def _schedule_after(self, cluster_id: OnlyClusterId, timer_id: str, delay_ns: int) -> OnlyTimerHandle:
        self._require_timer_permission(cluster_id)
        handle = self._services.clock.schedule_after(
            self._timer_name(cluster_id, timer_id),
            delay_ns,
            lambda event: self._timer_callback(cluster_id, event),
        )
        return self._remember_timer(cluster_id, timer_id, handle)

    def _schedule_every(
        self,
        cluster_id: OnlyClusterId,
        timer_id: str,
        interval_ns: int,
        start_ns: int | None,
    ) -> OnlyTimerHandle:
        self._require_timer_permission(cluster_id)
        handle = self._services.clock.schedule_every(
            self._timer_name(cluster_id, timer_id),
            interval_ns,
            lambda event: self._timer_callback(cluster_id, event),
            start_ns=start_ns,
        )
        return self._remember_timer(cluster_id, timer_id, handle)

    def _cancel_timer(self, cluster_id: OnlyClusterId, timer_id: str) -> bool:
        handle = self._timer_handles.get(cluster_id, {}).get(timer_id)
        return False if handle is None else handle.cancel()

    def _require_timer_permission(self, cluster_id: OnlyClusterId) -> None:
        if self._services.cluster_manager.state_of(cluster_id) not in {
            OnlyClusterState.LOADED,
            OnlyClusterState.INITIALIZED,
            OnlyClusterState.STARTING,
            OnlyClusterState.RUNNING,
            OnlyClusterState.PAUSED,
        }:
            raise OnlyRuntimeContextError("stopped, failed or unloaded Cluster cannot schedule Timer")

    def _cleanup_cluster(self, cluster_id: OnlyClusterId) -> None:
        for handle in self._timer_handles.pop(cluster_id, {}).values():
            handle.cancel()
        registration = self._subscriptions.pop(cluster_id, None)
        if registration is not None:
            self._services.dispatcher.unregister(cluster_id)
        self._current_snapshots.pop(cluster_id, None)
        self._services.risk_service.unbind_cluster_profile(cluster_id)

    def _prepare_risk_snapshot(
        self,
        cluster_id: OnlyClusterId,
        snapshot: OnlyMarketDataSnapshot,
    ) -> None:
        self._services.risk_service.update_pre_decision_state(
            OnlyRiskStateUpdateContext(
                self.config.runtime_id,  # type: ignore[arg-type]
                cluster_id,
                self.config.default_account_id,  # type: ignore[arg-type]
                snapshot.ts_event,
                snapshot.ts_init,
                snapshot,
            )
        )

    def _resolve_risk_profile(
        self,
        value: object,
        cluster_id: OnlyClusterId,
    ) -> OnlyRiskProfile:
        if value is None:
            return OnlyRiskProfile(OnlyRiskProfileId(f"{cluster_id}-DEFAULT"))
        if isinstance(value, OnlyRiskProfile):
            return value
        if isinstance(value, OnlyRiskProfileConfig):
            return self._risk_profile_factory.create(value)
        if not isinstance(value, Mapping):
            raise ValueError("risk_profile must be OnlyRiskProfile, OnlyRiskProfileConfig or mapping")
        raw_rules = value.get("rules", ())
        if not isinstance(raw_rules, (list, tuple)):
            raise ValueError("risk_profile.rules must be a list")
        rules: list[OnlyRiskRuleConfig] = []
        for raw in raw_rules:
            if not isinstance(raw, Mapping):
                raise ValueError("risk_profile Rule must be a mapping")
            config = raw.get("config", {})
            if not isinstance(config, Mapping):
                raise ValueError("risk_profile Rule config must be a mapping")
            rules.append(
                OnlyRiskRuleConfig(
                    str(raw.get("type", "")),
                    int(str(raw.get("order", 100))),
                    dict(config),
                    str(raw.get("mode", "ENFORCING")),
                )
            )
        disabled = value.get("disabled_rule_ids", ())
        if not isinstance(disabled, (list, tuple)):
            raise ValueError("disabled_rule_ids must be a list")
        config = OnlyRiskProfileConfig(
            OnlyRiskProfileId(str(value.get("profile_id", f"{cluster_id}-PROFILE"))),
            tuple(rules),
            tuple(OnlyRiskRuleId(str(item)) for item in disabled),
        )
        return self._risk_profile_factory.create(config)

    @staticmethod
    def _parse_account_permissions(value: object) -> frozenset[OnlyAccountId] | None:
        if value is None:
            return None
        if not isinstance(value, (list, tuple, set, frozenset)):
            raise ValueError("allowed_account_ids must be a sequence")
        return frozenset(item if isinstance(item, OnlyAccountId) else OnlyAccountId(str(item)) for item in value)

    @staticmethod
    def _parse_instrument_permissions(value: object) -> frozenset[OnlyInstrumentId] | None:
        if value is None:
            return None
        if not isinstance(value, (list, tuple, set, frozenset)):
            raise ValueError("allowed_instrument_ids must be a sequence")
        return frozenset(
            item if isinstance(item, OnlyInstrumentId) else OnlyInstrumentId.parse(str(item)) for item in value
        )

    def _set_current_snapshot(
        self,
        cluster_id: OnlyClusterId,
        snapshot: OnlyMarketDataSnapshot | None,
    ) -> None:
        if snapshot is None:
            self._current_snapshots.pop(cluster_id, None)
        else:
            self._current_snapshots[cluster_id] = snapshot

    def _active_timer_count(self) -> int:
        return sum(
            self._services.clock.has_timer(handle.timer_id)
            for handles in self._timer_handles.values()
            for handle in handles.values()
        )

    @staticmethod
    def _compatibility_calendar() -> OnlyTradingCalendar:
        return OnlyTradingCalendar(
            OnlyCalendarId("LEGACY"),
            OnlyVenueId("LEGACY"),
            OnlyTimeZone("UTC"),
            (OnlyTradingSession("full_day", time(0), time(0), OnlySessionType.CONTINUOUS),),
            weekend_days=(),
        )
