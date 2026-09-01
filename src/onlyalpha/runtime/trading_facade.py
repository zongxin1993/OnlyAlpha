from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol, cast

from onlyalpha.account.enums import OnlyAccountEconomicCashflowType
from onlyalpha.account.funding import only_derive_funding_cashflow
from onlyalpha.account.models import (
    OnlyAccountCashBalance,
    OnlyAccountConfig,
    OnlyAccountEconomicCashflow,
    OnlyAccountSnapshot,
    OnlyAccountValuation,
)
from onlyalpha.account.reconciliation import OnlyAccountReconciliationService
from onlyalpha.account.views import OnlyAccountQueryView
from onlyalpha.broker.execution import OnlyBrokerExecutionService
from onlyalpha.broker.identifiers import OnlyBrokerGatewayId
from onlyalpha.broker.inbound import OnlyBoundedBrokerInboundQueue, OnlyBrokerInboundQueue
from onlyalpha.broker.ports import OnlyBrokerGateway
from onlyalpha.broker.reconciliation import (
    OnlyBrokerFactApplicationReceipt,
    OnlyBrokerFactApplicationStatus,
)
from onlyalpha.broker.updates import OnlyBrokerInboundUpdate, OnlyBrokerOrderAcceptedUpdate, OnlyBrokerTradeUpdate
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.cluster.base import OnlyCluster, OnlyClusterState
from onlyalpha.cluster.manager import OnlyClusterExecutionResult, OnlyClusterManager
from onlyalpha.config.persistence import OnlyRuntimePersistenceConfig
from onlyalpha.core.clock import OnlyBacktestClock, OnlyClock, OnlyClockView, OnlyTimerEvent, OnlyTimerHandle
from onlyalpha.core.errors import OnlyLifecycleError
from onlyalpha.data.audit import OnlyMarketDataAuditStore, OnlyMarketDataEventPublisher
from onlyalpha.data.enums import (
    OnlyDataSequenceSemantics,
    OnlyMarketDataProcessingStatus,
    OnlyMarketDataQualityFlag,
    OnlyMarketDataType,
)
from onlyalpha.data.gateway import OnlyInMemoryMarketDataGateway
from onlyalpha.data.historical.models import OnlyHistoricalFactRequest
from onlyalpha.data.identifiers import (
    OnlyDataSequence,
    OnlyDataVersion,
    OnlyMarketDataGatewayId,
    OnlyMarketDataSourceId,
)
from onlyalpha.data.identity import only_bar_update_id
from onlyalpha.data.models import (
    OnlyBarUpdate,
    OnlyFundingRateUpdate,
    OnlyHistoricalBarRequest,
    OnlyHistoricalDataRange,
    OnlyHistoricalDataStream,
    OnlyHistoricalReplayConfig,
    OnlyHistoricalReplayResult,
    OnlyMarketDataInboundUpdate,
    OnlyMarketDataProcessingResult,
    OnlyMarketDataQuality,
    OnlyReferencePriceUpdate,
)
from onlyalpha.data.ports import OnlyHistoricalDataSource, OnlyHistoricalFactSource
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
from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide
from onlyalpha.domain.execution import OnlyOrderRequest, OnlyOrderSnapshot
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyCalendarId,
    OnlyClusterId,
    OnlyEngineId,
    OnlyInstrumentId,
    OnlyPositionId,
    OnlyRuntimeId,
)
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.market import OnlyBar, OnlyBarType, OnlyFundingRateFact, OnlyReferencePriceFact
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.trading import OnlyReferencePriceKind
from onlyalpha.domain.value import OnlyMoney, OnlyMultiplier, OnlyPrice, OnlyRate
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.event.model import OnlyEventScope
from onlyalpha.event.subscription_view import OnlyEventBusSubscriptionView
from onlyalpha.execution.accepted_identity import only_capture_execution_order_accepted_authority
from onlyalpha.execution.accepted_planner import OnlyOrderAcceptedExecutionTransactionPlanner
from onlyalpha.execution.capability import OnlyExecutionSupportDecision
from onlyalpha.execution.causal_recovery import (
    OnlyExecutionRecoveryEntry,
    OnlyExecutionRecoveryEntryState,
    OnlyExecutionRecoveryResolution,
    OnlyExecutionRecoverySession,
)
from onlyalpha.execution.committed import OnlyCommittedExecutionFact
from onlyalpha.execution.enums import OnlyExecutionProcessingStatus
from onlyalpha.execution.event_buffer import OnlyExecutionEventBuffer
from onlyalpha.execution.execution_state import (
    OnlyAccountExecutionState,
    OnlyStrategyLedgerExecutionState,
    only_account_cash_reservation_execution_state,
    only_account_execution_state,
    only_allocation_execution_state,
    only_margin_reservation_execution_state,
    only_order_execution_state,
    only_position_execution_state,
    only_position_reservation_execution_state,
    only_risk_execution_state,
    only_risk_reservation_execution_state,
    only_strategy_cash_reservation_execution_state,
    only_strategy_ledger_execution_state,
)
from onlyalpha.execution.fill_identity import only_capture_execution_fill_authority
from onlyalpha.execution.invariants import OnlyExecutionInvariantChecker
from onlyalpha.execution.models import OnlyExecutionProcessingResult, OnlyExecutionProcessorConfig
from onlyalpha.execution.order_intent_durability import OnlyRuntimeOrderIntentDurabilityService
from onlyalpha.execution.planning_context import (
    OnlyAllocationCreationAuthority,
    OnlyOrderAcceptedExecutionPlanningContext,
    OnlyPositionCreationAuthority,
    OnlyTerminalExecutionPlanningContext,
    OnlyTradeExecutionPlanningContext,
)
from onlyalpha.execution.processor import OnlyExecutionProcessor
from onlyalpha.execution.projection_targets import (
    OnlyExecutionValuationAuthority,
    only_create_generic_t0_execution_projection_targets,
)
from onlyalpha.execution.reference import OnlyExecutionReferencePlanningService, OnlyExecutionReferenceProfile
from onlyalpha.execution.scope import OnlyExecutionPositionScope
from onlyalpha.execution.state import (
    OnlyExecutionSequenceTracker,
    OnlyExecutionUpdateDeduplicator,
    OnlyInMemoryExecutionAuditStore,
    OnlyInMemoryExecutionReconciliationQueue,
)
from onlyalpha.execution.terminal_identity import (
    OnlyBrokerOrderTerminalUpdate,
    only_capture_execution_terminal_authority,
)
from onlyalpha.execution.terminal_planner import OnlyTerminalExecutionTransactionPlanner
from onlyalpha.execution.trade_planner import OnlyTradeExecutionTransactionPlanner
from onlyalpha.fee.accrual_manager import OnlyOrderFeeAccrualManager
from onlyalpha.fee.engine import OnlyFeeEngine
from onlyalpha.fee.estimate import OnlyOrderFeeEstimate, OnlyOrderFundingPlan
from onlyalpha.fee.evidence import (
    OnlyExternalFeeEvidence,
    OnlyFeeReconciliationComponentIdentity,
)
from onlyalpha.fee.models import OnlyOrderFeePolicyBinding
from onlyalpha.fee.reconciliation import (
    OnlyFeeReconciliationDecision,
    OnlyFeeReconciliationInput,
    OnlyFeeReconciliationPlanner,
    OnlyLocalFeeReconciliationComponent,
)
from onlyalpha.fee.reconciliation_query import OnlyFeeApplicationLocalFactQuery
from onlyalpha.fee.resolver import OnlyFeeResolver
from onlyalpha.fee.transaction_planner import (
    OnlyFeeReconciliationPlanningContext,
    OnlyFeeReconciliationTransactionPlanner,
)
from onlyalpha.indicator.pipeline import OnlyIndicatorPipeline
from onlyalpha.margin.models import OnlyMarginReservation
from onlyalpha.margin.order_port import OnlyOrderMarginReservationAdapter
from onlyalpha.market.economics import OnlyCompiledFundingPolicy, OnlyEconomicModel
from onlyalpha.market.models import OnlyPositionEffect
from onlyalpha.market.runtime_rules import OnlyTradeApplicationRequest
from onlyalpha.market_data.aggregation.manager import OnlyBarAggregationManager
from onlyalpha.market_data.cache import OnlyMarketDataCache
from onlyalpha.market_data.dispatcher import (
    OnlyBarDispatchResult,
    OnlyClusterBarSubscription,
    OnlyStrategyBarDispatcher,
)
from onlyalpha.market_data.pipeline import OnlyMarketDataPipeline, OnlyMarketDataUpdateResult
from onlyalpha.market_data.realtime_state import OnlyRealtimeMarketStateStore
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
from onlyalpha.order.results import OnlyOrderSubmitResult
from onlyalpha.order.service import OnlyOrderService
from onlyalpha.order.views import OnlyOrderServiceView
from onlyalpha.plugin.broker import OnlyDeterministicBrokerDriver
from onlyalpha.plugin.lifecycle import OnlyPluginResource
from onlyalpha.position.authority import OnlyPositionAuthorityPolicy
from onlyalpha.position.enums import OnlyPositionMode
from onlyalpha.position.identifiers import OnlyPositionAllocationId
from onlyalpha.position.keys import OnlyPositionAllocationKey
from onlyalpha.position.models import OnlyPositionAllocationSnapshot, OnlyPositionSettlementFact, OnlyPositionTrade
from onlyalpha.position.pnl import OnlyLinearPnLModel, OnlyPositionValuationService
from onlyalpha.position.reconciliation import OnlyPositionReconciliationService
from onlyalpha.position.reservations import OnlyOrderPositionReservationAdapter
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
    OnlyRiskSnapshotView,
)
from onlyalpha.runtime.backtest.checkpoint import OnlyBacktestReplayCursor
from onlyalpha.runtime.backtest.recovery_boundary import OnlyBacktestRecoverySession
from onlyalpha.runtime.backtest.recovery_replay import OnlyBacktestRecoveryReplayService
from onlyalpha.runtime.backtest.result_progress import OnlyBacktestBarCompletion, OnlyBacktestResultProgress
from onlyalpha.runtime.checkpoint.model import OnlyCheckpointCapability
from onlyalpha.runtime.checkpoint.participant import (
    OnlyJsonRuntimeCheckpointParticipant,
    OnlyStatelessRuntimeCheckpointParticipant,
)
from onlyalpha.runtime.checkpoint.registry import OnlyRuntimeCheckpointParticipantRegistry
from onlyalpha.runtime.checkpoint.service import OnlyRuntimeCheckpointService
from onlyalpha.runtime.context import (
    OnlyClusterContext,
    OnlyInstrumentView,
    OnlyMarketDataView,
    OnlyRuntimeContextError,
    OnlyRuntimeLogger,
    OnlySubscriptionService,
    OnlyTimerService,
)
from onlyalpha.runtime.events.gate import OnlyRuntimeRecoveryEventGate
from onlyalpha.runtime.events.router import OnlyRuntimeEventRouter
from onlyalpha.runtime.persistence.store import OnlyRuntimePersistenceStorePort
from onlyalpha.runtime.reconciliation import (
    OnlyCommittedTradeFeeAttribution,
    OnlyRuntimeLedgerReconciliationService,
    OnlyRuntimeLedgerReconciliationStatus,
)
from onlyalpha.runtime.recovery.authority_views import (
    OnlyGatewayBrokerRecoveryAuthorityView,
    OnlyRuntimeBoundaryAuthorityView,
    OnlyRuntimeDriverFrontierView,
)
from onlyalpha.runtime.recovery.finalizer import OnlyRuntimeRecoveryFinalizer
from onlyalpha.runtime.recovery.orchestrator import (
    OnlyRuntimeRecoveryDiagnostic,
    OnlyRuntimeRecoveryOrchestrator,
)
from onlyalpha.runtime.recovery.outcome import OnlyRuntimeRecoveryOutcome
from onlyalpha.runtime.recovery.validation import (
    OnlyPostRecoveryValidationContext,
    OnlyPostRecoveryValidationReport,
    only_default_post_recovery_authority_validator,
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
from onlyalpha.runtime.trading_day_boundary import OnlyRuntimeTradingDayBoundaryCoordinator
from onlyalpha.strategy_ledger.enums import OnlyStrategyCashEntryType
from onlyalpha.strategy_ledger.identifiers import OnlyStrategyCashFlowId
from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey
from onlyalpha.strategy_ledger.models import (
    OnlyStrategyCashSnapshot,
    OnlyStrategyLedgerSnapshot,
    OnlyStrategyMarkPrice,
    OnlyStrategyPnLSnapshot,
)
from onlyalpha.strategy_ledger.order_port import OnlyOrderStrategyCashReservationAdapter
from onlyalpha.strategy_ledger.publisher import OnlyRuntimeStrategyLedgerEventPublisherAdapter
from onlyalpha.strategy_ledger.valuation import OnlyStrategyValuationService
from onlyalpha.strategy_ledger.views import OnlyStrategyLedgerContextView, OnlyStrategyLedgerRiskView
from onlyalpha.transaction.applied_projection import OnlyInMemoryAppliedRuntimeProjectionLedger
from onlyalpha.transaction.coordinator import (
    OnlyRuntimeTransactionCoordinationResult,
    OnlyRuntimeTransactionCoordinationStatus,
    OnlyRuntimeTransactionCoordinator,
)
from onlyalpha.transaction.delivery import (
    OnlyExecutionEventDeliveryCoordinator,
    OnlyExecutionEventDeliveryIntent,
    OnlyExecutionEventDeliveryMode,
    OnlyExecutionOutboxPublisher,
    OnlyRoutedDirectExecutionPublisher,
)
from onlyalpha.transaction.enums import OnlyRuntimeOperationKind
from onlyalpha.transaction.projection import (
    OnlyValuationExecutionState,
)
from onlyalpha.transaction.projection_applier import OnlyRuntimeProjectionApplier
from onlyalpha.transaction.recovery import OnlyExecutionRecoveryService
from onlyalpha.transaction.transaction import OnlyCommittedRuntimeTransaction


@dataclass(frozen=True, slots=True)
class _OnlyStrategyEconomicCashflowApplication(OnlyDomainModel):
    key: OnlyStrategyLedgerKey
    cashflow_id: OnlyStrategyCashFlowId
    amount: OnlyMoney
    entry_type: OnlyStrategyCashEntryType
    timestamp: OnlyTimestamp


@dataclass(frozen=True, slots=True)
class _OnlyEconomicFactApplicationPlan(OnlyDomainModel):
    fact_id: str
    source_fact_json: str
    application_kind: str
    settlements: tuple[OnlyPositionSettlementFact, ...]
    account_cashflows: tuple[OnlyAccountEconomicCashflow, ...]
    strategy_cashflows: tuple[_OnlyStrategyEconomicCashflowApplication, ...]

    def __post_init__(self) -> None:
        if not self.fact_id.strip() or self.application_kind not in {"FUNDING", "SETTLEMENT"}:
            raise ValueError("ECONOMIC_FACT_APPLICATION_PLAN_INVALID")


class OnlyBacktestRunPlanPort(Protocol):
    def execute(self, runtime: OnlyTradingRuntimeFacade) -> object: ...


_LOGGER = logging.getLogger(__name__)


class OnlyTradingRuntimeFacade(OnlyRuntime):
    """Shared Trading Runtime facade composed around one Trading Kernel."""

    @property
    def order_fee_accrual_manager(self) -> OnlyOrderFeeAccrualManager:
        return self._order_fee_accrual_manager

    def submit_fee_evidence(
        self,
        evidence: OnlyExternalFeeEvidence,
    ) -> OnlyRuntimeTransactionCoordinationResult:
        """Validate and durably reconcile one normalized external fact."""

        if evidence.account_id != self.config.default_account_id:
            raise ValueError("FEE_EVIDENCE_ACCOUNT_AUTHORITY_CONFLICT")
        broker_contract = self.config.broker_fee_contract
        broker_id = self.config.broker_fee_authority_id
        if (
            broker_contract is None
            or broker_id is None
            or evidence.broker_id != broker_id
            or evidence.broker_id != broker_contract.identity.broker_id
        ):
            raise ValueError("FEE_EVIDENCE_BROKER_AUTHORITY_CONFLICT")
        policy = self.config.fee_reconciliation_policy
        if policy is None:
            raise ValueError("FEE_RECONCILIATION_POLICY_NOT_INSTALLED")
        if evidence.currency != policy.currency:
            raise ValueError("FEE_RECONCILIATION_POLICY_CURRENCY_MISMATCH")
        classification = self._fee_reconciliation_authority.classify(evidence)
        if classification == "DUPLICATE_EVIDENCE":
            raise ValueError("DUPLICATE_EVIDENCE")
        records = OnlyFeeApplicationLocalFactQuery(
            self._fee_application_ledger,
            broker_id=broker_id,
            account_id=evidence.account_id,
        ).query(evidence)
        clusters = {item.cluster_id for item in records}
        cluster_id = next(iter(clusters)) if len(clusters) == 1 else None
        gate = self._fee_reconciliation_risk_gate.get(evidence.account_id)
        family_blockers = (
            ()
            if gate is None
            else tuple(
                item
                for item in gate.active_blockers
                if item.evidence_family_fingerprint == evidence.family_identity.fingerprint
            )
        )
        if len(family_blockers) > 1:
            raise ValueError("FEE_RECONCILIATION_BLOCKER_CONFLICT")
        decision = OnlyFeeReconciliationPlanner().plan(
            OnlyFeeReconciliationInput(
                evidence,
                tuple(
                    OnlyLocalFeeReconciliationComponent(
                        OnlyFeeReconciliationComponentIdentity(
                            item.component_identity.fee_type,
                            item.component_identity.authority,
                            item.component_identity.economic_direction,
                            item.component_identity.source_id,
                        ),
                        item.incremental_amount,
                    )
                    for item in records
                ),
                self._fee_reconciliation_authority.prior_adjustments(evidence),
                cluster_id,
                policy,
                classification,
                None if not family_blockers else family_blockers[0].blocker_id,
            )
        )
        return self._commit_fee_reconciliation(evidence, decision)

    def _commit_fee_reconciliation(
        self,
        evidence: OnlyExternalFeeEvidence,
        decision: OnlyFeeReconciliationDecision,
    ) -> OnlyRuntimeTransactionCoordinationResult:
        """Commit an already-planned reconciliation through the Runtime transaction authority."""

        if evidence.account_id != self.config.default_account_id:
            raise ValueError("FEE_RECONCILIATION_ACCOUNT_SCOPE_CONFLICT")
        adjustments = decision.adjustments
        account_state = None
        ledger_state = None
        if adjustments:
            account_state = only_account_execution_state(self._account_manager.require_snapshot(evidence.account_id))
            cluster_ids = {item.cluster_id for item in adjustments}
            if len(cluster_ids) != 1:
                raise ValueError("FEE_RECONCILIATION_STRATEGY_AUTHORITY_MISSING")
            adjustment_cluster_id = next(iter(cluster_ids))
            if adjustment_cluster_id is not None:
                matching = tuple(
                    item
                    for item in self._strategy_ledger_manager.list_ledgers()
                    if item.key.account_id == evidence.account_id and item.key.cluster_id == adjustment_cluster_id
                )
                if len(matching) != 1:
                    raise ValueError("FEE_RECONCILIATION_STRATEGY_AUTHORITY_MISSING")
                ledger_state = only_strategy_ledger_execution_state(matching[0])
        processed_at = OnlyTimestamp.from_unix_nanos(self.clock.timestamp_ns())
        context = OnlyFeeReconciliationPlanningContext(
            OnlyRuntimeId(str(self.config.runtime_id)),
            evidence,
            decision,
            processed_at,
            self._fee_reconciliation_authority.evidence(evidence.evidence_id),
            self._fee_reconciliation_authority.decision(decision.reconciliation_id),
            tuple(self._fee_reconciliation_authority.adjustment(item.adjustment_id) for item in adjustments),
            account_state,
            ledger_state,
            self._fee_reconciliation_authority.unallocated(evidence.account_id),
            self._fee_reconciliation_risk_gate.get(evidence.account_id),
        )
        prepared = OnlyFeeReconciliationTransactionPlanner().prepare(context)
        return self._runtime_transaction_coordinator.commit(
            prepared,
            committed_at=processed_at,
            projected_at=processed_at,
        )

    def __init__(
        self,
        config: OnlyRuntimeAssemblyConfig,
        calendar_or_clock: OnlyTradingCalendar,
        initial_time_or_event_bus: datetime | int,
        *,
        run_plan: object | None = None,
        owned_clock: OnlyClock | None = None,
        owned_event_bus: OnlyEventBus | None = None,
        account_created_at: OnlyTimestamp | None = None,
        broker_gateway: OnlyBrokerGateway | None = None,
        execution_service: OnlyExecutionService | None = None,
        deterministic_broker_driver: OnlyDeterministicBrokerDriver | None = None,
        broker_inbound_queue: OnlyBrokerInboundQueue | None = None,
        market_data_inbound_queue: OnlyMarketDataInboundQueue | None = None,
        runtime_persistence_store: OnlyRuntimePersistenceStorePort,
        persistence_config: OnlyRuntimePersistenceConfig | None = None,
        config_fingerprint: str = "",
        replay_source_id: OnlyMarketDataSourceId | None = None,
        replay_data_version: OnlyDataVersion | None = None,
        recovery_source: OnlyHistoricalDataSource | None = None,
        recovery_request: OnlyHistoricalBarRequest | None = None,
        recovery_economic_requests: tuple[OnlyHistoricalFactRequest, ...] = (),
        plugin_resources: tuple[OnlyPluginResource, ...] = (),
        execution_reference_profile: OnlyExecutionReferenceProfile | None = None,
    ) -> None:
        if isinstance(initial_time_or_event_bus, bool):
            raise TypeError("Backtest Runtime requires an initial UTC time")
        runtime_config = config
        if persistence_config is None:
            persistence_config = OnlyRuntimePersistenceConfig()
        selected_calendar = calendar_or_clock
        clock = owned_clock or OnlyBacktestClock(initial_time_or_event_bus)
        event_bus = owned_event_bus
        super().__init__(runtime_config)
        self._realtime_market_state = OnlyRealtimeMarketStateStore(runtime_config.runtime_id)  # type: ignore[arg-type]
        self._order_fee_accrual_manager = OnlyOrderFeeAccrualManager()
        self._bind_runtime_persistence_store(runtime_persistence_store)
        self._selected_calendar = selected_calendar
        scope = OnlyEventScope(runtime_config.engine_id, runtime_config.runtime_id)  # type: ignore[arg-type]
        owned_bus = event_bus or OnlyEventBus(
            runtime_config.event_capacity,
            scope=scope,
            queue_policy=runtime_config.event_queue_policy,
        )
        event_gate = OnlyRuntimeRecoveryEventGate(runtime_config.event_capacity)
        event_router = OnlyRuntimeEventRouter(owned_bus, event_gate, scope)
        event_bus_view = OnlyEventBusSubscriptionView(owned_bus)
        execution_event_buffer = OnlyExecutionEventBuffer()
        direct_execution_event_publisher = OnlyRoutedDirectExecutionPublisher(event_router)
        self._strategy_ledger_manager.bind_publisher(
            OnlyRuntimeStrategyLedgerEventPublisherAdapter(
                runtime_config.engine_id,  # type: ignore[arg-type]
                execution_event_buffer.add,
            )
        )
        self._position_manager.bind_publisher(
            OnlyRuntimePositionEventPublisherAdapter(
                runtime_config.engine_id,  # type: ignore[arg-type]
                execution_event_buffer.add,
            )
        )
        self._account_manager.bind_publisher(
            OnlyRuntimeAccountEventPublisherAdapter(
                runtime_config.engine_id,  # type: ignore[arg-type]
                execution_event_buffer.add,
            )
        )
        if runtime_config.account_initial_cash is None:
            raise ValueError("Backtest Runtime requires explicit Account initial cash")
        account_initial_cash = runtime_config.account_initial_cash
        configured_gateway_id = runtime_config.broker_gateway_id
        execution_event_buffer.begin()
        self._account_manager.create_account(
            OnlyAccountConfig(
                runtime_config.runtime_id,  # type: ignore[arg-type]
                runtime_config.default_account_id,  # type: ignore[arg-type]
                (str(configured_gateway_id) if configured_gateway_id is not None else "placeholder"),
                runtime_config.account_type,
                runtime_config.strategy_base_currency,
                account_initial_cash,
            ),
            account_created_at or OnlyTimestamp.from_unix_nanos(clock.timestamp_ns()),
        )
        direct_execution_event_publisher.publish(execution_event_buffer.seal())
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
        self._execution_valuation_states: dict[OnlyAccountId, OnlyValuationExecutionState] = {}
        self._risk_profile_factory = OnlyRiskProfileFactory()
        manager = OnlyClusterManager(runtime_config.runtime_id, self._make_context, self._cleanup_cluster)  # type: ignore[arg-type]
        executor = OnlyManagedBarDispatchExecutor(
            manager,
            self._set_current_snapshot,
            self._prepare_risk_snapshot,
        )
        dispatcher = OnlyStrategyBarDispatcher(pipeline, OnlyClockView(clock), executor)
        order_manager = OnlyOrderManager(
            runtime_config.engine_id,  # type: ignore[arg-type]
            runtime_config.runtime_id,  # type: ignore[arg-type]
            OnlySequenceOrderIdGenerator(runtime_config.runtime_id),  # type: ignore[arg-type]
            OnlySequenceClientOrderIdGenerator(runtime_config.runtime_id),  # type: ignore[arg-type]
        )
        self._order_manager = order_manager
        order_publisher = OnlyRuntimeOrderEventPublisherAdapter(event_router)
        order_query = OnlyOrderQueryService(order_manager)
        position_manager = self._position_manager
        allocation_manager = self._allocation_manager
        position_query = self._position_query
        position_reservations = self._position_reservation_manager
        order_position_reservations = OnlyOrderPositionReservationAdapter(
            position_reservations,
            lambda order, timestamp: (
                OnlyPositionMode.HEDGING
                if runtime_config.market_rule_engine is not None
                and runtime_config.market_rule_engine.position_mode(
                    str(order.instrument_id), selected_calendar.trading_day_at(timestamp)
                )
                is OnlyPositionMode.HEDGING
                else OnlyPositionMode.NETTING
            ),
        )
        market_rule_engine = runtime_config.market_rule_engine
        if market_rule_engine is None:
            raise ValueError("FEE_AUTHORITY_REQUIRES_MARKET_RULE_ENGINE")
        if runtime_config.market_fee_pack is None:
            raise ValueError("MARKET_FEE_PACK_NOT_INSTALLED")
        if runtime_config.broker_fee_contract is None or runtime_config.broker_fee_authority_id is None:
            raise ValueError("BROKER_FEE_CONTRACT_NOT_INSTALLED")
        if runtime_config.fee_basis_providers is None:
            raise ValueError("FEE_BASIS_UNSUPPORTED")
        fee_resolver = OnlyFeeResolver(
            OnlyFeeEngine(),
            runtime_config.market_fee_pack,
            runtime_config.broker_fee_contract,
            runtime_config.broker_fee_authority_id,
            market_rule_engine,
            self._instruments,
            runtime_config.fee_basis_providers,
            selected_calendar.trading_day_at,
        )
        self._fee_resolver = fee_resolver
        strategy_cash_reservations = OnlyOrderStrategyCashReservationAdapter(
            self._strategy_ledger_manager,
            self._strategy_ledger_locator,
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
            lambda order, timestamp: (
                market_rule_engine.compiled_rules(
                    str(order.instrument_id), selected_calendar.trading_day_at(timestamp), as_of=timestamp.to_datetime()
                ).economic_model
                is OnlyEconomicModel.CASH_EXCHANGE
            ),
        )
        self._account_cash_reservations = account_cash_reservations
        order_margin_reservations = OnlyOrderMarginReservationAdapter(
            self._margin_manager,
            self._account_manager,
            runtime_config.market_rule_engine,
            self._instruments,
            selected_calendar.trading_day_at,
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
            order_query,
            OnlyRuntimeRiskEventPublisherAdapter(event_router),
            account_rules=(OnlyAvailableBalanceRiskRule(), OnlyAvailablePositionRiskRule()),
            account_risk=OnlyAccountManagerRiskView(self._account_query),
            position_risk=OnlyPositionRiskView(position_query, clock.timestamp_ns),
            market_rules=runtime_config.market_rule_engine,
            strategy_ledger_risk=OnlyStrategyLedgerRiskView(
                self._strategy_ledger_query,
                self._strategy_ledger_locator,
                runtime_config.strategy_base_currency,
            ),
        )
        broker_inbound = (
            broker_inbound_queue
            if broker_inbound_queue is not None
            else OnlyBoundedBrokerInboundQueue(runtime_config.event_capacity)
        )
        selected_broker_gateway = broker_gateway
        selected_execution_service: OnlyExecutionService = (
            execution_service
            if execution_service is not None
            else OnlyBrokerExecutionService(selected_broker_gateway, clock)
            if selected_broker_gateway is not None
            else OnlyPlaceholderExecutionService()
        )

        def fee_contract(
            order: OnlyOrderSnapshot,
            timestamp: OnlyTimestamp,
            planning_price: OnlyPrice | None,
        ) -> tuple[OnlyOrderFeePolicyBinding, OnlyOrderFeeEstimate, OnlyOrderFundingPlan]:
            price = (
                order.price
                or planning_price
                or (
                    self._current_snapshots[order.cluster_id].primary_bar.close
                    if order.cluster_id in self._current_snapshots
                    else None
                )
            )
            if price is None:
                raise ValueError("market Order requires a deterministic fee reference price")
            binding = fee_resolver.bind_order(order, timestamp)
            estimate = fee_resolver.estimate_order(order, binding, price, timestamp)
            return binding, estimate, fee_resolver.funding_plan(order, binding, estimate, price)

        order_update_processor = OnlyOrderUpdateProcessor(
            runtime_config.runtime_id,  # type: ignore[arg-type]
            order_manager,
            order_publisher,
        )
        account_reconciliation = OnlyAccountReconciliationService(self._account_manager)
        position_reconciliation = OnlyPositionReconciliationService(
            runtime_config.runtime_id,  # type: ignore[arg-type]
            position_manager,
            allocation_manager,
            OnlyPositionAuthorityPolicy.local(),
            position_reservations,
        )
        execution_audit_store = OnlyInMemoryExecutionAuditStore()
        persistence_store = runtime_persistence_store
        applied_projection_ledger = OnlyInMemoryAppliedRuntimeProjectionLedger()
        self._applied_projection_ledger = applied_projection_ledger
        execution_valuation_authority = OnlyExecutionValuationAuthority(
            account_performance=self._account_performance_projector,
            runtime_state_restorer=self._restore_execution_valuation_state,
            runtime_state_provider=self._execution_valuation_state,
        )
        execution_projection_targets = only_create_generic_t0_execution_projection_targets(
            order_manager=order_manager,
            position_manager=position_manager,
            allocation_manager=allocation_manager,
            position_reservation_manager=position_reservations,
            margin_manager=self._margin_manager,
            settlement_authority=self._settlement_authority,
            fee_application_ledger=self._fee_application_ledger,
            order_fee_accrual_manager=self._order_fee_accrual_manager,
            account_manager=self._account_manager,
            ledger_manager=self._strategy_ledger_manager,
            risk_service=risk_service,
            valuation_authority=execution_valuation_authority,
            applied_ledger=applied_projection_ledger,
            fee_reconciliation_authority=self._fee_reconciliation_authority,
            fee_reconciliation_risk_gate=self._fee_reconciliation_risk_gate,
        )
        execution_projection_applier = OnlyRuntimeProjectionApplier(execution_projection_targets)
        execution_commit_coordinator = OnlyRuntimeTransactionCoordinator(
            commit_port=persistence_store,
            query_port=persistence_store,
            projection_state_port=persistence_store,
            projection_applier=execution_projection_applier,
            now=lambda: OnlyTimestamp.from_unix_nanos(clock.timestamp_ns()),
        )
        self._runtime_transaction_coordinator = execution_commit_coordinator
        order_intent_durability = (
            OnlyRuntimeOrderIntentDurabilityService(
                accounts=self._account_manager,
                ledgers=self._strategy_ledger_manager,
                ledger_locator=self._strategy_ledger_locator,
                strategy_currency=runtime_config.strategy_base_currency,
                positions=position_manager,
                allocations=allocation_manager,
                position_reservations=position_reservations,
                margins=self._margin_manager,
                risk=risk_service,
                coordinator=execution_commit_coordinator,
                now=lambda: OnlyTimestamp.from_unix_nanos(clock.timestamp_ns()),
                on_ready=self._record_order_intent_recovery_continuation,
                recovery_session=self._active_execution_recovery_session,
            )
            if isinstance(selected_execution_service, OnlyBrokerExecutionService)
            else None
        )
        order_service = OnlyOrderService(
            order_manager,
            selected_execution_service,
            order_publisher,
            lambda: OnlyTimestamp.from_unix_nanos(clock.timestamp_ns()),
            risk_service,
            risk_service.make_evaluation_context,
            order_position_reservations,
            order_cash_reservations,
            order_margin_reservations,
            None,
            self._fee_reconciliation_risk_gate,
            order_intent_durability,
            selected_execution_service if isinstance(selected_execution_service, OnlyBrokerExecutionService) else None,
            (
                None
                if execution_reference_profile is None
                else OnlyExecutionReferencePlanningService(self._realtime_market_state, execution_reference_profile)
            ),
            fee_contract,
        )
        self._trading_day_boundary_coordinator = OnlyRuntimeTradingDayBoundaryCoordinator(
            settlement_authority=self._settlement_authority,
            position_manager=position_manager,
            allocation_manager=allocation_manager,
            account_manager=self._account_manager,
            transaction_coordinator=execution_commit_coordinator,
        )
        execution_recovery_service = OnlyExecutionRecoveryService(execution_commit_coordinator)
        execution_outbox_publisher = OnlyExecutionOutboxPublisher(
            persistence_store,
            event_router,
            lambda: OnlyTimestamp.from_unix_nanos(clock.timestamp_ns()),
        )
        execution_delivery_coordinator = OnlyExecutionEventDeliveryCoordinator(
            direct_execution_event_publisher,
            execution_outbox_publisher,
        )
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
                (runtime_config.broker_gateway_id or OnlyBrokerGatewayId("placeholder"),),
                (runtime_config.default_account_id,),  # type: ignore[arg-type]
            ),
            clock,
            self._instruments,
            order_query,
            position_manager,
            allocation_manager,
            self._strategy_ledger_manager,
            self._strategy_ledger_locator,
            self._account_manager,
            risk_service,
            position_reservations,
            position_reconciliation,
            account_reconciliation,
            execution_invariant_checker,
            execution_event_buffer,
            execution_audit_store,
            self._build_trade_execution_planning_context,
            OnlyTradeExecutionTransactionPlanner(),
            self._build_order_accepted_execution_planning_context,
            OnlyOrderAcceptedExecutionTransactionPlanner(),
            self._build_terminal_execution_planning_context,
            OnlyTerminalExecutionTransactionPlanner(),
            execution_commit_coordinator,
            persistence_store,
            execution_reconciliation_queue,
            execution_update_deduplicator,
            execution_sequence_tracker,
            self._apply_strategy_valuation,
            self._apply_account_valuation,
            self._set_broker_connection_state,
            runtime_config.strategy_base_currency,
            runtime_config.market_rule_engine,
            self._settlement_authority,
            self._margin_manager,
            self._fee_application_ledger,
            fee_resolver,
            selected_calendar.trading_day_at,
        )
        self._broker_results: list[object] = []
        historical_source_id = OnlyMarketDataSourceId(f"{runtime_config.runtime_id}-local-history")
        realtime_source_id = OnlyMarketDataSourceId(f"{runtime_config.runtime_id}-in-memory-live")
        market_data_source_registry = OnlyMarketDataSourceRegistry()
        historical_data_source = OnlyInMemoryHistoricalDataSource(historical_source_id)
        market_data_source_registry.register(historical_data_source, priority=0)
        market_data_inbound = (
            market_data_inbound_queue
            if market_data_inbound_queue is not None
            else OnlyMarketDataInboundQueue(runtime_config.event_capacity)
        )
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
        )
        market_data_audit_store = OnlyMarketDataAuditStore()
        self._result_progress = OnlyBacktestResultProgress()
        self._reference_price_facts: dict[str, OnlyReferencePriceFact] = {}
        self._reference_prices_by_boundary: dict[
            tuple[OnlyInstrumentId, OnlyReferencePriceKind, int], OnlyReferencePriceFact
        ] = {}
        self._funding_rate_facts: dict[str, OnlyFundingRateFact] = {}
        self._pending_economic_fact_applications: dict[str, _OnlyEconomicFactApplicationPlan] = {}
        self._position_valuation_service = OnlyPositionValuationService()
        market_data_deduplicator = OnlyMarketDataDeduplicator()
        market_data_sequence_tracker = OnlyMarketDataSequenceTracker()
        market_data_gap_detector = OnlyMarketDataGapDetector(self._market_calendars)
        market_data_event_publisher = OnlyMarketDataEventPublisher()
        self._last_market_trading_day: OnlyTradingDay | None = None
        self._execution_checkpoint_blocked = False
        self._deterministic_broker_driver = deterministic_broker_driver
        self._execution_recovery_session: OnlyExecutionRecoverySession | None = None

        def drain_execution_updates() -> None:
            for update in broker_inbound.drain():
                backtest_session = self._backtest_recovery_session
                execution_session = (
                    backtest_session.execution_session
                    if backtest_session is not None
                    else self._execution_recovery_session
                )
                processing = (
                    execution_processor.process(update)
                    if execution_session is None
                    else execution_processor.replay(update, execution_session)
                )
                if execution_session is None:
                    delivery = execution_delivery_coordinator.deliver(
                        runtime_config.runtime_id,  # type: ignore[arg-type]
                        processing.delivery_intent,
                    )
                    self._record_execution_delivery(processing.sequence, delivery)
                self._broker_results.append(processing)
                if processing.status is OnlyExecutionProcessingStatus.FAILED or (
                    processing.status is OnlyExecutionProcessingStatus.RECONCILIATION_REQUIRED
                    and processing.failure is not None
                ):
                    self._execution_checkpoint_blocked = True
                    break

        self._drain_execution_updates_for_checkpoint = drain_execution_updates

        def before_market_dispatch(result: OnlyMarketDataUpdateResult) -> None:
            event_router.publish_direct_many(result.facts)
            trading_day = OnlyTradingDay(result.base_bar.trading_day)
            execution_event_buffer.begin()
            try:
                if self._last_market_trading_day is None:
                    self._last_market_trading_day = trading_day
                elif trading_day != self._last_market_trading_day:
                    self._trading_day_boundary_coordinator.process_boundary(
                        self._last_market_trading_day,
                        trading_day,
                        OnlyTimestamp.from_datetime(result.base_bar.ts_event),
                    )
                    self._last_market_trading_day = trading_day
                self._apply_market_valuations(result.base_bar, trading_day)
            except Exception:
                execution_event_buffer.abort()
                raise
            batch = execution_event_buffer.seal()
            delivery = execution_delivery_coordinator.deliver(
                runtime_config.runtime_id,  # type: ignore[arg-type]
                OnlyExecutionEventDeliveryIntent(OnlyExecutionEventDeliveryMode.DIRECT, direct_batch=batch),
            )
            self._record_execution_delivery(None, delivery)
            if deterministic_broker_driver is not None and not self._execution_checkpoint_blocked:
                deterministic_broker_driver.on_bar(result.base_bar)
                drain_execution_updates()

        def after_market_dispatch(update: OnlyMarketDataInboundUpdate) -> None:
            if deterministic_broker_driver is not None and not self._execution_checkpoint_blocked:
                deterministic_broker_driver.run_due()
                drain_execution_updates()

        def after_market_processing(
            update: OnlyMarketDataInboundUpdate,
            result: OnlyMarketDataProcessingResult,
        ) -> None:
            completion = self._result_progress.observe_market_data_result(result, update)
            owned_bus.drain()
            recovery_session = self._backtest_recovery_session
            if recovery_session is not None:
                recovery_session.observe_completion(completion)
            if result.pipeline_result is not None and result.status in {
                OnlyMarketDataProcessingStatus.APPLIED,
                OnlyMarketDataProcessingStatus.GAP_DETECTED,
            }:
                self._checkpoint_barrier(completion)

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
            after_market_processing,
            self._realtime_market_state,
            self._apply_canonical_economic_fact,
        )
        historical_replay_service = OnlyHistoricalReplayService(cast(OnlyBacktestClock, clock), market_data_processor)
        self._trading_kernel.install_services(
            OnlyRuntimeServices(
                clock,
                owned_bus,
                event_bus_view,
                event_router,
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
                selected_execution_service,
                risk_service,
                position_manager,
                allocation_manager,
                position_reservations,
                position_query,
                self._strategy_ledger_manager,
                self._strategy_ledger_query,
                self._settlement_authority,
                self._margin_manager,
                self._fee_application_ledger,
                OnlyStrategyValuationService(),
                self._account_manager,
                self._account_performance_projector,
                self._account_query,
                broker_inbound,
                selected_broker_gateway,
                execution_processor,
                execution_commit_coordinator,
                execution_recovery_service,
                persistence_store,
                persistence_store,
                persistence_store,
                persistence_store,
                execution_event_buffer,
                execution_delivery_coordinator,
                execution_outbox_publisher,
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
        )

        self._valuation_versions: dict[OnlyStrategyLedgerKey, int] = {}
        self._account_valuation_version = 0
        self._broker_connection_state: object | None = None
        self._legacy_market_data_sequence = 0
        self._run_plan = cast(OnlyBacktestRunPlanPort | None, run_plan)
        self._persistence_config = persistence_config
        self._config_fingerprint = config_fingerprint
        self._replay_cursor = OnlyBacktestReplayCursor(
            replay_source_id or OnlyMarketDataSourceId(f"{runtime_config.runtime_id}-local-history"),
            replay_data_version or OnlyDataVersion("memory"),
            None,
            0,
            None,
            0,
        )
        self._checkpoint_query = runtime_persistence_store
        self._checkpoint_registry = OnlyRuntimeCheckpointParticipantRegistry()
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "runtime.progress",
                1,
                self._capture_runtime_progress_checkpoint,
                self._restore_runtime_progress_checkpoint,
            )
        )
        if run_plan is not None:
            self._checkpoint_registry.register(
                OnlyJsonRuntimeCheckpointParticipant(
                    "backtest.replay-frontier",
                    1,
                    lambda: self._replay_cursor.to_checkpoint(),
                    self._restore_backtest_replay_frontier,
                )
            )
            self._checkpoint_registry.register(
                OnlyJsonRuntimeCheckpointParticipant(
                    "backtest.clock",
                    1,
                    self._capture_backtest_clock_checkpoint,
                    self._restore_backtest_clock_checkpoint,
                )
            )
            self._checkpoint_registry.register(
                OnlyJsonRuntimeCheckpointParticipant(
                    "backtest.result-progress",
                    1,
                    self._result_progress.capture_checkpoint,
                    self._result_progress.restore_checkpoint,
                )
            )
        if persistence_config.checkpoint.enabled and replay_source_id is not None:
            self._checkpoint_registry.register(
                OnlyStatelessRuntimeCheckpointParticipant(f"data-source.{replay_source_id}")
            )
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "market-data.cache",
                1,
                market_cache.capture_checkpoint,
                market_cache.restore_checkpoint,
            )
        )
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "market-data.aggregation",
                1,
                aggregation.capture_checkpoint,
                aggregation.restore_checkpoint,
            )
        )
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "market-data.dedup",
                1,
                market_data_deduplicator.capture_checkpoint,
                market_data_deduplicator.restore_checkpoint,
            )
        )
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "market-data.sequence",
                1,
                market_data_sequence_tracker.capture_checkpoint,
                market_data_sequence_tracker.restore_checkpoint,
            )
        )
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "market-data.gap",
                1,
                market_data_gap_detector.capture_checkpoint,
                market_data_gap_detector.restore_checkpoint,
            )
        )
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "market-data.processor",
                1,
                market_data_processor.capture_checkpoint,
                market_data_processor.restore_checkpoint,
            )
        )
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "market.economic-facts",
                2,
                self._capture_economic_facts_checkpoint,
                self._restore_economic_facts_checkpoint,
            )
        )
        if runtime_config.market_rule_engine is not None:
            self._checkpoint_registry.register(
                OnlyJsonRuntimeCheckpointParticipant(
                    "market.rules",
                    runtime_config.market_rule_engine.checkpoint_schema_version,
                    runtime_config.market_rule_engine.capture_checkpoint,
                    runtime_config.market_rule_engine.restore_checkpoint,
                )
            )
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "account.authority",
                3,
                self._account_manager.capture_checkpoint,
                self._account_manager.restore_checkpoint,
            )
        )
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "account.valuation-timeline",
                1,
                self._account_performance_projector.capture_checkpoint,
                self._account_performance_projector.restore_checkpoint,
            )
        )
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "order.authority",
                2,
                order_manager.capture_checkpoint,
                order_manager.restore_checkpoint,
            )
        )
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "position-reservation.authority",
                1,
                position_reservations.capture_checkpoint,
                position_reservations.restore_checkpoint,
            )
        )
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "position.authority",
                2,
                position_manager.capture_checkpoint,
                position_manager.restore_checkpoint,
            )
        )
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "allocation.authority",
                2,
                allocation_manager.capture_checkpoint,
                allocation_manager.restore_checkpoint,
            )
        )
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "settlement.authority",
                2,
                self._settlement_authority.capture_checkpoint,
                self._settlement_authority.restore_checkpoint,
            )
        )
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "fee.authority",
                3,
                self._fee_application_ledger.capture_checkpoint,
                self._fee_application_ledger.restore_checkpoint,
            )
        )
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "order_fee_accrual.authority",
                1,
                self._order_fee_accrual_manager.capture_checkpoint,
                self._order_fee_accrual_manager.restore_checkpoint,
            )
        )
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "fee_reconciliation.authority",
                1,
                self._fee_reconciliation_authority.capture_checkpoint,
                self._fee_reconciliation_authority.restore_checkpoint,
            )
        )
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "fee_reconciliation_risk_gate.authority",
                1,
                self._fee_reconciliation_risk_gate.capture_checkpoint,
                self._fee_reconciliation_risk_gate.restore_checkpoint,
            )
        )
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "margin.authority",
                3,
                self._margin_manager.capture_checkpoint,
                self._margin_manager.restore_checkpoint,
            )
        )
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "risk.authority",
                1,
                risk_service.capture_checkpoint,
                risk_service.restore_checkpoint,
            )
        )
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "execution.dedup",
                1,
                execution_update_deduplicator.capture_checkpoint,
                execution_update_deduplicator.restore_checkpoint,
            )
        )
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "execution.sequence",
                1,
                execution_sequence_tracker.capture_checkpoint,
                execution_sequence_tracker.restore_checkpoint,
            )
        )
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "execution.processor",
                1,
                execution_processor.capture_checkpoint,
                execution_processor.restore_checkpoint,
            )
        )
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "execution.audit",
                1,
                execution_audit_store.capture_checkpoint,
                execution_audit_store.restore_checkpoint,
            )
        )
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "execution.reconciliation",
                1,
                execution_reconciliation_queue.capture_checkpoint,
                execution_reconciliation_queue.restore_checkpoint,
            )
        )
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "strategy-ledger.authority",
                1,
                self._strategy_ledger_manager.capture_checkpoint,
                self._strategy_ledger_manager.restore_checkpoint,
            )
        )
        if persistence_config.checkpoint.enabled:
            if deterministic_broker_driver is None:
                raise ValueError("checkpoint-enabled Backtest requires a checkpoint-capable Broker driver")
            if (
                not isinstance(deterministic_broker_driver.checkpoint_schema_version, int)
                or isinstance(deterministic_broker_driver.checkpoint_schema_version, bool)
                or deterministic_broker_driver.checkpoint_schema_version < 1
            ):
                raise ValueError("checkpoint-enabled Backtest requires a positive Broker checkpoint schema version")
            self._checkpoint_registry.register(
                OnlyJsonRuntimeCheckpointParticipant(
                    "broker.virtual",
                    deterministic_broker_driver.checkpoint_schema_version,
                    deterministic_broker_driver.capture_checkpoint,
                    deterministic_broker_driver.restore_checkpoint,
                )
            )
        self._checkpoint_service = OnlyRuntimeCheckpointService(
            runtime_id=runtime_config.runtime_id,  # type: ignore[arg-type]
            config_fingerprint=config_fingerprint,
            market_composition_fingerprint=market_rule_engine.market_composition_fingerprint,
            registry=self._checkpoint_registry,
            write_port=runtime_persistence_store,
            query_port=runtime_persistence_store,
            transaction_query=runtime_persistence_store,
            outbox_port=runtime_persistence_store,
            retain_last=persistence_config.checkpoint.retain_last,
        )
        self._backtest_recovery_session: OnlyBacktestRecoverySession | None = None
        recovery_replay = OnlyBacktestRecoveryReplayService(
            source=recovery_source,
            request=recovery_request,
            economic_requests=recovery_economic_requests,
            source_registry=market_data_source_registry,
            replay=historical_replay_service,
            activate=self._activate_backtest_recovery,
            deactivate=self._deactivate_backtest_recovery,
        )
        self._runtime_recovery_orchestrator = OnlyRuntimeRecoveryOrchestrator(
            runtime_id=runtime_config.runtime_id,  # type: ignore[arg-type]
            config_fingerprint=config_fingerprint,
            market_composition_fingerprint=market_rule_engine.market_composition_fingerprint,
            participant_registry=self._checkpoint_registry,
            checkpoint_query=runtime_persistence_store,
            transaction_query=runtime_persistence_store,
            causal_replay=recovery_replay.run,
            resolve_autonomous_entry=self._resolve_autonomous_execution_entry,
        )
        self._runtime_recovery_diagnostics: list[OnlyRuntimeRecoveryDiagnostic] = []
        self._post_recovery_validation_reports: list[OnlyPostRecoveryValidationReport] = []
        self._runtime_recovery_finalizer = OnlyRuntimeRecoveryFinalizer(
            cluster_manager=self._services.cluster_manager,
            event_bus=self._services.event_bus,
            validator=only_default_post_recovery_authority_validator(),
            context_factory=self._post_recovery_validation_context,
            checkpoint_service=self._checkpoint_service,
            created_at=lambda: OnlyTimestamp.from_unix_nanos(self._services.clock.timestamp_ns()),
        )
        self._cluster_checkpoint_participants_registered = False
        resources = plugin_resources
        if resources:
            self._bind_plugin_resources(resources)

    @property
    def realtime_market_state(self) -> OnlyRealtimeMarketStateStore:
        """Read/capture access to the Runtime-wide realtime projection."""

        return self._realtime_market_state

    def run(self) -> object:
        """Execute a configured product backtest through Replay and Runtime-owned services."""

        if self._run_plan is None:
            raise OnlyRuntimeError("run() requires a Factory-provided Backtest RunPlan")
        return self._run_plan.execute(self)

    @property
    def replay_cursor(self) -> OnlyBacktestReplayCursor:
        return self._replay_cursor

    @property
    def result_progress(self) -> OnlyBacktestResultProgress:
        return self._result_progress

    @property
    def runtime_recovery_diagnostics(self) -> tuple[OnlyRuntimeRecoveryDiagnostic, ...]:
        return tuple(self._runtime_recovery_diagnostics)

    @property
    def post_recovery_validation_reports(self) -> tuple[OnlyPostRecoveryValidationReport, ...]:
        return tuple(self._post_recovery_validation_reports)

    def _resolve_autonomous_execution_entry(
        self, entry: OnlyExecutionRecoveryEntry
    ) -> OnlyExecutionRecoveryResolution | None:
        committed = entry.stored.committed
        if committed.operation_kind is not OnlyRuntimeOperationKind.ORDER_INTENT:
            raise ValueError("RECOVERY_TRANSACTION_IS_NOT_AUTONOMOUS")
        order_id = getattr(committed.fact, "order_id", None)
        if order_id is None or self._order_manager.get_snapshot(order_id) is None:
            return None
        timestamp = committed.projected_at or committed.committed_at
        result = (
            self._runtime_transaction_coordinator.rehydrate_existing(committed, projected_at=timestamp)
            if entry.state is OnlyExecutionRecoveryEntryState.READY
            else self._runtime_transaction_coordinator.recover_existing(committed, projected_at=timestamp)
        )
        if result.status not in {
            OnlyRuntimeTransactionCoordinationStatus.COMMITTED_AND_PROJECTED,
            OnlyRuntimeTransactionCoordinationStatus.ALREADY_READY,
        }:
            raise RuntimeError(result.error or "ORDER_INTENT_RECOVERY_FAILED")
        return (
            OnlyExecutionRecoveryResolution.READY_REHYDRATED
            if entry.state is OnlyExecutionRecoveryEntryState.READY
            else OnlyExecutionRecoveryResolution.UNPROJECTED_RECOVERED
        )

    def _record_order_intent_recovery_continuation(self, transaction: object) -> None:
        session = self._backtest_recovery_session
        if session is None:
            return
        if not isinstance(transaction, OnlyCommittedRuntimeTransaction):
            raise TypeError("ORDER_INTENT_RECOVERY_CONTINUATION_INVALID")
        session.execution_session.record_autonomous_continuation(transaction)

    def _active_execution_recovery_session(self) -> OnlyExecutionRecoverySession | None:
        backtest = self._backtest_recovery_session
        if backtest is not None:
            return backtest.execution_session
        return self._execution_recovery_session

    def _recover_runtime(self) -> None:
        if not self._persistence_config.checkpoint.enabled:
            self._services.event_router.complete_fresh_bootstrap()
            return
        self._register_cluster_checkpoint_participants()
        self._checkpoint_query.bind_participant_registry_fingerprint(self._checkpoint_registry.fingerprint)
        has_checkpoint = self._checkpoint_query.latest_checkpoint(self.config.runtime_id) is not None  # type: ignore[arg-type]
        if has_checkpoint:
            self._services.event_router.begin_recovery()
            for update in self._services.broker_inbound.drain():
                self._services.execution_processor.replay_non_transaction(update)
            self._services.cluster_manager.enter_recovery_all()
        try:
            outcome = self._runtime_recovery_orchestrator.recover()
        except Exception as exc:
            self._services.event_router.fail()
            if has_checkpoint:
                self._services.cluster_manager.fail_recovery_finalization_all(exc)
            raise
        if outcome is None:
            if has_checkpoint:
                self._services.event_router.fail()
                raise AssertionError("checkpoint query and recovery outcome disagree")
            self._services.event_router.complete_fresh_bootstrap()
            return
        self._resume_pending_economic_fact_applications()
        self._services.event_router.begin_finalization()
        try:
            finalization = self._runtime_recovery_finalizer.finalize(outcome)
        except Exception:
            self._services.event_router.fail()
            raise
        self._services.event_router.complete_recovery()
        self._runtime_recovery_diagnostics.append(finalization.outcome.diagnostic)
        self._post_recovery_validation_reports.append(finalization.validation_report)
        self._clusters_recovered = True

    def _post_recovery_validation_context(
        self,
        outcome: OnlyRuntimeRecoveryOutcome,
    ) -> OnlyPostRecoveryValidationContext:
        runtime_id = OnlyRuntimeId(str(self.config.runtime_id))
        progress = self._result_progress.snapshot()
        accounts = self._services.account_query.list_accounts()
        ledgers = self._services.strategy_ledger_manager.list_ledgers()
        violations: list[str] = []
        ready = self._services.ready_execution_query.ready_records(runtime_id)
        for account in accounts:
            account_ledgers = tuple(item for item in ledgers if item.key.account_id == account.account_id)
            if not account_ledgers:
                violations.append(f"missing-ledger:{account.account_id}")
                continue
            result = OnlyRuntimeLedgerReconciliationService().reconcile(
                account=account,
                account_initial_equity=self.config.account_initial_cash or account.equity,
                ledgers=account_ledgers,
                committed_trade_fees=tuple(
                    OnlyCommittedTradeFeeAttribution(
                        item.fact.trade_id,
                        item.fact.cluster_id,
                        item.fact.fee_total_charges - item.fact.fee_total_rebates,
                    )
                    for item in ready
                    if isinstance(item.fact, OnlyCommittedExecutionFact) and item.fact.account_id == account.account_id
                ),
                ts_event=OnlyTimestamp.from_unix_nanos(self._services.clock.timestamp_ns()),
            )
            if result.status is OnlyRuntimeLedgerReconciliationStatus.MISMATCHED:
                violations.extend(f"{account.account_id}:{item.field}" for item in result.differences)
        broker_view = (
            None
            if self._services.broker_gateway is None
            else OnlyGatewayBrokerRecoveryAuthorityView(
                self._services.broker_gateway,
                tuple(item.account_id for item in accounts),
            )
        )
        return OnlyPostRecoveryValidationContext(
            runtime_id=runtime_id,
            outcome=outcome,
            transaction_query=self._services.execution_transaction_query,
            ready_transaction_query=self._services.ready_execution_query,
            outbox_query=self._services.runtime_transaction_outbox,
            applied_projection_view=self._applied_projection_ledger,
            runtime_boundary_view=OnlyRuntimeBoundaryAuthorityView(
                runtime_id,
                len(self._services.broker_inbound),
                len(self._services.market_data_inbound),
                self._services.event_bus.pending_count(),
                OnlyRuntimeDriverFrontierView(
                    self._replay_cursor.source_id,
                    self._replay_cursor.data_version,
                    self._replay_cursor.last_update_id,
                    self._replay_cursor.last_source_sequence,
                    self._replay_cursor.last_event_time,
                    self._replay_cursor.processed_bar_count,
                ),
                progress.processed_bar_count,
                progress.last_market_processing_sequence,
                self._services.market_data_processor.processing_sequence,
                OnlyTimestamp.from_unix_nanos(self._services.clock.timestamp_ns()),
            ),
            orders=self._services.order_manager.snapshot_all(),
            positions=self._services.position_manager.snapshot_all(),
            allocations=self._services.allocation_manager.snapshot_all(),
            accounts=accounts,
            strategy_ledgers=ledgers,
            account_reservations=self._account_reservation_manager.snapshots(),
            position_reservations=self._position_reservation_manager.snapshots(),
            strategy_reservations=tuple(item for ledger in ledgers for item in ledger.reservations),
            risk_reservations=self._services.risk_service.reservations.snapshot_all(),
            margin_reservations=self._margin_manager.active_reservations,
            fee_records=self._fee_application_ledger.records,
            settlement_records=self._settlement_authority.records,
            margin_records=self._margin_manager.records,
            broker_view=broker_view,
            ledger_reconciliation_violations=tuple(violations),
        )

    def _after_clusters_started(self) -> None:
        if not self._persistence_config.checkpoint.enabled:
            return
        if self._checkpoint_query.latest_checkpoint(self.config.runtime_id) is not None:  # type: ignore[arg-type]
            return
        self._drain_execution_updates_for_checkpoint()
        self._services.event_bus.drain()
        self._checkpoint_service.create(OnlyTimestamp.from_unix_nanos(self._services.clock.timestamp_ns()))

    def _register_cluster_checkpoint_participants(self) -> None:
        if self._cluster_checkpoint_participants_registered:
            return
        for cluster in sorted(self.clusters, key=lambda item: item.config.cluster_id):
            prefix = f"cluster.{cluster.config.cluster_id}"
            strategy = cluster.revision_strategy_participant
            if strategy is not None:
                strategy_component_id = f"{prefix}.30.strategy.{strategy.strategy_fingerprint}"
                if strategy.checkpoint_capability is OnlyCheckpointCapability.STATELESS:
                    self._checkpoint_registry.register(OnlyStatelessRuntimeCheckpointParticipant(strategy_component_id))
                else:
                    self._checkpoint_registry.register(
                        OnlyJsonRuntimeCheckpointParticipant(
                            strategy_component_id,
                            strategy.checkpoint_schema_version,
                            strategy.capture_checkpoint,
                            strategy.restore_checkpoint,
                        )
                    )
            self._checkpoint_registry.register(
                OnlyJsonRuntimeCheckpointParticipant(
                    f"{prefix}.40.result-recorder",
                    1,
                    cluster.result_recorder.capture_checkpoint,
                    cluster.result_recorder.restore_checkpoint,
                )
            )
            if cluster.action_workload is not None:
                self._checkpoint_registry.register(
                    OnlyJsonRuntimeCheckpointParticipant(
                        f"{prefix}.35.scenario-actions",
                        1,
                        cluster.action_workload.capture_checkpoint,
                        cluster.action_workload.restore_checkpoint,
                    )
                )
            for factor in cluster.factors:
                factor_component_id = f"{prefix}.20.factor.{factor.factor_id}"
                if factor.checkpoint_capability is None:
                    raise OnlyRuntimeError(f"checkpoint capability is not declared by Factor: {type(factor).__name__}")
                if factor.checkpoint_capability is OnlyCheckpointCapability.STATELESS:
                    self._checkpoint_registry.register(OnlyStatelessRuntimeCheckpointParticipant(factor_component_id))
                else:
                    if factor.checkpoint_schema_version is None:
                        raise OnlyRuntimeError(
                            f"checkpoint schema version is not declared by Factor: {type(factor).__name__}"
                        )
                    self._checkpoint_registry.register(
                        OnlyJsonRuntimeCheckpointParticipant(
                            factor_component_id,
                            factor.checkpoint_schema_version,
                            factor.capture_checkpoint,
                            factor.restore_checkpoint,
                        )
                    )
            for key, value in cluster.checkpoint_indicators:
                indicator = value
                indicator_component_id = f"{prefix}.10.indicator.{key.factor_id}.{key.indicator_id}"
                if indicator.checkpoint_capability is None:
                    raise OnlyRuntimeError(
                        f"checkpoint capability is not declared by Indicator: {type(indicator).__name__}"
                    )
                if indicator.checkpoint_capability is OnlyCheckpointCapability.STATELESS:
                    self._checkpoint_registry.register(
                        OnlyStatelessRuntimeCheckpointParticipant(indicator_component_id)
                    )
                else:
                    if indicator.checkpoint_schema_version is None:
                        raise OnlyRuntimeError(
                            f"checkpoint schema version is not declared by Indicator: {type(indicator).__name__}"
                        )
                    self._checkpoint_registry.register(
                        OnlyJsonRuntimeCheckpointParticipant(
                            indicator_component_id,
                            indicator.checkpoint_schema_version,
                            indicator.capture_checkpoint,
                            indicator.restore_checkpoint,
                        )
                    )

            def restore_factor_views(payload: object, selected: OnlyCluster = cluster) -> None:
                if payload != {}:
                    raise ValueError("Cluster factor view checkpoint must be empty")
                selected.refresh_checkpoint_factor_views()

            self._checkpoint_registry.register(
                OnlyJsonRuntimeCheckpointParticipant(
                    f"{prefix}.90.factor-views",
                    1,
                    lambda: {},
                    restore_factor_views,
                )
            )
        self._cluster_checkpoint_participants_registered = True

    def _checkpoint_barrier(self, completion: OnlyBacktestBarCompletion) -> None:
        if self._run_plan is None:
            return
        if self._execution_checkpoint_blocked:
            return
        if self._persistence_config.checkpoint.enabled and (
            len(self._services.broker_inbound) or len(self._services.market_data_inbound)
        ):
            raise OnlyRuntimeError("checkpoint barrier requires empty inbound queues")
        self._replay_cursor = OnlyBacktestReplayCursor(
            completion.source_id,
            completion.data_version,
            completion.update_id,
            completion.source_sequence,
            completion.ts_event,
            self._result_progress.snapshot().processed_bar_count,
        )
        if not self._persistence_config.checkpoint.enabled or self._backtest_recovery_session is not None:
            return
        self._checkpoint_service.create(OnlyTimestamp.from_unix_nanos(self._services.clock.timestamp_ns()))

    def _capture_runtime_progress_checkpoint(self) -> object:
        return {
            "account_valuation_version": self._account_valuation_version,
            "last_market_trading_day": None
            if self._last_market_trading_day is None
            else self._last_market_trading_day.value.isoformat(),
            "legacy_market_data_sequence": self._legacy_market_data_sequence,
            "strategy_valuation_versions": [
                [key.to_json(), value]
                for key, value in sorted(self._valuation_versions.items(), key=lambda item: item[0].to_json())
            ],
        }

    def _restore_runtime_progress_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, Mapping):
            raise ValueError("runtime progress checkpoint must be an object")
        self._account_valuation_version = int(payload["account_valuation_version"])
        self._legacy_market_data_sequence = int(payload["legacy_market_data_sequence"])
        trading_day = payload["last_market_trading_day"]
        self._last_market_trading_day = (
            None if trading_day is None else OnlyTradingDay(datetime.fromisoformat(str(trading_day)).date())
        )
        versions = payload["strategy_valuation_versions"]
        if not isinstance(versions, list):
            raise ValueError("strategy valuation versions checkpoint must be a list")
        self._valuation_versions = {
            OnlyStrategyLedgerKey.from_json(str(item[0])): int(item[1])
            for item in versions
            if isinstance(item, list) and len(item) == 2
        }

    def _restore_backtest_replay_frontier(self, payload: object) -> None:
        self._replay_cursor = OnlyBacktestReplayCursor.from_checkpoint(payload)

    def _capture_backtest_clock_checkpoint(self) -> object:
        snapshot = cast(OnlyBacktestClock, self._services.clock).snapshot()
        return {
            "clock_sequence": snapshot.sequence,
            "clock_timestamp_ns": snapshot.current_timestamp_ns,
            "timers": [
                {
                    "created_at_ns": timer.created_at_ns,
                    "fire_count": timer.fire_count,
                    "interval_ns": timer.interval_ns,
                    "metadata": dict(sorted(timer.metadata.items())),
                    "mode": timer.mode.value,
                    "next_deadline_ns": timer.next_deadline_ns,
                    "sequence": timer.sequence,
                    "state": timer.state.value,
                    "timer_id": str(timer.timer_id),
                }
                for timer in snapshot.active_timers
            ],
        }

    def _restore_backtest_clock_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, Mapping) or not isinstance(payload["timers"], list):
            raise ValueError("Backtest clock checkpoint must be an object with timers")
        from types import MappingProxyType

        from onlyalpha.core.clock import (
            OnlyClockSnapshot,
            OnlyTimerId,
            OnlyTimerMode,
            OnlyTimerSnapshot,
            OnlyTimerState,
        )

        timers: list[OnlyTimerSnapshot] = []
        for raw in payload["timers"]:
            if not isinstance(raw, Mapping) or not isinstance(raw["metadata"], Mapping):
                raise ValueError("Backtest Timer checkpoint entry must be an object")
            timers.append(
                OnlyTimerSnapshot(
                    OnlyTimerId(str(raw["timer_id"])),
                    OnlyTimerMode(str(raw["mode"])),
                    int(raw["created_at_ns"]),
                    int(raw["next_deadline_ns"]),
                    None if raw["interval_ns"] is None else int(raw["interval_ns"]),
                    int(raw["sequence"]),
                    OnlyTimerState(str(raw["state"])),
                    int(raw["fire_count"]),
                    MappingProxyType({str(key): str(value) for key, value in raw["metadata"].items()}),
                )
            )
        cast(OnlyBacktestClock, self._services.clock).restore_with_registered_callbacks(
            OnlyClockSnapshot(
                int(payload["clock_timestamp_ns"]),
                int(payload["clock_sequence"]),
                tuple(timers),
            )
        )

    def _activate_backtest_recovery(self, session: OnlyBacktestRecoverySession) -> None:
        if self._backtest_recovery_session is not None:
            raise OnlyRuntimeError("Backtest recovery session is already active")
        self._backtest_recovery_session = session

    def _deactivate_backtest_recovery(self) -> None:
        self._backtest_recovery_session = None

    def _activate_execution_recovery(self, session: OnlyExecutionRecoverySession) -> None:
        if self._execution_recovery_session is not None or self._backtest_recovery_session is not None:
            raise OnlyRuntimeError("Execution recovery session is already active")
        self._execution_recovery_session = session

    def _deactivate_execution_recovery(self) -> None:
        self._execution_recovery_session = None

    def register_instrument(
        self,
        instrument: OnlyInstrument,
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

    def process_bar(self, bar: OnlyBar) -> OnlyRuntimeBarResult:
        """Compatibility facade implemented as a one-record local historical replay."""

        if self._state is not OnlyRuntimeState.RUNNING:
            raise OnlyLifecycleError("Runtime accepts Bars only while RUNNING")
        try:
            self._legacy_market_data_sequence += 1
            source_id = self._services.historical_data_source.source_id
            data_version = OnlyDataVersion("runtime-local-v1")
            inbound = OnlyMarketDataInboundUpdate(
                only_bar_update_id(source_id, bar.instrument_id, bar.bar_type, bar.bar_start, data_version),
                OnlyRuntimeId(str(self.config.runtime_id)),
                source_id,
                OnlyDataSequence(self._legacy_market_data_sequence),
                data_version,
                bar.instrument_id,
                OnlyMarketDataType.BAR,
                OnlyBarUpdate(bar),
                OnlyTimestamp.from_datetime(bar.ts_event),
                OnlyTimestamp.from_datetime(bar.ts_init),
                OnlyMarketDataQuality(frozenset({OnlyMarketDataQualityFlag.UNADJUSTED})),
                sequence_semantics=OnlyDataSequenceSemantics.MONOTONIC,
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
        economic_requests: tuple[OnlyHistoricalFactRequest, ...] = (),
    ) -> OnlyHistoricalReplayResult:
        """Load through HistoricalDataSource, then merge/advance/process through ReplayService."""

        if self._state is not OnlyRuntimeState.RUNNING:
            raise OnlyLifecycleError("Runtime accepts historical replay only while RUNNING")
        if not self._services.market_data_source_registry.contains(source.source_id):
            self._services.market_data_source_registry.register(source)
        economic_source = cast(OnlyHistoricalFactSource, source)
        streams = (
            source.load_bars(request),
            *(economic_source.load_facts(item) for item in economic_requests),
        )
        prepared = self._services.historical_replay_service.prepare(
            OnlyHistoricalReplayConfig(streams, source_priority=(source.source_id,))
        )
        stream = OnlyHistoricalDataStream(prepared.updates, request.batch_size)
        replay_cursor = self._replay_cursor
        if replay_cursor.last_update_id is not None:
            if source.source_id != replay_cursor.source_id or request.data_version != replay_cursor.data_version:
                raise OnlyRuntimeError("replay cursor source identity or data version changed")
            matched = tuple(
                index
                for index, item in enumerate(stream.records)
                if item.update_id == replay_cursor.last_update_id
                and int(item.source_sequence) == replay_cursor.last_source_sequence
            )
            if len(matched) != 1:
                raise OnlyRuntimeError("replay cursor update identity is absent or ambiguous")
            stream = OnlyHistoricalDataStream(stream.records[matched[0] + 1 :], stream.batch_size)
        cursor = self._services.historical_replay_service.prepare(
            OnlyHistoricalReplayConfig((stream,), source_priority=(source.source_id,))
        )
        return self._services.historical_replay_service.run(cursor)

    def drain_broker_inbound(self) -> tuple[object, ...]:
        """Drain FIFO updates through the Runtime-owned sole business processor."""

        results, _receipts = self._drain_broker_inbound_batch()
        return results

    def drain_broker_inbound_with_receipts(self) -> tuple[OnlyBrokerFactApplicationReceipt, ...]:
        """Process Broker facts and return ACKs backed by canonical durable application."""

        results, receipts = self._drain_broker_inbound_batch()
        if len(receipts) != len(results):
            raise OnlyRuntimeError("BROKER_FACT_APPLICATION_NOT_ACKNOWLEDGEABLE")
        return receipts

    def _drain_broker_inbound_batch(
        self,
    ) -> tuple[tuple[OnlyExecutionProcessingResult, ...], tuple[OnlyBrokerFactApplicationReceipt, ...]]:
        """One implementation for normal draining and reconciliation ACK production."""

        if self._state is not OnlyRuntimeState.RUNNING:
            raise OnlyLifecycleError("Runtime accepts Broker updates only while RUNNING")
        results: list[OnlyExecutionProcessingResult] = []
        receipts: list[OnlyBrokerFactApplicationReceipt] = []
        for update in self._services.broker_inbound.drain():
            processing = self._services.execution_processor.process(update)
            delivery = self._services.execution_delivery_coordinator.deliver(
                self.config.runtime_id,  # type: ignore[arg-type]
                processing.delivery_intent,
            )
            self._record_execution_delivery(processing.sequence, delivery)
            results.append(processing)
            if processing.status in {
                OnlyExecutionProcessingStatus.APPLIED,
                OnlyExecutionProcessingStatus.DUPLICATE,
            }:
                receipts.append(
                    OnlyBrokerFactApplicationReceipt(
                        update.update_id,
                        OnlyBrokerFactApplicationStatus.APPLIED
                        if processing.status is OnlyExecutionProcessingStatus.APPLIED
                        else OnlyBrokerFactApplicationStatus.DUPLICATE,
                    )
                )
        self._broker_results.extend(results)
        self._services.event_bus.drain()
        return tuple(results), tuple(receipts)

    def receive_broker_update(self, update: OnlyBrokerInboundUpdate) -> None:
        """Runtime management inbound Port used by Gateways and explicit fault adapters."""

        if self._state is not OnlyRuntimeState.RUNNING:
            raise OnlyLifecycleError("Runtime accepts Broker updates only while RUNNING")
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

    def _validate_trade(
        self,
        update: OnlyGatewayOrderFillUpdate,
        trade: OnlyPositionTrade,
        order: object,
    ) -> None:

        if not isinstance(order, OnlyOrderSnapshot):
            raise TypeError("Order query must return OnlyOrderSnapshot")
        fill = update.fill
        if trade.cluster_id is None:
            raise ValueError("Runtime strategy Trade requires cluster attribution")
        expected_offset = (
            (OnlyOffset.OPEN if order.side is OnlyOrderSide.BUY else OnlyOffset.CLOSE)
            if order.offset is OnlyOffset.NONE
            else order.offset
        )
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
            expected_offset,
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
        instrument = self._instruments.get(trade.instrument_id)
        if instrument is None or trade.multiplier != instrument.contract_multiplier:
            raise ValueError("Position Trade requires the registered Instrument multiplier")

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

    def _has_account_ledger_parity(self, account: OnlyAccountSnapshot) -> bool:
        ledgers = tuple(
            item
            for item in self._strategy_ledger_manager.list_ledgers()
            if item.key.runtime_id == account.runtime_id
            and item.key.account_id == account.account_id
            and item.key.base_currency == account.base_currency
        )
        return (
            bool(ledgers)
            and account.cash.ledger_cash.amount == sum((item.cash.ledger_cash.amount for item in ledgers), Decimal(0))
            and account.position_market_value.amount
            == sum((item.equity.position_market_value.amount for item in ledgers), Decimal(0))
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
        if snapshot is None:
            return OnlyMoney(Decimal(0), self.config.strategy_base_currency)
        quantum = Decimal(1).scaleb(-self.config.strategy_base_currency.precision)
        amount = (snapshot.cumulative_open_price_quantity * trade.multiplier.value).quantize(quantum)
        return OnlyMoney(amount, self.config.strategy_base_currency)

    def _build_trade_execution_planning_context(
        self,
        update: OnlyBrokerTradeUpdate,
        processing_sequence: int,
        position_scope: OnlyExecutionPositionScope,
        support_decision: OnlyExecutionSupportDecision,
    ) -> OnlyTradeExecutionPlanningContext:
        order = self._services.order_manager.require_snapshot(update.order_id)
        market_rules = self.config.market_rule_engine
        if market_rules is None:
            raise ValueError("prepared Trade planning requires compiled market rules")
        trading_day = self._selected_calendar.trading_day_at(update.ts_event)
        instruction = market_rules.build_trade_instruction(
            OnlyTradeApplicationRequest(
                str(order.instrument_id),
                str(order.order_id),
                str(update.fill.trade_id),
                str(order.account_id),
                order.side,
                update.fill.quantity.value,
                update.fill.price.value,
                update.ts_event.to_datetime(),
                trading_day,
                position_scope.position_effect,
            )
        )
        binding = order.fee_policy_binding
        if binding is None:
            raise ValueError("ORDER_FEE_POLICY_BINDING_REQUIRED")
        fee_assessment = self._fee_resolver.assess_trade(
            order,
            binding,
            trade_id=update.fill.trade_id,
            price=update.fill.price,
            quantity=update.fill.quantity.value,
            timestamp=update.ts_event,
            liquidity_role=update.fill.liquidity_side,
            cumulative_quantity=order.filled_quantity.value + update.fill.quantity.value,
            cumulative_notional=OnlyMoney(
                (
                    (order.cumulative_price_quantity + update.fill.price.value * update.fill.quantity.value)
                    * self._instruments[order.instrument_id].contract_multiplier.value
                ).quantize(Decimal(1).scaleb(-self.config.strategy_base_currency.precision)),
                self.config.strategy_base_currency,
            ),
        )
        position_before_snapshot = self._services.position_manager.get_snapshot(position_scope.position_key)
        allocation_key = position_scope.allocation_key
        if allocation_key is None:
            raise ValueError("prepared Trade planning requires Cluster Allocation scope")
        allocation_before_snapshot = self._services.allocation_manager.get_snapshot(allocation_key)
        scoped_allocations = tuple(
            item
            for item in self._services.allocation_manager.list_by_instrument(order.instrument_id)
            if item.key.runtime_id == order.runtime_id
            and item.key.account_id == order.account_id
            and item.key.position_side is position_scope.position_side
        )
        account_snapshot = self._services.account_manager.get_snapshot(order.account_id)
        if account_snapshot is None:
            raise KeyError(f"Account not found: {order.account_id}")
        ledger_snapshot = self._strategy_ledger_locator.require_snapshot(
            runtime_id=order.runtime_id,
            account_id=order.account_id,
            cluster_id=order.cluster_id,
            currency=account_snapshot.base_currency,
        )
        account_reservation = next(
            (item for item in account_snapshot.reservations if item.order_id == order.order_id),
            None,
        )
        closing = position_scope.position_effect is OnlyPositionEffect.CLOSE
        margin_opening = not closing and instruction.margin_instruction is not None
        if account_reservation is None and not closing and not margin_opening:
            raise ValueError("prepared Trade planning requires Account cash Reservation")
        strategy_reservation = next(
            (item for item in ledger_snapshot.reservations if item.order_id == order.order_id),
            None,
        )
        if strategy_reservation is None and not closing and not margin_opening:
            raise ValueError("prepared Trade planning requires Strategy cash Reservation")
        position_reservation = self._position_reservation_manager.get(order.order_id)
        margin_reservation = self._margin_manager.get(str(order.order_id))
        margin_reservations: tuple[OnlyMarginReservation, ...] = (
            () if margin_reservation is None else (margin_reservation,)
        )
        if closing and instruction.margin_instruction is not None and margin_reservation is None:
            margin_candidates = self._margin_manager.occupied_reservations(
                str(order.account_id),
                str(order.instrument_id),
                position_scope.position_side,
            )
            if not margin_candidates:
                raise ValueError("prepared Margin Close requires occupied Margin authority")
            margin_reservation = margin_candidates[0]
            margin_reservations = margin_candidates
        if position_reservation is None and closing:
            raise ValueError("prepared Close planning requires Position Reservation")
        if instruction.margin_instruction is not None and not closing and margin_reservation is None:
            raise ValueError("prepared Margin Trade planning requires Margin Reservation")
        risk_reservation = self._services.risk_service.reservations.get_for_order(order.order_id)
        if risk_reservation is None:
            raise ValueError("prepared Trade planning requires Risk Reservation")
        position_cycle = self._services.position_manager.creation_cycle_head(position_scope.position_key)
        allocation_cycle = self._services.allocation_manager.creation_cycle_head(allocation_key)
        position_creation = (
            OnlyPositionCreationAuthority(
                OnlyPositionId(
                    f"POS-{position_scope.position_key.runtime_id}-{position_scope.position_key.account_id}-"
                    f"{position_scope.position_key.instrument_id}-"
                    f"{position_scope.position_key.position_side.value}-{position_cycle + 1:08d}"
                ),
                position_cycle + 1,
            )
            if position_before_snapshot is None and not closing
            else None
        )
        allocation_creation = (
            OnlyAllocationCreationAuthority(
                OnlyPositionAllocationId(
                    f"ALLOC-{allocation_key.runtime_id}-{allocation_key.account_id}-{allocation_key.cluster_id}-"
                    f"{allocation_key.instrument_id}-{allocation_cycle + 1:08d}"
                ),
                allocation_cycle + 1,
            )
            if allocation_before_snapshot is None and not closing
            else None
        )
        account_timeline = self._account_performance_projector.timeline(order.account_id)
        ledger_timeline = self._strategy_ledger_manager.equity_timeline(ledger_snapshot.key)
        valuation_price, _valuation_source = self._valuation_price(
            order.instrument_id,
            trading_day,
            update.ts_event,
        )
        valuation_state = self._execution_valuation_state(order.account_id)
        if valuation_state is None:
            raise ValueError("prepared Trade planning requires Runtime valuation authority")
        return OnlyTradeExecutionPlanningContext(
            update=update,
            prepared_at=update.ts_init,
            engine_id=OnlyEngineId(str(self.config.engine_id)),
            strategy_id=self._services.cluster_manager.require_cluster(order.cluster_id).strategy_id,
            processing_sequence=processing_sequence,
            trading_day=trading_day,
            contract_multiplier=self._instruments[order.instrument_id].contract_multiplier,
            valuation_price=valuation_price,
            position_scope=position_scope,
            trade_instruction=instruction,
            support_decision=support_decision,
            fee_assessment=fee_assessment,
            order_before=only_order_execution_state(order),
            position_before=(
                None if position_before_snapshot is None else only_position_execution_state(position_before_snapshot)
            ),
            allocation_before=(
                None
                if allocation_before_snapshot is None
                else only_allocation_execution_state(allocation_before_snapshot)
            ),
            aggregate_allocation_quantity_before=sum(
                (item.total_quantity.value for item in scoped_allocations), Decimal(0)
            ),
            aggregate_allocation_cumulative_cost_before=sum(
                (item.cumulative_open_price_quantity for item in scoped_allocations), Decimal(0)
            ),
            account_ledger_parity=self._has_account_ledger_parity(account_snapshot),
            settlement_before=None,
            fee_before=None,
            order_fee_accrual_before=self._order_fee_accrual_manager.get(order.order_id),
            account_before=only_account_execution_state(account_snapshot),
            strategy_ledger_before=only_strategy_ledger_execution_state(ledger_snapshot),
            account_cash_reservation_before=(
                None
                if account_reservation is None
                else only_account_cash_reservation_execution_state(account_reservation)
            ),
            strategy_cash_reservation_before=(
                None
                if strategy_reservation is None
                else only_strategy_cash_reservation_execution_state(strategy_reservation)
            ),
            risk_reservation_before=only_risk_reservation_execution_state(risk_reservation),
            risk_before=only_risk_execution_state(self._services.risk_service.get_snapshot(order.cluster_id)),
            valuation_before=valuation_state,
            fill_authority=only_capture_execution_fill_authority(
                self._services.execution_transaction_query,
                update,
            ),
            position_creation=position_creation,
            allocation_creation=allocation_creation,
            position_cycle=position_cycle,
            allocation_cycle=allocation_cycle,
            settlement_record_sequence=self._services.settlement_authority.sequence_head,
            fee_record_sequence=self._services.fee_application_ledger.sequence_head,
            account_equity_sequence=0 if not account_timeline else account_timeline[-1].sequence,
            ledger_equity_sequence=self._strategy_ledger_manager.equity_sequence_head,
            account_external_cash_flow=(
                OnlyMoney(Decimal(0), account_snapshot.base_currency)
                if not account_timeline
                else account_timeline[-1].external_cash_flow
            ),
            ledger_equity_before=None if not ledger_timeline else ledger_timeline[-1],
            ledger_high_water_mark=ledger_snapshot.equity.high_water_mark,
            account_equity_before=account_timeline,
            strategy_equity_before=ledger_timeline,
            position_reservation_before=(
                None
                if position_reservation is None
                else only_position_reservation_execution_state(position_reservation)
            ),
            margin_reservation_before=(
                None if margin_reservation is None else only_margin_reservation_execution_state(margin_reservation)
            ),
            margin_reservations_before=tuple(
                only_margin_reservation_execution_state(item) for item in margin_reservations
            ),
        )

    def _build_terminal_execution_planning_context(
        self,
        update: OnlyBrokerOrderTerminalUpdate,
        processing_sequence: int,
        position_scope: OnlyExecutionPositionScope,
        support_decision: OnlyExecutionSupportDecision,
    ) -> OnlyTerminalExecutionPlanningContext:
        order = self._services.order_manager.require_snapshot(update.order_id)
        account = self._services.account_manager.get_snapshot(order.account_id)
        if account is None:
            raise KeyError(f"Account not found: {order.account_id}")
        position_reservation = self._position_reservation_manager.get(order.order_id)
        margin_reservation = self._margin_manager.get(str(order.order_id))
        risk_reservation = self._services.risk_service.reservations.get_for_order(order.order_id)
        if risk_reservation is None:
            raise ValueError("prepared Terminal planning requires Risk Reservation")
        ledger = self._strategy_ledger_locator.require_snapshot(
            runtime_id=order.runtime_id,
            account_id=order.account_id,
            cluster_id=order.cluster_id,
            currency=account.base_currency,
        )
        account_reservation = next((item for item in account.reservations if item.order_id == order.order_id), None)
        strategy_reservation = next((item for item in ledger.reservations if item.order_id == order.order_id), None)
        position = self._services.position_manager.get_snapshot(position_scope.position_key)
        allocation = (
            None
            if position_scope.allocation_key is None
            else self._services.allocation_manager.get_snapshot(position_scope.allocation_key)
        )
        return OnlyTerminalExecutionPlanningContext(
            update=update,
            prepared_at=update.ts_init,
            engine_id=OnlyEngineId(str(self.config.engine_id)),
            processing_sequence=processing_sequence,
            position_scope=position_scope,
            support_decision=support_decision,
            terminal_authority=only_capture_execution_terminal_authority(update),
            order_before=only_order_execution_state(order),
            position_before=None if position is None else only_position_execution_state(position),
            allocation_before=None if allocation is None else only_allocation_execution_state(allocation),
            position_cycle=self._services.position_manager.creation_cycle_head(position_scope.position_key),
            allocation_cycle=(
                0
                if position_scope.allocation_key is None
                else self._services.allocation_manager.creation_cycle_head(position_scope.allocation_key)
            ),
            account_before=only_account_execution_state(account),
            strategy_ledger_before=only_strategy_ledger_execution_state(ledger),
            account_cash_reservation_before=(
                None
                if account_reservation is None
                else only_account_cash_reservation_execution_state(account_reservation)
            ),
            strategy_cash_reservation_before=(
                None
                if strategy_reservation is None
                else only_strategy_cash_reservation_execution_state(strategy_reservation)
            ),
            strategy_valuation_lines=self._strategy_ledger_manager.execution_valuation_lines(ledger.key),
            position_reservation_before=(
                None
                if position_reservation is None
                else only_position_reservation_execution_state(position_reservation)
            ),
            margin_reservation_before=(
                None if margin_reservation is None else only_margin_reservation_execution_state(margin_reservation)
            ),
            risk_reservation_before=only_risk_reservation_execution_state(risk_reservation),
            risk_before=only_risk_execution_state(self._services.risk_service.get_snapshot(order.cluster_id)),
        )

    def _build_order_accepted_execution_planning_context(
        self,
        update: OnlyBrokerOrderAcceptedUpdate,
        processing_sequence: int,
        position_scope: OnlyExecutionPositionScope,
        support_decision: OnlyExecutionSupportDecision,
    ) -> OnlyOrderAcceptedExecutionPlanningContext:
        order = self._services.order_manager.require_snapshot(update.order_id)
        account = self._services.account_manager.require_snapshot(order.account_id)
        ledger = self._strategy_ledger_locator.require_snapshot(
            runtime_id=order.runtime_id,
            account_id=order.account_id,
            cluster_id=order.cluster_id,
            currency=account.base_currency,
        )
        margin_reservation = self._margin_manager.get(str(order.order_id))
        position = self._services.position_manager.get_snapshot(position_scope.position_key)
        position_reservation = self._position_reservation_manager.get(order.order_id)
        strategy_reservation = next((item for item in ledger.reservations if item.order_id == order.order_id), None)
        return OnlyOrderAcceptedExecutionPlanningContext(
            update=update,
            accepted_authority=only_capture_execution_order_accepted_authority(update),
            prepared_at=update.ts_init,
            engine_id=OnlyEngineId(str(self.config.engine_id)),
            processing_sequence=processing_sequence,
            position_scope=position_scope,
            support_decision=support_decision,
            order_before=only_order_execution_state(order),
            position_before=None if position is None else only_position_execution_state(position),
            position_cycle=self._services.position_manager.creation_cycle_head(position_scope.position_key),
            position_reservation_before=(
                None
                if position_reservation is None
                else only_position_reservation_execution_state(position_reservation)
            ),
            margin_reservation_before=(
                None if margin_reservation is None else only_margin_reservation_execution_state(margin_reservation)
            ),
            strategy_ledger_before=only_strategy_ledger_execution_state(ledger),
            strategy_cash_reservation_before=(
                None
                if strategy_reservation is None
                else only_strategy_cash_reservation_execution_state(strategy_reservation)
            ),
            strategy_valuation_lines=self._strategy_ledger_manager.execution_valuation_lines(ledger.key),
        )

    def _execution_valuation_state(self, account_id: OnlyAccountId) -> OnlyValuationExecutionState | None:
        existing = self._execution_valuation_states.get(account_id)
        if existing is not None:
            return existing
        return self._capture_execution_valuation_state(account_id)

    def _capture_execution_valuation_state(self, account_id: OnlyAccountId) -> OnlyValuationExecutionState | None:
        snapshot = self._account_manager.get_snapshot(account_id)
        if snapshot is None:
            return None
        valuation_time = snapshot.valuation_time or snapshot.updated_at
        state = OnlyValuationExecutionState(
            account_id,
            valuation_time,
            snapshot.cash.ledger_cash,
            snapshot.position_market_value,
            snapshot.unrealized_pnl,
            snapshot.equity,
            self._account_valuation_version,
        )
        self._execution_valuation_states[account_id] = state
        return state

    def _restore_execution_valuation_state(self, state: OnlyValuationExecutionState) -> None:
        self.restore_execution_valuation_version(state.version)
        self._execution_valuation_states[state.account_id] = state

    def _capture_economic_facts_checkpoint(self) -> object:
        return {
            "reference_prices": [
                self._reference_price_facts[key].to_json() for key in sorted(self._reference_price_facts)
            ],
            "funding_rates": [self._funding_rate_facts[key].to_json() for key in sorted(self._funding_rate_facts)],
            "pending_applications": [
                self._pending_economic_fact_applications[key].to_json()
                for key in sorted(self._pending_economic_fact_applications)
            ],
        }

    def _restore_economic_facts_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise ValueError("economic facts checkpoint must be an object")
        references = tuple(OnlyReferencePriceFact.from_json(str(item)) for item in payload["reference_prices"])
        funding = tuple(OnlyFundingRateFact.from_json(str(item)) for item in payload["funding_rates"])
        self._reference_price_facts = {item.fact_id: item for item in references}
        self._funding_rate_facts = {item.fact_id: item for item in funding}
        pending = tuple(
            _OnlyEconomicFactApplicationPlan.from_json(str(item)) for item in payload.get("pending_applications", [])
        )
        self._pending_economic_fact_applications = {item.fact_id: item for item in pending}
        self._reference_prices_by_boundary = {}
        for fact in sorted(references, key=lambda item: item.stable_order):
            boundary = (
                fact.instrument_id,
                fact.kind,
                OnlyTimestamp.from_datetime(fact.ts_event).unix_nanos,
            )
            current = self._reference_prices_by_boundary.get(boundary)
            if current is None or (fact.revision, fact.source_sequence, fact.fact_id) > (
                current.revision,
                current.source_sequence,
                current.fact_id,
            ):
                self._reference_prices_by_boundary[boundary] = fact

    def _apply_canonical_economic_fact(self, update: OnlyMarketDataInboundUpdate) -> None:
        self._begin_direct_execution_events()
        try:
            if isinstance(update.payload, OnlyReferencePriceUpdate):
                self._install_reference_price(update.payload.fact, apply_valuation=True)
            elif isinstance(update.payload, OnlyFundingRateUpdate):
                self._apply_funding_rate(update.payload.fact)
            else:
                raise ValueError("CANONICAL_ECONOMIC_FACT_TYPE_UNSUPPORTED")
        except Exception:
            self._flush_direct_execution_events()
            raise
        else:
            self._complete_direct_execution_events(True)

    def _resume_pending_economic_fact_applications(self) -> None:
        plans = tuple(
            sorted(
                self._pending_economic_fact_applications.values(),
                key=_economic_fact_application_stable_order,
            )
        )
        for plan in plans:
            self._begin_direct_execution_events()
            try:
                if plan.application_kind == "SETTLEMENT":
                    fact = OnlyReferencePriceFact.from_json(plan.source_fact_json)
                    self._install_reference_price(fact, apply_valuation=True)
                elif plan.application_kind == "FUNDING":
                    funding = OnlyFundingRateFact.from_json(plan.source_fact_json)
                    self._apply_funding_rate(funding)
                else:
                    raise ValueError("ECONOMIC_FACT_APPLICATION_KIND_UNSUPPORTED")
            except Exception:
                self._flush_direct_execution_events()
                raise
            else:
                self._complete_direct_execution_events(True)

    def _install_reference_price(self, fact: OnlyReferencePriceFact, *, apply_valuation: bool) -> None:
        existing = self._reference_price_facts.get(fact.fact_id)
        if existing is not None:
            if existing != fact:
                raise ValueError("REFERENCE_PRICE_FACT_ID_CONFLICT")
            return
        boundary = (
            fact.instrument_id,
            fact.kind,
            OnlyTimestamp.from_datetime(fact.ts_event).unix_nanos,
        )
        current = self._reference_prices_by_boundary.get(boundary)
        if current is not None and current.revision == fact.revision and current != fact:
            raise ValueError("REFERENCE_PRICE_BOUNDARY_AUTHORITY_CONFLICT")
        if fact.kind is OnlyReferencePriceKind.SETTLEMENT and apply_valuation:
            self._apply_settlement_fact(fact)
        self._reference_price_facts[fact.fact_id] = fact
        selected = current is None or (fact.revision, fact.source_sequence, fact.fact_id) > (
            current.revision,
            current.source_sequence,
            current.fact_id,
        )
        if selected:
            self._reference_prices_by_boundary[boundary] = fact
        try:
            if not apply_valuation:
                return
            trading_day = self._selected_calendar.trading_day_at(fact.ts_event)
            engine = self.config.market_rule_engine
            if engine is None:
                raise ValueError("MARKET_RULE_ENGINE_REQUIRED")
            policy = engine.compiled_rules(str(fact.instrument_id), trading_day, as_of=fact.ts_event)
            if (
                policy.economic_model is OnlyEconomicModel.MARGINED_DERIVATIVE
                and policy.valuation_policy is not None
                and policy.valuation_policy.unrealized_price_kind is fact.kind
            ):
                self._apply_market_valuations_at(
                    OnlyTimestamp.from_datetime(fact.ts_event),
                    trading_day,
                )
        except Exception:
            self._reference_price_facts.pop(fact.fact_id, None)
            if selected:
                if current is None:
                    self._reference_prices_by_boundary.pop(boundary, None)
                else:
                    self._reference_prices_by_boundary[boundary] = current
            raise
        else:
            self._pending_economic_fact_applications.pop(fact.fact_id, None)

    def _apply_settlement_fact(self, fact: OnlyReferencePriceFact) -> None:
        trading_day = self._selected_calendar.trading_day_at(fact.ts_event)
        engine = self.config.market_rule_engine
        if engine is None:
            raise ValueError("MARKET_RULE_ENGINE_REQUIRED")
        policy = engine.compiled_rules(str(fact.instrument_id), trading_day, as_of=fact.ts_event)
        if policy.variation_margin_policy is None:
            raise ValueError("VARIATION_MARGIN_POLICY_UNAVAILABLE")
        plan = self._pending_economic_fact_applications.get(fact.fact_id)
        if plan is None:
            plan = self._plan_settlement_application(fact)
            self._pending_economic_fact_applications[fact.fact_id] = plan
        elif plan.source_fact_json != fact.to_json() or plan.application_kind != "SETTLEMENT":
            raise ValueError("ECONOMIC_FACT_APPLICATION_ID_CONFLICT")
        self._apply_economic_fact_plan(plan)

    def _apply_funding_rate(self, fact: OnlyFundingRateFact) -> None:
        existing = self._funding_rate_facts.get(fact.fact_id)
        if existing is not None:
            if existing != fact:
                raise ValueError("FUNDING_RATE_FACT_ID_CONFLICT")
            return
        trading_day = self._selected_calendar.trading_day_at(fact.funding_time)
        engine = self.config.market_rule_engine
        if engine is None:
            raise ValueError("MARKET_RULE_ENGINE_REQUIRED")
        policy = engine.compiled_rules(str(fact.instrument_id), trading_day, as_of=fact.funding_time)
        if policy.funding_policy is None:
            raise ValueError("FUNDING_POLICY_UNAVAILABLE")
        boundary = (
            fact.instrument_id,
            policy.funding_policy.valuation_price_kind,
            OnlyTimestamp.from_datetime(fact.funding_time).unix_nanos,
        )
        valuation = self._reference_prices_by_boundary.get(boundary)
        if valuation is None:
            raise ValueError("FUNDING_REFERENCE_PRICE_MISSING")
        plan = self._pending_economic_fact_applications.get(fact.fact_id)
        if plan is None:
            plan = self._plan_funding_application(fact, valuation, policy.funding_policy)
            self._pending_economic_fact_applications[fact.fact_id] = plan
        elif plan.source_fact_json != fact.to_json() or plan.application_kind != "FUNDING":
            raise ValueError("ECONOMIC_FACT_APPLICATION_ID_CONFLICT")
        self._apply_economic_fact_plan(plan)
        self._funding_rate_facts[fact.fact_id] = fact
        self._pending_economic_fact_applications.pop(fact.fact_id, None)

    def _plan_funding_application(
        self,
        fact: OnlyFundingRateFact,
        valuation: OnlyReferencePriceFact,
        funding_policy: OnlyCompiledFundingPolicy,
    ) -> _OnlyEconomicFactApplicationPlan:
        positions = tuple(
            item
            for item in self._services.position_manager.list_by_account(self.config.default_account_id)  # type: ignore[arg-type]
            if item.key.instrument_id == fact.instrument_id and item.total_quantity.value > 0
        )
        instrument = self._instruments[fact.instrument_id]
        account_cashflows: list[OnlyAccountEconomicCashflow] = []
        strategy_cashflows: list[_OnlyStrategyEconomicCashflowApplication] = []
        for position in positions:
            cashflow = only_derive_funding_cashflow(
                runtime_id=self.config.runtime_id,  # type: ignore[arg-type]
                account_id=position.key.account_id,
                position=position,
                funding=fact,
                valuation=valuation,
                multiplier=instrument.contract_multiplier,
                currency=instrument.settlement_currency,
                policy=funding_policy,
            )
            account_cashflows.append(cashflow)
            allocations = tuple(
                item
                for item in self._services.allocation_manager.list_by_instrument(fact.instrument_id)
                if item.key.account_id == position.key.account_id
                and item.key.position_side == position.key.position_side
                and item.total_quantity.value > 0
            )
            allocated = sum((item.total_quantity.value for item in allocations), Decimal(0))
            if allocated != position.total_quantity.value:
                raise ValueError("FUNDING_ALLOCATION_AUTHORITY_INCOMPLETE")
            remaining = cashflow.amount.amount
            quantum = Decimal(1).scaleb(-cashflow.amount.currency.precision)
            for index, allocation in enumerate(allocations):
                amount = (
                    remaining
                    if index == len(allocations) - 1
                    else (
                        cashflow.amount.amount * allocation.total_quantity.value / position.total_quantity.value
                    ).quantize(quantum)
                )
                remaining -= amount
                key = self._services.strategy_ledger_manager.require_key(
                    runtime_id=self.config.runtime_id,  # type: ignore[arg-type]
                    account_id=allocation.key.account_id,
                    cluster_id=allocation.key.cluster_id,
                    currency=cashflow.amount.currency,
                )
                strategy_cashflows.append(
                    _OnlyStrategyEconomicCashflowApplication(
                        key,
                        _strategy_economic_cashflow_id(cashflow.cashflow_id, allocation.key.cluster_id),
                        OnlyMoney(amount, cashflow.amount.currency),
                        OnlyStrategyCashEntryType.FUNDING,
                        cashflow.timestamp,
                    )
                )
        plan = _OnlyEconomicFactApplicationPlan(
            fact.fact_id,
            fact.to_json(),
            "FUNDING",
            (),
            tuple(account_cashflows),
            tuple(strategy_cashflows),
        )
        self._validate_economic_fact_plan(plan)
        return plan

    def _plan_settlement_application(
        self,
        fact: OnlyReferencePriceFact,
    ) -> _OnlyEconomicFactApplicationPlan:
        instrument = self._instruments[fact.instrument_id]
        timestamp = OnlyTimestamp.from_datetime(fact.ts_event)
        pnl_model = OnlyLinearPnLModel()
        positions = tuple(
            sorted(
                (
                    item
                    for item in self._services.position_manager.list_by_account(self.config.default_account_id)  # type: ignore[arg-type]
                    if item.key.instrument_id == fact.instrument_id and item.total_quantity.value > 0
                ),
                key=lambda item: str(item.position_id),
            )
        )
        settlements: list[OnlyPositionSettlementFact] = []
        account_cashflows: list[OnlyAccountEconomicCashflow] = []
        strategy_cashflows: list[_OnlyStrategyEconomicCashflowApplication] = []
        for position in positions:
            if position.average_open_price is None:
                raise ValueError("POSITION_SETTLEMENT_COST_BASIS_MISSING")
            settlement = OnlyPositionSettlementFact(
                position.key,
                fact,
                instrument.contract_multiplier,
                instrument.settlement_currency,
            )
            realized = pnl_model.realized(
                position.position_side,
                position.average_open_price,
                fact.value,
                position.total_quantity,
                instrument.contract_multiplier,
                instrument.settlement_currency,
            )
            allocations = tuple(
                sorted(
                    (
                        item
                        for item in self._services.allocation_manager.list_by_instrument(fact.instrument_id)
                        if item.key.account_id == position.key.account_id
                        and item.key.position_side == position.key.position_side
                        and item.total_quantity.value > 0
                    ),
                    key=lambda item: str(item.allocation_id),
                )
            )
            allocated_quantity = sum((item.total_quantity.value for item in allocations), Decimal(0))
            if allocated_quantity != position.total_quantity.value:
                raise ValueError("SETTLEMENT_ALLOCATION_AUTHORITY_INCOMPLETE")
            allocation_cashflows: list[tuple[OnlyPositionAllocationSnapshot, OnlyMoney]] = []
            for allocation in allocations:
                if allocation.average_open_price is None:
                    raise ValueError("ALLOCATION_SETTLEMENT_COST_BASIS_MISSING")
                allocation_cashflows.append(
                    (
                        allocation,
                        pnl_model.realized(
                            allocation.key.position_side,
                            allocation.average_open_price,
                            fact.value,
                            allocation.total_quantity,
                            instrument.contract_multiplier,
                            instrument.settlement_currency,
                        ),
                    )
                )
            if sum((item.amount for _allocation, item in allocation_cashflows), Decimal(0)) != realized.amount:
                raise ValueError("SETTLEMENT_ALLOCATION_PNL_DIVERGENCE")
            account_cashflow = OnlyAccountEconomicCashflow(
                f"SETTLE-{fact.fact_id}-{position.position_id}",
                self.config.runtime_id,  # type: ignore[arg-type]
                position.key.account_id,
                OnlyAccountEconomicCashflowType.VARIATION_MARGIN,
                realized,
                timestamp,
                fact.fact_id,
                str(fact.instrument_id),
            )
            settlements.append(settlement)
            account_cashflows.append(account_cashflow)
            for allocation, allocation_realized in allocation_cashflows:
                key = self._services.strategy_ledger_manager.require_key(
                    runtime_id=self.config.runtime_id,  # type: ignore[arg-type]
                    account_id=allocation.key.account_id,
                    cluster_id=allocation.key.cluster_id,
                    currency=allocation_realized.currency,
                )
                strategy_cashflows.append(
                    _OnlyStrategyEconomicCashflowApplication(
                        key,
                        _strategy_economic_cashflow_id(account_cashflow.cashflow_id, allocation.key.cluster_id),
                        allocation_realized,
                        OnlyStrategyCashEntryType.VARIATION_MARGIN,
                        timestamp,
                    )
                )
        plan = _OnlyEconomicFactApplicationPlan(
            fact.fact_id,
            fact.to_json(),
            "SETTLEMENT",
            tuple(settlements),
            tuple(account_cashflows),
            tuple(strategy_cashflows),
        )
        self._validate_economic_fact_plan(plan)
        return plan

    def _validate_economic_fact_plan(self, plan: _OnlyEconomicFactApplicationPlan) -> None:
        account_balances: dict[OnlyAccountId, Decimal] = {}
        for cashflow in plan.account_cashflows:
            snapshot = self._services.account_manager.require_snapshot(cashflow.account_id)
            if cashflow.amount.currency != snapshot.cash.ledger_cash.currency:
                raise ValueError("ACCOUNT_ECONOMIC_CASHFLOW_CURRENCY_CONFLICT")
            balance = account_balances.get(cashflow.account_id, snapshot.cash.ledger_cash.amount)
            balance += cashflow.amount.amount
            if balance < 0:
                raise ValueError("ACCOUNT_ECONOMIC_CASHFLOW_INSUFFICIENT_COLLATERAL")
            account_balances[cashflow.account_id] = balance
        strategy_balances: dict[OnlyStrategyLedgerKey, Decimal] = {}
        for application in plan.strategy_cashflows:
            ledger_snapshot = self._services.strategy_ledger_manager.require_snapshot(application.key)
            balance = strategy_balances.get(application.key, ledger_snapshot.cash.ledger_cash.amount)
            balance += application.amount.amount
            if balance < 0:
                raise ValueError("STRATEGY_ECONOMIC_CASHFLOW_INSUFFICIENT_COLLATERAL")
            strategy_balances[application.key] = balance

    def _apply_economic_fact_plan(self, plan: _OnlyEconomicFactApplicationPlan) -> None:
        for settlement in plan.settlements:
            self._services.position_manager.apply_settlement(settlement)
            self._services.allocation_manager.apply_settlement(settlement)
        for cashflow in plan.account_cashflows:
            self._services.account_manager.apply_economic_cashflow(cashflow)
        for application in plan.strategy_cashflows:
            self._services.strategy_ledger_manager.apply_economic_cashflow(
                application.key,
                application.cashflow_id,
                application.amount,
                application.entry_type,
                application.timestamp,
            )

    def _valuation_price(
        self,
        instrument_id: OnlyInstrumentId,
        trading_day: OnlyTradingDay,
        timestamp: OnlyTimestamp,
        bar: OnlyBar | None = None,
    ) -> tuple[OnlyPrice, str]:
        engine = self.config.market_rule_engine
        if engine is None:
            raise ValueError("MARKET_RULE_ENGINE_REQUIRED")
        policy = engine.compiled_rules(str(instrument_id), trading_day, as_of=timestamp.to_datetime())
        if policy.economic_model is OnlyEconomicModel.MARGINED_DERIVATIVE:
            if policy.valuation_policy is None:
                raise ValueError("DERIVATIVE_VALUATION_POLICY_MISSING")
            kind = policy.valuation_policy.unrealized_price_kind
            reference_candidates = tuple(
                item
                for (candidate_instrument, candidate_kind, event_ns), item in self._reference_prices_by_boundary.items()
                if candidate_instrument == instrument_id and candidate_kind is kind and event_ns <= timestamp.unix_nanos
            )
            if not reference_candidates:
                raise ValueError(f"REQUIRED_{kind.value}_PRICE_MISSING")
            fact = max(
                reference_candidates,
                key=lambda item: (
                    OnlyTimestamp.from_datetime(item.ts_event).unix_nanos,
                    item.revision,
                    item.source_sequence,
                    item.fact_id,
                ),
            )
            return fact.value, f"REFERENCE_PRICE:{kind.value}:{fact.fact_id}"
        if bar is not None and bar.instrument_id == instrument_id:
            return bar.close, "MARKET_DATA_SNAPSHOT"
        bar_candidates = tuple(
            cached
            for registration in self._subscriptions.values()
            for bar_type in registration.subscription.bar_types
            if bar_type.instrument_id == instrument_id
            if (cached := self._services.market_data_cache.latest_closed(bar_type)) is not None
        )
        if not bar_candidates:
            raise ValueError("CASH_EXCHANGE_CLOSED_BAR_MISSING")
        return max(bar_candidates, key=lambda item: item.ts_event).close, "MARKET_DATA_SNAPSHOT"

    def _apply_strategy_valuation(
        self,
        key: OnlyStrategyLedgerKey,
        trade: OnlyPositionTrade,
    ) -> None:
        allocations = self._services.allocation_manager.list_by_cluster(key.cluster_id)
        marks: tuple[OnlyStrategyMarkPrice, ...] = ()
        trading_day = self._selected_calendar.trading_day_at(trade.ts_event)
        version = self._valuation_versions.get(key, 0) + 1
        if allocations:
            price, source = self._valuation_price(trade.instrument_id, trading_day, trade.ts_event)
            marks = (OnlyStrategyMarkPrice(trade.instrument_id, price, version, source),)
        self._valuation_versions[key] = version
        valuation = self._services.strategy_valuation_service.value(
            key,
            allocations,
            marks,
            {trade.instrument_id: trade.multiplier},
            trade.ts_event,
            trade.ts_init,
            version,
            {
                allocation.key.instrument_id: self._settles_notional(
                    allocation.key.instrument_id,
                    trading_day,
                )
                for allocation in allocations
            },
        )
        self._services.strategy_ledger_manager.apply_valuation(valuation, trading_day)

    def _apply_account_valuation(self, trade: OnlyPositionTrade) -> None:
        market_value = Decimal(0)
        unrealized = Decimal(0)
        for position in self._services.position_manager.list_by_account(trade.account_id):
            instrument = self._instruments[position.key.instrument_id]
            if position.average_open_price is None:
                raise ValueError("Account valuation requires cost basis for every open Position")
            trading_day = self._selected_calendar.trading_day_at(trade.ts_event)
            mark, _source = self._valuation_price(position.key.instrument_id, trading_day, trade.ts_event)
            position_valuation = self._position_valuation_service.value(
                position,
                mark,
                instrument.contract_multiplier,
                instrument.settlement_currency,
                trade.ts_event,
                price_source=_source,
                settles_notional=self._settles_notional(position.key.instrument_id, trading_day),
            )
            unrealized += position_valuation.unrealized_pnl.amount
            market_value += position_valuation.market_value.amount
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
        self._capture_execution_valuation_state(trade.account_id)

    def _apply_market_valuations(self, bar: OnlyBar, trading_day: OnlyTradingDay) -> None:
        """Mark Runtime-owned account and strategy views before Broker reconciliation and strategy callbacks."""

        timestamp = OnlyTimestamp.from_datetime(bar.ts_event)
        self._apply_market_valuations_at(timestamp, trading_day, bar)

    def _apply_market_valuations_at(
        self,
        timestamp: OnlyTimestamp,
        trading_day: OnlyTradingDay,
        bar: OnlyBar | None = None,
    ) -> None:
        for ledger in self._services.strategy_ledger_manager.list_ledgers():
            allocations = self._services.allocation_manager.list_by_cluster(ledger.key.cluster_id)
            marks: list[OnlyStrategyMarkPrice] = []
            multipliers: dict[OnlyInstrumentId, OnlyMultiplier] = {}
            next_version = self._valuation_versions.get(ledger.key, 0) + 1
            for allocation in allocations:
                instrument = self._instruments[allocation.key.instrument_id]
                mark, source = self._valuation_price(allocation.key.instrument_id, trading_day, timestamp, bar)
                marks.append(
                    OnlyStrategyMarkPrice(
                        allocation.key.instrument_id,
                        mark,
                        next_version,
                        source,
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
                {
                    allocation.key.instrument_id: self._settles_notional(
                        allocation.key.instrument_id,
                        trading_day,
                    )
                    for allocation in allocations
                },
            )
            self._services.strategy_ledger_manager.apply_valuation(valuation, trading_day)

        market_value = Decimal(0)
        unrealized = Decimal(0)
        for position in self._services.position_manager.list_by_account(self.config.default_account_id):  # type: ignore[arg-type]
            instrument = self._instruments[position.key.instrument_id]
            if position.average_open_price is None:
                raise ValueError("Account mark-to-market requires cost basis for every Position")
            mark, source = self._valuation_price(position.key.instrument_id, trading_day, timestamp, bar)
            position_valuation = self._position_valuation_service.value(
                position,
                mark,
                instrument.contract_multiplier,
                instrument.settlement_currency,
                timestamp,
                price_source=source,
                settles_notional=self._settles_notional(position.key.instrument_id, trading_day),
            )
            unrealized += position_valuation.unrealized_pnl.amount
            market_value += position_valuation.market_value.amount
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
        self._capture_execution_valuation_state(self.config.default_account_id)  # type: ignore[arg-type]

    def _settles_notional(self, instrument_id: OnlyInstrumentId, trading_day: OnlyTradingDay) -> bool:
        engine = self.config.market_rule_engine
        return (
            engine is None
            or engine.compiled_rules(str(instrument_id), trading_day).economic_model is OnlyEconomicModel.CASH_EXCHANGE
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
            engine_id=self.config.engine_id,  # type: ignore[arg-type]
            runtime_id=OnlyRuntimeId(str(self.config.runtime_id)),
            cluster_id=cluster_id,
            clock=OnlyClockView(self._services.clock),
            market_data=OnlyMarketDataView(allowed_bar_types, latest, history, current_snapshot),
            instruments=OnlyInstrumentView(self._instruments),
            subscriptions=OnlySubscriptionService(lambda subscription: self._subscribe(cluster_id, subscription)),
            timers=OnlyTimerService(
                lambda timer_id, when_ns: self._schedule_at(cluster_id, timer_id, when_ns),
                lambda timer_id, delay_ns: self._schedule_after(cluster_id, timer_id, delay_ns),
                lambda timer_id, interval_ns, start_ns: self._schedule_every(
                    cluster_id, timer_id, interval_ns, start_ns
                ),
                lambda timer_id: self._cancel_timer(cluster_id, timer_id),
            ),
            orders=OnlyOrderServiceView(
                cluster_id,
                self.config.default_account_id,  # type: ignore[arg-type]
                self._services.order_service,
                self._services.order_query,
                lambda: self._order_commands_enabled(cluster_id),
                self._begin_direct_execution_events,
                self._complete_direct_execution_events,
                self._intercept_order_submit,
            ),
            positions=OnlyPositionContextView(
                self.config.default_account_id,  # type: ignore[arg-type]
                cluster_id,
                self._services.position_query,
            ),
            accounts=OnlyAccountQueryView(
                self.config.default_account_id,  # type: ignore[arg-type]
                self._services.account_query,
            ),
            ledger=OnlyStrategyLedgerContextView(
                self._strategy_ledger_locator.require_key(
                    runtime_id=self.config.runtime_id,  # type: ignore[arg-type]
                    account_id=self.config.default_account_id,  # type: ignore[arg-type]
                    cluster_id=cluster_id,
                    currency=self.config.strategy_base_currency,
                ),
                self._services.strategy_ledger_query,
            ),
            risk=OnlyRiskSnapshotView(lambda: self._services.risk_service.get_snapshot(cluster_id)),
            logger=OnlyRuntimeLogger(_LOGGER, self.config.runtime_id, cluster_id),  # type: ignore[arg-type]
        )

    def _order_commands_enabled(self, cluster_id: OnlyClusterId) -> bool:
        return self._state in {OnlyRuntimeState.RECOVERING, OnlyRuntimeState.READY, OnlyRuntimeState.RUNNING} and (
            self._services.cluster_manager.state_of(cluster_id)
            in {OnlyClusterState.RECOVERING, OnlyClusterState.STARTING, OnlyClusterState.RUNNING}
        )

    def _intercept_order_submit(self, request: OnlyOrderRequest) -> OnlyOrderSubmitResult | None:
        del request
        return None

    def _begin_direct_execution_events(self) -> None:
        self._services.execution_event_buffer.begin()

    def _complete_direct_execution_events(self, succeeded: bool) -> None:
        if not succeeded:
            self._services.execution_event_buffer.abort()
            return
        self._flush_direct_execution_events()

    def _flush_direct_execution_events(self) -> None:
        batch = self._services.execution_event_buffer.seal()
        intent = (
            OnlyExecutionEventDeliveryIntent(OnlyExecutionEventDeliveryMode.NONE)
            if batch.empty
            else OnlyExecutionEventDeliveryIntent(OnlyExecutionEventDeliveryMode.DIRECT, direct_batch=batch)
        )
        delivery = self._services.execution_delivery_coordinator.deliver(
            self.config.runtime_id,  # type: ignore[arg-type]
            intent,
        )
        self._record_execution_delivery(None, delivery)

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
            OnlyClusterState.RECOVERING,
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

    def restore_execution_valuation_version(self, version: int) -> None:
        """Restore the committed Runtime valuation sequence without running valuation."""

        if version < self._account_valuation_version:
            raise ValueError("Runtime valuation version cannot regress")
        ledgers = self._strategy_ledger_manager.list_ledgers()
        for ledger in ledgers:
            current = self._valuation_versions.get(ledger.key, 0)
            if version < current:
                raise ValueError("Runtime Strategy valuation version cannot regress")
        self._account_valuation_version = version
        for ledger in ledgers:
            self._valuation_versions[ledger.key] = version

    @property
    def execution_valuation_version(self) -> int:
        return self._account_valuation_version


def _execution_bootstrap_account_snapshot(
    state: OnlyAccountExecutionState, current: OnlyAccountSnapshot
) -> OnlyAccountSnapshot:
    return OnlyAccountSnapshot(
        state.runtime_id,
        state.account_id,
        state.gateway_id,
        state.account_type,
        state.base_currency,
        state.status,
        OnlyAccountCashBalance(
            state.ledger_cash,
            state.trade_available_cash,
            state.withdrawable_cash,
            state.order_reserved_cash,
            state.unsettled_receivable_cash,
        ),
        state.position_market_value,
        state.realized_pnl,
        state.unrealized_pnl,
        state.fees,
        state.equity,
        current.reservations,
        state.created_at,
        state.updated_at,
        state.valuation_time,
        state.version,
        state.last_external_sequence,
        state.quality_flags,
        state.metadata,
        state.reserved_margin,
        state.occupied_margin,
        state.released_margin,
        state.available_margin,
    )


def _execution_bootstrap_rate(value: Decimal) -> OnlyRate:
    return OnlyRate(value.quantize(Decimal("0.00000001")), 8)


def _strategy_economic_cashflow_id(
    account_cashflow_id: str,
    cluster_id: OnlyClusterId,
) -> OnlyStrategyCashFlowId:
    fingerprint = only_canonical_fingerprint((account_cashflow_id, str(cluster_id)))
    return OnlyStrategyCashFlowId(f"ECONOMIC-{fingerprint}")


def _economic_fact_application_stable_order(
    plan: _OnlyEconomicFactApplicationPlan,
) -> tuple[datetime, int, int, str]:
    if plan.application_kind == "SETTLEMENT":
        return OnlyReferencePriceFact.from_json(plan.source_fact_json).stable_order
    if plan.application_kind == "FUNDING":
        return OnlyFundingRateFact.from_json(plan.source_fact_json).stable_order
    raise ValueError("ECONOMIC_FACT_APPLICATION_KIND_UNSUPPORTED")


def _execution_bootstrap_ledger_snapshot(
    state: OnlyStrategyLedgerExecutionState,
    current: OnlyStrategyLedgerSnapshot,
) -> OnlyStrategyLedgerSnapshot:
    net = state.realized_pnl + state.unrealized_pnl - state.fees
    high = OnlyMoney(max(current.equity.high_water_mark.amount, state.equity.amount), state.key.base_currency)
    drawdown = _execution_bootstrap_rate(
        Decimal(0) if high.amount == 0 else state.equity.amount / high.amount - Decimal(1)
    )
    maximum = _execution_bootstrap_rate(min(current.equity.maximum_drawdown.value, drawdown.value))
    simple = (
        None
        if state.initial_capital.amount == 0 or state.external_cash_flow.amount != 0
        else _execution_bootstrap_rate(
            (state.equity.amount - state.initial_capital.amount) / state.initial_capital.amount
        )
    )
    daily_pnl = state.equity - current.equity.equity + current.equity.daily_pnl
    cash = OnlyStrategyCashSnapshot(state.ledger_cash, state.cash_reserved, state.cash_available)
    pnl = OnlyStrategyPnLSnapshot(state.realized_pnl, state.unrealized_pnl, state.fees, net)
    equity = replace(
        current.equity,
        ts_event=state.updated_at,
        ts_init=state.updated_at,
        trading_day=state.trading_day,
        version=state.version,
        initial_capital=state.initial_capital,
        external_cash_flow=state.external_cash_flow,
        ledger_cash=state.ledger_cash,
        cash_reserved=state.cash_reserved,
        cash_available=state.cash_available,
        position_cost=state.position_cost,
        position_market_value=state.position_market_value,
        realized_pnl=state.realized_pnl,
        unrealized_pnl=state.unrealized_pnl,
        fees=state.fees,
        net_pnl=net,
        equity=state.equity,
        equity_by_cash_view=state.ledger_cash + state.position_market_value,
        equity_by_pnl_view=state.initial_capital + state.external_cash_flow + net,
        high_water_mark=high,
        drawdown=drawdown,
        maximum_drawdown=maximum,
        return_since_start=simple,
        daily_pnl=daily_pnl,
        quality_flags=state.quality_flags,
    )
    performance = replace(
        current.performance,
        ts_event=state.updated_at,
        equity=state.equity,
        net_pnl=net,
        return_since_start=simple,
        daily_pnl=daily_pnl,
        drawdown=drawdown,
        maximum_drawdown=maximum,
        fees=state.fees,
    )
    return replace(
        current,
        status=state.status,
        capital=replace(
            current.capital,
            initial_capital=state.initial_capital,
            external_cash_flow=state.external_cash_flow,
            as_of=state.updated_at,
            version=state.version,
        ),
        cash=cash,
        pnl=pnl,
        equity=equity,
        performance=performance,
        cash_entries=state.cash_entries,
        fee_entries=state.fee_entries,
        created_at=state.created_at,
        updated_at=state.updated_at,
        valuation_time=state.valuation_time,
        version=state.version,
        last_trade_sequence=state.last_trade_sequence,
        last_trade_order=state.last_trade_order,
        quality_flags=state.quality_flags,
    )
