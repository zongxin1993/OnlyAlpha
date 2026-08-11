"""Private service bundles owned by one Trading Kernel."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.account.manager import OnlyAccountManager
from onlyalpha.account.performance import OnlyAccountPerformanceProjector
from onlyalpha.account.reservations import OnlyAccountReservationManager
from onlyalpha.account.views import OnlyAccountQueryService
from onlyalpha.broker.ports import OnlyBrokerGateway
from onlyalpha.cluster.manager import OnlyClusterManager
from onlyalpha.core.clock import OnlyClock
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
from onlyalpha.data.sources import OnlyInMemoryHistoricalDataSource, OnlyInMemoryReferenceDataSource
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.event.subscription_view import OnlyEventBusSubscriptionView
from onlyalpha.execution.event_buffer import OnlyExecutionEventBuffer
from onlyalpha.execution.processor import OnlyExecutionProcessor
from onlyalpha.execution.state import (
    OnlyExecutionSequenceTracker,
    OnlyExecutionUpdateDeduplicator,
    OnlyInMemoryExecutionAuditStore,
    OnlyInMemoryExecutionReconciliationQueue,
)
from onlyalpha.fee.ledger import OnlyFeeApplicationLedger
from onlyalpha.fee.reconciliation_authority import OnlyFeeReconciliationAuthority
from onlyalpha.fee.risk_gate import OnlyFeeReconciliationRiskGate
from onlyalpha.indicator.pipeline import OnlyIndicatorPipeline
from onlyalpha.margin.manager import OnlyMarginManager
from onlyalpha.market_data.aggregation.manager import OnlyBarAggregationManager
from onlyalpha.market_data.cache import OnlyMarketDataCache
from onlyalpha.market_data.dispatcher import OnlyStrategyBarDispatcher
from onlyalpha.market_data.pipeline import OnlyMarketDataPipeline
from onlyalpha.order.execution.processor import OnlyOrderUpdateProcessor
from onlyalpha.order.execution.service import OnlyExecutionService
from onlyalpha.order.manager import OnlyOrderManager
from onlyalpha.order.query import OnlyOrderQueryService
from onlyalpha.order.service import OnlyOrderService
from onlyalpha.plugin.broker import OnlyBrokerInboundQueue
from onlyalpha.position.allocation_manager import OnlyPositionAllocationManager
from onlyalpha.position.manager import OnlyPositionManager
from onlyalpha.position.queries import OnlyPositionQueryService
from onlyalpha.position.reservations import OnlyPositionReservationManager
from onlyalpha.risk.service import OnlyRiskService
from onlyalpha.runtime.events.router import OnlyRuntimeEventRouter
from onlyalpha.settlement.authority import OnlySettlementAuthority
from onlyalpha.strategy_ledger.locator import OnlyStrategyLedgerLocator
from onlyalpha.strategy_ledger.manager import OnlyStrategyLedgerManager
from onlyalpha.strategy_ledger.query import OnlyStrategyLedgerQueryService
from onlyalpha.strategy_ledger.valuation import OnlyStrategyValuationService
from onlyalpha.transaction.coordinator import OnlyRuntimeTransactionCoordinator
from onlyalpha.transaction.delivery import (
    OnlyExecutionEventDeliveryCoordinator,
    OnlyExecutionOutboxPublisher,
)
from onlyalpha.transaction.persistence_ports import (
    OnlyProjectionReadyRuntimeQueryPort,
    OnlyRuntimeProjectionStatePort,
    OnlyRuntimeTransactionOutboxPort,
    OnlyRuntimeTransactionQueryPort,
)
from onlyalpha.transaction.recovery import OnlyExecutionRecoveryService


@dataclass(slots=True)
class OnlyTradingAuthorities:
    """Mutable economic authorities with exactly one owner per Trading Runtime."""

    position_manager: OnlyPositionManager
    allocation_manager: OnlyPositionAllocationManager
    position_reservation_manager: OnlyPositionReservationManager
    position_query: OnlyPositionQueryService
    strategy_ledger_manager: OnlyStrategyLedgerManager
    strategy_ledger_query: OnlyStrategyLedgerQueryService
    strategy_ledger_locator: OnlyStrategyLedgerLocator
    account_reservation_manager: OnlyAccountReservationManager
    account_manager: OnlyAccountManager
    account_performance_projector: OnlyAccountPerformanceProjector
    account_query: OnlyAccountQueryService
    settlement_authority: OnlySettlementAuthority
    margin_manager: OnlyMarginManager
    fee_application_ledger: OnlyFeeApplicationLedger
    fee_reconciliation_authority: OnlyFeeReconciliationAuthority
    fee_reconciliation_risk_gate: OnlyFeeReconciliationRiskGate


@dataclass(slots=True)
class OnlyTradingKernelServices:
    """Installed shared processing graph; never exposed to Strategy Context."""

    clock: OnlyClock
    event_bus: OnlyEventBus
    event_bus_view: OnlyEventBusSubscriptionView
    event_router: OnlyRuntimeEventRouter
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
    settlement_authority: OnlySettlementAuthority
    margin_manager: OnlyMarginManager
    fee_application_ledger: OnlyFeeApplicationLedger
    strategy_valuation_service: OnlyStrategyValuationService
    account_manager: OnlyAccountManager
    account_performance_projector: OnlyAccountPerformanceProjector
    account_query: OnlyAccountQueryService
    broker_inbound: OnlyBrokerInboundQueue
    broker_gateway: OnlyBrokerGateway | None
    execution_processor: OnlyExecutionProcessor
    execution_commit_coordinator: OnlyRuntimeTransactionCoordinator
    execution_recovery_service: OnlyExecutionRecoveryService
    execution_transaction_query: OnlyRuntimeTransactionQueryPort
    ready_execution_query: OnlyProjectionReadyRuntimeQueryPort
    execution_projection_state: OnlyRuntimeProjectionStatePort
    runtime_transaction_outbox: OnlyRuntimeTransactionOutboxPort
    execution_event_buffer: OnlyExecutionEventBuffer
    execution_delivery_coordinator: OnlyExecutionEventDeliveryCoordinator
    execution_outbox_publisher: OnlyExecutionOutboxPublisher
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
