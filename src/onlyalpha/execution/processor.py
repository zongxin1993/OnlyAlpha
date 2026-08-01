"""Runtime-owned ordered business application of normalized Broker updates."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from decimal import Decimal
from enum import StrEnum

from onlyalpha.account.manager import OnlyAccountManager
from onlyalpha.account.models import OnlyAccountMutationResult, OnlyAccountSnapshot, OnlyAccountTradeCashFlow
from onlyalpha.account.reconciliation import OnlyAccountReconciliationService
from onlyalpha.broker.updates import (
    OnlyBrokerAccountUpdate,
    OnlyBrokerConnectionUpdate,
    OnlyBrokerInboundUpdate,
    OnlyBrokerOrderAcceptedUpdate,
    OnlyBrokerOrderCancelledUpdate,
    OnlyBrokerOrderExpiredUpdate,
    OnlyBrokerOrderRejectedUpdate,
    OnlyBrokerPositionUpdate,
    OnlyBrokerTradeUpdate,
)
from onlyalpha.core.clock import OnlyClock
from onlyalpha.domain.enums import OnlyDirection, OnlyOffset, OnlyOrderSide, OnlyOrderStatus
from onlyalpha.domain.execution import OnlyOrderFill, OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyOrderId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.event.model import OnlyEvent
from onlyalpha.fee.manager import OnlyFeeManager
from onlyalpha.fee.models import OnlyFeeInstruction
from onlyalpha.fee.resolver import OnlyFeeResolver
from onlyalpha.margin.manager import OnlyMarginManager
from onlyalpha.market.models import OnlyMarketPositionMode
from onlyalpha.market.runtime_rules import (
    OnlyTradeApplicationInstruction,
    OnlyTradeApplicationRequest,
    OnlyTradeInstructionPort,
)
from onlyalpha.order.enums import OnlyOrderApplyResult
from onlyalpha.order.execution.models import (
    OnlyGatewayOrderAcceptedUpdate,
    OnlyGatewayOrderCancelledUpdate,
    OnlyGatewayOrderExpiredUpdate,
    OnlyGatewayOrderFillUpdate,
    OnlyGatewayOrderRejectedUpdate,
    OnlyGatewayOrderUpdate,
)
from onlyalpha.order.execution.processor import OnlyOrderUpdateProcessor
from onlyalpha.order.query import OnlyOrderQueryService
from onlyalpha.order.results import OnlyOrderMutationResult
from onlyalpha.position.allocation_manager import OnlyPositionAllocationManager
from onlyalpha.position.enums import (
    OnlyPositionMode,
    OnlyPositionMutationStatus,
    OnlySettlementBucket,
)
from onlyalpha.position.identifiers import OnlyGatewayId
from onlyalpha.position.keys import OnlyPositionAllocationKey
from onlyalpha.position.manager import OnlyPositionManager
from onlyalpha.position.models import OnlyBrokerPositionSnapshot as OnlyLocalBrokerPositionSnapshot
from onlyalpha.position.models import (
    OnlyPositionAllocationSnapshot,
    OnlyPositionMutationResult,
    OnlyPositionTrade,
)
from onlyalpha.position.reconciliation import OnlyPositionReconciliationService
from onlyalpha.position.reservations import OnlyOrderPositionReservationAdapter, OnlyPositionReservationManager
from onlyalpha.risk.enums import OnlyRiskReleaseReason
from onlyalpha.risk.service import OnlyRiskService
from onlyalpha.settlement.manager import OnlySettlementManager
from onlyalpha.strategy_ledger.enums import OnlyStrategyFeeType
from onlyalpha.strategy_ledger.identifiers import OnlyStrategyFeeEntryId
from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey
from onlyalpha.strategy_ledger.locator import OnlyStrategyLedgerLocator
from onlyalpha.strategy_ledger.manager import OnlyStrategyLedgerManager
from onlyalpha.strategy_ledger.models import (
    OnlyStrategyFeeEntry,
    OnlyStrategyLedgerMutationResult,
    OnlyStrategyTradeAccountingInput,
)

from .capability import OnlyExecutionCapability, only_resolve_execution_capability
from .causal_recovery import (
    OnlyExecutionRecoveryDecision,
    OnlyExecutionRecoveryDecisionKind,
    OnlyExecutionRecoveryResolution,
    OnlyExecutionRecoverySession,
)
from .commit_coordinator import (
    OnlyExecutionCommitCoordinationStatus,
    OnlyExecutionCommitCoordinator,
)
from .committed import OnlyCommittedExecutionFact
from .delivery import (
    OnlyExecutionEventDeliveryIntent,
    OnlyExecutionEventDeliveryMode,
)
from .enums import (
    OnlyExecutionFailureCode,
    OnlyExecutionMutationStatus,
    OnlyExecutionMutationStep,
    OnlyExecutionOperationKind,
    OnlyExecutionProcessingStatus,
)
from .event_buffer import OnlyExecutionEventBatch, OnlyExecutionEventBuffer
from .fill_identity import (
    only_execution_fill_identity_from_update,
    only_execution_fill_payload_fingerprint,
)
from .invariants import OnlyExecutionInvariantChecker
from .models import (
    OnlyExecutionAuditRecord,
    OnlyExecutionFailure,
    OnlyExecutionInvariantResult,
    OnlyExecutionMutationBundle,
    OnlyExecutionMutationRecord,
    OnlyExecutionProcessingContext,
    OnlyExecutionProcessingResult,
    OnlyExecutionProcessorConfig,
    OnlyExecutionReconciliationRequest,
    OnlyExecutionSnapshotBundle,
)
from .persistence_ports import OnlyExecutionTransactionQueryPort
from .planning_context import OnlyTerminalExecutionPlanningContext, OnlyTradeExecutionPlanningContext
from .planning_results import OnlyTradeExecutionPlanningError
from .projection import OnlyExecutionProjectionComponent
from .scope import OnlyExecutionPositionScope, OnlyExecutionPositionScopeResolver
from .state import (
    OnlyExecutionAuditStore,
    OnlyExecutionReconciliationPort,
    OnlyExecutionSequenceTracker,
    OnlyExecutionUpdateDeduplicator,
)
from .terminal_fact import OnlyCommittedTerminalExecutionFact
from .terminal_identity import (
    OnlyBrokerOrderTerminalUpdate,
    only_capture_execution_terminal_authority,
)
from .terminal_planner import OnlyTerminalExecutionTransactionPlanner
from .trade_planner import OnlyTradeExecutionTransactionPlanner
from .transaction import OnlyPreparedExecutionTransaction

OnlyExecutionValuation = Callable[[OnlyStrategyLedgerKey, OnlyPositionTrade], None]
OnlyAccountValuation = Callable[[OnlyPositionTrade], None]
OnlyAccountReservationConsumer = Callable[[OnlyOrderFill, OnlyMoney, OnlyTimestamp], None]
OnlyAccountReservationReleaser = Callable[[OnlyOrderId, OnlyTimestamp], None]
OnlyConnectionStateConsumer = Callable[[object], None]
OnlyMarginReservationReleaser = Callable[[OnlyOrderId, OnlyTimestamp], None]
OnlyTradePlanningContextBuilder = Callable[
    [OnlyBrokerTradeUpdate, int, OnlyExecutionPositionScope],
    OnlyTradeExecutionPlanningContext,
]
OnlyTerminalPlanningContextBuilder = Callable[
    [OnlyBrokerOrderTerminalUpdate, int, OnlyExecutionPositionScope],
    OnlyTerminalExecutionPlanningContext,
]
OnlyExecutionDispatchPayload = tuple[
    OnlyExecutionProcessingStatus,
    OnlyOrderMutationResult | None,
    OnlyPositionMutationResult | None,
    OnlyPositionMutationStatus | None,
    OnlyStrategyLedgerMutationResult | None,
    OnlyExecutionInvariantResult,
    OnlyAccountMutationResult | None,
    tuple[str, ...],
]


class OnlyExecutionProcessingMode(StrEnum):
    NORMAL = "NORMAL"
    RECOVERY = "RECOVERY"


class OnlyExecutionProcessor:
    """Single public business entry for every Broker update owned by one Runtime."""

    def __init__(
        self,
        config: OnlyExecutionProcessorConfig,
        clock: OnlyClock,
        instruments: Mapping[OnlyInstrumentId, OnlyInstrument],
        orders: OnlyOrderQueryService,
        order_updates: OnlyOrderUpdateProcessor,
        positions: OnlyPositionManager,
        allocations: OnlyPositionAllocationManager,
        ledgers: OnlyStrategyLedgerManager,
        ledger_locator: OnlyStrategyLedgerLocator,
        accounts: OnlyAccountManager,
        risk: OnlyRiskService,
        position_reservations: OnlyPositionReservationManager,
        position_reservation_port: OnlyOrderPositionReservationAdapter,
        consume_account_reservation: OnlyAccountReservationConsumer,
        release_account_reservation: OnlyAccountReservationReleaser,
        position_reconciliation: OnlyPositionReconciliationService,
        account_reconciliation: OnlyAccountReconciliationService,
        invariant_checker: OnlyExecutionInvariantChecker,
        event_buffer: OnlyExecutionEventBuffer,
        audit_store: OnlyExecutionAuditStore,
        trade_planning_context_builder: OnlyTradePlanningContextBuilder,
        trade_planner: OnlyTradeExecutionTransactionPlanner,
        terminal_planning_context_builder: OnlyTerminalPlanningContextBuilder,
        terminal_planner: OnlyTerminalExecutionTransactionPlanner,
        execution_commit_coordinator: OnlyExecutionCommitCoordinator,
        execution_transaction_query: OnlyExecutionTransactionQueryPort,
        reconciliation: OnlyExecutionReconciliationPort,
        deduplicator: OnlyExecutionUpdateDeduplicator,
        sequence_tracker: OnlyExecutionSequenceTracker,
        strategy_valuation: OnlyExecutionValuation,
        account_valuation: OnlyAccountValuation,
        connection_state: OnlyConnectionStateConsumer,
        base_currency: OnlyCurrency,
        market_rules: OnlyTradeInstructionPort | None = None,
        settlement_manager: OnlySettlementManager | None = None,
        margin_manager: OnlyMarginManager | None = None,
        fee_manager: OnlyFeeManager | None = None,
        fee_resolver: OnlyFeeResolver | None = None,
        release_margin_reservation: OnlyMarginReservationReleaser | None = None,
        trading_day: Callable[[OnlyTimestamp], OnlyTradingDay] | None = None,
    ) -> None:
        self.config = config
        self._clock = clock
        self._instruments = instruments
        self._orders = orders
        self._order_updates = order_updates
        self._positions = positions
        self._allocations = allocations
        self._ledgers = ledgers
        self._ledger_locator = ledger_locator
        self._accounts = accounts
        self._risk = risk
        self._position_reservations = position_reservations
        self._position_reservation_port = position_reservation_port
        self._consume_account_reservation = consume_account_reservation
        self._release_account_reservation = release_account_reservation
        self._position_reconciliation = position_reconciliation
        self._account_reconciliation = account_reconciliation
        self._invariants = invariant_checker
        self._events = event_buffer
        self._audit = audit_store
        self._trade_planning_context_builder = trade_planning_context_builder
        self._trade_planner = trade_planner
        self._terminal_planning_context_builder = terminal_planning_context_builder
        self._terminal_planner = terminal_planner
        self._execution_commit_coordinator = execution_commit_coordinator
        self._execution_transaction_query = execution_transaction_query
        self._reconciliation = reconciliation
        self._deduplicator = deduplicator
        self._sequences = sequence_tracker
        self._strategy_valuation = strategy_valuation
        self._account_valuation = account_valuation
        self._connection_state = connection_state
        self._base_currency = base_currency
        self._market_rules = market_rules
        self._settlement_manager = settlement_manager
        self._margin_manager = margin_manager
        self._fee_manager = fee_manager
        self._fee_resolver = fee_resolver
        self._release_margin_reservation = release_margin_reservation
        self._trading_day = trading_day
        self._trade_instructions: dict[str, OnlyTradeApplicationInstruction] = {}
        self._position_scope_resolver = OnlyExecutionPositionScopeResolver(config.runtime_id)
        self._processing_sequence = 0

    def capture_checkpoint(self) -> object:
        return {"processing_sequence": self._processing_sequence}

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise ValueError("Execution Processor checkpoint must be an object")
        self.restore_processing_sequence(int(payload["processing_sequence"]))

    def restore_processing_sequence(self, sequence: int) -> None:
        if sequence < self._processing_sequence:
            raise ValueError("Execution processing sequence cannot regress")
        self._processing_sequence = sequence

    def process(self, update: OnlyBrokerInboundUpdate) -> OnlyExecutionProcessingResult:
        return self._process(update, OnlyExecutionProcessingMode.NORMAL, None)

    def replay(
        self,
        update: OnlyBrokerInboundUpdate,
        session: OnlyExecutionRecoverySession,
    ) -> OnlyExecutionProcessingResult:
        result = self._process(update, OnlyExecutionProcessingMode.RECOVERY, session)
        return replace(
            result,
            delivery_intent=OnlyExecutionEventDeliveryIntent(OnlyExecutionEventDeliveryMode.NONE),
        )

    def replay_non_transaction(self, update: OnlyBrokerInboundUpdate) -> OnlyExecutionProcessingResult:
        """Normalize a bootstrap/recovery non-transaction Update without external delivery."""

        if isinstance(
            update,
            OnlyBrokerTradeUpdate
            | OnlyBrokerOrderCancelledUpdate
            | OnlyBrokerOrderRejectedUpdate
            | OnlyBrokerOrderExpiredUpdate,
        ):
            raise ValueError("replay_non_transaction does not accept durable execution updates")
        result = self._process(update, OnlyExecutionProcessingMode.RECOVERY, None)
        return replace(
            result,
            delivery_intent=OnlyExecutionEventDeliveryIntent(OnlyExecutionEventDeliveryMode.NONE),
        )

    def _process(
        self,
        update: OnlyBrokerInboundUpdate,
        mode: OnlyExecutionProcessingMode,
        recovery_session: OnlyExecutionRecoverySession | None,
    ) -> OnlyExecutionProcessingResult:
        self._processing_sequence += 1
        started = OnlyTimestamp.from_unix_nanos(self._clock.timestamp_ns())
        context = OnlyExecutionProcessingContext(
            self.config.runtime_id,
            update.gateway_id,
            update.account_id,
            update.update_id,
            update.source_sequence,
            self._processing_sequence,
            started,
        )
        validation = self._validate(update, context)
        if validation is not None:
            return self._terminal(update, context, OnlyExecutionProcessingStatus.REJECTED, failure=validation)
        position_scope = self._resolve_position_scope(update)
        if isinstance(update, OnlyBrokerTradeUpdate) and mode is OnlyExecutionProcessingMode.NORMAL:
            fill_identity = only_execution_fill_identity_from_update(update)
            fill_fingerprint = only_execution_fill_payload_fingerprint(update)
            existing_fill = self._execution_transaction_query.get_by_fill_identity(update.runtime_id, fill_identity)
            if existing_fill is not None:
                existing_fill_fact = existing_fill.fact
                if not isinstance(existing_fill_fact, OnlyCommittedExecutionFact):
                    failure = OnlyExecutionFailure(
                        OnlyExecutionFailureCode.INVALID_UPDATE,
                        "FILL_IDENTITY_CONFLICT: durable Fill identity resolved to a non-Trade operation",
                        OnlyExecutionMutationStep.VALIDATION,
                    )
                    return self._terminal(
                        update,
                        context,
                        OnlyExecutionProcessingStatus.REJECTED,
                        failure=failure,
                        position_scope=position_scope,
                    )
                if existing_fill_fact.fill_payload_fingerprint != fill_fingerprint:
                    failure = OnlyExecutionFailure(
                        OnlyExecutionFailureCode.INVALID_UPDATE,
                        "FILL_IDENTITY_CONFLICT: durable Fill identity has a different payload",
                        OnlyExecutionMutationStep.VALIDATION,
                    )
                    return self._terminal(
                        update,
                        context,
                        OnlyExecutionProcessingStatus.REJECTED,
                        failure=failure,
                        position_scope=position_scope,
                    )
                if existing_fill.projection_ready:
                    return self._terminal(
                        update,
                        context,
                        OnlyExecutionProcessingStatus.DUPLICATE,
                        position_scope=position_scope,
                    )
        if (
            isinstance(
                update,
                OnlyBrokerOrderCancelledUpdate | OnlyBrokerOrderRejectedUpdate | OnlyBrokerOrderExpiredUpdate,
            )
            and mode is OnlyExecutionProcessingMode.NORMAL
        ):
            terminal_authority = only_capture_execution_terminal_authority(update)
            existing_terminal = self._execution_transaction_query.get_by_terminal_identity(
                update.runtime_id,
                terminal_authority.terminal_identity,
            )
            if existing_terminal is not None:
                existing_fact = existing_terminal.fact
                if (
                    not isinstance(existing_fact, OnlyCommittedTerminalExecutionFact)
                    or existing_fact.terminal_payload_fingerprint != terminal_authority.payload_fingerprint
                ):
                    failure = OnlyExecutionFailure(
                        OnlyExecutionFailureCode.INVALID_UPDATE,
                        "TERMINAL_IDENTITY_CONFLICT: durable terminal identity has a different payload",
                        OnlyExecutionMutationStep.VALIDATION,
                    )
                    return self._terminal(
                        update,
                        context,
                        OnlyExecutionProcessingStatus.REJECTED,
                        failure=failure,
                        position_scope=position_scope,
                    )
                if existing_terminal.projection_ready:
                    return self._terminal(
                        update,
                        context,
                        OnlyExecutionProcessingStatus.DUPLICATE,
                        position_scope=position_scope,
                    )
        if self._deduplicator.contains_update(update.update_id):
            return self._terminal(
                update, context, OnlyExecutionProcessingStatus.DUPLICATE, position_scope=position_scope
            )
        trade_fingerprints = self._trade_fingerprints(update)
        if trade_fingerprints and self._deduplicator.contains_trade(trade_fingerprints):
            self._deduplicator.remember(update.update_id)
            return self._terminal(
                update, context, OnlyExecutionProcessingStatus.DUPLICATE, position_scope=position_scope
            )
        sequence_scope = self._sequence_scope(update)
        stale = self._sequences.is_stale(sequence_scope, update.source_sequence)
        if stale and isinstance(update, OnlyBrokerTradeUpdate):
            failure = OnlyExecutionFailure(
                OnlyExecutionFailureCode.OUT_OF_ORDER_TRADE,
                "out-of-order Trade cannot be safely applied",
                OnlyExecutionMutationStep.VALIDATION,
            )
            request = self._make_reconciliation(
                update, (), OnlyExecutionMutationStep.VALIDATION, failure.message, position_scope
            )
            self._deduplicator.remember(update.update_id, trade_fingerprints)
            self._reconciliation.request_reconciliation(request)
            return self._terminal(
                update,
                context,
                OnlyExecutionProcessingStatus.RECONCILIATION_REQUIRED,
                failure=failure,
                reconciliation=request,
                quality_flags=("OUT_OF_ORDER",),
                position_scope=position_scope,
            )
        if isinstance(update, OnlyBrokerTradeUpdate) and self._uses_prepared_trade_path(update, position_scope):
            if position_scope is None:
                failure = OnlyExecutionFailure(
                    OnlyExecutionFailureCode.INVALID_UPDATE,
                    "POSITION_SIDE_RESOLUTION_FAILED: Trade has no Position Scope",
                    OnlyExecutionMutationStep.VALIDATION,
                )
                return self._terminal(
                    update,
                    context,
                    OnlyExecutionProcessingStatus.REJECTED,
                    failure=failure,
                )
            return self._prepared_trade(
                update,
                context,
                position_scope,
                trade_fingerprints,
                sequence_scope,
                mode,
                recovery_session,
            )
        if isinstance(
            update,
            OnlyBrokerOrderCancelledUpdate | OnlyBrokerOrderRejectedUpdate | OnlyBrokerOrderExpiredUpdate,
        ) and self._uses_prepared_terminal_path(update, position_scope):
            if position_scope is None:
                raise AssertionError("Durable terminal capability lost its Position Scope")
            return self._prepared_terminal(
                update,
                context,
                position_scope,
                sequence_scope,
                mode,
                recovery_session,
            )
        self._events.begin()
        steps: list[OnlyExecutionMutationRecord] = [
            OnlyExecutionMutationRecord(
                OnlyExecutionMutationStep.VALIDATION, OnlyExecutionMutationStatus.APPLIED, "scope and plan valid"
            )
        ]
        batch: OnlyExecutionEventBatch | None = None
        try:
            payload = self._dispatch(update, stale, steps, position_scope)
            invariant = payload[5]
            if not invariant.passed:
                raise _OnlyExecutionInvariantError(invariant)
            steps.append(
                OnlyExecutionMutationRecord(
                    OnlyExecutionMutationStep.INVARIANT_CHECK,
                    OnlyExecutionMutationStatus.APPLIED,
                    "all invariants passed",
                )
            )
            status = payload[0]
            reconciliation = None
            if status is OnlyExecutionProcessingStatus.RECONCILIATION_REQUIRED:
                reconciliation = self._make_reconciliation(
                    update,
                    tuple(item.step for item in steps if item.status is OnlyExecutionMutationStatus.APPLIED),
                    OnlyExecutionMutationStep.INVARIANT_CHECK,
                    "Broker and local state require reconciliation",
                    position_scope,
                )
                self._reconciliation.request_reconciliation(reconciliation)
            self._deduplicator.remember(update.update_id, trade_fingerprints)
            self._sequences.observe(sequence_scope, update.source_sequence)
            event_type = (
                "EXECUTION_RECONCILIATION_REQUIRED" if reconciliation is not None else "EXECUTION_UPDATE_APPLIED"
            )
            applied_event = self._processing_event(update, context, event_type)
            self._events.add(applied_event)
            steps.append(
                OnlyExecutionMutationRecord(
                    OnlyExecutionMutationStep.EVENT, OnlyExecutionMutationStatus.APPLIED, "facts committed"
                )
            )
            batch = self._events.seal()
            generated = batch.events
            intent = self._direct_intent(batch)
            result = self._complete(
                update,
                context,
                status,
                steps,
                payload,
                generated,
                intent,
                invariant,
                reconciliation,
                position_scope,
            )
            return result
        except Exception as exc:
            if batch is None:
                self._events.abort()
            failed_step = self._failed_step(steps)
            steps.append(OnlyExecutionMutationRecord(failed_step, OnlyExecutionMutationStatus.FAILED, str(exc)))
            failure = OnlyExecutionFailure(
                OnlyExecutionFailureCode.INVARIANT_VIOLATION
                if isinstance(exc, _OnlyExecutionInvariantError)
                else OnlyExecutionFailureCode.DEPENDENCY_FAILURE,
                str(exc),
                failed_step,
                type(exc).__name__,
            )
            request = self._make_reconciliation(
                update,
                tuple(item.step for item in steps if item.status is OnlyExecutionMutationStatus.APPLIED),
                failed_step,
                failure.message,
                position_scope,
            )
            self._block_scope(update, position_scope)
            self._deduplicator.remember(update.update_id, trade_fingerprints)
            self._sequences.observe(sequence_scope, update.source_sequence)
            self._reconciliation.request_reconciliation(request)
            failure_events = (
                self._processing_event(update, context, "EXECUTION_PROCESSING_FAILED"),
                self._processing_event(update, context, "EXECUTION_RECONCILIATION_REQUIRED"),
            )
            return self._terminal(
                update,
                context,
                OnlyExecutionProcessingStatus.RECONCILIATION_REQUIRED,
                steps=tuple(steps),
                failure=failure,
                reconciliation=request,
                generated_events=failure_events,
                delivery_intent=OnlyExecutionEventDeliveryIntent(
                    OnlyExecutionEventDeliveryMode.DIRECT,
                    direct_batch=OnlyExecutionEventBatch(failure_events),
                ),
                invariant=exc.result if isinstance(exc, _OnlyExecutionInvariantError) else None,
                quality_flags=("PARTIAL_MUTATION",),
                position_scope=position_scope,
            )

    def _prepared_trade(
        self,
        update: OnlyBrokerTradeUpdate,
        context: OnlyExecutionProcessingContext,
        position_scope: OnlyExecutionPositionScope,
        trade_fingerprints: tuple[str, ...],
        sequence_scope: tuple[str, ...],
        mode: OnlyExecutionProcessingMode,
        recovery_session: OnlyExecutionRecoverySession | None,
    ) -> OnlyExecutionProcessingResult:
        steps = [
            OnlyExecutionMutationRecord(
                OnlyExecutionMutationStep.VALIDATION,
                OnlyExecutionMutationStatus.APPLIED,
                "Trade scope resolved for prepared transaction planning",
            )
        ]
        try:
            planning_context = self._trade_planning_context_builder(
                update,
                context.processing_sequence,
                position_scope,
            )
            prepared = self._trade_planner.prepare(planning_context)
        except OnlyTradeExecutionPlanningError as exc:
            failure = OnlyExecutionFailure(
                OnlyExecutionFailureCode.UNSUPPORTED_UPDATE_TYPE,
                f"{exc.code.value}: {exc}",
                OnlyExecutionMutationStep.VALIDATION,
                type(exc).__name__,
            )
            return self._terminal(
                update,
                context,
                OnlyExecutionProcessingStatus.REJECTED,
                steps=tuple(steps),
                failure=failure,
                quality_flags=("UNSUPPORTED_PREPARED_TRADE_SCOPE",),
                position_scope=position_scope,
            )
        except (KeyError, RuntimeError, TypeError, ValueError) as exc:
            failure = OnlyExecutionFailure(
                OnlyExecutionFailureCode.INVALID_UPDATE,
                f"{type(exc).__name__}: {exc}",
                OnlyExecutionMutationStep.VALIDATION,
                type(exc).__name__,
            )
            return self._terminal(
                update,
                context,
                OnlyExecutionProcessingStatus.REJECTED,
                steps=tuple(steps),
                failure=failure,
                position_scope=position_scope,
            )
        return self._coordinate_prepared_operation(
            update,
            context,
            position_scope,
            trade_fingerprints,
            sequence_scope,
            mode,
            recovery_session,
            prepared,
            planning_context.order_before.instrument_id,
            steps,
        )

    def _prepared_terminal(
        self,
        update: OnlyBrokerOrderTerminalUpdate,
        context: OnlyExecutionProcessingContext,
        position_scope: OnlyExecutionPositionScope,
        sequence_scope: tuple[str, ...],
        mode: OnlyExecutionProcessingMode,
        recovery_session: OnlyExecutionRecoverySession | None,
    ) -> OnlyExecutionProcessingResult:
        steps = [
            OnlyExecutionMutationRecord(
                OnlyExecutionMutationStep.VALIDATION,
                OnlyExecutionMutationStatus.APPLIED,
                "Long Close terminal scope resolved for prepared transaction planning",
            )
        ]
        try:
            planning_context = self._terminal_planning_context_builder(
                update,
                context.processing_sequence,
                position_scope,
            )
            prepared = self._terminal_planner.prepare(planning_context)
        except (KeyError, RuntimeError, TypeError, ValueError) as exc:
            failure = OnlyExecutionFailure(
                OnlyExecutionFailureCode.INVALID_UPDATE,
                f"{type(exc).__name__}: {exc}",
                OnlyExecutionMutationStep.VALIDATION,
                type(exc).__name__,
            )
            return self._terminal(
                update,
                context,
                OnlyExecutionProcessingStatus.REJECTED,
                steps=tuple(steps),
                failure=failure,
                quality_flags=("INVALID_DURABLE_TERMINAL_SCOPE",),
                position_scope=position_scope,
            )
        return self._coordinate_prepared_operation(
            update,
            context,
            position_scope,
            (),
            sequence_scope,
            mode,
            recovery_session,
            prepared,
            planning_context.order_before.instrument_id,
            steps,
        )

    def _coordinate_prepared_operation(
        self,
        update: OnlyBrokerInboundUpdate,
        context: OnlyExecutionProcessingContext,
        position_scope: OnlyExecutionPositionScope,
        trade_fingerprints: tuple[str, ...],
        sequence_scope: tuple[str, ...],
        mode: OnlyExecutionProcessingMode,
        recovery_session: OnlyExecutionRecoverySession | None,
        prepared: OnlyPreparedExecutionTransaction,
        instrument_id: OnlyInstrumentId,
        steps: list[OnlyExecutionMutationRecord],
    ) -> OnlyExecutionProcessingResult:
        coordinated_at = OnlyTimestamp.from_unix_nanos(self._clock.timestamp_ns())
        recovery_decision: OnlyExecutionRecoveryDecision | None = None
        resolution: OnlyExecutionRecoveryResolution | None = None
        if mode is OnlyExecutionProcessingMode.RECOVERY:
            if recovery_session is None:
                raise AssertionError("Recovery processing requires an explicit causal session")
            recovery_decision = recovery_session.decide(update, prepared)
            entry = recovery_decision.entry
            if recovery_decision.kind is OnlyExecutionRecoveryDecisionKind.REHYDRATE_READY:
                if entry is None:
                    raise AssertionError("Ready recovery decision lost its persisted entry")
                coordination = self._execution_commit_coordinator.rehydrate_existing(
                    entry.stored.committed,
                    projected_at=coordinated_at,
                )
                resolution = OnlyExecutionRecoveryResolution.READY_REHYDRATED
            elif recovery_decision.kind is OnlyExecutionRecoveryDecisionKind.RECOVER_UNPROJECTED:
                if entry is None:
                    raise AssertionError("Unprojected recovery decision lost its persisted entry")
                coordination = self._execution_commit_coordinator.recover_existing(
                    entry.stored.committed,
                    projected_at=coordinated_at,
                )
                resolution = OnlyExecutionRecoveryResolution.UNPROJECTED_RECOVERED
            else:
                coordination = self._execution_commit_coordinator.commit(
                    prepared,
                    committed_at=coordinated_at,
                    projected_at=coordinated_at,
                )
        else:
            coordination = self._execution_commit_coordinator.commit(
                prepared,
                committed_at=coordinated_at,
                projected_at=coordinated_at,
            )
        if coordination.status in {
            OnlyExecutionCommitCoordinationStatus.COMMITTED_AND_PROJECTED,
            OnlyExecutionCommitCoordinationStatus.ALREADY_READY,
        }:
            transaction = coordination.transaction
            if transaction is None:
                raise AssertionError("successful execution coordination lost its committed transaction")
            component_steps = {
                OnlyExecutionProjectionComponent.ORDER: OnlyExecutionMutationStep.ORDER,
                OnlyExecutionProjectionComponent.POSITION: OnlyExecutionMutationStep.POSITION,
                OnlyExecutionProjectionComponent.ALLOCATION: OnlyExecutionMutationStep.ALLOCATION,
                OnlyExecutionProjectionComponent.SETTLEMENT: OnlyExecutionMutationStep.SETTLEMENT,
                OnlyExecutionProjectionComponent.MARGIN: OnlyExecutionMutationStep.MARGIN,
                OnlyExecutionProjectionComponent.FEE: OnlyExecutionMutationStep.FEE,
                OnlyExecutionProjectionComponent.ORDER_FEE_ACCRUAL: OnlyExecutionMutationStep.FEE,
                OnlyExecutionProjectionComponent.ACCOUNT: OnlyExecutionMutationStep.ACCOUNT,
                OnlyExecutionProjectionComponent.STRATEGY_LEDGER: OnlyExecutionMutationStep.STRATEGY_LEDGER,
                OnlyExecutionProjectionComponent.ACCOUNT_CASH_RESERVATION: OnlyExecutionMutationStep.RESERVATION,
                OnlyExecutionProjectionComponent.STRATEGY_CASH_RESERVATION: OnlyExecutionMutationStep.RESERVATION,
                OnlyExecutionProjectionComponent.POSITION_RESERVATION: OnlyExecutionMutationStep.RESERVATION,
                OnlyExecutionProjectionComponent.MARGIN_RESERVATION: OnlyExecutionMutationStep.RESERVATION,
                OnlyExecutionProjectionComponent.RISK_RESERVATION: OnlyExecutionMutationStep.RESERVATION,
                OnlyExecutionProjectionComponent.RISK: OnlyExecutionMutationStep.RISK,
                OnlyExecutionProjectionComponent.VALUATION: OnlyExecutionMutationStep.ACCOUNT,
            }
            mutation_status = (
                OnlyExecutionMutationStatus.APPLIED
                if coordination.status is OnlyExecutionCommitCoordinationStatus.COMMITTED_AND_PROJECTED
                else OnlyExecutionMutationStatus.DUPLICATE
            )
            steps.extend(
                OnlyExecutionMutationRecord(
                    component_steps[projection.identity.component],
                    mutation_status,
                    f"{projection.identity.component.value} committed projection",
                )
                for projection in transaction.projections
            )
            invariant = self._invariants.check(update.account_id, instrument_id)
            if not invariant.passed:
                raise _OnlyExecutionInvariantError(invariant)
            steps.append(
                OnlyExecutionMutationRecord(
                    OnlyExecutionMutationStep.INVARIANT_CHECK,
                    OnlyExecutionMutationStatus.APPLIED,
                    "all committed projection invariants passed",
                )
            )
            self._deduplicator.remember(update.update_id, trade_fingerprints)
            self._sequences.observe(sequence_scope, update.source_sequence)
            status = (
                OnlyExecutionProcessingStatus.APPLIED
                if coordination.status is OnlyExecutionCommitCoordinationStatus.COMMITTED_AND_PROJECTED
                else OnlyExecutionProcessingStatus.DUPLICATE
            )
            payload: OnlyExecutionDispatchPayload = (
                status,
                None,
                None,
                None,
                None,
                invariant,
                None,
                (),
            )
            if mode is OnlyExecutionProcessingMode.RECOVERY:
                assert recovery_session is not None
                assert recovery_decision is not None
                if recovery_decision.kind is OnlyExecutionRecoveryDecisionKind.COMMIT_CONTINUATION:
                    recovery_session.record_continuation(transaction)
                else:
                    if resolution is None:
                        raise AssertionError("persisted recovery decision lost its resolution")
                    recovery_session.resolve_persisted(transaction.execution_sequence, resolution)
            return self._complete(
                update,
                context,
                status,
                steps,
                payload,
                transaction.outbox_events,
                coordination.delivery_intent,
                invariant,
                position_scope=position_scope,
            )
        failure = OnlyExecutionFailure(
            OnlyExecutionFailureCode.DEPENDENCY_FAILURE,
            coordination.error or coordination.status.value,
            OnlyExecutionMutationStep.INVARIANT_CHECK,
            coordination.status.value,
        )
        steps.append(
            OnlyExecutionMutationRecord(
                OnlyExecutionMutationStep.INVARIANT_CHECK,
                OnlyExecutionMutationStatus.FAILED,
                failure.message,
            )
        )
        reconciliation = None
        processing_status = OnlyExecutionProcessingStatus.FAILED
        if coordination.transaction is not None and coordination.status in {
            OnlyExecutionCommitCoordinationStatus.PROJECTION_FAILED,
            OnlyExecutionCommitCoordinationStatus.STORE_FAILURE,
        }:
            reconciliation = self._make_reconciliation(
                update,
                tuple(item.step for item in steps if item.status is OnlyExecutionMutationStatus.APPLIED),
                OnlyExecutionMutationStep.INVARIANT_CHECK,
                failure.message,
                position_scope,
            )
            self._reconciliation.request_reconciliation(reconciliation)
            processing_status = OnlyExecutionProcessingStatus.RECONCILIATION_REQUIRED
        return self._terminal(
            update,
            context,
            processing_status,
            steps=tuple(steps),
            failure=failure,
            reconciliation=reconciliation,
            invariant=OnlyExecutionInvariantResult(False),
            quality_flags=(coordination.status.value,),
            position_scope=position_scope,
        )

    def process_many(self, updates: tuple[OnlyBrokerInboundUpdate, ...]) -> tuple[OnlyExecutionProcessingResult, ...]:
        return tuple(self.process(update) for update in updates)

    def _dispatch(
        self,
        update: OnlyBrokerInboundUpdate,
        stale: bool,
        steps: list[OnlyExecutionMutationRecord],
        position_scope: OnlyExecutionPositionScope | None,
    ) -> OnlyExecutionDispatchPayload:
        if isinstance(update, OnlyBrokerOrderAcceptedUpdate):
            return self._accepted(update, stale, steps)
        if isinstance(update, OnlyBrokerOrderRejectedUpdate):
            return self._terminal_order(update, steps, rejected=True)
        if isinstance(update, OnlyBrokerOrderCancelledUpdate):
            return self._terminal_order(update, steps, rejected=False)
        if isinstance(update, OnlyBrokerOrderExpiredUpdate):
            return self._terminal_order(update, steps, rejected=False)
        if isinstance(update, OnlyBrokerTradeUpdate):
            return self._unmigrated_trade(update, steps, position_scope)
        if isinstance(update, OnlyBrokerPositionUpdate):
            result = self._position_reconciliation.reconcile(self._local_broker_position(update))
            steps.append(
                OnlyExecutionMutationRecord(
                    OnlyExecutionMutationStep.POSITION, OnlyExecutionMutationStatus.APPLIED, result.severity.value
                )
            )
            invariant = self._invariants.check(update.account_id, update.snapshot.instrument_id)
            status = (
                OnlyExecutionProcessingStatus.APPLIED
                if result.reconciled
                else OnlyExecutionProcessingStatus.RECONCILIATION_REQUIRED
            )
            return status, None, None, None, None, invariant, None, ("POSITION_RECONCILIATION",)
        if isinstance(update, OnlyBrokerAccountUpdate):
            account_reconciliation = self._account_reconciliation.reconcile(update.snapshot)
            difference_summary = tuple(
                f"{item.field}:local={item.local_value}:broker={item.broker_value}"
                for item in account_reconciliation.differences
            )
            steps.append(
                OnlyExecutionMutationRecord(
                    OnlyExecutionMutationStep.ACCOUNT,
                    OnlyExecutionMutationStatus.APPLIED,
                    ":".join(
                        (
                            account_reconciliation.severity.value,
                            account_reconciliation.action.value,
                            *difference_summary,
                        )
                    ),
                )
            )
            invariant = OnlyExecutionInvariantResult(True)
            status = (
                OnlyExecutionProcessingStatus.APPLIED
                if not account_reconciliation.differences
                else OnlyExecutionProcessingStatus.RECONCILIATION_REQUIRED
            )
            return status, None, None, None, None, invariant, None, ("ACCOUNT_RECONCILIATION",)
        if isinstance(update, OnlyBrokerConnectionUpdate):
            self._connection_state(update.state)
            steps.append(
                OnlyExecutionMutationRecord(
                    OnlyExecutionMutationStep.RISK, OnlyExecutionMutationStatus.APPLIED, update.state.value
                )
            )
            return (
                OnlyExecutionProcessingStatus.APPLIED,
                None,
                None,
                None,
                None,
                OnlyExecutionInvariantResult(True),
                None,
                (),
            )
        raise TypeError(f"unsupported Broker update: {type(update).__name__}")

    def _accepted(
        self,
        update: OnlyBrokerOrderAcceptedUpdate,
        stale: bool,
        steps: list[OnlyExecutionMutationRecord],
    ) -> OnlyExecutionDispatchPayload:
        order_update = OnlyGatewayOrderAcceptedUpdate(
            runtime_id=self.config.runtime_id,
            order_id=update.order_id,
            ts_event=update.ts_event,
            ts_init=update.ts_init,
            external_sequence=update.source_sequence,
            external_event_id=str(update.update_id),
            metadata=update.metadata,
            venue_order_id=update.venue_order_id,
        )
        result = self._order_updates.process(order_update, publish_events=False, coordinate_reservations=False)
        if result.apply_result is OnlyOrderApplyResult.CONFLICT:
            raise ValueError(result.error or "Accepted conflicts with Order")
        status = OnlyExecutionProcessingStatus.APPLIED
        if not result.changed:
            status = (
                OnlyExecutionProcessingStatus.STALE if result.stale or stale else OnlyExecutionProcessingStatus.IGNORED
            )
            mutation_status = OnlyExecutionMutationStatus.SKIPPED
        else:
            self._events.extend(result.events)
            self._position_reservation_port.acknowledged(result.order_id, update.ts_init)
            mutation_status = OnlyExecutionMutationStatus.APPLIED
        steps.append(
            OnlyExecutionMutationRecord(OnlyExecutionMutationStep.ORDER, mutation_status, result.apply_result.value)
        )
        instrument_id = result.snapshot.instrument_id
        invariant = self._invariants.check(update.account_id, instrument_id)
        return status, result, None, None, None, invariant, None, ()

    def _terminal_order(
        self,
        update: OnlyBrokerOrderRejectedUpdate | OnlyBrokerOrderCancelledUpdate | OnlyBrokerOrderExpiredUpdate,
        steps: list[OnlyExecutionMutationRecord],
        *,
        rejected: bool,
    ) -> OnlyExecutionDispatchPayload:
        direct_order = self._orders.get(update.order_id)
        if direct_order is not None:
            direct_scope = self._position_scope_resolver.resolve_order(direct_order)
            if self._uses_prepared_terminal_path(update, direct_scope):
                raise RuntimeError("DURABLE_TERMINAL_REQUIRED: formal Long Close cannot use direct terminal mutation")
        gateway_update: OnlyGatewayOrderUpdate
        if rejected:
            assert isinstance(update, OnlyBrokerOrderRejectedUpdate)
            gateway_update = OnlyGatewayOrderRejectedUpdate(
                runtime_id=self.config.runtime_id,
                order_id=update.order_id,
                ts_event=update.ts_event,
                ts_init=update.ts_init,
                external_sequence=update.source_sequence,
                external_event_id=str(update.update_id),
                metadata=update.metadata,
                rejection=update.rejection,
            )
            reason = OnlyRiskReleaseReason.ORDER_REJECTED
        else:
            update_type = (
                OnlyGatewayOrderExpiredUpdate
                if isinstance(update, OnlyBrokerOrderExpiredUpdate)
                else OnlyGatewayOrderCancelledUpdate
            )
            gateway_update = update_type(
                runtime_id=self.config.runtime_id,
                order_id=update.order_id,
                ts_event=update.ts_event,
                ts_init=update.ts_init,
                external_sequence=update.source_sequence,
                external_event_id=str(update.update_id),
                metadata=update.metadata,
            )
            reason = (
                OnlyRiskReleaseReason.ORDER_EXPIRED
                if isinstance(update, OnlyBrokerOrderExpiredUpdate)
                else OnlyRiskReleaseReason.ORDER_CANCELLED
            )
        result = self._order_updates.process(gateway_update, publish_events=False, coordinate_reservations=False)
        steps.append(
            OnlyExecutionMutationRecord(
                OnlyExecutionMutationStep.ORDER,
                OnlyExecutionMutationStatus.APPLIED if result.changed else OnlyExecutionMutationStatus.SKIPPED,
                result.apply_result.value,
            )
        )
        reservations: list[str] = []
        if result.changed:
            self._events.extend(result.events)
            self._position_reservation_port.release(result.order_id, update.ts_init, broker_confirmed=True)
            self._release_account_reservation(result.order_id, update.ts_init)
            if self._release_margin_reservation is not None:
                self._release_margin_reservation(result.order_id, update.ts_init)
            ledger_key = self._ledger_locator.require_key(
                runtime_id=self.config.runtime_id,
                account_id=update.account_id,
                cluster_id=result.snapshot.cluster_id,
                currency=self._base_currency,
            )
            ledger = self._ledgers.require_snapshot(ledger_key)
            if any(item.order_id == result.order_id for item in ledger.reservations):
                self._ledgers.release_cash_reservation(ledger_key, result.order_id, update.ts_init)
            self._risk.release_order(
                result.order_id, result.snapshot.cluster_id, update.account_id, reason, update.ts_init
            )
            reservations.append("REMAINING_RELEASED")
        steps.append(
            OnlyExecutionMutationRecord(
                OnlyExecutionMutationStep.RESERVATION,
                OnlyExecutionMutationStatus.APPLIED if reservations else OnlyExecutionMutationStatus.SKIPPED,
                ",".join(reservations) or "none",
            )
        )
        steps.append(
            OnlyExecutionMutationRecord(
                OnlyExecutionMutationStep.RISK,
                OnlyExecutionMutationStatus.APPLIED if result.changed else OnlyExecutionMutationStatus.SKIPPED,
                reason.value,
            )
        )
        invariant = self._invariants.check(update.account_id, result.snapshot.instrument_id)
        status = (
            OnlyExecutionProcessingStatus.APPLIED
            if result.changed
            else (OnlyExecutionProcessingStatus.STALE if result.stale else OnlyExecutionProcessingStatus.IGNORED)
        )
        return status, result, None, None, None, invariant, None, tuple(reservations)

    def _unmigrated_trade(
        self,
        update: OnlyBrokerTradeUpdate,
        steps: list[OnlyExecutionMutationRecord],
        position_scope: OnlyExecutionPositionScope | None,
    ) -> OnlyExecutionDispatchPayload:
        """Apply explicitly unmigrated SELL/CLOSE, partial, futures, or multi-capital scope."""
        order = self._orders.require(update.order_id)
        if position_scope is None:
            raise ValueError("POSITION_SIDE_RESOLUTION_FAILED: Trade has no Position Scope")
        instruction = self._trade_instructions.get(str(update.fill.trade_id))
        account = self._accounts.get_snapshot(order.account_id)
        if instruction is not None and account is not None:
            capability = only_resolve_execution_capability(
                operation_kind=OnlyExecutionOperationKind.TRADE_FILL,
                market_profile_id=instruction.compiled_identity.profile_id,
                account_type=account.account_type,
                order_type=order.order_type,
                order_side=order.side,
                offset=order.offset,
                position_side=position_scope.position_side,
                position_effect=position_scope.position_effect,
                position_mode=position_scope.position_mode,
                has_margin=instruction.margin_instruction is not None,
                account_ledger_parity=self._has_account_ledger_parity(order, account),
            )
            if capability is OnlyExecutionCapability.DURABLE_TRADE:
                raise RuntimeError("DURABLE_TRADE_REQUIRED: formal Generic T0 Trade cannot use legacy mutation")
        fee_instruction = self._resolve_fee_instruction(update, order, position_scope)
        trade = self._position_trade(update, order, position_scope, fee_instruction)
        if trade.cluster_id is None:
            raise ValueError("strategy Trade requires Cluster attribution")
        allocation_key = position_scope.allocation_key
        if allocation_key is None:
            raise ValueError("strategy Trade requires Allocation Scope")
        allocation_before = self._allocation_snapshot(allocation_key)
        fill_update = OnlyGatewayOrderFillUpdate(
            runtime_id=self.config.runtime_id,
            order_id=update.order_id,
            ts_event=update.ts_event,
            ts_init=update.ts_init,
            external_sequence=update.source_sequence,
            external_event_id=str(update.update_id),
            metadata=update.metadata,
            fill=update.fill,
        )
        order_result = self._order_updates.process(fill_update, publish_events=False, coordinate_reservations=False)
        if not order_result.changed:
            steps.append(
                OnlyExecutionMutationRecord(
                    OnlyExecutionMutationStep.ORDER,
                    OnlyExecutionMutationStatus.DUPLICATE,
                    order_result.apply_result.value,
                )
            )
            invariant = self._invariants.check(update.account_id, order.instrument_id)
            return OnlyExecutionProcessingStatus.DUPLICATE, order_result, None, None, None, invariant, None, ()
        self._events.extend(order_result.events)
        steps.append(
            OnlyExecutionMutationRecord(
                OnlyExecutionMutationStep.ORDER, OnlyExecutionMutationStatus.APPLIED, order_result.current_status.value
            )
        )
        position_reservation = self._position_reservations.get(trade.order_id)
        position_result = self._positions.apply_trade(
            trade,
            own_order_reserved_quantity=(
                None if position_reservation is None else position_reservation.remaining_quantity
            ),
        )
        if position_result.status is not OnlyPositionMutationStatus.APPLIED:
            raise ValueError(f"Position rejected validated Trade: {position_result.status.value}")
        steps.append(
            OnlyExecutionMutationRecord(
                OnlyExecutionMutationStep.POSITION, OnlyExecutionMutationStatus.APPLIED, position_result.status.value
            )
        )
        allocation_status = self._allocations.apply_trade(
            trade,
            own_order_reserved_quantity=(
                None if position_reservation is None else position_reservation.remaining_quantity
            ),
        )
        if allocation_status is not OnlyPositionMutationStatus.APPLIED:
            raise ValueError(f"Allocation rejected validated Trade: {allocation_status.value}")
        steps.append(
            OnlyExecutionMutationRecord(
                OnlyExecutionMutationStep.ALLOCATION, OnlyExecutionMutationStatus.APPLIED, allocation_status.value
            )
        )
        instruction = self._trade_instructions.get(str(trade.trade_id))
        if instruction is None or self._settlement_manager is None:
            raise ValueError("Trade commit requires a Market instruction and Settlement Manager")
        trading_day = (
            self._trading_day(trade.ts_event)
            if self._trading_day is not None
            else OnlyTradingDay(trade.ts_event.to_datetime().date())
        )
        self._settlement_manager.register(
            instruction.settlement_instruction,
            cash_currency=fee_instruction.fee_breakdown.total.currency,
        )
        self._settlement_manager.advance(trading_day)
        steps.append(
            OnlyExecutionMutationRecord(
                OnlyExecutionMutationStep.SETTLEMENT,
                OnlyExecutionMutationStatus.APPLIED,
                instruction.settlement_instruction.instruction_id,
            )
        )
        margin_record = None
        if instruction.margin_instruction is not None:
            if self._margin_manager is None:
                raise ValueError("Trade margin instruction requires Runtime Margin Manager")
            occupied_before = self._margin_manager.occupied(
                instruction.margin_instruction.account_id,
                instruction.margin_instruction.instrument_id,
                instruction.margin_instruction.currency,
            )
            margin_record = self._margin_manager.apply(instruction.margin_instruction)
            if instruction.margin_instruction.action == "OCCUPY":
                self._accounts.apply_margin_change(
                    trade.account_id,
                    reserved_delta=-instruction.margin_instruction.amount,
                    occupied_delta=instruction.margin_instruction.amount,
                    timestamp=trade.ts_init,
                )
            else:
                released_amount = occupied_before - margin_record.occupied_after
                self._accounts.apply_margin_change(
                    trade.account_id,
                    occupied_delta=-released_amount,
                    released_delta=released_amount,
                    timestamp=trade.ts_init,
                )
            steps.append(
                OnlyExecutionMutationRecord(
                    OnlyExecutionMutationStep.MARGIN,
                    OnlyExecutionMutationStatus.APPLIED,
                    f"{margin_record.action}:{margin_record.amount}",
                )
            )
        if self._fee_manager is None:
            raise ValueError("Trade commit requires Runtime Fee Manager")
        fee_records = self._fee_manager.apply(
            fee_instruction,
            instrument_id=str(trade.instrument_id),
        )
        steps.append(
            OnlyExecutionMutationRecord(
                OnlyExecutionMutationStep.FEE,
                OnlyExecutionMutationStatus.APPLIED,
                f"records={len(fee_records)}",
            )
        )
        allocation_after = self._allocation_snapshot(allocation_key, include_closed=True)
        if trade.fee.currency != self._base_currency:
            raise ValueError("Trade, fee, Account and Strategy Ledger currencies must match; FX is unsupported")
        ledger_key = self._ledger_locator.require_key(
            runtime_id=trade.runtime_id,
            account_id=trade.account_id,
            cluster_id=trade.cluster_id,
            currency=trade.fee.currency,
        )
        ledger_snapshot = self._ledgers.require_snapshot(ledger_key)
        reservation = next((item for item in ledger_snapshot.reservations if item.order_id == trade.order_id), None)
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
        notional = self._notional(trade)
        settle_notional = True if instruction is None else instruction.cash_instruction.settle_notional
        account_result = self._accounts.apply_trade_cash_flow(
            OnlyAccountTradeCashFlow(
                trade.runtime_id,
                trade.account_id,
                trade.order_id,
                trade.trade_id,
                trade.side,
                notional,
                trade.fee,
                position_result.realized_pnl_delta,
                trade.ts_init,
                trade.external_sequence or 0,
                settle_notional,
            )
        )
        self._account_valuation(trade)
        steps.append(
            OnlyExecutionMutationRecord(
                OnlyExecutionMutationStep.ACCOUNT, OnlyExecutionMutationStatus.APPLIED, account_result.status.value
            )
        )
        ledger_result = self._ledgers.apply_trade_accounting(
            ledger_key,
            OnlyStrategyTradeAccountingInput(
                trade,
                order_result.snapshot,
                allocation_before,
                allocation_after,
                self._allocation_money(allocation_after, True, ledger_key.base_currency)
                - self._allocation_money(allocation_before, True, ledger_key.base_currency),
                self._allocation_cost(allocation_after, trade) - self._allocation_cost(allocation_before, trade),
                (fee_entry,),
                reservation,
                trade.ts_event,
                trade.external_sequence or 0,
                settle_notional,
            ),
            consume_cash_reservation=False,
        )
        self._strategy_valuation(ledger_key, trade)
        steps.append(
            OnlyExecutionMutationRecord(
                OnlyExecutionMutationStep.STRATEGY_LEDGER,
                OnlyExecutionMutationStatus.APPLIED,
                ledger_result.status.value,
            )
        )
        reservation_results: list[str] = []
        if trade.opens_position and trade.side is OnlyOrderSide.BUY:
            self._consume_account_reservation(update.fill, notional + trade.fee, trade.ts_init)
            self._ledgers.consume_cash_reservation(ledger_key, trade.order_id, notional + trade.fee, trade.ts_init)
            reservation_results.extend(("ACCOUNT_CASH_CONSUMED", "STRATEGY_CASH_CONSUMED"))
            if order_result.snapshot.status is OnlyOrderStatus.FILLED:
                self._release_account_reservation(trade.order_id, trade.ts_init)
                self._ledgers.release_cash_reservation(ledger_key, trade.order_id, trade.ts_init)
                reservation_results.extend(("ACCOUNT_REMAINDER_RELEASED", "STRATEGY_REMAINDER_RELEASED"))
        elif trade.closes_position:
            self._position_reservation_port.consume(
                trade.order_id,
                trade.quantity,
                trade.ts_init,
                allocation_hold_already_released=True,
            )
            reservation_results.append("POSITION_CONSUMED")
        if order_result.snapshot.status is OnlyOrderStatus.FILLED and self._release_margin_reservation is not None:
            self._release_margin_reservation(trade.order_id, trade.ts_init)
            reservation_results.append("MARGIN_REMAINDER_RELEASED")
        self._risk.consume_order_fill(
            trade.order_id,
            order.cluster_id,
            trade.account_id,
            trade.quantity,
            notional,
            order_result.snapshot.status is OnlyOrderStatus.FILLED,
            trade.ts_init,
        )
        steps.append(
            OnlyExecutionMutationRecord(
                OnlyExecutionMutationStep.RESERVATION,
                OnlyExecutionMutationStatus.APPLIED,
                ",".join(reservation_results),
            )
        )
        steps.append(
            OnlyExecutionMutationRecord(
                OnlyExecutionMutationStep.RISK, OnlyExecutionMutationStatus.APPLIED, "post-trade state refreshed"
            )
        )
        invariant = self._invariants.check(update.account_id, order.instrument_id)
        return (
            OnlyExecutionProcessingStatus.APPLIED,
            order_result,
            position_result,
            allocation_status,
            ledger_result,
            invariant,
            account_result,
            tuple(reservation_results),
        )

    def _validate(
        self, update: OnlyBrokerInboundUpdate, context: OnlyExecutionProcessingContext
    ) -> OnlyExecutionFailure | None:
        if update.runtime_id != self.config.runtime_id:
            return OnlyExecutionFailure(
                OnlyExecutionFailureCode.SCOPE_MISMATCH,
                "Broker update belongs to another Runtime",
                OnlyExecutionMutationStep.VALIDATION,
            )
        if update.gateway_id not in self.config.gateway_ids:
            return OnlyExecutionFailure(
                OnlyExecutionFailureCode.UNKNOWN_GATEWAY,
                "Broker Gateway is not registered",
                OnlyExecutionMutationStep.VALIDATION,
            )
        if update.account_id not in self.config.account_ids:
            return OnlyExecutionFailure(
                OnlyExecutionFailureCode.UNKNOWN_ACCOUNT,
                "Broker Account is not registered",
                OnlyExecutionMutationStep.VALIDATION,
            )
        if update.ts_init < update.ts_event or update.source_sequence < 0:
            return OnlyExecutionFailure(
                OnlyExecutionFailureCode.INVALID_UPDATE,
                "Broker update has invalid causal ordering",
                OnlyExecutionMutationStep.VALIDATION,
            )
        order_id = getattr(update, "order_id", None)
        if isinstance(order_id, OnlyOrderId):
            try:
                order = self._orders.require(order_id)
            except KeyError:
                return OnlyExecutionFailure(
                    OnlyExecutionFailureCode.UNKNOWN_ORDER,
                    "Broker update references an unknown Order",
                    OnlyExecutionMutationStep.VALIDATION,
                )
            if order.runtime_id != context.runtime_id or order.account_id != context.account_id:
                return OnlyExecutionFailure(
                    OnlyExecutionFailureCode.SCOPE_MISMATCH,
                    "Order Scope differs from Broker update",
                    OnlyExecutionMutationStep.VALIDATION,
                )
        return None

    def _complete(
        self,
        update: OnlyBrokerInboundUpdate,
        context: OnlyExecutionProcessingContext,
        status: OnlyExecutionProcessingStatus,
        steps: list[OnlyExecutionMutationRecord],
        payload: OnlyExecutionDispatchPayload,
        generated: tuple[OnlyEvent, ...],
        delivery_intent: OnlyExecutionEventDeliveryIntent,
        invariant: OnlyExecutionInvariantResult,
        reconciliation: OnlyExecutionReconciliationRequest | None = None,
        position_scope: OnlyExecutionPositionScope | None = None,
    ) -> OnlyExecutionProcessingResult:
        bundle = OnlyExecutionMutationBundle(
            tuple(steps), payload[1], payload[2], payload[3], payload[4], payload[6], payload[7], "UPDATED"
        )
        snapshot = self._snapshot(update, context.processing_sequence, position_scope)
        completed = OnlyTimestamp.from_unix_nanos(self._clock.timestamp_ns())
        audit = self._audit_record(
            update,
            context,
            status,
            tuple(steps),
            invariant,
            generated,
            completed,
            reconciliation=reconciliation,
            position_scope=position_scope,
        )
        self._audit.append(audit)
        return OnlyExecutionProcessingResult(
            self.config.runtime_id,
            update.update_id,
            type(update).__name__,
            status,
            context.processing_sequence,
            context.ts_started,
            completed,
            bundle,
            snapshot,
            generated,
            delivery_intent,
            audit,
            reconciliation_request=reconciliation,
            quality_flags=update.quality_flags,
        )

    def _terminal(
        self,
        update: OnlyBrokerInboundUpdate,
        context: OnlyExecutionProcessingContext,
        status: OnlyExecutionProcessingStatus,
        *,
        steps: tuple[OnlyExecutionMutationRecord, ...] = (),
        failure: OnlyExecutionFailure | None = None,
        reconciliation: OnlyExecutionReconciliationRequest | None = None,
        generated_events: tuple[OnlyEvent, ...] = (),
        delivery_intent: OnlyExecutionEventDeliveryIntent | None = None,
        invariant: OnlyExecutionInvariantResult | None = None,
        quality_flags: tuple[str, ...] = (),
        position_scope: OnlyExecutionPositionScope | None = None,
    ) -> OnlyExecutionProcessingResult:
        completed = OnlyTimestamp.from_unix_nanos(self._clock.timestamp_ns())
        invariant_result = invariant or OnlyExecutionInvariantResult(True)
        bundle = OnlyExecutionMutationBundle(tuple(steps))
        snapshot = self._snapshot(update, context.processing_sequence, position_scope)
        audit = self._audit_record(
            update,
            context,
            status,
            tuple(steps),
            invariant_result,
            tuple(generated_events),
            completed,
            failure,
            reconciliation,
            position_scope,
        )
        self._audit.append(audit)
        return OnlyExecutionProcessingResult(
            self.config.runtime_id,
            update.update_id,
            type(update).__name__,
            status,
            context.processing_sequence,
            context.ts_started,
            completed,
            bundle,
            snapshot,
            tuple(generated_events),
            delivery_intent or OnlyExecutionEventDeliveryIntent(OnlyExecutionEventDeliveryMode.NONE),
            audit,
            failure,
            reconciliation,
            tuple(sorted(set(update.quality_flags + tuple(quality_flags)))),
        )

    @staticmethod
    def _direct_intent(batch: OnlyExecutionEventBatch) -> OnlyExecutionEventDeliveryIntent:
        if batch.empty:
            return OnlyExecutionEventDeliveryIntent(OnlyExecutionEventDeliveryMode.NONE)
        return OnlyExecutionEventDeliveryIntent(OnlyExecutionEventDeliveryMode.DIRECT, direct_batch=batch)

    def _audit_record(
        self,
        update: OnlyBrokerInboundUpdate,
        context: OnlyExecutionProcessingContext,
        status: OnlyExecutionProcessingStatus,
        steps: tuple[OnlyExecutionMutationRecord, ...],
        invariant: OnlyExecutionInvariantResult,
        events: tuple[OnlyEvent, ...],
        completed: OnlyTimestamp,
        failure: OnlyExecutionFailure | None = None,
        reconciliation: OnlyExecutionReconciliationRequest | None = None,
        position_scope: OnlyExecutionPositionScope | None = None,
    ) -> OnlyExecutionAuditRecord:
        order_id = getattr(update, "order_id", None)
        order = self._orders.get(order_id) if isinstance(order_id, OnlyOrderId) else None
        trade_id = update.fill.trade_id if isinstance(update, OnlyBrokerTradeUpdate) else None
        return OnlyExecutionAuditRecord(
            f"{self.config.runtime_id}-EXEC-{context.processing_sequence:08d}",
            self.config.runtime_id,
            update.gateway_id,
            update.account_id,
            update.update_id,
            type(update).__name__,
            status,
            context.processing_sequence,
            tuple(item.step for item in steps if item.status is OnlyExecutionMutationStatus.APPLIED),
            tuple(item.summary for item in steps),
            invariant,
            tuple(str(item.event_type) for item in events),
            context.ts_started,
            completed,
            failure,
            None if reconciliation is None else reconciliation.request_id,
            order_id if isinstance(order_id, OnlyOrderId) else None,
            trade_id,
            None if order is None else order.cluster_id,
            None if order is None else order.instrument_id,
            position_scope,
        )

    def _snapshot(
        self,
        update: OnlyBrokerInboundUpdate,
        sequence: int,
        position_scope: OnlyExecutionPositionScope | None,
    ) -> OnlyExecutionSnapshotBundle:
        order_id = getattr(update, "order_id", None)
        order = self._orders.get(order_id) if isinstance(order_id, OnlyOrderId) else None
        account = self._accounts.get_snapshot(update.account_id)
        position = allocation = ledger = risk = None
        if order is not None:
            if position_scope is not None:
                position = self._positions.get_snapshot(position_scope.position_key)
                allocation = (
                    None
                    if position_scope.allocation_key is None
                    else self._allocation_snapshot(position_scope.allocation_key)
                )
            ledger = self._ledger_locator.require_snapshot(
                runtime_id=order.runtime_id,
                account_id=order.account_id,
                cluster_id=order.cluster_id,
                currency=self._base_currency,
            )
            try:
                risk = self._risk.get_snapshot(order.cluster_id)
            except KeyError:
                risk = None
        return OnlyExecutionSnapshotBundle(
            sequence,
            OnlyTimestamp.from_unix_nanos(self._clock.timestamp_ns()),
            order,
            position,
            allocation,
            ledger,
            account,
            risk,
            position_scope,
        )

    def _make_reconciliation(
        self,
        update: OnlyBrokerInboundUpdate,
        completed_steps: tuple[OnlyExecutionMutationStep, ...],
        failed_step: OnlyExecutionMutationStep,
        reason: str,
        position_scope: OnlyExecutionPositionScope | None,
    ) -> OnlyExecutionReconciliationRequest:
        order_id = getattr(update, "order_id", None)
        order = self._orders.get(order_id) if isinstance(order_id, OnlyOrderId) else None
        return OnlyExecutionReconciliationRequest(
            f"{self.config.runtime_id}-RECON-{self._processing_sequence:08d}",
            self.config.runtime_id,
            update.gateway_id,
            update.account_id,
            update.update_id,
            reason,
            tuple(completed_steps),
            failed_step,
            order_id if isinstance(order_id, OnlyOrderId) else None,
            update.fill.trade_id if isinstance(update, OnlyBrokerTradeUpdate) else None,
            None if order is None else order.cluster_id,
            None if order is None else order.instrument_id,
            position_scope,
        )

    def _block_scope(self, update: OnlyBrokerInboundUpdate, scope: OnlyExecutionPositionScope | None) -> None:
        if scope is not None and self._positions.get_snapshot(scope.position_key) is not None:
            self._positions.set_reconciling(scope.position_key)
        if self._accounts.get_snapshot(update.account_id) is not None:
            self._events.begin()
            self._accounts.start_reconciliation(update.account_id, update.ts_init, "EXECUTION_PARTIAL_MUTATION")
            self._events.abort()

    def _position_trade(
        self,
        update: OnlyBrokerTradeUpdate,
        order: OnlyOrderSnapshot,
        scope: OnlyExecutionPositionScope,
        fee_instruction: OnlyFeeInstruction,
    ) -> OnlyPositionTrade:
        instrument = self._instruments[order.instrument_id]
        fee = fee_instruction.fee_breakdown.total
        settlement_bucket = (
            OnlySettlementBucket.UNSETTLED if order.side is OnlyOrderSide.BUY else OnlySettlementBucket.SETTLED
        )
        trade_offset = order.offset if order.offset is not OnlyOffset.NONE else OnlyOffset(scope.position_effect.value)
        position_side = scope.position_side
        position_mode = scope.position_mode
        if self._market_rules is not None:
            instruction = self._trade_instructions.get(str(update.fill.trade_id))
            if instruction is None:
                raise ValueError("POSITION_SCOPE_CONFLICT: missing resolved Trade instruction")
            settlement_bucket = (
                OnlySettlementBucket.SETTLED
                if instruction.settlement_instruction.asset_available_on.value <= update.ts_event.to_datetime().date()
                else OnlySettlementBucket.UNSETTLED
            )
        return OnlyPositionTrade(
            update.fill.trade_id,
            update.fill.venue_trade_id,
            order.order_id,
            order.cluster_id,
            order.runtime_id,
            order.account_id,
            order.instrument_id,
            order.side,
            OnlyDirection.BUY if order.side is OnlyOrderSide.BUY else OnlyDirection.SELL,
            trade_offset,
            position_side,
            update.fill.price,
            update.fill.quantity,
            fee,
            update.ts_event,
            update.ts_init,
            update.source_sequence,
            execution_id=str(update.update_id),
            settlement_bucket=settlement_bucket,
            multiplier=instrument.contract_multiplier,
            position_mode=position_mode,
        )

    def _resolve_fee_instruction(
        self,
        update: OnlyBrokerTradeUpdate,
        order: OnlyOrderSnapshot,
        scope: OnlyExecutionPositionScope,
    ) -> OnlyFeeInstruction:
        if self._fee_resolver is None:
            raise ValueError("FEE_RESOLUTION_REQUIRES_RUNTIME_FEE_RESOLVER")
        return self._fee_resolver.resolve_trade(
            order,
            trade_id=str(update.fill.trade_id),
            price=update.fill.price,
            quantity=update.fill.quantity.value,
            timestamp=update.ts_event,
            liquidity_role=update.fill.liquidity_side.value,
            created_at=update.ts_init.to_datetime(),
            reported_fee=update.fill.reported_fee,
            reporting_mode=update.fill.fee_reporting_mode,
        )

    def _notional(self, trade: OnlyPositionTrade) -> OnlyMoney:
        currency = trade.fee.currency
        quantum = Decimal(1).scaleb(-currency.precision)
        return OnlyMoney(
            (trade.price.value * trade.quantity.value * trade.multiplier.value).quantize(quantum), currency
        )

    def _allocation_snapshot(
        self,
        key: OnlyPositionAllocationKey,
        *,
        include_closed: bool = False,
    ) -> OnlyPositionAllocationSnapshot | None:
        active = self._allocations.get_snapshot(key)
        if active is not None or not include_closed:
            return active
        return next(
            (item for item in reversed(self._allocations.closed()) if item.key == key),
            None,
        )

    def _allocation_money(
        self,
        snapshot: OnlyPositionAllocationSnapshot | None,
        realized: bool,
        currency: OnlyCurrency,
    ) -> OnlyMoney:
        if snapshot is None:
            return OnlyMoney(Decimal(0), currency)
        return snapshot.realized_pnl if realized else snapshot.fees

    def _allocation_cost(
        self,
        snapshot: OnlyPositionAllocationSnapshot | None,
        trade: OnlyPositionTrade,
    ) -> OnlyMoney:
        currency = trade.fee.currency
        if snapshot is None or snapshot.average_open_price is None:
            return OnlyMoney(Decimal(0), currency)
        quantum = Decimal(1).scaleb(-currency.precision)
        return OnlyMoney(
            (snapshot.average_open_price.value * snapshot.total_quantity.value * trade.multiplier.value).quantize(
                quantum
            ),
            currency,
        )

    @staticmethod
    def _trade_fingerprints(update: OnlyBrokerInboundUpdate) -> tuple[str, ...]:
        if not isinstance(update, OnlyBrokerTradeUpdate):
            return ()
        values = [f"trade:{update.fill.trade_id}"]
        if update.fill.venue_trade_id is not None:
            values.append(f"venue_trade:{update.fill.venue_trade_id}")
        return tuple(values)

    def _uses_prepared_trade_path(
        self,
        update: OnlyBrokerTradeUpdate,
        position_scope: OnlyExecutionPositionScope | None = None,
    ) -> bool:
        instruction = self._trade_instructions.get(str(update.fill.trade_id))
        order = self._orders.get(update.order_id)
        account = None if order is None else self._accounts.get_snapshot(order.account_id)
        capability = (
            OnlyExecutionCapability.UNSUPPORTED
            if instruction is None or order is None or account is None or position_scope is None
            else only_resolve_execution_capability(
                operation_kind=OnlyExecutionOperationKind.TRADE_FILL,
                market_profile_id=instruction.compiled_identity.profile_id,
                account_type=account.account_type,
                order_type=order.order_type,
                order_side=order.side,
                offset=order.offset,
                position_side=position_scope.position_side,
                position_effect=position_scope.position_effect,
                position_mode=position_scope.position_mode,
                has_margin=instruction.margin_instruction is not None,
                account_ledger_parity=self._has_account_ledger_parity(order, account),
            )
        )
        return capability is OnlyExecutionCapability.DURABLE_TRADE

    def _uses_prepared_terminal_path(
        self,
        update: OnlyBrokerOrderTerminalUpdate,
        position_scope: OnlyExecutionPositionScope | None = None,
    ) -> bool:
        order = self._orders.get(update.order_id)
        account = None if order is None else self._accounts.get_snapshot(order.account_id)
        if order is None or account is None or position_scope is None or self._market_rules is None:
            return False
        trading_day = (
            self._trading_day(update.ts_event)
            if self._trading_day is not None
            else OnlyTradingDay(update.ts_event.to_datetime().date())
        )
        compiled = self._market_rules.compiled_rules(str(order.instrument_id), trading_day)
        capability = only_resolve_execution_capability(
            operation_kind=OnlyExecutionOperationKind.ORDER_TERMINAL,
            market_profile_id=compiled.identity.profile_id,
            account_type=account.account_type,
            order_type=order.order_type,
            order_side=order.side,
            offset=order.offset,
            position_side=position_scope.position_side,
            position_effect=position_scope.position_effect,
            position_mode=position_scope.position_mode,
            has_margin=compiled.margin_policy is not None,
            account_ledger_parity=self._has_account_ledger_parity(order, account),
        )
        return capability is OnlyExecutionCapability.DURABLE_TERMINAL

    def _has_account_ledger_parity(self, order: OnlyOrderSnapshot, account: OnlyAccountSnapshot) -> bool:
        ledger = self._ledger_locator.require_snapshot(
            runtime_id=order.runtime_id,
            account_id=order.account_id,
            cluster_id=order.cluster_id,
            currency=account.base_currency,
        )
        return (
            account.cash.cash_balance == ledger.cash.cash_balance
            and account.position_market_value == ledger.equity.position_market_value
        )

    def _resolve_position_scope(self, update: OnlyBrokerInboundUpdate) -> OnlyExecutionPositionScope | None:
        if isinstance(update, OnlyBrokerPositionUpdate):
            return self._position_scope_resolver.resolve_broker_position(
                update.account_id, update.snapshot.instrument_id, update.snapshot.position_side
            )
        order_id = getattr(update, "order_id", None)
        if not isinstance(order_id, OnlyOrderId):
            return None
        order = self._orders.get(order_id)
        if order is None:
            return None
        if not isinstance(update, OnlyBrokerTradeUpdate) or self._market_rules is None:
            return self._position_scope_resolver.resolve_order(order)
        trading_day = (
            self._trading_day(update.ts_event)
            if self._trading_day is not None
            else OnlyTradingDay(update.ts_event.to_datetime().date())
        )
        fallback = self._position_scope_resolver.resolve_order(order)
        instruction = self._market_rules.build_trade_instruction(
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
                fallback.position_effect,
            )
        )
        self._trade_instructions[str(update.fill.trade_id)] = instruction
        compiled = self._market_rules.compiled_rules(str(order.instrument_id), trading_day)
        mode = (
            OnlyPositionMode.HEDGING
            if compiled.position_policy.mode is OnlyMarketPositionMode.HEDGING
            else OnlyPositionMode.NETTING
        )
        return self._position_scope_resolver.resolve_trade(order, instruction, mode)

    @staticmethod
    def _sequence_scope(update: OnlyBrokerInboundUpdate) -> tuple[str, ...]:
        order_id = getattr(update, "order_id", None)
        suffix = str(order_id) if order_id is not None else type(update).__name__
        return str(update.runtime_id), str(update.gateway_id), str(update.account_id), suffix

    def _local_broker_position(
        self,
        update: OnlyBrokerPositionUpdate,
    ) -> OnlyLocalBrokerPositionSnapshot:
        broker = update.snapshot
        settled_value = broker.available_quantity.value + broker.frozen_quantity.value
        settled = type(broker.quantity)(settled_value, broker.quantity.precision)
        unsettled = type(broker.quantity)(broker.quantity.value - settled_value, broker.quantity.precision)
        return OnlyLocalBrokerPositionSnapshot(
            OnlyGatewayId(str(broker.gateway_id)),
            broker.account_id,
            broker.instrument_id,
            broker.position_side,
            broker.quantity,
            broker.available_quantity,
            broker.frozen_quantity,
            settled,
            unsettled,
            unsettled,
            settled,
            broker.average_price,
            None,
            broker.snapshot_time,
            broker.source_sequence,
        )

    def _processing_event(
        self,
        update: OnlyBrokerInboundUpdate,
        context: OnlyExecutionProcessingContext,
        event_type: str,
    ) -> OnlyEvent:
        return OnlyEvent(
            event_type,
            update.ts_event.to_datetime(),
            self.config.engine_id,
            self.config.runtime_id,
            "execution_processor",
            context.processing_sequence,
            payload={"update_id": str(update.update_id), "update_type": type(update).__name__},
            ts_init=update.ts_init.to_datetime(),
            timestamp_ns=update.ts_event.unix_nanos,
            ts_init_ns=update.ts_init.unix_nanos,
        )

    @staticmethod
    def _failed_step(steps: list[OnlyExecutionMutationRecord]) -> OnlyExecutionMutationStep:
        completed = {item.step for item in steps}
        if OnlyExecutionMutationStep.ORDER not in completed and completed & {
            OnlyExecutionMutationStep.POSITION,
            OnlyExecutionMutationStep.ACCOUNT,
            OnlyExecutionMutationStep.RISK,
        }:
            return OnlyExecutionMutationStep.INVARIANT_CHECK
        for step in (
            OnlyExecutionMutationStep.ORDER,
            OnlyExecutionMutationStep.POSITION,
            OnlyExecutionMutationStep.ALLOCATION,
            OnlyExecutionMutationStep.SETTLEMENT,
            OnlyExecutionMutationStep.MARGIN,
            OnlyExecutionMutationStep.FEE,
            OnlyExecutionMutationStep.ACCOUNT,
            OnlyExecutionMutationStep.STRATEGY_LEDGER,
            OnlyExecutionMutationStep.RESERVATION,
            OnlyExecutionMutationStep.RISK,
            OnlyExecutionMutationStep.INVARIANT_CHECK,
        ):
            if step not in completed:
                return step
        return OnlyExecutionMutationStep.EVENT


class _OnlyExecutionInvariantError(Exception):
    def __init__(self, result: OnlyExecutionInvariantResult) -> None:
        self.result = result
        super().__init__("; ".join(item.message for item in result.violations))
