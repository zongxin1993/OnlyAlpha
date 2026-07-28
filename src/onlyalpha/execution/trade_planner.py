"""Deterministic, side-effect-free Generic T0 Cash Trade transaction planner."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import NoReturn

from onlyalpha.account.enums import OnlyAccountReservationState, OnlyAccountStatus, OnlyAccountType
from onlyalpha.account.performance import OnlyAccountEquityPoint, OnlyAccountValuationSource
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderStatus, OnlyOrderType
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyRate
from onlyalpha.event.model import OnlyEvent
from onlyalpha.fee.models import OnlyFeeAuthority, OnlyFeeComponent, OnlyFeeType
from onlyalpha.market.models import OnlyPositionEffect
from onlyalpha.position.enums import OnlyPositionMode, OnlyPositionSide, OnlySettlementBucket
from onlyalpha.position.keys import OnlyPositionAllocationKey, OnlyPositionKey
from onlyalpha.risk.enums import OnlyRiskReservationState
from onlyalpha.strategy_ledger.enums import OnlyStrategyCashReservationState, OnlyStrategyLedgerStatus
from onlyalpha.strategy_ledger.models import OnlyStrategyLedgerEquityPoint, OnlyStrategyValuationLine

from .event_identity import OnlyExecutionTransactionEventFactory
from .identity import only_execution_transaction_id
from .planned_trade import OnlyPlannedTrade
from .planning_context import OnlyTradeExecutionPlanningContext
from .planning_results import (
    OnlyExecutionEventIntent,
    OnlyTradeExecutionPlanningError,
    OnlyTradeExecutionPlanningErrorCode,
)
from .projection import OnlyExecutionProjection, OnlyExecutionProjectionComponent, OnlyValuationExecutionProjection
from .projection_builder import OnlyExecutionProjectionBuilder
from .reducers import (
    OnlyAccountCashReservationTradeReducer,
    OnlyAccountTradeReducer,
    OnlyAllocationTradeReducer,
    OnlyFeeTradeReducer,
    OnlyOrderTradeReducer,
    OnlyPositionTradeReducer,
    OnlyRiskReservationTradeReducer,
    OnlyRiskTradeReducer,
    OnlySettlementTradeReducer,
    OnlyStrategyCashReservationTradeReducer,
    OnlyStrategyLedgerTradeReducer,
    OnlyValuationTradeReducer,
)
from .transaction import OnlyCommittedExecutionFactDraft, OnlyExecutionPrecondition, OnlyPreparedExecutionTransaction

_PROFILE_ID = "GENERIC_T0_CASH"


@dataclass(frozen=True, slots=True)
class _OnlyTradePlan:
    trade: OnlyPlannedTrade
    projections: tuple[OnlyExecutionProjection, ...]
    event_intents: tuple[OnlyExecutionEventIntent, ...]
    fact: OnlyCommittedExecutionFactDraft


class OnlyTradeExecutionTransactionPlanner:
    """Compile one complete immutable authority into a Prepared Transaction."""

    def prepare(self, context: OnlyTradeExecutionPlanningContext) -> OnlyPreparedExecutionTransaction:
        self._validate(context)
        try:
            plan = self._reduce(context)
            transaction_id = only_execution_transaction_id(
                runtime_id=context.update.runtime_id,
                gateway_id=context.update.gateway_id,
                account_id=context.update.account_id,
                broker_update_id=context.update.update_id,
                trade_id=context.update.fill.trade_id,
            )
            preconditions = tuple(
                OnlyExecutionPrecondition(
                    item.identity.component,
                    item.identity.entity_key,
                    item.identity.expected_version,
                    item.identity.expected_state_hash,
                )
                for item in plan.projections
            )
            events = self._events(context, transaction_id, plan.event_intents)
            return OnlyPreparedExecutionTransaction(
                transaction_id,
                context.update.runtime_id,
                context.update.gateway_id,
                context.update.account_id,
                context.update.update_id,
                context.update.fill.trade_id,
                context.update.source_sequence,
                context.prepared_at,
                plan.fact,
                plan.projections,
                events,
                preconditions,
            )
        except OnlyTradeExecutionPlanningError:
            raise
        except (AssertionError, TypeError, ValueError) as exc:
            raise OnlyTradeExecutionPlanningError(
                OnlyTradeExecutionPlanningErrorCode.REDUCTION_INVARIANT_FAILED,
                str(exc),
            ) from exc

    def _reduce(self, context: OnlyTradeExecutionPlanningContext) -> _OnlyTradePlan:
        trade = self._planned_trade(context)
        order = OnlyOrderTradeReducer().reduce(context.order_before, trade, projection_sequence=1)
        position = OnlyPositionTradeReducer().reduce(
            context.position_before,
            trade,
            context.position_creation,
            cycle=context.position_cycle,
            projection_sequence=2,
        )
        allocation = OnlyAllocationTradeReducer().reduce(
            context.allocation_before,
            trade,
            context.allocation_creation,
            cycle=context.allocation_cycle,
            projection_sequence=3,
        )
        settlement = OnlySettlementTradeReducer().reduce(
            context.settlement_before,
            context.trade_instruction.settlement_instruction,
            context.trading_day,
            trade,
            record_sequence=context.settlement_record_sequence,
            projection_sequence=4,
        )
        fee = OnlyFeeTradeReducer().reduce(
            context.fee_before,
            context.fee_instruction,
            trade.instrument_id,
            record_sequence=context.fee_record_sequence,
            projection_sequence=5,
        )
        currency = trade.authoritative_fee.currency
        quantum = Decimal(1).scaleb(-currency.precision)
        if position.after.average_open_price is None:
            raise ValueError("open Position requires average price")
        position_market_value = _money(
            (context.valuation_price.value * position.after.total_quantity.value * trade.multiplier.value).quantize(
                quantum
            ),
            currency,
        )
        position_market_delta = position_market_value - context.account_before.position_market_value
        position_unrealized = _money(
            (
                (context.valuation_price.value - position.after.average_open_price.value)
                * position.after.total_quantity.value
                * trade.multiplier.value
            ).quantize(quantum),
            currency,
        )
        account = OnlyAccountTradeReducer().reduce(
            context.account_before,
            context.account_cash_reservation_before,
            trade,
            position_market_delta,
            position_unrealized,
            projection_sequence=6,
        )
        ledger = OnlyStrategyLedgerTradeReducer().reduce(
            context.strategy_ledger_before,
            context.strategy_cash_reservation_before,
            context.allocation_before,
            allocation.after,
            trade,
            context.valuation_price,
            projection_sequence=7,
        )
        account_reservation = OnlyAccountCashReservationTradeReducer().reduce(
            context.account_cash_reservation_before, trade, projection_sequence=8
        )
        strategy_reservation = OnlyStrategyCashReservationTradeReducer().reduce(
            context.strategy_cash_reservation_before, trade, projection_sequence=9
        )
        risk_reservation = OnlyRiskReservationTradeReducer().reduce(
            context.risk_reservation_before, trade, projection_sequence=10
        )
        risk = OnlyRiskTradeReducer().reduce(context.risk_before, risk_reservation.after, trade, projection_sequence=11)
        valuation = OnlyValuationTradeReducer().reduce(
            context.valuation_before,
            trade,
            account.after.cash_balance,
            account.after.position_market_value,
            account.after.unrealized_pnl,
            projection_sequence=12,
        )
        ledger_projection = replace(
            ledger.projection,
            valuation_lines=(
                OnlyStrategyValuationLine(
                    trade.instrument_id,
                    ledger.after.position_cost,
                    ledger.after.position_market_value,
                    ledger.after.unrealized_pnl,
                    context.valuation_price,
                    valuation.after.version,
                ),
            ),
            identity=replace(ledger.projection.identity, payload_hash="0" * 64),
        )
        ledger_projection = OnlyExecutionProjectionBuilder().finalize(ledger_projection)
        valuation_projection = replace(
            valuation.projection,
            account_equity_points=_account_equity_points(context, trade, account.after),
            strategy_equity_points=_strategy_equity_points(context, trade, ledger.after, allocation.after),
            account_equity_before=context.account_equity_before,
            strategy_equity_before=context.strategy_equity_before,
        )
        valuation_projection = OnlyExecutionProjectionBuilder().finalize(valuation_projection)
        assert isinstance(valuation_projection, OnlyValuationExecutionProjection)
        projections: tuple[OnlyExecutionProjection, ...] = (
            order.projection,
            position.projection,
            allocation.projection,
            settlement.projection,
            fee.projection,
            account.projection,
            ledger_projection,
            account_reservation.projection,
            strategy_reservation.projection,
            risk_reservation.projection,
            risk.projection,
            valuation_projection,
        )
        intents = (
            order.event_intents
            + position.event_intents
            + settlement.event_intents
            + fee.event_intents
            + account.event_intents
            + ledger.event_intents
            + account_reservation.event_intents[:1]
            + strategy_reservation.event_intents[:1]
            + account_reservation.event_intents[1:]
            + strategy_reservation.event_intents[1:]
            + risk.event_intents
        )
        fact = self._fact(
            context, trade, order.after, position.after, allocation.after, settlement.after, account, ledger
        )
        return _OnlyTradePlan(trade, projections, intents, fact)

    @staticmethod
    def _planned_trade(context: OnlyTradeExecutionPlanningContext) -> OnlyPlannedTrade:
        update = context.update
        order = context.order_before
        currency = context.fee_instruction.fee_breakdown.currency
        notional = _money(
            update.fill.price.value * update.fill.quantity.value * context.contract_multiplier.value,
            currency,
        )
        zero = _money(Decimal(0), currency)
        bucket = (
            OnlySettlementBucket.SETTLED
            if context.trade_instruction.settlement_instruction.asset_available_on <= context.trading_day
            else OnlySettlementBucket.UNSETTLED
        )
        return OnlyPlannedTrade(
            update.runtime_id,
            update.gateway_id,
            update.account_id,
            order.cluster_id,
            order.order_id,
            update.fill.trade_id,
            update.update_id,
            order.instrument_id,
            order.side,
            order.order_type,
            order.offset,
            context.position_scope.position_side,
            context.position_scope.position_effect,
            context.position_scope.position_mode,
            bucket,
            update.fill.quantity,
            update.fill.price,
            context.contract_multiplier,
            notional,
            notional if context.trade_instruction.cash_instruction.settle_notional else zero,
            context.fee_instruction.fee_breakdown.total,
            update.fill,
            update.fill.liquidity_side,
            update.ts_event,
            update.ts_init,
            context.trading_day,
            update.source_sequence,
            (update.source_sequence, update.ts_event.unix_nanos, str(update.fill.trade_id)),
        )

    @staticmethod
    def _fact(
        context: OnlyTradeExecutionPlanningContext,
        trade: OnlyPlannedTrade,
        order_after: object,
        position_after: object,
        allocation_after: object,
        settlement_after: object,
        account: object,
        ledger: object,
    ) -> OnlyCommittedExecutionFactDraft:
        from .execution_state import OnlyAllocationExecutionState, OnlyOrderExecutionState, OnlyPositionExecutionState
        from .projection import OnlySettlementExecutionState
        from .reducers.trade_accounting import OnlyAccountTradeReduction, OnlyStrategyLedgerTradeReduction

        assert isinstance(order_after, OnlyOrderExecutionState)
        assert isinstance(position_after, OnlyPositionExecutionState)
        assert isinstance(allocation_after, OnlyAllocationExecutionState)
        assert isinstance(settlement_after, OnlySettlementExecutionState)
        assert isinstance(account, OnlyAccountTradeReduction)
        assert isinstance(ledger, OnlyStrategyLedgerTradeReduction)
        update = context.update
        fee = context.fee_instruction
        components = fee.fee_breakdown.components
        currency = fee.fee_breakdown.currency
        zero = _money(Decimal(0), currency)
        market_components = tuple(item for item in components if item.authority is not OnlyFeeAuthority.BROKER)
        broker_components = tuple(item for item in components if item.authority is OnlyFeeAuthority.BROKER)
        market_fee = _sum_fee(currency, market_components)
        broker_fee = _sum_fee(currency, broker_components)
        tax = _sum_fee(currency, tuple(item for item in components if item.fee_type is OnlyFeeType.STAMP_DUTY))
        commission = _sum_fee(
            currency, tuple(item for item in components if item.fee_type is OnlyFeeType.BROKER_COMMISSION)
        )
        other = _money(fee.fee_breakdown.total.amount - tax.amount - commission.amount, currency)
        direction = Decimal(1)
        slippage = None
        if trade.fill.reference_price is not None:
            slippage = _money(
                direction
                * (trade.price.value - trade.fill.reference_price.value)
                * trade.quantity.value
                * trade.multiplier.value,
                currency,
            )
        position_before_quantity = (
            Decimal(0) if context.position_before is None else context.position_before.total_quantity.value
        )
        allocation_before_quantity = (
            Decimal(0) if context.allocation_before is None else context.allocation_before.total_quantity.value
        )
        settlement_status = "SETTLED" if settlement_after.legal_settled else "PENDING"
        identity = context.trade_instruction.compiled_identity
        return OnlyCommittedExecutionFactDraft(
            execution_id=_execution_id(context),
            trade_id=trade.trade_id,
            venue_trade_id=None if trade.fill.venue_trade_id is None else str(trade.fill.venue_trade_id),
            order_id=trade.order_id,
            client_order_id=str(order_after.client_order_id),
            request_id=str(order_after.request_id),
            broker_update_id=trade.broker_update_id,
            runtime_id=trade.runtime_id,
            gateway_id=trade.gateway_id,
            account_id=trade.account_id,
            cluster_id=trade.cluster_id,
            strategy_id=context.strategy_id,
            instrument_id=trade.instrument_id,
            venue_id=identity.venue,
            source_sequence=trade.source_sequence,
            processing_sequence=context.processing_sequence,
            correlation_id=update.correlation_id,
            causation_id=update.causation_id,
            external_event_id=trade.fill.external_event_id,
            ts_event=trade.ts_event,
            ts_init=trade.ts_init,
            trading_day=trade.trading_day,
            order_side=trade.side,
            order_type=trade.order_type,
            offset=trade.offset,
            position_side=trade.position_side,
            position_effect=trade.position_effect,
            position_mode=trade.position_mode,
            liquidity_side=trade.liquidity_side,
            fill_quantity=trade.quantity,
            fill_price=trade.price,
            cumulative_filled_quantity=order_after.filled_quantity,
            remaining_quantity=order_after.remaining_quantity,
            order_status_after=order_after.status,
            currency=currency,
            contract_multiplier=trade.multiplier,
            gross_notional=trade.gross_notional,
            settled_notional=trade.settled_notional,
            authoritative_fee_total=trade.authoritative_fee,
            market_fee=market_fee,
            broker_fee=broker_fee,
            tax=tax,
            commission=commission,
            other_fee=other,
            reported_broker_fee=trade.fill.reported_fee,
            fee_reporting_mode=trade.fill.fee_reporting_mode,
            reference_price=trade.fill.reference_price,
            slippage=slippage,
            realized_pnl_delta=zero,
            cash_delta=account.cash_delta,
            fee_instruction_id=fee.instruction_id,
            fee_authority="+".join(sorted({item.authority.value for item in components})) or "NONE",
            fee_status=fee.fee_breakdown.status.value,
            market_fee_schedule_ids=_schedule_values(market_components, "schedule_id"),
            market_fee_schedule_versions=_schedule_values(market_components, "schedule_version"),
            broker_fee_schedule_ids=_schedule_values(broker_components, "schedule_id"),
            broker_fee_schedule_versions=_schedule_values(broker_components, "schedule_version"),
            fee_breakdown=fee.fee_breakdown,
            market_profile_id=identity.profile_id,
            market_profile_version=identity.profile_version,
            compiled_rule_fingerprint=identity.compiled_rules_fingerprint,
            reference_fingerprint=identity.reference_fingerprint,
            trade_instruction_id=_trade_instruction_id(context),
            settlement_instruction_id=settlement_after.instruction_id,
            settlement_status=settlement_status,
            asset_available_on=settlement_after.asset_available_on,
            cash_available_on=settlement_after.cash_trade_available_on,
            legal_settlement_date=settlement_after.legal_settlement_on,
            margin_instruction_id=None,
            margin_action=None,
            margin_currency=None,
            margin_amount=None,
            reserved_margin_delta=None,
            occupied_margin_delta=None,
            released_margin_delta=None,
            maintenance_margin_after=None,
            position_quantity_delta=position_after.total_quantity.value - position_before_quantity,
            position_realized_pnl_delta=zero,
            allocation_quantity_delta=allocation_after.total_quantity.value - allocation_before_quantity,
            account_cash_delta=account.cash_delta,
            account_fee_delta=account.fee_delta,
            account_realized_pnl_delta=zero,
            ledger_cash_delta=ledger.cash_delta,
            ledger_fee_delta=ledger.fee_delta,
            ledger_realized_pnl_delta=zero,
        )

    @staticmethod
    def _events(
        context: OnlyTradeExecutionPlanningContext,
        transaction_id: str,
        intents: tuple[OnlyExecutionEventIntent, ...],
    ) -> tuple[OnlyEvent, ...]:
        factory = OnlyExecutionTransactionEventFactory()
        return tuple(
            factory.create(
                transaction_id=transaction_id,
                event_sequence=sequence,
                event_type=intent.event_type,
                timestamp=_event_timestamp(context, intent).to_datetime(),
                engine_id=context.engine_id,
                runtime_id=context.update.runtime_id,
                cluster_id=context.order_before.cluster_id,
                source=intent.source,
                payload=intent.payload,
                ts_init=_event_initialized_at(context, intent).to_datetime(),
                metadata={"broker_update_id": str(context.update.update_id)},
            )
            for sequence, intent in enumerate(intents, start=1)
        )

    @staticmethod
    def _validate(context: OnlyTradeExecutionPlanningContext) -> None:
        mandatory_before = (
            context.order_before,
            context.account_before,
            context.strategy_ledger_before,
            context.account_cash_reservation_before,
            context.strategy_cash_reservation_before,
            context.risk_reservation_before,
            context.risk_before,
            context.valuation_before,
        )
        if any(item is None for item in mandatory_before):
            _fail(
                OnlyTradeExecutionPlanningErrorCode.MISSING_BEFORE_STATE,
                "Planning Context is missing mandatory before authority",
            )
        update = context.update
        order = context.order_before
        scope = context.position_scope
        instruction = context.trade_instruction
        fee = context.fee_instruction
        if instruction.compiled_identity.profile_id != _PROFILE_ID:
            _fail(OnlyTradeExecutionPlanningErrorCode.UNSUPPORTED_MARKET_PROFILE, "only GENERIC_T0_CASH is supported")
        if context.account_before.account_type is not OnlyAccountType.CASH:
            _fail(
                OnlyTradeExecutionPlanningErrorCode.UNSUPPORTED_MARKET_PROFILE,
                "Generic T0 planning requires a cash Account",
            )
        if order.order_type is not OnlyOrderType.LIMIT:
            _fail(OnlyTradeExecutionPlanningErrorCode.UNSUPPORTED_ORDER_TYPE, "only LIMIT is supported")
        if order.side is not OnlyOrderSide.BUY:
            _fail(OnlyTradeExecutionPlanningErrorCode.UNSUPPORTED_ORDER_SIDE, "only BUY is supported")
        if order.offset is not OnlyOffset.OPEN:
            _fail(OnlyTradeExecutionPlanningErrorCode.UNSUPPORTED_OFFSET, "only OPEN is supported")
        if scope.position_side is not OnlyPositionSide.LONG:
            _fail(OnlyTradeExecutionPlanningErrorCode.UNSUPPORTED_POSITION_SIDE, "only LONG is supported")
        if scope.position_mode is not OnlyPositionMode.NETTING:
            _fail(OnlyTradeExecutionPlanningErrorCode.UNSUPPORTED_POSITION_MODE, "only NETTING is supported")
        if instruction.margin_instruction is not None or context.margin_reservation_before is not None:
            _fail(OnlyTradeExecutionPlanningErrorCode.MARGIN_UNSUPPORTED, "Margin is not supported")
        if context.position_reservation_before is not None:
            _fail(
                OnlyTradeExecutionPlanningErrorCode.POSITION_RESERVATION_FORBIDDEN,
                "BUY OPEN cannot carry a Position Reservation",
            )
        if update.fill.quantity != order.remaining_quantity or order.filled_quantity.value != 0:
            _fail(OnlyTradeExecutionPlanningErrorCode.PARTIAL_FILL_UNSUPPORTED, "Fill must complete an unfilled Order")
        if (
            update.fill.ts_event != update.ts_event
            or update.fill.ts_init != update.ts_init
            or update.fill.quantity.precision != order.quantity.precision
            or (order.price is not None and update.fill.price.precision != order.price.precision)
            or (update.fill.external_sequence is not None and update.fill.external_sequence != update.source_sequence)
        ):
            _fail(
                OnlyTradeExecutionPlanningErrorCode.SCOPE_MISMATCH,
                "Fill precision, time, or external sequence disagrees",
            )
        if order.status not in {OnlyOrderStatus.SUBMITTED, OnlyOrderStatus.ACCEPTED, OnlyOrderStatus.PENDING_CANCEL}:
            _fail(OnlyTradeExecutionPlanningErrorCode.INVALID_ORDER_STATE, "Order does not accept a Fill")
        if order.last_external_sequence is not None and update.source_sequence <= order.last_external_sequence:
            _fail(OnlyTradeExecutionPlanningErrorCode.STALE_EXTERNAL_SEQUENCE, "Broker sequence must advance")
        if context.prepared_at < update.ts_event:
            _fail(OnlyTradeExecutionPlanningErrorCode.SCOPE_MISMATCH, "prepared_at precedes Broker event")
        if update.fill.order_id != update.order_id or update.order_id != order.order_id:
            _fail(OnlyTradeExecutionPlanningErrorCode.SCOPE_MISMATCH, "Order scope disagrees")
        scope_values = (
            update.runtime_id == order.runtime_id == scope.runtime_id,
            update.account_id == order.account_id == scope.account_id,
            order.cluster_id == scope.cluster_id,
            order.instrument_id == scope.instrument_id,
            scope.position_key == _position_key(context),
            scope.allocation_key == _allocation_key(context),
        )
        if not all(scope_values):
            _fail(
                OnlyTradeExecutionPlanningErrorCode.SCOPE_MISMATCH, "Runtime/Account/Cluster/Instrument scope disagrees"
            )
        position_instruction = instruction.position_instruction
        settlement = instruction.settlement_instruction
        expected_notional = _money(
            update.fill.price.value * update.fill.quantity.value * context.contract_multiplier.value,
            fee.fee_breakdown.currency,
        )
        if (
            position_instruction.instrument_id != str(order.instrument_id)
            or position_instruction.source_order_id != str(order.order_id)
            or position_instruction.source_trade_id != str(update.fill.trade_id)
            or position_instruction.position_side != scope.position_side.value
            or position_instruction.position_effect is not OnlyPositionEffect.OPEN
            or position_instruction.quantity != update.fill.quantity.value
            or position_instruction.price != update.fill.price.value
            or settlement.account_id != str(order.account_id)
            or settlement.instrument_id != str(order.instrument_id)
            or settlement.source_order_id != str(order.order_id)
            or settlement.source_trade_id != str(update.fill.trade_id)
            or settlement.asset_quantity != update.fill.quantity.value
            or settlement.cash_amount != expected_notional.amount
        ):
            _fail(OnlyTradeExecutionPlanningErrorCode.SCOPE_MISMATCH, "Market instruction scope disagrees")
        if (
            fee.runtime_id != str(update.runtime_id)
            or fee.account_id != str(update.account_id)
            or fee.cluster_id != str(order.cluster_id)
            or fee.order_id != str(order.order_id)
            or fee.trade_id != str(update.fill.trade_id)
        ):
            _fail(OnlyTradeExecutionPlanningErrorCode.SCOPE_MISMATCH, "Fee instruction scope disagrees")
        currency = fee.fee_breakdown.currency
        monies = (
            context.account_before.cash_balance,
            context.strategy_ledger_before.cash_balance,
            context.account_cash_reservation_before.reserved_amount,
            context.strategy_cash_reservation_before.reserved_amount,
            context.risk_reservation_before.reserved_notional,
            context.valuation_before.cash,
        )
        if any(item is None or item.currency != currency for item in monies):
            _fail(OnlyTradeExecutionPlanningErrorCode.CURRENCY_MISMATCH, "Planning authority requires one Currency")
        optional_risk_money = (
            context.risk_before.reserved_notional,
            context.risk_before.remaining_order_notional,
        )
        if any(item is not None and item.currency != currency for item in optional_risk_money):
            _fail(OnlyTradeExecutionPlanningErrorCode.CURRENCY_MISMATCH, "Risk authority Currency disagrees")
        if (
            context.account_before.cash_balance != context.strategy_ledger_before.cash_balance
            or context.account_before.position_market_value != context.strategy_ledger_before.position_market_value
            or context.valuation_before.cash != context.account_before.cash_balance
            or context.valuation_before.position_market_value != context.account_before.position_market_value
            or context.valuation_before.unrealized_pnl != context.account_before.unrealized_pnl
        ):
            _fail(
                OnlyTradeExecutionPlanningErrorCode.REDUCTION_INVARIANT_FAILED,
                "Account, Ledger, Valuation, or Risk before authority is inconsistent",
            )
        if instruction.cash_instruction.currency != currency.code:
            _fail(OnlyTradeExecutionPlanningErrorCode.CURRENCY_MISMATCH, "Cash instruction Currency disagrees")
        if (
            not instruction.cash_instruction.settle_notional
            or instruction.cash_instruction.amount != -expected_notional.amount
            or instruction.cash_instruction.available_on != settlement.cash_trade_available_on
        ):
            _fail(
                OnlyTradeExecutionPlanningErrorCode.SCOPE_MISMATCH,
                "Cash instruction disagrees with Generic cash settlement",
            )
        if context.settlement_before is not None and (
            context.settlement_before.instruction_id != settlement.instruction_id
            or context.settlement_before.source_trade_id != str(update.fill.trade_id)
        ):
            _fail(
                OnlyTradeExecutionPlanningErrorCode.SCOPE_MISMATCH,
                "Settlement before authority belongs to another instruction",
            )
        if context.fee_before is not None and (
            context.fee_before.instruction.instruction_id != fee.instruction_id
            or context.fee_before.instruction.idempotency_key != fee.idempotency_key
        ):
            _fail(
                OnlyTradeExecutionPlanningErrorCode.SCOPE_MISMATCH,
                "Fee before authority belongs to another instruction",
            )
        if context.account_before.status not in {OnlyAccountStatus.ACTIVE, OnlyAccountStatus.RECONCILING}:
            _fail(OnlyTradeExecutionPlanningErrorCode.MISSING_BEFORE_STATE, "Account is not processable")
        if context.strategy_ledger_before.status not in {
            OnlyStrategyLedgerStatus.ACTIVE,
            OnlyStrategyLedgerStatus.RECONCILING,
        }:
            _fail(OnlyTradeExecutionPlanningErrorCode.MISSING_BEFORE_STATE, "Strategy Ledger is not processable")
        if (
            context.account_cash_reservation_before.state is not OnlyAccountReservationState.ACTIVE
            or context.strategy_cash_reservation_before.state is not OnlyStrategyCashReservationState.ACTIVE
            or context.risk_reservation_before.state is not OnlyRiskReservationState.ACTIVE
        ):
            _fail(OnlyTradeExecutionPlanningErrorCode.INVALID_RESERVATION_STATE, "Reservation is not ACTIVE")
        stable_order = (update.source_sequence, update.ts_event.unix_nanos, str(update.fill.trade_id))
        if any(
            previous is not None and stable_order <= previous
            for previous in (
                None if context.position_before is None else context.position_before.last_trade_order,
                None if context.allocation_before is None else context.allocation_before.last_trade_order,
                context.strategy_ledger_before.last_trade_order,
            )
        ):
            _fail(
                OnlyTradeExecutionPlanningErrorCode.STALE_EXTERNAL_SEQUENCE,
                "Trade stable order must advance all before states",
            )
        _validate_reservation_scope(context)
        _validate_creation(context)


def _validate_creation(context: OnlyTradeExecutionPlanningContext) -> None:
    scope = context.position_scope
    if context.position_before is None:
        position_creation = context.position_creation
        if position_creation is None:
            _fail(
                OnlyTradeExecutionPlanningErrorCode.MISSING_CREATION_AUTHORITY,
                "Position creation authority is required",
            )
        expected = (
            f"POS-{scope.runtime_id}-{scope.account_id}-{scope.instrument_id}-"
            f"{scope.position_side.value}-{position_creation.cycle:08d}"
        )
        if str(position_creation.position_id) != expected:
            _fail(OnlyTradeExecutionPlanningErrorCode.SCOPE_MISMATCH, "Position creation identity disagrees")
    elif context.position_creation is not None:
        _fail(OnlyTradeExecutionPlanningErrorCode.UNEXPECTED_CREATION_AUTHORITY, "Position already exists")
    elif context.position_before.key != scope.position_key:
        _fail(OnlyTradeExecutionPlanningErrorCode.SCOPE_MISMATCH, "Position before scope disagrees")
    if context.allocation_before is None:
        allocation_creation = context.allocation_creation
        if allocation_creation is None:
            _fail(
                OnlyTradeExecutionPlanningErrorCode.MISSING_CREATION_AUTHORITY,
                "Allocation creation authority is required",
            )
        expected = (
            f"ALLOC-{scope.runtime_id}-{scope.account_id}-{scope.cluster_id}-"
            f"{scope.instrument_id}-{allocation_creation.cycle:08d}"
        )
        if str(allocation_creation.allocation_id) != expected:
            _fail(OnlyTradeExecutionPlanningErrorCode.SCOPE_MISMATCH, "Allocation creation identity disagrees")
    elif context.allocation_creation is not None:
        _fail(OnlyTradeExecutionPlanningErrorCode.UNEXPECTED_CREATION_AUTHORITY, "Allocation already exists")
    elif context.allocation_before.key != scope.allocation_key:
        _fail(OnlyTradeExecutionPlanningErrorCode.SCOPE_MISMATCH, "Allocation before scope disagrees")


def _validate_reservation_scope(context: OnlyTradeExecutionPlanningContext) -> None:
    update = context.update
    order = context.order_before
    account = context.account_cash_reservation_before
    strategy = context.strategy_cash_reservation_before
    risk = context.risk_reservation_before
    if (
        account.runtime_id != update.runtime_id
        or account.account_id != update.account_id
        or account.order_id != update.order_id
        or strategy.key != context.strategy_ledger_before.key
        or strategy.order_id != update.order_id
        or risk.runtime_id != update.runtime_id
        or risk.account_id != update.account_id
        or risk.cluster_id != order.cluster_id
        or risk.instrument_id != order.instrument_id
        or risk.order_id != order.order_id
        or context.risk_before.runtime_id != order.runtime_id
        or context.risk_before.cluster_id != order.cluster_id
        or context.risk_before.account_id != order.account_id
        or context.valuation_before.account_id != order.account_id
    ):
        _fail(OnlyTradeExecutionPlanningErrorCode.SCOPE_MISMATCH, "Reservation/Risk/Valuation scope disagrees")


def _position_key(context: OnlyTradeExecutionPlanningContext) -> OnlyPositionKey:
    scope = context.position_scope
    return OnlyPositionKey(
        scope.runtime_id, scope.account_id, scope.instrument_id, scope.position_side, scope.position_mode
    )


def _allocation_key(context: OnlyTradeExecutionPlanningContext) -> OnlyPositionAllocationKey:
    scope = context.position_scope
    assert scope.cluster_id is not None
    return OnlyPositionAllocationKey(
        scope.runtime_id, scope.account_id, scope.cluster_id, scope.instrument_id, scope.position_side
    )


def _execution_id(context: OnlyTradeExecutionPlanningContext) -> str:
    fill = context.update.fill
    authority = "|".join(
        (
            str(context.update.runtime_id),
            str(context.update.gateway_id),
            str(context.update.account_id),
            str(fill.trade_id),
            "" if fill.venue_trade_id is None else str(fill.venue_trade_id),
        )
    )
    return f"EXEC-{hashlib.sha256(authority.encode('utf-8')).hexdigest()}"


def _trade_instruction_id(context: OnlyTradeExecutionPlanningContext) -> str:
    instruction = context.trade_instruction
    authority = "|".join(
        (
            instruction.settlement_instruction.instruction_id,
            instruction.compiled_identity.compiled_rules_fingerprint,
            instruction.position_instruction.position_side,
            instruction.position_instruction.position_effect.value,
        )
    )
    return f"TINSTR-{hashlib.sha256(authority.encode('utf-8')).hexdigest()}"


def _schedule_values(components: tuple[OnlyFeeComponent, ...], field: str) -> tuple[str, ...]:
    return tuple(sorted({value for item in components if (value := getattr(item, field)) is not None}))


def _sum_fee(currency: OnlyCurrency, components: tuple[OnlyFeeComponent, ...]) -> OnlyMoney:
    return _money(sum((item.amount.amount for item in components), Decimal(0)), currency)


def _money(amount: Decimal, currency: OnlyCurrency) -> OnlyMoney:
    return OnlyMoney(amount.quantize(Decimal(1).scaleb(-currency.precision)), currency)


def _rate(value: Decimal) -> OnlyRate:
    return OnlyRate(value.quantize(Decimal("0.00000001")), 8)


def _account_equity_points(
    context: OnlyTradeExecutionPlanningContext,
    trade: OnlyPlannedTrade,
    after: object,
) -> tuple[OnlyAccountEquityPoint, ...]:
    from .execution_state import OnlyAccountExecutionState

    if not isinstance(after, OnlyAccountExecutionState):
        raise TypeError("Account replay points require Account execution state")
    external = context.account_external_cash_flow or _money(Decimal(0), after.base_currency)
    values = (
        (
            context.account_before.position_market_value,
            context.account_before.unrealized_pnl,
            OnlyAccountValuationSource.COMMITTED_EXECUTION,
        ),
        (after.position_market_value, after.unrealized_pnl, OnlyAccountValuationSource.MARKET_VALUATION),
        (after.position_market_value, after.unrealized_pnl, OnlyAccountValuationSource.STATE_CHANGE),
        (after.position_market_value, after.unrealized_pnl, OnlyAccountValuationSource.STATE_CHANGE),
    )
    start_version = after.version - 3
    return tuple(
        OnlyAccountEquityPoint(
            context.account_equity_sequence + index,
            after.runtime_id,
            after.account_id,
            trade.ts_init,
            None,
            after.base_currency,
            after.cash_balance,
            market_value,
            after.realized_pnl,
            unrealized,
            after.fees,
            after.cash_balance + market_value,
            external,
            source,
            start_version + index - 1,
            after.quality_flags,
        )
        for index, (market_value, unrealized, source) in enumerate(values, start=1)
    )


def _strategy_equity_points(
    context: OnlyTradeExecutionPlanningContext,
    trade: OnlyPlannedTrade,
    after: object,
    allocation_after: object,
) -> tuple[OnlyStrategyLedgerEquityPoint, ...]:
    from .execution_state import OnlyAllocationExecutionState, OnlyStrategyLedgerExecutionState

    if not isinstance(after, OnlyStrategyLedgerExecutionState) or not isinstance(
        allocation_after, OnlyAllocationExecutionState
    ):
        raise TypeError("Strategy replay points require Ledger execution state")
    stage_market = _money(
        trade.price.value * allocation_after.total_quantity.value * trade.multiplier.value,
        after.key.base_currency,
    )
    stage_unrealized = stage_market - after.position_cost
    stage_equity = after.cash_balance + stage_market
    economic_values = (
        (stage_market, stage_unrealized, stage_equity),
        (after.position_market_value, after.unrealized_pnl, after.equity),
        (after.position_market_value, after.unrealized_pnl, after.equity),
        (after.position_market_value, after.unrealized_pnl, after.equity),
    )
    high = (
        after.initial_capital.amount
        if context.ledger_high_water_mark is None
        else context.ledger_high_water_mark.amount
    )
    previous_max = OnlyRate(Decimal(0), 8)
    if context.ledger_equity_before is not None:
        high = max(high, context.ledger_equity_before.equity.amount)
        previous_max = context.ledger_equity_before.maximum_drawdown
    start_version = after.version - 3
    points: list[OnlyStrategyLedgerEquityPoint] = []
    maximum = previous_max
    for index, (market_value, unrealized, equity) in enumerate(economic_values, start=1):
        high = max(high, equity.amount)
        drawdown = Decimal(0) if high == 0 else equity.amount / high - Decimal(1)
        if drawdown < maximum.value:
            maximum = _rate(drawdown)
        simple = None
        if after.external_cash_flow.amount == 0 and after.initial_capital.amount > 0:
            simple = _rate((equity.amount - after.initial_capital.amount) / after.initial_capital.amount)
        points.append(
            OnlyStrategyLedgerEquityPoint(
                context.ledger_equity_sequence + index,
                after.ledger_id,
                after.key,
                trade.ts_event if index <= 2 else trade.ts_init,
                after.key.base_currency,
                after.initial_capital,
                after.cash_balance,
                market_value,
                after.realized_pnl,
                unrealized,
                after.fees,
                equity,
                simple,
                _rate(drawdown),
                maximum,
                start_version + index - 1,
                after.quality_flags,
            )
        )
    return tuple(points)


def _event_timestamp(
    context: OnlyTradeExecutionPlanningContext,
    intent: OnlyExecutionEventIntent,
) -> OnlyTimestamp:
    initialized_components = {
        OnlyExecutionProjectionComponent.ACCOUNT,
        OnlyExecutionProjectionComponent.ACCOUNT_CASH_RESERVATION,
        OnlyExecutionProjectionComponent.STRATEGY_CASH_RESERVATION,
        OnlyExecutionProjectionComponent.RISK,
    }
    return context.update.ts_init if intent.component in initialized_components else context.update.ts_event


def _event_initialized_at(
    context: OnlyTradeExecutionPlanningContext,
    intent: OnlyExecutionEventIntent,
) -> OnlyTimestamp:
    event_time_components = {
        OnlyExecutionProjectionComponent.POSITION,
        OnlyExecutionProjectionComponent.STRATEGY_LEDGER,
    }
    return context.update.ts_event if intent.component in event_time_components else context.update.ts_init


def _fail(code: OnlyTradeExecutionPlanningErrorCode, message: str) -> NoReturn:
    raise OnlyTradeExecutionPlanningError(code, message)


__all__ = ["OnlyTradeExecutionTransactionPlanner"]
