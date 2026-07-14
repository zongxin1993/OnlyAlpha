"""Runtime resource ownership and deterministic Backtest orchestration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time
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
from onlyalpha.domain.enums import OnlyRuntimeMode, OnlySessionType
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyCalendarId,
    OnlyClusterId,
    OnlyEngineId,
    OnlyRuntimeId,
    OnlyVenueId,
)
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp, OnlyTimeZone
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
from onlyalpha.order.execution.models import OnlyGatewayOrderUpdate
from onlyalpha.order.execution.placeholder import OnlyPlaceholderExecutionService
from onlyalpha.order.execution.processor import OnlyOrderUpdateProcessor
from onlyalpha.order.id_generator import OnlySequenceClientOrderIdGenerator, OnlySequenceOrderIdGenerator
from onlyalpha.order.manager import OnlyOrderManager
from onlyalpha.order.publisher import OnlyRuntimeOrderEventPublisherAdapter
from onlyalpha.order.query import OnlyOrderQueryService
from onlyalpha.order.results import OnlyOrderMutationResult
from onlyalpha.order.service import OnlyOrderService
from onlyalpha.order.views import OnlyOrderServiceView
from onlyalpha.runtime.context import (
    OnlyClusterContext,
    OnlyInstrumentView,
    OnlyMarketDataView,
    OnlyRuntimeContextError,
    OnlyRuntimeLogger,
    OnlySubscriptionService,
    OnlyTimerService,
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

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "engine_id",
            self.engine_id if isinstance(self.engine_id, OnlyEngineId) else OnlyEngineId(self.engine_id),
        )
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


class OnlyManagedBarDispatchExecutor(OnlyBarDispatchExecutor):
    """Adapts Dispatcher selection to ClusterManager execution."""

    def __init__(
        self,
        manager: OnlyClusterManager,
        set_snapshot: Callable[[OnlyClusterId, OnlyMarketDataSnapshot | None], None],
    ) -> None:
        self._manager = manager
        self._set_snapshot = set_snapshot

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
        self._set_snapshot(cluster_id, snapshot)
        try:
            return self._manager.execute_bar(cluster_id, bar, snapshot)
        finally:
            self._set_snapshot(cluster_id, None)


class OnlyRuntime:
    """Base Runtime facade; concrete modes own their mutable resources."""

    def __init__(self, config: OnlyRuntimeConfig) -> None:
        self.config = config
        self._state = OnlyRuntimeState.CREATED
        self._services: OnlyRuntimeServices
        self._last_error: str | None = None

    @property
    def runtime_id(self) -> str:
        return str(self.config.runtime_id)

    @property
    def state(self) -> OnlyRuntimeState:
        return self._state

    @property
    def clusters(self) -> tuple[OnlyCluster, ...]:
        return self._services.cluster_manager.clusters

    def add_cluster(self, engine_id: str | OnlyEngineId, cluster: OnlyCluster) -> None:
        if self._state is not OnlyRuntimeState.CREATED:
            raise OnlyLifecycleError("Clusters must be loaded while Runtime is CREATED")
        if OnlyEngineId(str(engine_id)) != self.config.engine_id:
            raise ValueError("Cluster engine_id does not match Runtime scope")
        self._services.cluster_manager.register(cluster)

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
        manager = OnlyClusterManager(runtime_config.runtime_id, self._make_context, self._cleanup_cluster)  # type: ignore[arg-type]
        executor = OnlyManagedBarDispatchExecutor(manager, self._set_current_snapshot)
        dispatcher = OnlyStrategyBarDispatcher(pipeline, OnlyClockView(clock), executor)
        order_manager = OnlyOrderManager(
            runtime_config.engine_id,  # type: ignore[arg-type]
            runtime_config.runtime_id,  # type: ignore[arg-type]
            OnlySequenceOrderIdGenerator(runtime_config.runtime_id),  # type: ignore[arg-type]
            OnlySequenceClientOrderIdGenerator(runtime_config.runtime_id),  # type: ignore[arg-type]
        )
        order_publisher = OnlyRuntimeOrderEventPublisherAdapter(owned_bus)
        order_query = OnlyOrderQueryService(order_manager)
        order_service = OnlyOrderService(
            order_manager,
            OnlyPlaceholderExecutionService(),
            order_publisher,
            lambda: OnlyTimestamp.from_unix_nanos(clock.timestamp_ns()),
        )
        order_update_processor = OnlyOrderUpdateProcessor(
            runtime_config.runtime_id,  # type: ignore[arg-type]
            order_manager,
            order_publisher,
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
        )

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
            OnlyInstrumentView(),
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
