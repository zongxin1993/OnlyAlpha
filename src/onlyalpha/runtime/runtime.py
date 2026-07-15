"""Runtime resource ownership and deterministic Backtest orchestration."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal
from enum import StrEnum

from onlyalpha.cache.base import OnlyCache
from onlyalpha.cluster.base import OnlyCluster, OnlyClusterState
from onlyalpha.cluster.manager import (
    OnlyClusterExecutionResult,
    OnlyClusterManager,
    OnlyClusterStatus,
)
from onlyalpha.core.clock import (
    OnlyBacktestClock,
    OnlyClockView,
    OnlyTimeAdvanceResult,
    OnlyTimerEvent,
    OnlyTimerHandle,
)
from onlyalpha.core.errors import OnlyLifecycleError
from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import OnlyOrderStatus, OnlyRuntimeMode, OnlySessionType
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyCalendarId,
    OnlyClusterId,
    OnlyEngineId,
    OnlyInstrumentId,
    OnlyRuntimeId,
    OnlyVenueId,
)
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.domain.market_rules import OnlyMarketRule
from onlyalpha.domain.time import OnlyTimestamp, OnlyTimeZone, OnlyTradingDay
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.event.bus import OnlyEventBus, OnlyEventQueuePolicy
from onlyalpha.event.model import OnlyEvent, OnlyEventScope
from onlyalpha.indicator.base import OnlyIndicatorId, OnlyIndicatorRegistration, OnlyIndicatorValue
from onlyalpha.indicator.pipeline import OnlyIndicatorPipeline
from onlyalpha.market_data.aggregation.manager import OnlyBarAggregationManager
from onlyalpha.market_data.cache import OnlyMarketDataCache
from onlyalpha.market_data.dispatcher import (
    OnlyBarDispatchExecutor,
    OnlyBarDispatchResult,
    OnlyClusterBarSubscription,
    OnlyStrategyBarDispatcher,
)
from onlyalpha.market_data.pipeline import OnlyMarketDataPipeline, OnlyMarketDataUpdateResult
from onlyalpha.market_data.snapshot import OnlyMarketDataSnapshot
from onlyalpha.market_data.subscriptions import OnlyBarSubscription, OnlyBarSubscriptionId
from onlyalpha.order.execution.models import OnlyGatewayOrderFillUpdate, OnlyGatewayOrderUpdate
from onlyalpha.order.execution.placeholder import OnlyPlaceholderExecutionService
from onlyalpha.order.execution.processor import OnlyOrderUpdateProcessor
from onlyalpha.order.id_generator import OnlySequenceClientOrderIdGenerator, OnlySequenceOrderIdGenerator
from onlyalpha.order.manager import OnlyOrderManager
from onlyalpha.order.publisher import OnlyRuntimeOrderEventPublisherAdapter
from onlyalpha.order.query import OnlyOrderQueryService
from onlyalpha.order.results import OnlyOrderMutationResult
from onlyalpha.order.service import OnlyOrderService
from onlyalpha.order.views import OnlyOrderServiceView
from onlyalpha.position.allocation_manager import OnlyPositionAllocationManager
from onlyalpha.position.enums import OnlyPositionMutationStatus, OnlyPositionSide
from onlyalpha.position.events import OnlyPositionEvent
from onlyalpha.position.keys import OnlyPositionAllocationKey
from onlyalpha.position.manager import OnlyPositionManager
from onlyalpha.position.models import (
    OnlyPositionAllocationSnapshot,
    OnlyPositionMutationResult,
    OnlyPositionTrade,
    OnlySettlementResult,
)
from onlyalpha.position.ports import OnlyPositionEventPublisher
from onlyalpha.position.queries import OnlyPositionQueryService
from onlyalpha.position.reservations import OnlyOrderPositionReservationAdapter, OnlyPositionReservationManager
from onlyalpha.position.settlement import OnlySettlementService
from onlyalpha.position.views import OnlyPositionContextView, OnlyPositionRiskView
from onlyalpha.risk.contexts import OnlyRiskStateUpdateContext
from onlyalpha.risk.factory import OnlyRiskProfileFactory
from onlyalpha.risk.identifiers import OnlyRiskProfileId, OnlyRiskRuleId
from onlyalpha.risk.profile import OnlyRiskProfile, OnlyRiskProfileConfig, OnlyRiskRuleConfig
from onlyalpha.risk.publisher import OnlyRuntimeRiskEventPublisherAdapter
from onlyalpha.risk.rules.account import OnlyAvailablePositionRiskRule
from onlyalpha.risk.service import OnlyRiskService
from onlyalpha.risk.views import (
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
from onlyalpha.strategy_ledger.enums import OnlyStrategyFeeType
from onlyalpha.strategy_ledger.identifiers import OnlyStrategyFeeEntryId
from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey
from onlyalpha.strategy_ledger.manager import OnlyStrategyLedgerManager
from onlyalpha.strategy_ledger.models import (
    OnlyStrategyFeeEntry,
    OnlyStrategyLedgerMutationResult,
    OnlyStrategyLedgerSnapshot,
    OnlyStrategyMarkPrice,
    OnlyStrategyTradeAccountingInput,
)
from onlyalpha.strategy_ledger.order_port import OnlyOrderStrategyCashReservationAdapter
from onlyalpha.strategy_ledger.publisher import OnlyRuntimeStrategyLedgerEventPublisherAdapter
from onlyalpha.strategy_ledger.query import OnlyStrategyLedgerQueryService
from onlyalpha.strategy_ledger.valuation import OnlyStrategyValuationService
from onlyalpha.strategy_ledger.views import (
    OnlyStrategyLedgerContextView,
    OnlyStrategyLedgerRiskView,
)

_LOGGER = logging.getLogger(__name__)


class OnlyRuntimeError(Exception):
    """Base Runtime orchestration error."""


class OnlyRuntimeState(StrEnum):
    CREATED = "CREATED"
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"
    CLOSED = "CLOSED"


class OnlyRuntimeErrorPolicy(StrEnum):
    ISOLATE_CLUSTER = "ISOLATE_CLUSTER"
    FAIL_RUNTIME = "FAIL_RUNTIME"


@dataclass(frozen=True, slots=True)
class OnlyRuntimeConfig:
    engine_id: OnlyEngineId | str
    runtime_id: OnlyRuntimeId | str
    mode: OnlyRuntimeMode
    event_capacity: int = 1024
    history_limit: int = 1024
    event_queue_policy: OnlyEventQueuePolicy = OnlyEventQueuePolicy.REJECT
    cluster_error_policy: OnlyRuntimeErrorPolicy = OnlyRuntimeErrorPolicy.ISOLATE_CLUSTER
    default_account_id: OnlyAccountId | str | None = None
    strategy_initial_capital: Decimal | str = Decimal("1000000.00")
    strategy_base_currency: OnlyCurrency = OnlyCurrency("CNY", 2)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "engine_id",
            self.engine_id if isinstance(self.engine_id, OnlyEngineId) else OnlyEngineId(self.engine_id),
        )
        strategy_initial_capital = Decimal(str(self.strategy_initial_capital))
        object.__setattr__(self, "strategy_initial_capital", strategy_initial_capital)
        if strategy_initial_capital < 0:
            raise ValueError("strategy_initial_capital cannot be negative")
        object.__setattr__(
            self,
            "runtime_id",
            self.runtime_id if isinstance(self.runtime_id, OnlyRuntimeId) else OnlyRuntimeId(self.runtime_id),
        )
        object.__setattr__(
            self,
            "default_account_id",
            (
                self.default_account_id
                if isinstance(self.default_account_id, OnlyAccountId)
                else OnlyAccountId(self.default_account_id or f"{self.runtime_id}-DEFAULT")
            ),
        )
        if self.event_capacity <= 0 or self.history_limit <= 0:
            raise ValueError("Runtime capacities must be positive")


@dataclass(frozen=True, slots=True)
class OnlyRuntimeStatus:
    runtime_id: OnlyRuntimeId
    mode: OnlyRuntimeMode
    state: OnlyRuntimeState
    clock_time_ns: int
    cluster_count: int
    running_cluster_count: int
    failed_cluster_count: int
    event_queue_size: int
    active_timer_count: int
    subscription_count: int
    last_error: str | None


@dataclass(frozen=True, slots=True)
class OnlyRuntimeBarResult:
    advance: OnlyTimeAdvanceResult
    update: OnlyMarketDataUpdateResult
    dispatches: tuple[OnlyBarDispatchResult, ...]
    events_dispatched: int


@dataclass(frozen=True, slots=True)
class OnlyRuntimeTradeResult:
    """Result of one Runtime-owned standardized fill orchestration."""

    order: OnlyOrderMutationResult
    position: OnlyPositionMutationResult | None
    allocation_status: OnlyPositionMutationStatus | None
    ledger: OnlyStrategyLedgerMutationResult | None
    final_ledger: OnlyStrategyLedgerSnapshot | None
    events_dispatched: int


@dataclass(slots=True)
class OnlyRuntimeServices:
    """Runtime-private mutable service container; never exposed through Context."""

    clock: OnlyBacktestClock
    event_bus: OnlyEventBus
    market_data_cache: OnlyMarketDataCache
    aggregation_manager: OnlyBarAggregationManager
    indicator_pipeline: OnlyIndicatorPipeline
    pipeline: OnlyMarketDataPipeline
    dispatcher: OnlyStrategyBarDispatcher
    cluster_manager: OnlyClusterManager
    order_manager: OnlyOrderManager
    order_query: OnlyOrderQueryService
    order_service: OnlyOrderService
    order_update_processor: OnlyOrderUpdateProcessor
    execution_service: OnlyPlaceholderExecutionService
    risk_service: OnlyRiskService
    position_manager: OnlyPositionManager
    allocation_manager: OnlyPositionAllocationManager
    position_reservation_manager: OnlyPositionReservationManager
    position_query: OnlyPositionQueryService
    strategy_ledger_manager: OnlyStrategyLedgerManager
    strategy_ledger_query: OnlyStrategyLedgerQueryService
    settlement_service: OnlySettlementService
    strategy_valuation_service: OnlyStrategyValuationService


class OnlyManagedBarDispatchExecutor(OnlyBarDispatchExecutor):
    """Adapts Dispatcher selection to ClusterManager execution."""

    def __init__(
        self,
        manager: OnlyClusterManager,
        set_snapshot: Callable[[OnlyClusterId, OnlyMarketDataSnapshot | None], None],
        prepare_risk: Callable[[OnlyClusterId, OnlyMarketDataSnapshot], None],
    ) -> None:
        self._manager = manager
        self._set_snapshot = set_snapshot
        self._prepare_risk = prepare_risk

    def execute_bar(
        self,
        cluster_id: OnlyClusterId,
        cluster: OnlyCluster,
        bar: OnlyBar,
        snapshot: object,
    ) -> OnlyClusterExecutionResult:
        del cluster
        if not isinstance(snapshot, OnlyMarketDataSnapshot):
            raise TypeError("Dispatcher must provide OnlyMarketDataSnapshot")
        self._prepare_risk(cluster_id, snapshot)
        self._set_snapshot(cluster_id, snapshot)
        try:
            return self._manager.execute_bar(cluster_id, bar, snapshot)
        finally:
            self._set_snapshot(cluster_id, None)


class OnlyRuntimePositionEventPublisherAdapter(OnlyPositionEventPublisher):
    """Publishes completed Position facts to the owning Runtime EventBus."""

    def __init__(self, engine_id: OnlyEngineId, event_bus: OnlyEventBus) -> None:
        self._engine_id = engine_id
        self._event_bus = event_bus

    def publish(self, event: OnlyPositionEvent) -> None:
        self._event_bus.publish(
            OnlyEvent(
                event.event_type,
                event.timestamp.to_datetime(),
                self._engine_id,
                event.runtime_id,
                "position_manager",
                event.sequence,
                payload=event.to_dict(),
                cluster_id=event.cluster_id,
                timestamp_ns=event.timestamp.unix_nanos,
                ts_init_ns=event.timestamp.unix_nanos,
            )
        )


class OnlyRuntime:
    """Base Runtime facade; concrete modes own their mutable resources."""

    def __init__(self, config: OnlyRuntimeConfig) -> None:
        self.config = config
        self._state = OnlyRuntimeState.CREATED
        self._services: OnlyRuntimeServices
        self._last_error: str | None = None
        # Position is a Runtime state domain even where the mode-specific market/execution
        # assembly is intentionally deferred (Live/Paper/Research in the current phase).
        self._position_manager = OnlyPositionManager(config.runtime_id)  # type: ignore[arg-type]
        self._allocation_manager = OnlyPositionAllocationManager(config.runtime_id)  # type: ignore[arg-type]
        self._position_query = OnlyPositionQueryService(
            self._position_manager,
            self._allocation_manager,
        )
        self._position_reservation_manager = OnlyPositionReservationManager(
            config.runtime_id,  # type: ignore[arg-type]
            self._position_manager,
            self._allocation_manager,
        )
        self._strategy_ledger_manager = OnlyStrategyLedgerManager(
            config.runtime_id  # type: ignore[arg-type]
        )
        self._strategy_ledger_query = OnlyStrategyLedgerQueryService(self._strategy_ledger_manager)

    @property
    def runtime_id(self) -> str:
        return str(self.config.runtime_id)

    @property
    def state(self) -> OnlyRuntimeState:
        return self._state

    @property
    def clusters(self) -> tuple[OnlyCluster, ...]:
        return self._services.cluster_manager.clusters

    @property
    def position_manager(self) -> OnlyPositionManager:
        """Runtime management port; never passed directly to a Cluster."""

        return self._position_manager

    @property
    def allocation_manager(self) -> OnlyPositionAllocationManager:
        """Runtime management port for Cluster attribution updates."""

        return self._allocation_manager

    @property
    def position_reservation_manager(self) -> OnlyPositionReservationManager:
        return self._position_reservation_manager

    @property
    def strategy_ledger_manager(self) -> OnlyStrategyLedgerManager:
        """Runtime management port; never exposed through Cluster Context."""

        return self._strategy_ledger_manager

    @property
    def clock(self) -> OnlyBacktestClock:
        """Runtime management clock; Cluster receives only ``OnlyClockView``."""

        return self._services.clock

    @property
    def event_bus(self) -> OnlyEventBus:
        """Runtime management EventBus; never injected into Cluster Context."""

        return self._services.event_bus

    @property
    def market_data_pipeline(self) -> OnlyMarketDataPipeline:
        return self._services.pipeline

    @property
    def order_manager(self) -> OnlyOrderManager:
        return self._services.order_manager

    @property
    def risk_service(self) -> OnlyRiskService:
        return self._services.risk_service

    @property
    def execution_service(self) -> OnlyPlaceholderExecutionService:
        return self._services.execution_service

    def add_cluster(self, engine_id: str | OnlyEngineId, cluster: OnlyCluster) -> None:
        if self._state is not OnlyRuntimeState.CREATED:
            raise OnlyLifecycleError("Clusters must be loaded while Runtime is CREATED")
        if OnlyEngineId(str(engine_id)) != self.config.engine_id:
            raise ValueError("Cluster engine_id does not match Runtime scope")
        cluster_id = OnlyClusterId(cluster.config.cluster_id)
        ledger_key = OnlyStrategyLedgerKey(
            self.config.runtime_id,  # type: ignore[arg-type]
            self.config.default_account_id,  # type: ignore[arg-type]
            cluster_id,
            self.config.strategy_base_currency,
        )
        configured_capital = cluster.config.values.get("strategy_initial_capital", self.config.strategy_initial_capital)
        timestamp = OnlyTimestamp.from_unix_nanos(self._services.clock.timestamp_ns())
        self._strategy_ledger_manager.create_ledger(
            ledger_key,
            OnlyMoney(Decimal(str(configured_capital)), self.config.strategy_base_currency),
            timestamp,
        )
        self._strategy_ledger_manager.activate_ledger(ledger_key, timestamp)
        profile = self._resolve_risk_profile(cluster.config.values.get("risk_profile"), cluster_id)
        allowed_accounts = self._parse_account_permissions(cluster.config.values.get("allowed_account_ids"))
        allowed_instruments = self._parse_instrument_permissions(cluster.config.values.get("allowed_instrument_ids"))
        self._services.risk_service.bind_cluster_profile(
            cluster_id,
            self.config.default_account_id,  # type: ignore[arg-type]
            profile,
            allowed_accounts=allowed_accounts,
            allowed_instruments=allowed_instruments,
        )
        try:
            self._services.cluster_manager.register(cluster)
        except Exception:
            self._services.risk_service.unbind_cluster_profile(cluster_id)
            self._strategy_ledger_manager.close_ledger(ledger_key, timestamp)
            raise

    def initialize(self) -> None:
        if self._state is not OnlyRuntimeState.CREATED:
            raise OnlyLifecycleError("Runtime can only initialize from CREATED")
        self._services.cluster_manager.initialize_all()
        self._state = OnlyRuntimeState.READY

    def start(self) -> None:
        if self._state is OnlyRuntimeState.CREATED:
            self.initialize()
        if self._state is not OnlyRuntimeState.READY:
            raise OnlyLifecycleError("Runtime can only start from READY")
        self._services.cluster_manager.start_all()
        self._state = OnlyRuntimeState.RUNNING
        self._publish_runtime_fact("RUNTIME_STARTED")
        self._services.event_bus.drain()

    def pause(self) -> None:
        if self._state is not OnlyRuntimeState.RUNNING:
            raise OnlyLifecycleError("Runtime can only pause from RUNNING")
        self._services.cluster_manager.pause_all()
        self._state = OnlyRuntimeState.PAUSED

    def resume(self) -> None:
        if self._state is not OnlyRuntimeState.PAUSED:
            raise OnlyLifecycleError("Runtime can only resume from PAUSED")
        self._services.cluster_manager.resume_all()
        self._state = OnlyRuntimeState.RUNNING

    def stop(self) -> None:
        if self._state in {OnlyRuntimeState.STOPPED, OnlyRuntimeState.CLOSED}:
            return
        self._state = OnlyRuntimeState.STOPPING
        self._services.cluster_manager.stop_all()
        self._services.event_bus.drain()
        self._state = OnlyRuntimeState.STOPPED

    def close(self) -> None:
        if self._state is OnlyRuntimeState.CLOSED:
            return
        self.stop()
        self._services.cluster_manager.unload_all()
        self._services.event_bus.close()
        self._services.clock.close()
        self._state = OnlyRuntimeState.CLOSED

    def status(self) -> OnlyRuntimeStatus:
        clusters = self._services.cluster_manager.status()
        return OnlyRuntimeStatus(
            self.config.runtime_id,  # type: ignore[arg-type]
            self.config.mode,
            self._state,
            self._services.clock.timestamp_ns(),
            len(clusters),
            sum(item.state is OnlyClusterState.RUNNING for item in clusters),
            sum(item.state is OnlyClusterState.FAILED for item in clusters),
            self._services.event_bus.pending_count(),
            self._active_timer_count(),
            self._services.dispatcher.subscription_count,
            self._last_error,
        )

    def cluster_status(self) -> tuple[OnlyClusterStatus, ...]:
        return self._services.cluster_manager.status()

    def stop_cluster(self, cluster_id: OnlyClusterId | str) -> None:
        """Stop one Cluster without affecting its Runtime peers."""

        self._services.cluster_manager.stop(
            cluster_id if isinstance(cluster_id, OnlyClusterId) else OnlyClusterId(cluster_id)
        )

    def _publish_runtime_fact(self, event_type: str) -> None:
        clock = self._services.clock
        self._services.event_bus.publish(
            OnlyEvent(
                event_type,
                clock.now_utc(),
                self.config.engine_id,
                self.config.runtime_id,
                "runtime",
                1,
                ts_init_ns=clock.timestamp_ns(),
                timestamp_ns=clock.timestamp_ns(),
            )
        )

    def _active_timer_count(self) -> int:
        return 0

    def _resolve_risk_profile(self, value: object, cluster_id: OnlyClusterId) -> OnlyRiskProfile:
        raise NotImplementedError

    @staticmethod
    def _parse_account_permissions(value: object) -> frozenset[OnlyAccountId] | None:
        raise NotImplementedError

    @staticmethod
    def _parse_instrument_permissions(value: object) -> frozenset[OnlyInstrumentId] | None:
        raise NotImplementedError


class OnlyBacktestRuntime(OnlyRuntime):
    """Synchronous, single-threaded and deterministically Bar-driven Runtime."""

    def __init__(
        self,
        config: OnlyRuntimeConfig | str,
        calendar_or_clock: OnlyTradingCalendar | OnlyBacktestClock,
        initial_time_or_event_bus: datetime | int | OnlyEventBus | None = None,
        legacy_cache: OnlyCache | None = None,
        *,
        calendar: OnlyTradingCalendar | None = None,
        engine_id: str = "engine",
    ) -> None:
        if isinstance(config, str):
            if not isinstance(calendar_or_clock, OnlyBacktestClock):
                raise TypeError("legacy Runtime construction requires OnlyBacktestClock")
            runtime_config = OnlyRuntimeConfig(engine_id, config, OnlyRuntimeMode.BACKTEST)
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
            clock = OnlyBacktestClock(initial_time_or_event_bus)
            event_bus = None
        super().__init__(runtime_config)
        scope = OnlyEventScope(runtime_config.engine_id, runtime_config.runtime_id)  # type: ignore[arg-type]
        owned_bus = event_bus or OnlyEventBus(
            runtime_config.event_capacity,
            scope=scope,
            queue_policy=runtime_config.event_queue_policy,
        )
        self._strategy_ledger_manager.bind_publisher(
            OnlyRuntimeStrategyLedgerEventPublisherAdapter(
                runtime_config.engine_id,  # type: ignore[arg-type]
                owned_bus,
            )
        )
        self._position_manager.bind_publisher(
            OnlyRuntimePositionEventPublisherAdapter(
                runtime_config.engine_id,  # type: ignore[arg-type]
                owned_bus,
            )
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
        order_publisher = OnlyRuntimeOrderEventPublisherAdapter(owned_bus)
        order_query = OnlyOrderQueryService(order_manager)
        position_manager = self._position_manager
        allocation_manager = self._allocation_manager
        position_query = self._position_query
        position_reservations = self._position_reservation_manager
        order_position_reservations = OnlyOrderPositionReservationAdapter(position_reservations)
        order_cash_reservations = OnlyOrderStrategyCashReservationAdapter(
            self._strategy_ledger_manager,
            runtime_config.strategy_base_currency,
            self._instruments,
            lambda order: (
                self._current_snapshots[order.cluster_id].primary_bar.close
                if order.cluster_id in self._current_snapshots
                else None
            ),
        )
        risk_service = OnlyRiskService(
            runtime_config.engine_id,  # type: ignore[arg-type]
            runtime_config.runtime_id,  # type: ignore[arg-type]
            OnlyClockView(clock),
            selected_calendar,
            OnlyInstrumentRiskMappingView(self._instruments),
            OnlyMarketRuleRiskMappingView(self._market_rules),
            order_query,
            OnlyRuntimeRiskEventPublisherAdapter(owned_bus),
            account_rules=(OnlyAvailablePositionRiskRule(),),
            position_risk=OnlyPositionRiskView(position_query, clock.timestamp_ns),
            strategy_ledger_risk=OnlyStrategyLedgerRiskView(
                self._strategy_ledger_query, runtime_config.strategy_base_currency
            ),
        )
        execution_service = OnlyPlaceholderExecutionService()
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
        )
        self._valuation_versions: dict[OnlyStrategyLedgerKey, int] = {}

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
        if market_rule is not None:
            self._market_rules[instrument.instrument_id] = market_rule

    def register_indicator(self, registration: OnlyIndicatorRegistration) -> None:
        if self._state is not OnlyRuntimeState.CREATED:
            raise OnlyLifecycleError("Indicators must be registered while Runtime is CREATED")
        self._services.indicator_pipeline.register(registration)

    def process_bar(self, bar: OnlyBar) -> OnlyRuntimeBarResult:
        if self._state is not OnlyRuntimeState.RUNNING:
            raise OnlyLifecycleError("Runtime accepts Bars only while RUNNING")
        try:
            advance = self._services.clock.advance_to(bar.ts_event)
            update = self._services.pipeline.process_bar(bar)
            self._services.event_bus.publish_many(update.facts)
            dispatches = self._services.dispatcher.dispatch(update)
            dispatched = self._services.event_bus.drain()
            if self.config.cluster_error_policy is OnlyRuntimeErrorPolicy.FAIL_RUNTIME and any(
                item.called and not item.succeeded for item in dispatches
            ):
                self._state = OnlyRuntimeState.FAILED
                self._last_error = "Cluster callback failed under FAIL_RUNTIME policy"
            return OnlyRuntimeBarResult(advance, update, dispatches, dispatched)
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            self._state = OnlyRuntimeState.FAILED
            raise

    def process_order_update(self, update: OnlyGatewayOrderUpdate) -> OnlyOrderMutationResult:
        """Apply one normalized external update on the owning Runtime thread."""

        if self._state is not OnlyRuntimeState.RUNNING:
            raise OnlyLifecycleError("Runtime accepts Order updates only while RUNNING")
        result = self._services.order_update_processor.process(update)
        self._services.event_bus.drain()
        return result

    def process_trade(
        self,
        update: OnlyGatewayOrderFillUpdate,
        trade: OnlyPositionTrade,
    ) -> OnlyRuntimeTradeResult:
        """Apply Order, Position, Allocation and Ledger changes in Runtime order.

        The caller supplies already-standardized Gateway facts.  Placeholder Execution
        never manufactures an acceptance, fill or trade.
        """

        if self._state is not OnlyRuntimeState.RUNNING:
            raise OnlyLifecycleError("Runtime accepts Trades only while RUNNING")
        order_before = self._services.order_query.require(update.order_id)
        self._validate_trade(update, trade, order_before)
        allocation_key = OnlyPositionAllocationKey(
            trade.runtime_id,
            trade.account_id,
            trade.cluster_id,  # type: ignore[arg-type]
            trade.instrument_id,
            trade.position_side,
        )
        allocation_before = self._services.allocation_manager.get_snapshot(allocation_key)
        order_result = self._services.order_update_processor.process(
            update,
            consume_cash_reservation=False,
        )
        if not order_result.changed:
            dispatched = self._services.event_bus.drain()
            return OnlyRuntimeTradeResult(order_result, None, None, None, None, dispatched)

        position_result = self._services.position_manager.apply_trade(trade)
        allocation_status = self._services.allocation_manager.apply_trade(trade)
        allocation_after = self._allocation_snapshot(allocation_key)
        ledger_key = OnlyStrategyLedgerKey(
            trade.runtime_id,
            trade.account_id,
            trade.cluster_id,  # type: ignore[arg-type]
            self.config.strategy_base_currency,
        )
        ledger_snapshot = self._services.strategy_ledger_manager.require_snapshot(ledger_key)
        cash_reservation = next(
            (item for item in ledger_snapshot.reservations if item.order_id == trade.order_id),
            None,
        )
        realized_before = self._allocation_money(allocation_before, realized=True)
        realized_after = self._allocation_money(allocation_after, realized=True)
        cost_before = self._allocation_cost(allocation_before, trade)
        cost_after = self._allocation_cost(allocation_after, trade)
        fee_entry = OnlyStrategyFeeEntry(
            OnlyStrategyFeeEntryId(f"SFEE-{trade.runtime_id}-{trade.trade_id}"),
            ledger_key,
            trade.fee,
            OnlyStrategyFeeType.COMMISSION,
            trade.trade_id,
            trade.order_id,
            trade.ts_event,
            trade.ts_init,
            trade.external_sequence or 0,
        )
        ledger_result = self._services.strategy_ledger_manager.apply_trade_accounting(
            ledger_key,
            OnlyStrategyTradeAccountingInput(
                trade,
                order_result.snapshot,
                allocation_before,
                allocation_after,
                realized_after - realized_before,
                cost_after - cost_before,
                (fee_entry,),
                cash_reservation,
                trade.ts_event,
                trade.external_sequence or 0,
            ),
        )
        self._apply_strategy_valuation(ledger_key, trade)
        if order_result.snapshot.status is OnlyOrderStatus.FILLED:
            self._services.risk_service.consume_order(
                trade.order_id,
                order_result.snapshot.cluster_id,
                trade.account_id,
                trade.ts_init,
            )
        final_ledger = self._services.strategy_ledger_manager.require_snapshot(ledger_key)
        dispatched = self._services.event_bus.drain()
        return OnlyRuntimeTradeResult(
            order_result,
            position_result,
            allocation_status,
            ledger_result,
            final_ledger,
            dispatched,
        )

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

    def _make_context(self, cluster_id: OnlyClusterId) -> OnlyClusterContext:
        def allowed_bar_types() -> frozenset[OnlyBarType]:
            registration = self._subscriptions.get(cluster_id)
            return frozenset() if registration is None else frozenset(registration.subscription.bar_types)

        def latest(bar_type: OnlyBarType) -> OnlyBar | None:
            return self._services.market_data_cache.latest_closed(bar_type)

        def history(bar_type: OnlyBarType, count: int) -> tuple[OnlyBar, ...]:
            return self._services.market_data_cache.history(bar_type, count)

        def indicator(indicator_id: OnlyIndicatorId) -> OnlyIndicatorValue | None:
            registration = self._subscriptions.get(cluster_id)
            if registration is None or indicator_id not in registration.indicator_ids:
                raise OnlyRuntimeContextError("Cluster cannot read an undeclared Indicator")
            return self._services.indicator_pipeline.values().get(indicator_id)

        def current_snapshot() -> OnlyMarketDataSnapshot | None:
            return self._current_snapshots.get(cluster_id)

        return OnlyClusterContext(
            self.config.engine_id,  # type: ignore[arg-type]
            self.config.runtime_id,  # type: ignore[arg-type]
            cluster_id,
            self.config.mode,
            OnlyClockView(self._services.clock),
            OnlyMarketDataView(allowed_bar_types, latest, history, indicator, current_snapshot),
            OnlyInstrumentView(self._instruments),
            OnlySubscriptionService(
                lambda subscription, indicator_ids: self._subscribe(cluster_id, subscription, indicator_ids)
            ),
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
        indicator_ids: tuple[OnlyIndicatorId, ...],
    ) -> OnlyBarSubscriptionId:
        if self._services.cluster_manager.state_of(cluster_id) is not OnlyClusterState.LOADED:
            raise OnlyRuntimeContextError("Bar subscriptions are accepted only during Cluster initialization")
        if cluster_id in self._subscriptions:
            raise OnlyRuntimeContextError("first-phase Cluster supports one Bar subscription")
        cluster = next(item for item in self.clusters if item.config.cluster_id == str(cluster_id))
        registration = OnlyClusterBarSubscription(cluster, subscription, tuple(sorted(set(indicator_ids))))
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


class OnlyLiveRuntime(OnlyRuntime):
    """Live Runtime marker; resource assembly is intentionally deferred."""


class OnlyPaperRuntime(OnlyRuntime):
    """Paper Runtime marker; resource assembly is intentionally deferred."""


class OnlyResearchRuntime(OnlyRuntime):
    """Research Runtime marker; resource assembly is intentionally deferred."""


class OnlyRuntimeManager:
    """Engine-facing collection and lifecycle coordinator for isolated Runtimes."""

    def __init__(self) -> None:
        self._runtimes: dict[str, OnlyRuntime] = {}

    def register(self, runtime: OnlyRuntime) -> None:
        if runtime.runtime_id in self._runtimes:
            raise ValueError(f"duplicate Runtime: {runtime.runtime_id}")
        self._runtimes[runtime.runtime_id] = runtime

    def initialize_all(self) -> None:
        for runtime in self._runtimes.values():
            runtime.initialize()

    def start_all(self) -> None:
        for runtime in self._runtimes.values():
            runtime.start()

    def stop_all(self) -> None:
        for runtime in reversed(tuple(self._runtimes.values())):
            runtime.stop()

    def close_all(self) -> None:
        for runtime in reversed(tuple(self._runtimes.values())):
            runtime.close()
