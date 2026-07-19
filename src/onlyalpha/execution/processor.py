"""Runtime-owned ordered business application of normalized Broker updates."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from decimal import Decimal

from onlyalpha.account.manager import OnlyAccountManager
from onlyalpha.account.models import OnlyAccountMutationResult, OnlyAccountTradeCashFlow
from onlyalpha.account.reconciliation import OnlyAccountReconciliationService
from onlyalpha.broker.updates import (
    OnlyBrokerAccountUpdate,
    OnlyBrokerConnectionUpdate,
    OnlyBrokerInboundUpdate,
    OnlyBrokerOrderAcceptedUpdate,
    OnlyBrokerOrderCancelledUpdate,
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
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.event.model import OnlyEvent
from onlyalpha.market.models import OnlyPositionEffect
from onlyalpha.market.runtime_rules import OnlyTradeApplicationRequest, OnlyTradeInstructionPort
from onlyalpha.order.enums import OnlyOrderApplyResult
from onlyalpha.order.execution.models import (
    OnlyGatewayOrderAcceptedUpdate,
    OnlyGatewayOrderCancelledUpdate,
    OnlyGatewayOrderFillUpdate,
    OnlyGatewayOrderRejectedUpdate,
    OnlyGatewayOrderUpdate,
)
from onlyalpha.order.execution.processor import OnlyOrderUpdateProcessor
from onlyalpha.order.query import OnlyOrderQueryService
from onlyalpha.order.results import OnlyOrderMutationResult
from onlyalpha.position.allocation_manager import OnlyPositionAllocationManager
from onlyalpha.position.enums import OnlyPositionMutationStatus, OnlyPositionSide, OnlySettlementBucket
from onlyalpha.position.identifiers import OnlyGatewayId
from onlyalpha.position.keys import OnlyPositionAllocationKey, OnlyPositionKey
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
from onlyalpha.strategy_ledger.enums import OnlyStrategyFeeType
from onlyalpha.strategy_ledger.identifiers import OnlyStrategyFeeEntryId
from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey
from onlyalpha.strategy_ledger.manager import OnlyStrategyLedgerManager
from onlyalpha.strategy_ledger.models import (
    OnlyStrategyFeeEntry,
    OnlyStrategyLedgerMutationResult,
    OnlyStrategyTradeAccountingInput,
)

from .enums import (
    OnlyExecutionFailureCode,
    OnlyExecutionMutationStatus,
    OnlyExecutionMutationStep,
    OnlyExecutionProcessingStatus,
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
from .publisher import OnlyExecutionEventPublisher
from .state import (
    OnlyExecutionAuditStore,
    OnlyExecutionReconciliationPort,
    OnlyExecutionSequenceTracker,
    OnlyExecutionUpdateDeduplicator,
)

OnlyExecutionValuation = Callable[[OnlyStrategyLedgerKey, OnlyPositionTrade], None]
OnlyAccountValuation = Callable[[OnlyPositionTrade], None]
OnlyAccountReservationConsumer = Callable[[OnlyOrderFill, OnlyTimestamp], None]
OnlyAccountReservationReleaser = Callable[[OnlyOrderId, OnlyTimestamp], None]
OnlyConnectionStateConsumer = Callable[[object], None]
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
        accounts: OnlyAccountManager,
        risk: OnlyRiskService,
        position_reservations: OnlyPositionReservationManager,
        position_reservation_port: OnlyOrderPositionReservationAdapter,
        consume_account_reservation: OnlyAccountReservationConsumer,
        release_account_reservation: OnlyAccountReservationReleaser,
        position_reconciliation: OnlyPositionReconciliationService,
        account_reconciliation: OnlyAccountReconciliationService,
        invariant_checker: OnlyExecutionInvariantChecker,
        event_publisher: OnlyExecutionEventPublisher,
        audit_store: OnlyExecutionAuditStore,
        reconciliation: OnlyExecutionReconciliationPort,
        deduplicator: OnlyExecutionUpdateDeduplicator,
        sequence_tracker: OnlyExecutionSequenceTracker,
        strategy_valuation: OnlyExecutionValuation,
        account_valuation: OnlyAccountValuation,
        connection_state: OnlyConnectionStateConsumer,
        base_currency: object,
        market_rules: OnlyTradeInstructionPort | None = None,
    ) -> None:
        self.config = config
        self._clock = clock
        self._instruments = instruments
        self._orders = orders
        self._order_updates = order_updates
        self._positions = positions
        self._allocations = allocations
        self._ledgers = ledgers
        self._accounts = accounts
        self._risk = risk
        self._position_reservations = position_reservations
        self._position_reservation_port = position_reservation_port
        self._consume_account_reservation = consume_account_reservation
        self._release_account_reservation = release_account_reservation
        self._position_reconciliation = position_reconciliation
        self._account_reconciliation = account_reconciliation
        self._invariants = invariant_checker
        self._events = event_publisher
        self._audit = audit_store
        self._reconciliation = reconciliation
        self._deduplicator = deduplicator
        self._sequences = sequence_tracker
        self._strategy_valuation = strategy_valuation
        self._account_valuation = account_valuation
        self._connection_state = connection_state
        self._base_currency = base_currency
        self._market_rules = market_rules
        self._processing_sequence = 0

    def process(self, update: OnlyBrokerInboundUpdate) -> OnlyExecutionProcessingResult:
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
        if self._deduplicator.contains_update(update.update_id):
            return self._terminal(update, context, OnlyExecutionProcessingStatus.DUPLICATE)
        trade_fingerprints = self._trade_fingerprints(update)
        if trade_fingerprints and self._deduplicator.contains_trade(trade_fingerprints):
            self._deduplicator.remember(update.update_id)
            return self._terminal(update, context, OnlyExecutionProcessingStatus.DUPLICATE)
        scope = self._sequence_scope(update)
        stale = self._sequences.is_stale(scope, update.source_sequence)
        if stale and isinstance(update, OnlyBrokerTradeUpdate):
            failure = OnlyExecutionFailure(
                OnlyExecutionFailureCode.OUT_OF_ORDER_TRADE,
                "out-of-order Trade cannot be safely applied",
                OnlyExecutionMutationStep.VALIDATION,
            )
            request = self._make_reconciliation(update, (), OnlyExecutionMutationStep.VALIDATION, failure.message)
            self._deduplicator.remember(update.update_id, trade_fingerprints)
            self._reconciliation.request_reconciliation(request)
            return self._terminal(
                update,
                context,
                OnlyExecutionProcessingStatus.RECONCILIATION_REQUIRED,
                failure=failure,
                reconciliation=request,
                quality_flags=("OUT_OF_ORDER",),
            )
        self._events.begin()
        steps: list[OnlyExecutionMutationRecord] = [
            OnlyExecutionMutationRecord(
                OnlyExecutionMutationStep.VALIDATION, OnlyExecutionMutationStatus.APPLIED, "scope and plan valid"
            )
        ]
        try:
            payload = self._dispatch(update, stale, steps)
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
                )
                self._reconciliation.request_reconciliation(reconciliation)
            self._deduplicator.remember(update.update_id, trade_fingerprints)
            self._sequences.observe(scope, update.source_sequence)
            event_type = (
                "EXECUTION_RECONCILIATION_REQUIRED" if reconciliation is not None else "EXECUTION_UPDATE_APPLIED"
            )
            applied_event = self._processing_event(update, context, event_type)
            self._events.publish(applied_event)
            steps.append(
                OnlyExecutionMutationRecord(
                    OnlyExecutionMutationStep.EVENT, OnlyExecutionMutationStatus.APPLIED, "facts committed"
                )
            )
            generated = self._events.commit()
            return self._complete(
                update,
                context,
                status,
                steps,
                payload,
                generated,
                invariant,
                reconciliation,
            )
        except Exception as exc:
            self._events.rollback()
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
            )
            self._block_scope(update)
            self._deduplicator.remember(update.update_id, trade_fingerprints)
            self._sequences.observe(scope, update.source_sequence)
            self._reconciliation.request_reconciliation(request)
            failure_events = (
                self._processing_event(update, context, "EXECUTION_PROCESSING_FAILED"),
                self._processing_event(update, context, "EXECUTION_RECONCILIATION_REQUIRED"),
            )
            self._events.publish_many(failure_events)
            return self._terminal(
                update,
                context,
                OnlyExecutionProcessingStatus.RECONCILIATION_REQUIRED,
                steps=tuple(steps),
                failure=failure,
                reconciliation=request,
                generated_events=failure_events,
                invariant=exc.result if isinstance(exc, _OnlyExecutionInvariantError) else None,
                quality_flags=("PARTIAL_MUTATION",),
            )

    def process_many(self, updates: tuple[OnlyBrokerInboundUpdate, ...]) -> tuple[OnlyExecutionProcessingResult, ...]:
        return tuple(self.process(update) for update in updates)

    def _dispatch(
        self,
        update: OnlyBrokerInboundUpdate,
        stale: bool,
        steps: list[OnlyExecutionMutationRecord],
    ) -> OnlyExecutionDispatchPayload:
        if isinstance(update, OnlyBrokerOrderAcceptedUpdate):
            return self._accepted(update, stale, steps)
        if isinstance(update, OnlyBrokerOrderRejectedUpdate):
            return self._terminal_order(update, steps, rejected=True)
        if isinstance(update, OnlyBrokerOrderCancelledUpdate):
            return self._terminal_order(update, steps, rejected=False)
        if isinstance(update, OnlyBrokerTradeUpdate):
            return self._trade(update, steps)
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
            self._events.publish_many(result.events)
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
        update: OnlyBrokerOrderRejectedUpdate | OnlyBrokerOrderCancelledUpdate,
        steps: list[OnlyExecutionMutationRecord],
        *,
        rejected: bool,
    ) -> OnlyExecutionDispatchPayload:
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
            assert isinstance(update, OnlyBrokerOrderCancelledUpdate)
            gateway_update = OnlyGatewayOrderCancelledUpdate(
                runtime_id=self.config.runtime_id,
                order_id=update.order_id,
                ts_event=update.ts_event,
                ts_init=update.ts_init,
                external_sequence=update.source_sequence,
                external_event_id=str(update.update_id),
                metadata=update.metadata,
            )
            reason = OnlyRiskReleaseReason.ORDER_CANCELLED
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
            self._events.publish_many(result.events)
            self._position_reservation_port.release(result.order_id, update.ts_init, broker_confirmed=True)
            self._release_account_reservation(result.order_id, update.ts_init)
            ledger_key = OnlyStrategyLedgerKey(
                self.config.runtime_id,
                update.account_id,
                result.snapshot.cluster_id,
                self._ledgers.list_ledgers()[0].key.base_currency,
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

    def _trade(
        self,
        update: OnlyBrokerTradeUpdate,
        steps: list[OnlyExecutionMutationRecord],
    ) -> OnlyExecutionDispatchPayload:
        order = self._orders.require(update.order_id)
        trade = self._position_trade(update, order)
        if trade.cluster_id is None:
            raise ValueError("strategy Trade requires Cluster attribution")
        allocation_key = OnlyPositionAllocationKey(
            trade.runtime_id,
            trade.account_id,
            trade.cluster_id,
            trade.instrument_id,
            trade.position_side,
        )
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
        self._events.publish_many(order_result.events)
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
        allocation_after = self._allocation_snapshot(allocation_key, include_closed=True)
        ledger_key = OnlyStrategyLedgerKey(
            trade.runtime_id,
            trade.account_id,
            trade.cluster_id,
            self._ledgers.list_ledgers()[0].key.base_currency,
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
        ledger_result = self._ledgers.apply_trade_accounting(
            ledger_key,
            OnlyStrategyTradeAccountingInput(
                trade,
                order_result.snapshot,
                allocation_before,
                allocation_after,
                self._allocation_money(allocation_after, True) - self._allocation_money(allocation_before, True),
                self._allocation_cost(allocation_after, trade) - self._allocation_cost(allocation_before, trade),
                (fee_entry,),
                reservation,
                trade.ts_event,
                trade.external_sequence or 0,
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
        notional = self._notional(trade)
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
            )
        )
        self._account_valuation(trade)
        steps.append(
            OnlyExecutionMutationRecord(
                OnlyExecutionMutationStep.ACCOUNT, OnlyExecutionMutationStatus.APPLIED, account_result.status.value
            )
        )
        reservation_results: list[str] = []
        if trade.side is OnlyOrderSide.BUY:
            self._consume_account_reservation(update.fill, trade.ts_init)
            self._ledgers.consume_cash_reservation(ledger_key, trade.order_id, notional + trade.fee, trade.ts_init)
            reservation_results.extend(("ACCOUNT_CASH_CONSUMED", "STRATEGY_CASH_CONSUMED"))
            if order_result.snapshot.status is OnlyOrderStatus.FILLED:
                self._release_account_reservation(trade.order_id, trade.ts_init)
                self._ledgers.release_cash_reservation(ledger_key, trade.order_id, trade.ts_init)
                reservation_results.extend(("ACCOUNT_REMAINDER_RELEASED", "STRATEGY_REMAINDER_RELEASED"))
        else:
            self._position_reservation_port.consume(
                trade.order_id,
                trade.quantity,
                trade.ts_init,
                allocation_hold_already_released=True,
            )
            reservation_results.append("POSITION_CONSUMED")
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
        invariant: OnlyExecutionInvariantResult,
        reconciliation: OnlyExecutionReconciliationRequest | None = None,
    ) -> OnlyExecutionProcessingResult:
        bundle = OnlyExecutionMutationBundle(
            tuple(steps), payload[1], payload[2], payload[3], payload[4], payload[6], payload[7], "UPDATED"
        )
        snapshot = self._snapshot(update, context.processing_sequence)
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
        invariant: OnlyExecutionInvariantResult | None = None,
        quality_flags: tuple[str, ...] = (),
    ) -> OnlyExecutionProcessingResult:
        completed = OnlyTimestamp.from_unix_nanos(self._clock.timestamp_ns())
        invariant_result = invariant or OnlyExecutionInvariantResult(True)
        bundle = OnlyExecutionMutationBundle(tuple(steps))
        snapshot = self._snapshot(update, context.processing_sequence)
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
            audit,
            failure,
            reconciliation,
            tuple(sorted(set(update.quality_flags + tuple(quality_flags)))),
        )

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
        )

    def _snapshot(
        self,
        update: OnlyBrokerInboundUpdate,
        sequence: int,
    ) -> OnlyExecutionSnapshotBundle:
        order_id = getattr(update, "order_id", None)
        order = self._orders.get(order_id) if isinstance(order_id, OnlyOrderId) else None
        account = self._accounts.get_snapshot(update.account_id)
        position = allocation = ledger = risk = None
        if order is not None:
            position = self._positions.get_snapshot(
                OnlyPositionKey(self.config.runtime_id, order.account_id, order.instrument_id, OnlyPositionSide.LONG)
            )
            key = OnlyPositionAllocationKey(
                self.config.runtime_id, order.account_id, order.cluster_id, order.instrument_id, OnlyPositionSide.LONG
            )
            allocation = self._allocation_snapshot(key)
            ledger = next(
                (
                    item
                    for item in self._ledgers.list_ledgers()
                    if item.key.account_id == order.account_id and item.key.cluster_id == order.cluster_id
                ),
                None,
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
        )

    def _make_reconciliation(
        self,
        update: OnlyBrokerInboundUpdate,
        completed_steps: tuple[OnlyExecutionMutationStep, ...],
        failed_step: OnlyExecutionMutationStep,
        reason: str,
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
        )

    def _block_scope(self, update: OnlyBrokerInboundUpdate) -> None:
        order_id = getattr(update, "order_id", None)
        order = self._orders.get(order_id) if isinstance(order_id, OnlyOrderId) else None
        if order is not None:
            key = OnlyPositionKey(self.config.runtime_id, order.account_id, order.instrument_id, OnlyPositionSide.LONG)
            if self._positions.get_snapshot(key) is not None:
                self._positions.set_reconciling(key)
        if self._accounts.get_snapshot(update.account_id) is not None:
            self._events.begin()
            self._accounts.start_reconciliation(update.account_id, update.ts_init, "EXECUTION_PARTIAL_MUTATION")
            self._events.rollback()

    def _position_trade(
        self,
        update: OnlyBrokerTradeUpdate,
        order: OnlyOrderSnapshot,
    ) -> OnlyPositionTrade:
        instrument = self._instruments[order.instrument_id]
        fee = update.fill.fee or OnlyMoney(Decimal(0), instrument.settlement_currency)
        settlement_bucket = (
            OnlySettlementBucket.UNSETTLED if order.side is OnlyOrderSide.BUY else OnlySettlementBucket.SETTLED
        )
        if self._market_rules is not None:
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
                    OnlyTradingDay(update.ts_event.to_datetime().date()),
                    OnlyPositionEffect.OPEN if order.side is OnlyOrderSide.BUY else OnlyPositionEffect.CLOSE,
                )
            )
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
            OnlyOffset.OPEN if order.side is OnlyOrderSide.BUY else OnlyOffset.CLOSE,
            OnlyPositionSide.LONG,
            update.fill.price,
            update.fill.quantity,
            fee,
            update.ts_event,
            update.ts_init,
            update.source_sequence,
            execution_id=str(update.update_id),
            settlement_bucket=settlement_bucket,
            multiplier=instrument.contract_multiplier,
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
    ) -> OnlyMoney:
        currency = self._ledgers.list_ledgers()[0].key.base_currency
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
            OnlyPositionSide.LONG,
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
            OnlyExecutionMutationStep.STRATEGY_LEDGER,
            OnlyExecutionMutationStep.ACCOUNT,
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
