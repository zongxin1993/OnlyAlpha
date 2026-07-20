"""Runtime resource ownership and deterministic Backtest orchestration."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from onlyalpha.account.enums import OnlyAccountReservationState
from onlyalpha.account.events import OnlyAccountEvent, OnlyAccountEventPublisher
from onlyalpha.account.identifiers import OnlyAccountReservationId
from onlyalpha.account.manager import OnlyAccountManager
from onlyalpha.account.models import (
    OnlyAccountReservation,
)
from onlyalpha.account.reservations import OnlyAccountReservationManager
from onlyalpha.account.views import OnlyAccountQueryService
from onlyalpha.broker.identifiers import OnlyBrokerGatewayId
from onlyalpha.broker.virtual.config import OnlyVirtualBrokerConfig
from onlyalpha.cluster.base import OnlyCluster, OnlyClusterState
from onlyalpha.cluster.manager import (
    OnlyClusterExecutionResult,
    OnlyClusterManager,
    OnlyClusterStatus,
)
from onlyalpha.core.clock import (
    OnlyBacktestClock,
    OnlyTimeAdvanceResult,
)
from onlyalpha.core.errors import OnlyLifecycleError
from onlyalpha.data.audit import OnlyMarketDataAuditStore
from onlyalpha.data.gateway import OnlyInMemoryMarketDataGateway
from onlyalpha.data.processor import (
    OnlyMarketDataDeduplicator,
    OnlyMarketDataGapDetector,
    OnlyMarketDataProcessor,
    OnlyMarketDataSequenceTracker,
)
from onlyalpha.data.queue import OnlyMarketDataInboundQueue
from onlyalpha.data.registry import OnlyMarketDataSourceRegistry
from onlyalpha.data.replay import OnlyHistoricalReplayService
from onlyalpha.data.sources import (
    OnlyInMemoryHistoricalDataSource,
    OnlyInMemoryReferenceDataSource,
)
from onlyalpha.domain.enums import (
    OnlyOffset,
    OnlyOrderSide,
    OnlyRuntimeMode,
)
from onlyalpha.domain.execution import OnlyOrderFill, OnlyOrderSnapshot
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyEngineId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyRuntimeId,
)
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.market import OnlyBar
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice
from onlyalpha.event.bus import OnlyEventBus, OnlyEventQueuePolicy
from onlyalpha.event.model import OnlyEvent
from onlyalpha.execution import (
    OnlyExecutionEventPublisher,
    OnlyExecutionProcessor,
    OnlyExecutionSequenceTracker,
    OnlyExecutionUpdateDeduplicator,
    OnlyInMemoryExecutionAuditStore,
    OnlyInMemoryExecutionReconciliationQueue,
)
from onlyalpha.fee.manager import OnlyFeeManager
from onlyalpha.indicator.pipeline import OnlyIndicatorPipeline
from onlyalpha.margin.manager import OnlyMarginManager
from onlyalpha.market.runtime_rules import OnlyMarketRuleEngine
from onlyalpha.market_data.aggregation.manager import OnlyBarAggregationManager
from onlyalpha.market_data.cache import OnlyMarketDataCache
from onlyalpha.market_data.dispatcher import (
    OnlyBarDispatchExecutor,
    OnlyBarDispatchResult,
    OnlyStrategyBarDispatcher,
)
from onlyalpha.market_data.pipeline import OnlyMarketDataPipeline, OnlyMarketDataUpdateResult
from onlyalpha.market_data.snapshot import OnlyMarketDataSnapshot
from onlyalpha.order.cash_port import OnlyOrderCashReservationPort
from onlyalpha.order.execution.processor import OnlyOrderUpdateProcessor
from onlyalpha.order.execution.service import OnlyExecutionService
from onlyalpha.order.manager import OnlyOrderManager
from onlyalpha.order.query import OnlyOrderQueryService
from onlyalpha.order.service import OnlyOrderService
from onlyalpha.plugin.broker import OnlyBacktestBrokerGateway, OnlyBrokerInboundQueue
from onlyalpha.plugin.errors import OnlyPluginLifecycleError
from onlyalpha.plugin.lifecycle import OnlyPluginResource, OnlyPluginResourceSnapshot
from onlyalpha.position.allocation_manager import OnlyPositionAllocationManager
from onlyalpha.position.events import OnlyPositionEvent
from onlyalpha.position.manager import OnlyPositionManager
from onlyalpha.position.ports import OnlyPositionEventPublisher
from onlyalpha.position.queries import OnlyPositionQueryService
from onlyalpha.position.reservations import OnlyPositionReservationManager
from onlyalpha.position.settlement import OnlySettlementService
from onlyalpha.risk.profile import OnlyRiskProfile
from onlyalpha.risk.service import OnlyRiskService
from onlyalpha.settlement.manager import OnlySettlementManager
from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey
from onlyalpha.strategy_ledger.manager import OnlyStrategyLedgerManager
from onlyalpha.strategy_ledger.query import OnlyStrategyLedgerQueryService
from onlyalpha.strategy_ledger.valuation import OnlyStrategyValuationService

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
class OnlyRuntimeAssemblyConfig:
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
    virtual_broker_config: OnlyVirtualBrokerConfig | None = None
    broker_gateway_id: OnlyBrokerGatewayId | None = None
    account_initial_cash: OnlyMoney | None = None
    market_rule_engine: OnlyMarketRuleEngine | None = None

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
        if self.virtual_broker_config is not None:
            if self.virtual_broker_config.account_id != self.default_account_id:
                raise ValueError("Virtual Broker account must match Runtime default_account_id")
            if self.virtual_broker_config.base_currency != self.strategy_base_currency:
                raise ValueError("Virtual Broker and Runtime base currencies must match")


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
    execution_service: OnlyExecutionService
    risk_service: OnlyRiskService
    position_manager: OnlyPositionManager
    allocation_manager: OnlyPositionAllocationManager
    position_reservation_manager: OnlyPositionReservationManager
    position_query: OnlyPositionQueryService
    strategy_ledger_manager: OnlyStrategyLedgerManager
    strategy_ledger_query: OnlyStrategyLedgerQueryService
    settlement_service: OnlySettlementService
    settlement_manager: OnlySettlementManager
    margin_manager: OnlyMarginManager
    fee_manager: OnlyFeeManager
    strategy_valuation_service: OnlyStrategyValuationService
    account_manager: OnlyAccountManager
    account_query: OnlyAccountQueryService
    broker_inbound: OnlyBrokerInboundQueue
    broker_gateway: OnlyBacktestBrokerGateway | None
    execution_processor: OnlyExecutionProcessor
    execution_event_publisher: OnlyExecutionEventPublisher
    execution_audit_store: OnlyInMemoryExecutionAuditStore
    execution_reconciliation_queue: OnlyInMemoryExecutionReconciliationQueue
    execution_update_deduplicator: OnlyExecutionUpdateDeduplicator
    execution_sequence_tracker: OnlyExecutionSequenceTracker
    market_data_source_registry: OnlyMarketDataSourceRegistry
    historical_data_source: OnlyInMemoryHistoricalDataSource
    reference_data_source: OnlyInMemoryReferenceDataSource
    market_data_gateway: OnlyInMemoryMarketDataGateway
    market_data_inbound: OnlyMarketDataInboundQueue
    market_data_processor: OnlyMarketDataProcessor
    historical_replay_service: OnlyHistoricalReplayService
    market_data_audit_store: OnlyMarketDataAuditStore
    market_data_deduplicator: OnlyMarketDataDeduplicator
    market_data_sequence_tracker: OnlyMarketDataSequenceTracker
    market_data_gap_detector: OnlyMarketDataGapDetector


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


class OnlyRuntimeAccountEventPublisherAdapter(OnlyAccountEventPublisher):
    """Publishes local Account facts without exposing EventBus to AccountManager."""

    def __init__(self, engine_id: OnlyEngineId, event_bus: OnlyEventBus) -> None:
        self._engine_id = engine_id
        self._event_bus = event_bus

    def publish(self, event: OnlyAccountEvent) -> None:
        snapshot = event.snapshot
        self._event_bus.publish(
            OnlyEvent(
                event.event_type,
                event.timestamp.to_datetime(),
                self._engine_id,
                snapshot.runtime_id,
                "account_manager",
                event.sequence,
                payload=event.to_dict(),
                timestamp_ns=event.timestamp.unix_nanos,
                ts_init_ns=event.timestamp.unix_nanos,
            )
        )


class OnlyRuntimeAccountCashReservationAdapter:
    """Runtime assembly adapter from Order cash lifecycle to AccountManager."""

    def __init__(
        self,
        manager: OnlyAccountManager,
        currency: OnlyCurrency,
        instruments: Mapping[OnlyInstrumentId, OnlyInstrument],
        reference_price: Callable[[OnlyOrderSnapshot], OnlyPrice | None],
    ) -> None:
        self._manager = manager
        self._currency = currency
        self._instruments = instruments
        self._reference_price = reference_price
        self._reservations: dict[OnlyOrderId, OnlyAccountReservationId] = {}

    def reserve(self, order: OnlyOrderSnapshot, timestamp: OnlyTimestamp) -> None:
        if order.side is not OnlyOrderSide.BUY or order.offset in {
            OnlyOffset.CLOSE,
            OnlyOffset.CLOSE_TODAY,
            OnlyOffset.CLOSE_YESTERDAY,
        }:
            return
        instrument = self._instruments.get(order.instrument_id)
        if instrument is None or instrument.settlement_currency != self._currency:
            raise ValueError("Account cash reservation requires a known same-currency Instrument")
        reference = self._reference_price(order)
        price = order.price or (reference if isinstance(reference, OnlyPrice) else None)
        if price is None:
            raise ValueError("market BUY requires a deterministic Account reference price")
        quantum = Decimal(1).scaleb(-self._currency.precision)
        amount = OnlyMoney(
            (price.value * order.quantity.value * instrument.contract_multiplier.value).quantize(quantum),
            self._currency,
        )
        zero = OnlyMoney(Decimal(0), self._currency)
        reservation_id = OnlyAccountReservationId(f"ARESV-{order.runtime_id}-{order.order_id}")
        self._manager.reserve_cash(
            OnlyAccountReservation(
                reservation_id,
                order.runtime_id,
                order.account_id,
                order.order_id,
                amount,
                zero,
                amount,
                OnlyAccountReservationState.ACTIVE,
                timestamp,
                timestamp,
            )
        )
        self._reservations[order.order_id] = reservation_id

    def sent(self, order_id: OnlyOrderId, timestamp: OnlyTimestamp) -> None:
        del order_id, timestamp

    def acknowledged(self, order_id: OnlyOrderId, timestamp: OnlyTimestamp) -> None:
        del order_id, timestamp

    def consume(self, fill: OnlyOrderFill, timestamp: OnlyTimestamp) -> None:
        reservation_id = self._reservations.get(fill.order_id)
        if reservation_id is None:
            return
        quantum = Decimal(1).scaleb(-self._currency.precision)
        amount = OnlyMoney((fill.price.value * fill.quantity.value).quantize(quantum), self._currency)
        self._manager.consume_cash_reservation(reservation_id, amount, timestamp)

    def release(self, order_id: OnlyOrderId, timestamp: OnlyTimestamp) -> None:
        reservation_id = self._reservations.get(order_id)
        if reservation_id is not None:
            self._manager.release_cash(reservation_id, timestamp)


class OnlyRuntimeCompositeCashReservationAdapter:
    """Coordinates two independent cash books without sharing their state."""

    def __init__(self, account: OnlyOrderCashReservationPort, strategy: OnlyOrderCashReservationPort) -> None:
        self.account = account
        self.strategy = strategy

    def reserve(self, order: OnlyOrderSnapshot, timestamp: OnlyTimestamp) -> None:
        self.account.reserve(order, timestamp)
        try:
            self.strategy.reserve(order, timestamp)
        except Exception:
            self.account.release(order.order_id, timestamp)
            raise

    def sent(self, order_id: OnlyOrderId, timestamp: OnlyTimestamp) -> None:
        self.account.sent(order_id, timestamp)
        self.strategy.sent(order_id, timestamp)

    def acknowledged(self, order_id: OnlyOrderId, timestamp: OnlyTimestamp) -> None:
        self.account.acknowledged(order_id, timestamp)
        self.strategy.acknowledged(order_id, timestamp)

    def consume(self, fill: OnlyOrderFill, timestamp: OnlyTimestamp) -> None:
        self.account.consume(fill, timestamp)
        self.strategy.consume(fill, timestamp)

    def release(self, order_id: OnlyOrderId, timestamp: OnlyTimestamp) -> None:
        self.account.release(order_id, timestamp)
        self.strategy.release(order_id, timestamp)


class OnlyRuntime:
    """Base Runtime facade; concrete modes own their mutable resources."""

    def __init__(self, config: OnlyRuntimeAssemblyConfig) -> None:
        self.config = config
        self._state = OnlyRuntimeState.CREATED
        self._services: OnlyRuntimeServices
        self._last_error: str | None = None
        self._plugin_resources: tuple[OnlyPluginResource, ...] = ()
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
        self._account_reservation_manager = OnlyAccountReservationManager(config.runtime_id)  # type: ignore[arg-type]
        self._account_manager = OnlyAccountManager(
            config.runtime_id,  # type: ignore[arg-type]
            reservation_manager=self._account_reservation_manager,
        )
        self._account_query = OnlyAccountQueryService(self._account_manager)
        self._settlement_manager = OnlySettlementManager()
        self._margin_manager = OnlyMarginManager()
        self._fee_manager = OnlyFeeManager()

    @property
    def runtime_id(self) -> str:
        return str(self.config.runtime_id)

    @property
    def runtime_type(self) -> str:
        return self.config.mode.value

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
    def account_manager(self) -> OnlyAccountManager:
        """Runtime-owned local Account truth; never injected into a Cluster."""

        return self._account_manager

    @property
    def account_reservation_manager(self) -> OnlyAccountReservationManager:
        return self._account_reservation_manager

    @property
    def settlement_manager(self) -> OnlySettlementManager:
        return self._settlement_manager

    @property
    def margin_manager(self) -> OnlyMarginManager:
        return self._margin_manager

    @property
    def fee_manager(self) -> OnlyFeeManager:
        return self._fee_manager

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
    def execution_service(self) -> OnlyExecutionService:
        return self._services.execution_service

    @property
    def execution_processor(self) -> OnlyExecutionProcessor:
        """Runtime-owned sole business consumer for Broker inbound updates."""

        return self._services.execution_processor

    @property
    def execution_audit_store(self) -> OnlyInMemoryExecutionAuditStore:
        return self._services.execution_audit_store

    @property
    def execution_reconciliation_queue(self) -> OnlyInMemoryExecutionReconciliationQueue:
        return self._services.execution_reconciliation_queue

    @property
    def execution_update_deduplicator(self) -> OnlyExecutionUpdateDeduplicator:
        return self._services.execution_update_deduplicator

    @property
    def execution_sequence_tracker(self) -> OnlyExecutionSequenceTracker:
        return self._services.execution_sequence_tracker

    @property
    def broker_gateway(self) -> OnlyBacktestBrokerGateway | None:
        return self._services.broker_gateway

    @property
    def broker_inbound_queue(self) -> OnlyBrokerInboundQueue:
        return self._services.broker_inbound

    @property
    def market_data_source_registry(self) -> OnlyMarketDataSourceRegistry:
        return self._services.market_data_source_registry

    @property
    def historical_data_source(self) -> OnlyInMemoryHistoricalDataSource:
        return self._services.historical_data_source

    @property
    def reference_data_source(self) -> OnlyInMemoryReferenceDataSource:
        return self._services.reference_data_source

    @property
    def market_data_gateway(self) -> OnlyInMemoryMarketDataGateway:
        return self._services.market_data_gateway

    @property
    def market_data_inbound_queue(self) -> OnlyMarketDataInboundQueue:
        return self._services.market_data_inbound

    @property
    def market_data_processor(self) -> OnlyMarketDataProcessor:
        return self._services.market_data_processor

    @property
    def historical_replay_service(self) -> OnlyHistoricalReplayService:
        return self._services.historical_replay_service

    @property
    def market_data_audit_store(self) -> OnlyMarketDataAuditStore:
        return self._services.market_data_audit_store

    @property
    def market_data_deduplicator(self) -> OnlyMarketDataDeduplicator:
        return self._services.market_data_deduplicator

    @property
    def market_data_sequence_tracker(self) -> OnlyMarketDataSequenceTracker:
        return self._services.market_data_sequence_tracker

    @property
    def market_data_gap_detector(self) -> OnlyMarketDataGapDetector:
        return self._services.market_data_gap_detector

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
        initialized: list[OnlyPluginResource] = []
        current_resource: OnlyPluginResource | None = None
        try:
            for resource in self._plugin_resources:
                current_resource = resource
                resource.initialize()
                initialized.append(resource)
                resource.connect()
            self._services.cluster_manager.initialize_all()
            self._state = OnlyRuntimeState.READY
        except Exception as exc:
            self._rollback_plugin_resources(tuple(initialized))
            self._state = OnlyRuntimeState.FAILED
            failing = self._plugin_context(current_resource)
            raise OnlyPluginLifecycleError(
                "PLUGIN_INITIALIZATION_FAILED",
                str(exc),
                plugin_id=failing[0],
                resource_id=failing[1],
            ) from exc

    def start(self) -> None:
        if self._state is OnlyRuntimeState.CREATED:
            self.initialize()
        if self._state is not OnlyRuntimeState.READY:
            raise OnlyLifecycleError("Runtime can only start from READY")
        current_resource: OnlyPluginResource | None = None
        try:
            for resource in self._plugin_resources:
                current_resource = resource
                resource.start()
            self._services.cluster_manager.start_all()
        except Exception as exc:
            self._rollback_plugin_resources(self._plugin_resources)
            self._state = OnlyRuntimeState.FAILED
            failing = self._plugin_context(current_resource)
            raise OnlyPluginLifecycleError(
                "PLUGIN_START_FAILED",
                str(exc),
                plugin_id=failing[0],
                resource_id=failing[1],
            ) from exc
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
        failure = self._run_plugin_cleanup("stop")
        if failure is not None:
            self._state = OnlyRuntimeState.FAILED
            raise failure
        self._state = OnlyRuntimeState.STOPPED

    def close(self) -> None:
        if self._state is OnlyRuntimeState.CLOSED:
            return
        failure: Exception | None = None
        try:
            self.stop()
        except Exception as exc:
            failure = exc
        try:
            self._services.cluster_manager.unload_all()
        except Exception as exc:
            failure = failure or exc
        plugin_failure = self._run_plugin_cleanup("close")
        failure = failure or plugin_failure
        try:
            self._services.event_bus.close()
        except Exception as exc:
            failure = failure or exc
        try:
            self._services.clock.close()
        except Exception as exc:
            failure = failure or exc
        if failure is not None:
            self._state = OnlyRuntimeState.FAILED
            raise failure
        self._state = OnlyRuntimeState.CLOSED

    def run(self) -> object:
        raise OnlyRuntimeError(f"{self.runtime_type} Runtime has no configured run loop")

    def snapshot(self) -> OnlyRuntimeStatus:
        return self.status()

    @property
    def plugin_resource_snapshots(self) -> tuple[OnlyPluginResourceSnapshot, ...]:
        return tuple(
            OnlyPluginResourceSnapshot(
                resource.plugin_descriptor.plugin_id,
                resource.plugin_descriptor.plugin_type.value,
                resource.plugin_resource_id,
                resource.state,
                resource.health(),
                resource.plugin_descriptor.capabilities,
                1,
            )
            for resource in self._plugin_resources
        )

    def _bind_plugin_resources(self, resources: tuple[OnlyPluginResource, ...]) -> None:
        if self._state is not OnlyRuntimeState.CREATED or self._plugin_resources:
            raise OnlyLifecycleError("plugin resources must be bound once while Runtime is CREATED")
        self._plugin_resources = resources

    def _rollback_plugin_resources(self, resources: tuple[OnlyPluginResource, ...]) -> None:
        for operation in ("stop", "close"):
            for resource in reversed(resources):
                try:
                    getattr(resource, operation)()
                except Exception:
                    plugin_id, resource_id = self._plugin_context(resource)
                    _LOGGER.exception(
                        "plugin rollback %s failed: plugin_id=%s resource_id=%s",
                        operation,
                        plugin_id,
                        resource_id,
                    )

    def _run_plugin_cleanup(self, operation: str) -> OnlyPluginLifecycleError | None:
        first_failure: OnlyPluginLifecycleError | None = None
        for resource in reversed(self._plugin_resources):
            try:
                getattr(resource, operation)()
            except Exception as exc:
                plugin_id, resource_id = self._plugin_context(resource)
                _LOGGER.exception(
                    "plugin %s failed: plugin_id=%s resource_id=%s",
                    operation,
                    plugin_id,
                    resource_id,
                )
                if first_failure is None:
                    first_failure = OnlyPluginLifecycleError(
                        f"PLUGIN_{operation.upper()}_FAILED",
                        str(exc),
                        plugin_id=plugin_id,
                        resource_id=resource_id,
                    )
        return first_failure

    @staticmethod
    def _plugin_context(resource: OnlyPluginResource | None) -> tuple[str | None, str | None]:
        if resource is None:
            return None, None
        return resource.plugin_descriptor.plugin_id, resource.plugin_resource_id

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
