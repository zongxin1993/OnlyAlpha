"""Runtime resource ownership and deterministic Backtest orchestration."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

from onlyalpha.account.enums import OnlyAccountReservationState
from onlyalpha.account.events import OnlyAccountEvent, OnlyAccountEventPublisher
from onlyalpha.account.identifiers import OnlyAccountReservationId
from onlyalpha.account.manager import OnlyAccountManager
from onlyalpha.account.models import OnlyAccountReservation, OnlyAccountSnapshot
from onlyalpha.account.performance import (
    OnlyAccountPerformanceProjector,
    OnlyAccountValuationSource,
)
from onlyalpha.account.reservations import OnlyAccountReservationManager
from onlyalpha.account.views import OnlyAccountQueryService
from onlyalpha.broker.identifiers import OnlyBrokerGatewayId
from onlyalpha.broker.ports import OnlyBrokerGateway
from onlyalpha.cluster.base import OnlyCluster, OnlyClusterState
from onlyalpha.cluster.manager import (
    OnlyClusterExecutionResult,
    OnlyClusterManager,
    OnlyClusterStatus,
)
from onlyalpha.core.clock import OnlyClock, OnlyTimeAdvanceResult
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
from onlyalpha.event.bus import OnlyEventQueuePolicy
from onlyalpha.event.model import OnlyEvent
from onlyalpha.event.subscription_view import OnlyEventBusSubscriptionView
from onlyalpha.execution.processor import OnlyExecutionProcessor
from onlyalpha.execution.state import (
    OnlyExecutionSequenceTracker,
    OnlyExecutionUpdateDeduplicator,
    OnlyInMemoryExecutionAuditStore,
    OnlyInMemoryExecutionReconciliationQueue,
)
from onlyalpha.fee.basis import OnlyFeeBasisProviderRegistry
from onlyalpha.fee.broker_contract import OnlyBrokerFeeContract
from onlyalpha.fee.ledger import OnlyFeeApplicationLedger
from onlyalpha.fee.market_pack import OnlyMarketFeePack
from onlyalpha.fee.reconciliation_authority import OnlyFeeReconciliationAuthority
from onlyalpha.fee.reconciliation_policy import OnlyFeeReconciliationPolicy
from onlyalpha.fee.risk_gate import OnlyFeeReconciliationRiskGate
from onlyalpha.margin.manager import OnlyMarginManager
from onlyalpha.market.runtime_rules import OnlyMarketRuleEngine
from onlyalpha.market_data.dispatcher import (
    OnlyBarDispatchExecutor,
    OnlyBarDispatchResult,
)
from onlyalpha.market_data.pipeline import OnlyMarketDataPipeline, OnlyMarketDataUpdateResult
from onlyalpha.market_data.snapshot import OnlyMarketDataSnapshot
from onlyalpha.order.cash_port import OnlyOrderCashReservationPort
from onlyalpha.order.execution.service import OnlyExecutionService
from onlyalpha.order.manager import OnlyOrderManager
from onlyalpha.plugin.broker import OnlyBrokerInboundQueue
from onlyalpha.plugin.errors import OnlyPluginLifecycleError
from onlyalpha.plugin.lifecycle import OnlyPluginResource, OnlyPluginResourceSnapshot
from onlyalpha.position.allocation_manager import OnlyPositionAllocationManager
from onlyalpha.position.events import OnlyPositionEvent
from onlyalpha.position.manager import OnlyPositionManager
from onlyalpha.position.ports import OnlyPositionEventPublisher
from onlyalpha.position.queries import OnlyPositionQueryService
from onlyalpha.position.reservations import OnlyPositionReservationManager
from onlyalpha.risk.profile import OnlyRiskProfile
from onlyalpha.risk.service import OnlyRiskService
from onlyalpha.runtime.events.gate import OnlyRuntimeEventGatePhase, OnlyRuntimeEventGateSnapshot
from onlyalpha.runtime.persistence.store import (
    OnlyRuntimePersistenceStorePort,
)
from onlyalpha.runtime.trading.builder import OnlyTradingKernelBuilder
from onlyalpha.runtime.trading.config import OnlyTradingKernelConfig
from onlyalpha.runtime.trading.services import OnlyTradingKernelServices
from onlyalpha.settlement.authority import OnlySettlementAuthority
from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey
from onlyalpha.strategy_ledger.locator import OnlyStrategyLedgerLocator
from onlyalpha.strategy_ledger.manager import OnlyStrategyLedgerManager
from onlyalpha.strategy_ledger.query import OnlyStrategyLedgerQueryService
from onlyalpha.transaction.delivery import (
    OnlyExecutionDeliveryDiagnostic,
    OnlyExecutionEventDeliveryIntent,
    OnlyExecutionEventDeliveryMode,
    OnlyExecutionEventDeliveryResult,
    OnlyOutboxPublishResult,
)
from onlyalpha.transaction.persistence_ports import (
    OnlyProjectionReadyRuntimeQueryPort,
    OnlyRuntimeTransactionQueryPort,
)
from onlyalpha.transaction.recovery import (
    OnlyExecutionRecoveryResult,
)

_LOGGER = logging.getLogger(__name__)


class OnlyRuntimeError(Exception):
    """Base Runtime orchestration error."""


class OnlyRuntimeRecoveryError(OnlyRuntimeError):
    """Startup was blocked because committed execution authority could not recover."""

    def __init__(self, result: OnlyExecutionRecoveryResult) -> None:
        self.result = result
        super().__init__(
            "execution recovery failed: "
            f"runtime_id={result.runtime_id} status={result.status.value} "
            f"coordinator_status={None if result.coordinator_status is None else result.coordinator_status.value} "
            f"sequence={result.failed_sequence} transaction_id={result.failed_transaction_id} "
            f"component={None if result.failure_component is None else result.failure_component.value} "
            f"projection_error={result.projection_error!r} error={result.error!r}"
        )


class OnlyRuntimeOutboxDeliveryError(OnlyRuntimeError):
    """Recovered durable events could not be delivered before Cluster startup."""


class OnlyRuntimeState(StrEnum):
    CREATED = "CREATED"
    INITIALIZING = "INITIALIZING"
    RECOVERING = "RECOVERING"
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
    strategy_base_currency: OnlyCurrency = OnlyCurrency("CNY", 2)
    strategy_capitals: Mapping[OnlyClusterId, OnlyMoney] = field(default_factory=dict)
    broker_gateway_id: OnlyBrokerGatewayId | None = None
    account_initial_cash: OnlyMoney | None = None
    market_rule_engine: OnlyMarketRuleEngine | None = None
    market_fee_pack: OnlyMarketFeePack | None = None
    broker_fee_contract: OnlyBrokerFeeContract | None = None
    broker_fee_authority_id: str | None = None
    fee_basis_providers: OnlyFeeBasisProviderRegistry | None = None
    fee_reconciliation_policy: OnlyFeeReconciliationPolicy | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "engine_id",
            self.engine_id if isinstance(self.engine_id, OnlyEngineId) else OnlyEngineId(self.engine_id),
        )
        capitals = MappingProxyType(dict(self.strategy_capitals))
        if any(value.amount < 0 for value in capitals.values()):
            raise ValueError("Strategy capital cannot be negative")
        if any(value.currency != self.strategy_base_currency for value in capitals.values()):
            raise ValueError("Strategy capital currency must equal Runtime base currency")
        object.__setattr__(self, "strategy_capitals", capitals)
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


OnlyRuntimeServices = OnlyTradingKernelServices
"""Deprecated internal name retained while callers migrate to the Kernel boundary."""


class OnlyManagedBarDispatchExecutor(OnlyBarDispatchExecutor):
    """Adapts Dispatcher selection to ClusterManager execution."""

    def __init__(
        self,
        manager: OnlyClusterManager,
        set_snapshot: Callable[[OnlyClusterId, OnlyMarketDataSnapshot | None], None],
        prepare_risk: Callable[[OnlyClusterId, OnlyMarketDataSnapshot], None],
        begin_events: Callable[[], None] | None = None,
        complete_events: Callable[[bool], None] | None = None,
    ) -> None:
        self._manager = manager
        self._set_snapshot = set_snapshot
        self._prepare_risk = prepare_risk
        self._begin_events = begin_events
        self._complete_events = complete_events

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
        if self._begin_events is not None:
            self._begin_events()
        try:
            result = self._manager.execute_bar(cluster_id, bar, snapshot)
        except Exception:
            if self._complete_events is not None:
                self._complete_events(False)
            raise
        else:
            if self._complete_events is not None:
                self._complete_events(True)
            return result
        finally:
            self._set_snapshot(cluster_id, None)


class OnlyRuntimePositionEventPublisherAdapter(OnlyPositionEventPublisher):
    """Publishes completed Position facts to the owning Runtime EventBus."""

    def __init__(self, engine_id: OnlyEngineId, publish_event: Callable[[OnlyEvent], None]) -> None:
        self._engine_id = engine_id
        self._publish_event = publish_event

    def publish(self, event: OnlyPositionEvent) -> None:
        self._publish_event(
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

    def __init__(self, engine_id: OnlyEngineId, publish_event: Callable[[OnlyEvent], None]) -> None:
        self._engine_id = engine_id
        self._publish_event = publish_event

    def publish(self, event: OnlyAccountEvent) -> None:
        snapshot = event.snapshot
        self._publish_event(
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
        if order.funding_plan is None:
            raise ValueError("ORDER_FUNDING_PLAN_REQUIRED")
        estimated_fee = order.funding_plan.fee_reservation
        if order.funding_plan.principal_reservation != amount:
            raise ValueError("ORDER_FUNDING_PLAN_PRINCIPAL_CONFLICT")
        reservation_id = OnlyAccountReservationId(f"ARESV-{order.runtime_id}-{order.order_id}")
        self._manager.reserve_cash(
            OnlyAccountReservation(
                reservation_id,
                order.runtime_id,
                order.account_id,
                order.order_id,
                amount + estimated_fee,
                OnlyMoney(Decimal(0), self._currency),
                amount + estimated_fee,
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

    def consume_confirmed(self, fill: OnlyOrderFill, amount: OnlyMoney, timestamp: OnlyTimestamp) -> None:
        reservation_id = self._reservations.get(fill.order_id)
        if reservation_id is None:
            return
        self._manager.consume_cash_reservation(reservation_id, amount, timestamp)

    def consume(self, fill: OnlyOrderFill, timestamp: OnlyTimestamp) -> None:
        """Order-port compatibility; confirmed execution uses ``consume_confirmed``."""
        del fill, timestamp

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

    _supported_modes: frozenset[OnlyRuntimeMode] = frozenset()

    def __init__(self, config: OnlyRuntimeAssemblyConfig) -> None:
        if config.mode not in self._supported_modes:
            raise ValueError(f"{type(self).__name__} does not support {config.mode.value} mode")
        self.config = config
        self._state = OnlyRuntimeState.CREATED
        self._trading_kernel = OnlyTradingKernelBuilder().build(
            OnlyTradingKernelConfig(
                config.engine_id,  # type: ignore[arg-type]
                config.runtime_id,  # type: ignore[arg-type]
                config.default_account_id,  # type: ignore[arg-type]
                config.strategy_base_currency,
                config.strategy_capitals,
                config.event_capacity,
                config.history_limit,
                config.event_queue_policy,
            )
        )
        self._last_error: str | None = None
        self._execution_delivery_diagnostics: list[OnlyExecutionDeliveryDiagnostic] = []
        self._execution_recovery_diagnostics: list[OnlyExecutionRecoveryResult] = []
        self._plugin_resources: tuple[OnlyPluginResource, ...] = ()
        self._runtime_persistence_store: OnlyRuntimePersistenceStorePort | None = None
        self._clusters_started = False
        self._clusters_recovered = False
        self._stop_attempted = False
        self._close_attempted = False
        self._stop_failure: BaseException | None = None

    @property
    def _services(self) -> OnlyTradingKernelServices:
        return self._trading_kernel.services

    @property
    def _position_manager(self) -> OnlyPositionManager:
        return self._trading_kernel.authorities.position_manager

    @property
    def _allocation_manager(self) -> OnlyPositionAllocationManager:
        return self._trading_kernel.authorities.allocation_manager

    @property
    def _position_query(self) -> OnlyPositionQueryService:
        return self._trading_kernel.authorities.position_query

    @property
    def _position_reservation_manager(self) -> OnlyPositionReservationManager:
        return self._trading_kernel.authorities.position_reservation_manager

    @property
    def _strategy_ledger_manager(self) -> OnlyStrategyLedgerManager:
        return self._trading_kernel.authorities.strategy_ledger_manager

    @property
    def _strategy_ledger_query(self) -> OnlyStrategyLedgerQueryService:
        return self._trading_kernel.authorities.strategy_ledger_query

    @property
    def _strategy_ledger_locator(self) -> OnlyStrategyLedgerLocator:
        return self._trading_kernel.authorities.strategy_ledger_locator

    @property
    def _account_reservation_manager(self) -> OnlyAccountReservationManager:
        return self._trading_kernel.authorities.account_reservation_manager

    @property
    def _account_manager(self) -> OnlyAccountManager:
        return self._trading_kernel.authorities.account_manager

    @property
    def _account_performance_projector(self) -> OnlyAccountPerformanceProjector:
        return self._trading_kernel.authorities.account_performance_projector

    @property
    def _account_query(self) -> OnlyAccountQueryService:
        return self._trading_kernel.authorities.account_query

    @property
    def _settlement_authority(self) -> OnlySettlementAuthority:
        return self._trading_kernel.authorities.settlement_authority

    @property
    def _margin_manager(self) -> OnlyMarginManager:
        return self._trading_kernel.authorities.margin_manager

    @property
    def _fee_application_ledger(self) -> OnlyFeeApplicationLedger:
        return self._trading_kernel.authorities.fee_application_ledger

    @property
    def _fee_reconciliation_authority(self) -> OnlyFeeReconciliationAuthority:
        return self._trading_kernel.authorities.fee_reconciliation_authority

    @property
    def _fee_reconciliation_risk_gate(self) -> OnlyFeeReconciliationRiskGate:
        return self._trading_kernel.authorities.fee_reconciliation_risk_gate

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
    def strategy_ledger_locator(self) -> OnlyStrategyLedgerLocator:
        return self._strategy_ledger_locator

    @property
    def account_manager(self) -> OnlyAccountManager:
        """Runtime-owned local Account truth; never injected into a Cluster."""

        return self._account_manager

    @property
    def account_performance_projector(self) -> OnlyAccountPerformanceProjector:
        return self._account_performance_projector

    def _project_account_performance(
        self,
        snapshot: OnlyAccountSnapshot,
        source: OnlyAccountValuationSource,
        previous: OnlyAccountSnapshot | None,
    ) -> None:
        self._account_performance_projector.record(snapshot, source, previous=previous)

    @property
    def account_reservation_manager(self) -> OnlyAccountReservationManager:
        return self._account_reservation_manager

    @property
    def settlement_authority(self) -> OnlySettlementAuthority:
        return self._settlement_authority

    @property
    def margin_manager(self) -> OnlyMarginManager:
        return self._margin_manager

    @property
    def fee_application_ledger(self) -> OnlyFeeApplicationLedger:
        return self._fee_application_ledger

    @property
    def fee_reconciliation_risk_gate(self) -> OnlyFeeReconciliationRiskGate:
        return self._fee_reconciliation_risk_gate

    @property
    def fee_reconciliation_authority(self) -> OnlyFeeReconciliationAuthority:
        return self._fee_reconciliation_authority

    @property
    def clock(self) -> OnlyClock:
        """Runtime management clock; Cluster receives only ``OnlyClockView``."""

        return self._services.clock

    @property
    def event_bus(self) -> OnlyEventBusSubscriptionView:
        """Read-only Runtime event subscription and diagnostic view."""

        return self._services.event_bus_view

    @property
    def event_gate_snapshot(self) -> OnlyRuntimeEventGateSnapshot:
        return self._services.event_router.snapshot()

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
    def broker_gateway(self) -> OnlyBrokerGateway | None:
        return self._services.broker_gateway

    @property
    def execution_transaction_query(self) -> OnlyRuntimeTransactionQueryPort:
        """Administrative query over every durably committed transaction."""

        return self._services.execution_transaction_query

    @property
    def ready_execution_query(self) -> OnlyProjectionReadyRuntimeQueryPort:
        """Business query over Projection Ready transactions only."""

        return self._services.ready_execution_query

    @property
    def execution_recovery_diagnostics(self) -> tuple[OnlyExecutionRecoveryResult, ...]:
        return tuple(self._execution_recovery_diagnostics)

    @property
    def execution_delivery_diagnostics(self) -> tuple[OnlyExecutionDeliveryDiagnostic, ...]:
        return tuple(self._execution_delivery_diagnostics)

    def _record_execution_delivery(
        self, processing_sequence: int | None, result: OnlyExecutionEventDeliveryResult
    ) -> None:
        self._execution_delivery_diagnostics.append(
            OnlyExecutionDeliveryDiagnostic(
                OnlyRuntimeId(str(self.config.runtime_id)),
                processing_sequence,
                result.mode,
                result.attempted,
                result.published,
                result.staged,
                result.suppressed,
                result.failed,
                result.remaining,
                result.last_error,
                OnlyTimestamp.from_unix_nanos(self._services.clock.timestamp_ns()),
            )
        )

    def _drain_execution_outbox(self) -> OnlyOutboxPublishResult:
        try:
            result = self._services.execution_outbox_publisher.publish_pending(
                OnlyRuntimeId(str(self.config.runtime_id))
            )
        except Exception as exc:
            raise OnlyRuntimeOutboxDeliveryError(
                f"execution Outbox query/delivery failed: {type(exc).__name__}: {exc}"
            ) from exc
        self._record_execution_delivery(
            None,
            OnlyExecutionEventDeliveryResult(
                OnlyExecutionEventDeliveryMode.DURABLE_OUTBOX,
                result.attempted,
                result.published,
                0,
                0,
                result.failed,
                result.remaining,
                result.stopped_on_error,
                result.last_error,
            ),
        )
        return result

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
            OnlyRuntimeId(str(self.config.runtime_id)),
            self.config.default_account_id,  # type: ignore[arg-type]
            cluster_id,
            self.config.strategy_base_currency,
        )
        try:
            configured_capital = self.config.strategy_capitals[cluster_id]
        except KeyError as exc:
            raise ValueError(f"No validated FIXED_CAPITAL allocation for Cluster {cluster_id}") from exc
        timestamp = OnlyTimestamp.from_unix_nanos(self._services.clock.timestamp_ns())
        self._services.execution_event_buffer.begin()
        try:
            self._strategy_ledger_manager.create_ledger(
                ledger_key,
                configured_capital,
                timestamp,
            )
            self._strategy_ledger_manager.activate_ledger(ledger_key, timestamp)
            profile = self._resolve_risk_profile(cluster.config.values.get("risk_profile"), cluster_id)
            allowed_accounts = self._parse_account_permissions(cluster.config.values.get("allowed_account_ids"))
            allowed_instruments = self._parse_instrument_permissions(
                cluster.config.values.get("allowed_instrument_ids")
            )
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
        except Exception:
            self._services.execution_event_buffer.abort()
            raise
        batch = self._services.execution_event_buffer.seal()
        delivery = self._services.execution_delivery_coordinator.deliver(
            self.config.runtime_id,  # type: ignore[arg-type]
            OnlyExecutionEventDeliveryIntent(OnlyExecutionEventDeliveryMode.DIRECT, direct_batch=batch),
        )
        self._record_execution_delivery(None, delivery)

    def initialize(self) -> None:
        if self._state is not OnlyRuntimeState.CREATED:
            raise OnlyLifecycleError("Runtime can only initialize from CREATED")
        self._state = OnlyRuntimeState.INITIALIZING
        initialized: list[OnlyPluginResource] = []
        current_resource: OnlyPluginResource | None = None
        try:
            for resource in self._plugin_resources:
                current_resource = resource
                resource.initialize()
                initialized.append(resource)
                resource.connect()
            self._services.cluster_manager.initialize_all()
            self._state = OnlyRuntimeState.RECOVERING
            self._recover_runtime()
            self._state = OnlyRuntimeState.READY
        except OnlyRuntimeRecoveryError:
            self._services.event_router.fail()
            self._rollback_plugin_resources(tuple(initialized))
            self._state = OnlyRuntimeState.FAILED
            raise
        except OnlyRuntimeError:
            self._services.event_router.fail()
            self._rollback_plugin_resources(tuple(initialized))
            self._state = OnlyRuntimeState.FAILED
            raise
        except Exception as exc:
            self._services.event_router.fail()
            self._rollback_plugin_resources(tuple(initialized))
            self._state = OnlyRuntimeState.FAILED
            failing = self._plugin_context(current_resource)
            raise OnlyPluginLifecycleError(
                "PLUGIN_INITIALIZATION_FAILED",
                str(exc),
                plugin_id=failing[0],
                resource_id=failing[1],
            ) from exc

    def _recover_runtime(self) -> None:
        """Concrete Runtime recovery hook invoked only in RECOVERING state."""

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
            self._services.event_router.open()
            outbox = self._drain_execution_outbox()
            if outbox.failed or outbox.remaining:
                raise OnlyRuntimeOutboxDeliveryError(
                    "recovered execution Outbox delivery failed: "
                    f"failed={outbox.failed} remaining={outbox.remaining} error={outbox.last_error!r}"
                )
            if self._clusters_recovered:
                self._services.cluster_manager.resume_recovered_all()
                self._require_all_clusters_running("resume recovered")
                self._clusters_started = True
                self._clusters_recovered = False
            elif not self._clusters_started:
                self._services.cluster_manager.start_all()
                self._require_all_clusters_running("start")
                self._clusters_started = True
            self._after_clusters_started()
            self._state = OnlyRuntimeState.RUNNING
            self._publish_runtime_fact("RUNTIME_STARTED")
            self._services.event_bus.drain()
        except OnlyRuntimeOutboxDeliveryError:
            self._services.event_router.fail()
            self._rollback_plugin_resources(self._plugin_resources)
            self._state = OnlyRuntimeState.FAILED
            raise
        except Exception as exc:
            self._services.event_router.fail()
            self._rollback_plugin_resources(self._plugin_resources)
            self._state = OnlyRuntimeState.FAILED
            failing = self._plugin_context(current_resource)
            raise OnlyPluginLifecycleError(
                "PLUGIN_START_FAILED",
                str(exc),
                plugin_id=failing[0],
                resource_id=failing[1],
            ) from exc

    def _after_clusters_started(self) -> None:
        """Concrete Runtime hook for a stable post-start boundary."""

    def _require_all_clusters_running(self, operation: str) -> None:
        failed = tuple(
            item for item in self._services.cluster_manager.status() if item.state is not OnlyClusterState.RUNNING
        )
        if not failed:
            return
        details = ", ".join(
            f"{item.cluster_id}:{item.state.value}"
            + ("" if item.last_failure is None else f":{item.last_failure.error_type}: {item.last_failure.message}")
            for item in failed
        )
        raise OnlyRuntimeError(f"Cluster {operation} failed: {details}")

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
        if self._stop_attempted:
            return
        self._stop_attempted = True
        previous_state = self._state
        self._state = OnlyRuntimeState.STOPPING
        failure: BaseException | None = None
        try:
            self._services.cluster_manager.stop_all()
        except BaseException as exc:
            failure = exc
        if previous_state not in {
            OnlyRuntimeState.CREATED,
            OnlyRuntimeState.INITIALIZING,
            OnlyRuntimeState.RECOVERING,
            OnlyRuntimeState.FAILED,
        }:
            try:
                self._drain_execution_outbox()
            except BaseException as exc:
                failure = failure or exc
        try:
            self._services.event_bus.drain()
        except BaseException as exc:
            failure = failure or exc
        plugin_failure = self._run_plugin_cleanup("stop")
        failure = failure or plugin_failure
        if failure is not None:
            try:
                self._services.event_router.fail()
            except BaseException as router_failure:
                failure.add_note(
                    f"Runtime event-router failure marking also failed: "
                    f"{type(router_failure).__name__}: {router_failure}"
                )
            self._state = OnlyRuntimeState.FAILED
            self._stop_failure = failure
            raise failure
        self._state = OnlyRuntimeState.STOPPED

    def close(self) -> None:
        if self._state is OnlyRuntimeState.CLOSED or self._close_attempted:
            return
        self._close_attempted = True
        failure = self._stop_failure
        if not self._stop_attempted:
            try:
                self.stop()
            except BaseException as exc:
                failure = failure or exc
        try:
            self._services.cluster_manager.unload_all()
        except BaseException as exc:
            failure = failure or exc
        plugin_failure = self._run_plugin_cleanup("close")
        failure = failure or plugin_failure
        try:
            if self._services.event_router.snapshot().phase not in {
                OnlyRuntimeEventGatePhase.OPEN,
                OnlyRuntimeEventGatePhase.FAILED,
                OnlyRuntimeEventGatePhase.CLOSED,
            }:
                self._services.event_router.fail()
            self._services.event_router.close()
        except BaseException as exc:
            failure = failure or exc
        try:
            self._services.event_bus.close()
        except BaseException as exc:
            failure = failure or exc
        if self._runtime_persistence_store is not None:
            try:
                self._runtime_persistence_store.close()
            except BaseException as exc:
                failure = failure or exc
        try:
            self._services.clock.close()
        except BaseException as exc:
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

    def _bind_runtime_persistence_store(self, store: OnlyRuntimePersistenceStorePort) -> None:
        if self._state is not OnlyRuntimeState.CREATED or self._runtime_persistence_store is not None:
            raise OnlyLifecycleError("Runtime Persistence Store must be bound once while Runtime is CREATED")
        self._runtime_persistence_store = store

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
        self._services.event_router.publish_lifecycle(
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
