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
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyQuantity, OnlyRate
from onlyalpha.event.model import OnlyEvent
from onlyalpha.fee.application import OnlyFeeApplicationComponent, OnlyFeeApplicationInstruction
from onlyalpha.fee.models import OnlyFeeAuthority, OnlyFeeType
from onlyalpha.market.models import OnlyPositionEffect
from onlyalpha.position.enums import (
    OnlyPositionMode,
    OnlyPositionReservationState,
    OnlyPositionSide,
    OnlyPositionStatus,
    OnlySettlementBucket,
)
from onlyalpha.position.keys import OnlyPositionAllocationKey, OnlyPositionKey
from onlyalpha.risk.enums import OnlyRiskReservationState
from onlyalpha.settlement.identity import only_instruction_identity_payload, only_settlement_instruction_id
from onlyalpha.settlement.models import (
    OnlyAssetSettlementLeg,
    OnlyCashSettlementLeg,
    OnlySettlementInstruction,
    OnlySettlementLegDirection,
    only_settlement_instruction_content_fingerprint,
)
from onlyalpha.strategy_ledger.enums import OnlyStrategyCashReservationState, OnlyStrategyLedgerStatus
from onlyalpha.strategy_ledger.models import OnlyStrategyLedgerEquityPoint, OnlyStrategyValuationLine
from onlyalpha.transaction.enums import OnlyRuntimeOperationKind
from onlyalpha.transaction.event_identity import OnlyExecutionTransactionEventFactory
from onlyalpha.transaction.identity import only_runtime_transaction_id
from onlyalpha.transaction.projection import (
    OnlyRuntimeProjection,
    OnlyRuntimeProjectionComponent,
    OnlyValuationExecutionProjection,
)
from onlyalpha.transaction.projection_builder import OnlyRuntimeProjectionBuilder
from onlyalpha.transaction.transaction import OnlyPreparedRuntimeTransaction, OnlyRuntimePrecondition

from .capability import OnlyExecutionCapability, only_resolve_execution_capability
from .close_cost_authority import (
    OnlyAttributedCloseCostAuthority,
    only_build_attributed_close_cost_authority,
)
from .execution_state import (
    OnlyAccountCashReservationExecutionState,
    OnlyPositionReservationExecutionState,
    OnlyStrategyCashReservationExecutionState,
)
from .fill_identity import only_execution_fill_identity_from_update, only_execution_fill_payload_fingerprint
from .planned_trade import OnlyPlannedTrade
from .planning_context import OnlyTradeExecutionPlanningContext
from .planning_results import (
    OnlyExecutionEventIntent,
    OnlyTradeExecutionPlanningError,
    OnlyTradeExecutionPlanningErrorCode,
)
from .reducers import (
    OnlyAccountCashReservationTradeReducer,
    OnlyAccountTradeReducer,
    OnlyAllocationTradeReducer,
    OnlyFeeTradeReducer,
    OnlyOrderFeeAccrualTradeReducer,
    OnlyOrderTradeReducer,
    OnlyPositionReservationTradeReducer,
    OnlyPositionTradeReducer,
    OnlyRiskReservationTradeReducer,
    OnlyRiskTradeReducer,
    OnlySettlementTradeReducer,
    OnlyStrategyCashReservationTradeReducer,
    OnlyStrategyLedgerTradeReducer,
    OnlyValuationTradeReducer,
)
from .trade_fact import OnlyCommittedExecutionFactDraft

_PROFILE_ID = "GENERIC_T0_CASH"


@dataclass(frozen=True, slots=True)
class _OnlyTradePlan:
    trade: OnlyPlannedTrade
    projections: tuple[OnlyRuntimeProjection, ...]
    event_intents: tuple[OnlyExecutionEventIntent, ...]
    fact: OnlyCommittedExecutionFactDraft


class OnlyTradeExecutionTransactionPlanner:
    """Compile one complete immutable authority into a Prepared Transaction."""

    def prepare(self, context: OnlyTradeExecutionPlanningContext) -> OnlyPreparedRuntimeTransaction:
        self._validate(context)
        try:
            plan = self._reduce(context)
            transaction_id = only_runtime_transaction_id(
                runtime_id=context.update.runtime_id,
                gateway_id=context.update.gateway_id,
                account_id=context.update.account_id,
                broker_update_id=context.update.update_id,
                trade_id=context.update.fill.trade_id,
            )
            preconditions = tuple(
                OnlyRuntimePrecondition(
                    item.identity.component,
                    item.identity.entity_key,
                    item.identity.expected_version,
                    item.identity.expected_state_hash,
                )
                for item in plan.projections
            )
            events = self._events(context, transaction_id, plan.event_intents)
            prepared = OnlyPreparedRuntimeTransaction(
                transaction_id=transaction_id,
                runtime_id=context.update.runtime_id,
                operation_kind=OnlyRuntimeOperationKind.TRADE_FILL,
                operation_identity=context.fill_authority.identity,
                account_id=context.update.account_id,
                effective_time=context.update.ts_event,
                prepared_at=context.prepared_at,
                fact_draft=plan.fact,
                projections=plan.projections,
                outbox_events=events,
                preconditions=preconditions,
            )
            from .economic_invariants import OnlyPreparedExecutionEconomicInvariantValidator

            OnlyPreparedExecutionEconomicInvariantValidator().validate(prepared)
            return prepared
        except OnlyTradeExecutionPlanningError:
            raise
        except (AssertionError, TypeError, ValueError) as exc:
            for code in (
                OnlyTradeExecutionPlanningErrorCode.ACCOUNT_RESERVATION_INSUFFICIENT,
                OnlyTradeExecutionPlanningErrorCode.STRATEGY_RESERVATION_INSUFFICIENT,
                OnlyTradeExecutionPlanningErrorCode.RISK_RESERVATION_INSUFFICIENT,
                OnlyTradeExecutionPlanningErrorCode.FEE_ACCRUAL_NEGATIVE_INCREMENT,
                OnlyTradeExecutionPlanningErrorCode.RISK_REMAINING_NOTIONAL_UNDERFLOW,
            ):
                if code.value in str(exc):
                    raise OnlyTradeExecutionPlanningError(code, str(exc)) from exc
            raise OnlyTradeExecutionPlanningError(
                OnlyTradeExecutionPlanningErrorCode.REDUCTION_INVARIANT_FAILED,
                str(exc),
            ) from exc

    def _reduce(self, context: OnlyTradeExecutionPlanningContext) -> _OnlyTradePlan:
        closing = context.position_scope.position_effect is OnlyPositionEffect.CLOSE
        trade_without_fee = self._planned_trade(context)
        order = OnlyOrderTradeReducer().reduce(context.order_before, trade_without_fee, projection_sequence=1)
        cumulative_notional = (
            trade_without_fee.gross_notional
            if context.order_fee_accrual_before is None
            else context.order_fee_accrual_before.cumulative_fill_notional + trade_without_fee.gross_notional
        )
        fee_accrual = OnlyOrderFeeAccrualTradeReducer().reduce(
            context.order_fee_accrual_before,
            context.fee_assessment,
            trade_without_fee,
            cumulative_fill_quantity=order.after.filled_quantity,
            cumulative_fill_notional=cumulative_notional,
            order_fixed_policy_fingerprint=context.fee_assessment.binding.fingerprint,
            projection_sequence=5,
        )
        trade = replace(trade_without_fee, fee_application=fee_accrual.application)
        close_authority = _close_cost_authority(context, trade) if closing else None
        position = OnlyPositionTradeReducer().reduce(
            context.position_before,
            trade,
            context.position_creation,
            context.position_reservation_before,
            close_authority,
            cycle=context.position_cycle,
            projection_sequence=2,
        )
        allocation = OnlyAllocationTradeReducer().reduce(
            context.allocation_before,
            trade,
            context.allocation_creation,
            context.position_reservation_before,
            close_authority,
            cycle=context.allocation_cycle,
            projection_sequence=3,
        )
        settlement_instruction = _settlement_instruction(context, trade, position.after, allocation.after)
        settlement = OnlySettlementTradeReducer().reduce(
            context.settlement_before,
            settlement_instruction,
            context.trading_day,
            trade,
            record_sequence=context.settlement_record_sequence,
            projection_sequence=4,
        )
        fee = OnlyFeeTradeReducer().reduce(
            context.fee_before,
            fee_accrual.application,
            trade.instrument_id,
            record_sequence=context.fee_record_sequence,
            projection_sequence=6,
        )
        account_reservation = (
            None
            if closing
            else OnlyAccountCashReservationTradeReducer().reduce(
                _require_account_reservation(context),
                trade,
                order.terminal_fill,
                projection_sequence=9,
            )
        )
        strategy_reservation = (
            None
            if closing
            else OnlyStrategyCashReservationTradeReducer().reduce(
                _require_strategy_reservation(context),
                trade,
                order.terminal_fill,
                projection_sequence=10,
            )
        )
        position_reservation = (
            OnlyPositionReservationTradeReducer().reduce(
                _require_position_reservation(context),
                trade,
                order.terminal_fill,
                projection_sequence=9,
            )
            if closing
            else None
        )
        risk_reservation = OnlyRiskReservationTradeReducer().reduce(
            context.risk_reservation_before,
            trade,
            order.terminal_fill,
            projection_sequence=10 if closing else 11,
        )
        currency = trade.gross_notional.currency
        quantum = Decimal(1).scaleb(-currency.precision)
        position_market_value = _money(
            (context.valuation_price.value * position.after.total_quantity.value * trade.multiplier.value).quantize(
                quantum
            ),
            currency,
        )
        position_market_delta = position_market_value - context.account_before.position_market_value
        position_unrealized = _money(
            Decimal(0)
            if position.after.average_open_price is None
            else (
                (context.valuation_price.value - position.after.average_open_price.value)
                * position.after.total_quantity.value
                * trade.multiplier.value
            ).quantize(quantum),
            currency,
        )
        account = OnlyAccountTradeReducer().reduce(
            context.account_before,
            account_reservation,
            trade,
            position_market_delta,
            position_unrealized,
            position.realized_pnl_delta if closing else None,
            settlement.after.withdrawable_cash_released,
            projection_sequence=7,
        )
        ledger = OnlyStrategyLedgerTradeReducer().reduce(
            context.strategy_ledger_before,
            strategy_reservation,
            context.allocation_before,
            allocation.after,
            trade,
            context.valuation_price,
            position.realized_pnl_delta if closing else None,
            projection_sequence=8,
        )
        risk = OnlyRiskTradeReducer().reduce(
            context.risk_before,
            risk_reservation,
            trade,
            order.terminal_fill,
            projection_sequence=11 if closing else 12,
        )
        valuation = OnlyValuationTradeReducer().reduce(
            context.valuation_before,
            trade,
            account.after.ledger_cash,
            account.after.position_market_value,
            account.after.unrealized_pnl,
            projection_sequence=12 if closing else 13,
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
        ledger_projection = OnlyRuntimeProjectionBuilder().finalize(ledger_projection)
        valuation_projection = replace(
            valuation.projection,
            account_equity_points=_account_equity_points(context, trade, account.after),
            strategy_equity_points=_strategy_equity_points(context, trade, ledger.after, allocation.after),
            account_equity_before=context.account_equity_before,
            strategy_equity_before=context.strategy_equity_before,
        )
        valuation_projection = OnlyRuntimeProjectionBuilder().finalize(valuation_projection)
        assert isinstance(valuation_projection, OnlyValuationExecutionProjection)
        common_projections: tuple[OnlyRuntimeProjection, ...] = (
            order.projection,
            position.projection,
            allocation.projection,
            settlement.projection,
            fee_accrual.projection,
            fee.projection,
            account.projection,
            ledger_projection,
        )
        reservation_projections: tuple[OnlyRuntimeProjection, ...]
        if closing:
            assert position_reservation is not None
            reservation_projections = (position_reservation.projection,)
        else:
            assert account_reservation is not None and strategy_reservation is not None
            reservation_projections = (account_reservation.projection, strategy_reservation.projection)
        projections = (
            *common_projections,
            *reservation_projections,
            risk_reservation.projection,
            risk.projection,
            valuation_projection,
        )
        common_intents = (
            order.event_intents
            + position.event_intents
            + settlement.event_intents
            + fee_accrual.event_intents
            + fee.event_intents
            + account.event_intents
            + ledger.event_intents
        )
        if closing:
            assert position_reservation is not None
            reservation_intents = position_reservation.event_intents
        else:
            assert account_reservation is not None and strategy_reservation is not None
            reservation_intents = (
                account_reservation.event_intents[:1]
                + strategy_reservation.event_intents[:1]
                + account_reservation.event_intents[1:]
                + strategy_reservation.event_intents[1:]
            )
        intents = common_intents + reservation_intents + risk.event_intents
        fact = self._fact(
            context,
            trade,
            fee_accrual.application,
            order.after,
            position,
            allocation,
            settlement.after,
            fee_accrual,
            account_reservation,
            strategy_reservation,
            position_reservation,
            risk_reservation,
            account,
            ledger,
            close_authority,
        )
        return _OnlyTradePlan(trade, projections, intents, fact)

    @staticmethod
    def _planned_trade(context: OnlyTradeExecutionPlanningContext) -> OnlyPlannedTrade:
        update = context.update
        order = context.order_before
        currency = context.fee_assessment.total_charges.currency
        notional = _money(
            update.fill.price.value * update.fill.quantity.value * context.contract_multiplier.value,
            currency,
        )
        zero = _money(Decimal(0), currency)
        bucket = (
            OnlySettlementBucket.SETTLED
            if context.trade_instruction.settlement_schedule.asset_trade_available_on <= context.trading_day
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
            None,
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
        fee: object,
        order_after: object,
        position: object,
        allocation: object,
        settlement_after: object,
        fee_accrual: object,
        account_reservation: object,
        strategy_reservation: object,
        position_reservation: object,
        risk_reservation: object,
        account: object,
        ledger: object,
        close_authority: OnlyAttributedCloseCostAuthority | None,
    ) -> OnlyCommittedExecutionFactDraft:
        from onlyalpha.transaction.projection import OnlySettlementExecutionState

        from .execution_state import OnlyOrderExecutionState
        from .reducers.trade_accounting import OnlyAccountTradeReduction, OnlyStrategyLedgerTradeReduction
        from .reducers.trade_fee_accrual import OnlyOrderFeeAccrualTradeReduction
        from .reducers.trade_reservations import (
            OnlyAccountCashReservationTradeReduction,
            OnlyPositionReservationTradeReduction,
            OnlyRiskReservationTradeReduction,
            OnlyStrategyCashReservationTradeReduction,
        )

        assert isinstance(order_after, OnlyOrderExecutionState)
        from .reducers.trade_state import OnlyAllocationTradeReduction, OnlyPositionTradeReduction

        assert isinstance(position, OnlyPositionTradeReduction)
        assert isinstance(allocation, OnlyAllocationTradeReduction)
        position_after = position.after
        allocation_after = allocation.after
        assert isinstance(settlement_after, OnlySettlementExecutionState)
        assert isinstance(account, OnlyAccountTradeReduction)
        assert isinstance(ledger, OnlyStrategyLedgerTradeReduction)
        assert isinstance(fee, OnlyFeeApplicationInstruction)
        assert isinstance(fee_accrual, OnlyOrderFeeAccrualTradeReduction)
        assert account_reservation is None or isinstance(account_reservation, OnlyAccountCashReservationTradeReduction)
        assert strategy_reservation is None or isinstance(
            strategy_reservation, OnlyStrategyCashReservationTradeReduction
        )
        assert position_reservation is None or isinstance(position_reservation, OnlyPositionReservationTradeReduction)
        assert isinstance(risk_reservation, OnlyRiskReservationTradeReduction)
        update = context.update
        components = fee.components
        currency = fee.total_charges.currency
        zero = _money(Decimal(0), currency)
        market_components = tuple(item for item in components if item.identity.authority is not OnlyFeeAuthority.BROKER)
        broker_components = tuple(item for item in components if item.identity.authority is OnlyFeeAuthority.BROKER)
        market_fee = _sum_fee(currency, market_components)
        broker_fee = _sum_fee(currency, broker_components)
        tax = _sum_fee(currency, tuple(item for item in components if item.identity.fee_type is OnlyFeeType.STAMP_DUTY))
        commission = _sum_fee(
            currency,
            tuple(item for item in components if item.identity.fee_type is OnlyFeeType.BROKER_COMMISSION),
        )
        other = _money(fee.total_charges.amount - tax.amount - commission.amount, currency)
        direction = Decimal(1) if trade.side is OnlyOrderSide.BUY else Decimal(-1)
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
            fill_identity=context.fill_authority.identity,
            fill_payload_fingerprint=context.fill_authority.payload_fingerprint,
            fill_index=context.fill_authority.fill_index,
            fill_count_after=order_after.fill_count,
            terminal_fill=order_after.remaining_quantity.value == 0,
            cumulative_price_quantity_after=order_after.cumulative_price_quantity,
            currency=currency,
            contract_multiplier=trade.multiplier,
            gross_notional=trade.gross_notional,
            settled_notional=trade.settled_notional,
            fee_total_charges=fee.total_charges,
            fee_total_rebates=fee.total_rebates,
            fee_signed_cash_effect=fee.signed_cash_effect,
            market_fee=market_fee,
            broker_fee=broker_fee,
            tax=tax,
            commission=commission,
            other_fee=other,
            reference_price=trade.fill.reference_price,
            slippage=slippage,
            realized_pnl_delta=position.realized_pnl_delta,
            cash_delta=account.cash_delta,
            fee_application_id=fee.application_id,
            fee_authority="+".join(sorted({item.identity.authority.value for item in components})) or "NONE",
            fee_status=fee.local_finality.value,
            market_fee_schedule_ids=_schedule_values(market_components, "schedule_id"),
            market_fee_schedule_versions=_schedule_values(market_components, "schedule_version"),
            broker_fee_schedule_ids=_schedule_values(broker_components, "schedule_id"),
            broker_fee_schedule_versions=_schedule_values(broker_components, "schedule_version"),
            fee_application=fee,
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
            position_realized_pnl_delta=position.realized_pnl_delta,
            allocation_quantity_delta=allocation_after.total_quantity.value - allocation_before_quantity,
            account_cash_delta=account.cash_delta,
            account_fee_delta=account.fee_delta,
            account_realized_pnl_delta=position.realized_pnl_delta,
            ledger_cash_delta=ledger.cash_delta,
            ledger_fee_delta=ledger.fee_delta,
            ledger_realized_pnl_delta=position.realized_pnl_delta,
            incremental_fee_charges=fee.total_charges,
            incremental_fee_rebates=fee.total_rebates,
            order_cumulative_fee_charges_after=fee_accrual.after.cumulative_charges,
            order_cumulative_fee_rebates_after=fee_accrual.after.cumulative_rebates,
            account_reservation_consumed_delta=(
                zero if account_reservation is None else account_reservation.consumed_delta
            ),
            account_reservation_released_delta=(
                zero if account_reservation is None else account_reservation.released_delta
            ),
            strategy_reservation_consumed_delta=(
                zero if strategy_reservation is None else strategy_reservation.consumed_delta
            ),
            strategy_reservation_released_delta=(
                zero if strategy_reservation is None else strategy_reservation.released_delta
            ),
            risk_reservation_quantity_consumed_delta=risk_reservation.consumed_quantity_delta,
            risk_reservation_notional_consumed_delta=risk_reservation.consumed_notional_delta,
            position_cumulative_open_price_quantity_after=position_after.cumulative_open_price_quantity,
            allocation_cumulative_open_price_quantity_after=allocation_after.cumulative_open_price_quantity,
            position_quantity_before=position_before_quantity,
            position_quantity_after=position_after.total_quantity.value,
            allocation_quantity_before=allocation_before_quantity,
            allocation_quantity_after=allocation_after.total_quantity.value,
            position_cumulative_open_price_quantity_before=(
                Decimal(0)
                if context.position_before is None
                else context.position_before.cumulative_open_price_quantity
            ),
            allocation_cumulative_open_price_quantity_before=(
                Decimal(0)
                if context.allocation_before is None
                else context.allocation_before.cumulative_open_price_quantity
            ),
            released_open_price_quantity=(
                Decimal(0) if close_authority is None else close_authority.released_open_price_quantity
            ),
            gross_cash_inflow=(trade.gross_notional if trade.side is OnlyOrderSide.SELL else zero),
            net_cash_inflow=(account.cash_delta if trade.side is OnlyOrderSide.SELL else zero),
            allocation_realized_pnl_delta=allocation.realized_pnl_delta,
            position_reservation_consumed_delta=(
                OnlyQuantity(Decimal(0), trade.quantity.precision)
                if position_reservation is None
                else position_reservation.consumed_quantity_delta
            ),
            position_closed=position_after.total_quantity.value == 0,
            allocation_closed=allocation_after.total_quantity.value == 0,
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
        fee = context.fee_assessment
        closing = scope.position_effect is OnlyPositionEffect.CLOSE
        if instruction.compiled_identity.profile_id != _PROFILE_ID:
            _fail(OnlyTradeExecutionPlanningErrorCode.UNSUPPORTED_MARKET_PROFILE, "only GENERIC_T0_CASH is supported")
        if context.account_before.account_type is not OnlyAccountType.CASH:
            _fail(
                OnlyTradeExecutionPlanningErrorCode.UNSUPPORTED_MARKET_PROFILE,
                "Generic T0 planning requires a cash Account",
            )
        if order.order_type is not OnlyOrderType.LIMIT:
            _fail(OnlyTradeExecutionPlanningErrorCode.UNSUPPORTED_ORDER_TYPE, "only LIMIT is supported")
        expected_side = OnlyOrderSide.SELL if closing else OnlyOrderSide.BUY
        expected_offset = OnlyOffset.CLOSE if closing else OnlyOffset.OPEN
        if order.side is not expected_side:
            _fail(OnlyTradeExecutionPlanningErrorCode.UNSUPPORTED_ORDER_SIDE, "unsupported Order side")
        if order.offset is not expected_offset:
            _fail(OnlyTradeExecutionPlanningErrorCode.UNSUPPORTED_OFFSET, "unsupported Order offset")
        supported_open = not closing
        supported_close = closing
        if scope.position_side is not OnlyPositionSide.LONG:
            _fail(OnlyTradeExecutionPlanningErrorCode.UNSUPPORTED_POSITION_SIDE, "only LONG is supported")
        if scope.position_mode is not OnlyPositionMode.NETTING:
            _fail(OnlyTradeExecutionPlanningErrorCode.UNSUPPORTED_POSITION_MODE, "only NETTING is supported")
        if instruction.margin_instruction is not None or context.margin_reservation_before is not None:
            _fail(OnlyTradeExecutionPlanningErrorCode.MARGIN_UNSUPPORTED, "Margin is not supported")
        capability = only_resolve_execution_capability(
            operation_kind=OnlyRuntimeOperationKind.TRADE_FILL,
            market_profile_id=instruction.compiled_identity.profile_id,
            account_type=context.account_before.account_type,
            order_type=order.order_type,
            order_side=order.side,
            offset=order.offset,
            position_side=scope.position_side,
            position_effect=scope.position_effect,
            position_mode=scope.position_mode,
            has_margin=False,
            account_ledger_parity=context.account_ledger_parity,
        )
        if capability is not OnlyExecutionCapability.DURABLE_TRADE:
            _fail(
                OnlyTradeExecutionPlanningErrorCode.UNSUPPORTED_MARKET_PROFILE,
                f"execution capability is {capability.value}",
            )
        if supported_open and context.position_reservation_before is not None:
            _fail(
                OnlyTradeExecutionPlanningErrorCode.POSITION_RESERVATION_FORBIDDEN,
                "BUY OPEN cannot carry a Position Reservation",
            )
        if supported_open and (
            context.account_cash_reservation_before is None or context.strategy_cash_reservation_before is None
        ):
            _fail(OnlyTradeExecutionPlanningErrorCode.MISSING_BEFORE_STATE, "BUY OPEN requires cash Reservations")
        if supported_close:
            if (
                context.account_cash_reservation_before is not None
                or context.strategy_cash_reservation_before is not None
            ):
                _fail(
                    OnlyTradeExecutionPlanningErrorCode.CLOSE_CASH_RESERVATION_FORBIDDEN,
                    "SELL CLOSE cannot carry cash Reservations",
                )
            if context.position_reservation_before is None:
                _fail(
                    OnlyTradeExecutionPlanningErrorCode.CLOSE_POSITION_RESERVATION_REQUIRED,
                    "SELL CLOSE requires Position Reservation",
                )
        if update.fill.quantity.value > order.remaining_quantity.value:
            _fail(
                OnlyTradeExecutionPlanningErrorCode.FILL_EXCEEDS_REMAINING_QUANTITY,
                "Fill exceeds Order remaining quantity",
            )
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
        if order.status not in {
            OnlyOrderStatus.SUBMITTED,
            OnlyOrderStatus.ACCEPTED,
            OnlyOrderStatus.PARTIALLY_FILLED,
            OnlyOrderStatus.PENDING_CANCEL,
        }:
            _fail(OnlyTradeExecutionPlanningErrorCode.INVALID_ORDER_STATE, "Order does not accept a Fill")
        if context.fill_authority.fill_index != order.fill_count + 1:
            _fail(OnlyTradeExecutionPlanningErrorCode.INVALID_FILL_INDEX, "Fill index does not follow Order authority")
        if context.fill_authority.identity != only_execution_fill_identity_from_update(
            update
        ) or context.fill_authority.payload_fingerprint != only_execution_fill_payload_fingerprint(update):
            _fail(OnlyTradeExecutionPlanningErrorCode.FILL_IDENTITY_CONFLICT, "Captured Fill authority disagrees")
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
        settlement = instruction.settlement_schedule
        expected_notional = _money(
            update.fill.price.value * update.fill.quantity.value * context.contract_multiplier.value,
            fee.total_charges.currency,
        )
        if (
            position_instruction.instrument_id != str(order.instrument_id)
            or position_instruction.source_order_id != str(order.order_id)
            or position_instruction.source_trade_id != str(update.fill.trade_id)
            or position_instruction.position_side != scope.position_side.value
            or position_instruction.position_effect is not scope.position_effect
            or position_instruction.quantity != update.fill.quantity.value
            or position_instruction.price != update.fill.price.value
            or settlement.policy_id != instruction.settlement_schedule.policy_id
        ):
            _fail(OnlyTradeExecutionPlanningErrorCode.SCOPE_MISMATCH, "Market instruction scope disagrees")
        if (
            fee.subject.runtime_id != update.runtime_id
            or fee.subject.account_id != update.account_id
            or fee.subject.cluster_id != order.cluster_id
            or fee.subject.order_id != order.order_id
            or fee.trade_id != update.fill.trade_id
        ):
            _fail(OnlyTradeExecutionPlanningErrorCode.SCOPE_MISMATCH, "Fee instruction scope disagrees")
        currency = fee.total_charges.currency
        monies: list[OnlyMoney | None] = [
            context.account_before.ledger_cash,
            context.strategy_ledger_before.ledger_cash,
            context.risk_reservation_before.reserved_notional,
            context.valuation_before.cash,
        ]
        if context.account_cash_reservation_before is not None:
            monies.append(context.account_cash_reservation_before.reserved_amount)
        if context.strategy_cash_reservation_before is not None:
            monies.append(context.strategy_cash_reservation_before.reserved_amount)
        if any(item is None or item.currency != currency for item in monies):
            _fail(OnlyTradeExecutionPlanningErrorCode.CURRENCY_MISMATCH, "Planning authority requires one Currency")
        optional_risk_money = (
            context.risk_before.reserved_notional,
            context.risk_before.remaining_order_notional,
        )
        if any(item is not None and item.currency != currency for item in optional_risk_money):
            _fail(OnlyTradeExecutionPlanningErrorCode.CURRENCY_MISMATCH, "Risk authority Currency disagrees")
        if (
            not context.account_ledger_parity
            or context.valuation_before.cash != context.account_before.ledger_cash
            or context.valuation_before.position_market_value != context.account_before.position_market_value
            or context.valuation_before.unrealized_pnl != context.account_before.unrealized_pnl
        ):
            _fail(
                OnlyTradeExecutionPlanningErrorCode.REDUCTION_INVARIANT_FAILED,
                "Account, Ledger, Valuation, or Risk before authority is inconsistent",
            )
        if instruction.cash_instruction.currency != currency.code:
            _fail(OnlyTradeExecutionPlanningErrorCode.CURRENCY_MISMATCH, "Cash instruction Currency disagrees")
        expected_cash = expected_notional.amount if closing else -expected_notional.amount
        if (
            not instruction.cash_instruction.settle_notional
            or _money(instruction.cash_instruction.amount, currency).amount != expected_cash
            or instruction.cash_instruction.available_on != settlement.cash_trade_available_on
        ):
            _fail(
                OnlyTradeExecutionPlanningErrorCode.SCOPE_MISMATCH,
                "Cash instruction disagrees with Generic cash settlement",
            )
        if context.settlement_before is not None and (
            context.settlement_before.instruction is None
            or context.settlement_before.instruction.trade_id != update.fill.trade_id
        ):
            _fail(
                OnlyTradeExecutionPlanningErrorCode.SCOPE_MISMATCH,
                "Settlement before authority belongs to another instruction",
            )
        if context.fee_before is not None and (
            context.fee_before.application.trade_id != fee.trade_id
            or context.fee_before.application.subject != fee.subject
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
        if context.risk_reservation_before.state is not OnlyRiskReservationState.ACTIVE:
            _fail(OnlyTradeExecutionPlanningErrorCode.INVALID_RESERVATION_STATE, "Reservation is not ACTIVE")
        if supported_open and (
            _require_account_reservation(context).state
            not in {OnlyAccountReservationState.ACTIVE, OnlyAccountReservationState.PARTIALLY_CONSUMED}
            or _require_strategy_reservation(context).state
            not in {OnlyStrategyCashReservationState.ACTIVE, OnlyStrategyCashReservationState.PARTIALLY_CONSUMED}
        ):
            _fail(OnlyTradeExecutionPlanningErrorCode.INVALID_RESERVATION_STATE, "Cash Reservation is not ACTIVE")
        if supported_close:
            _validate_close_authority(context)
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
        if supported_open:
            _validate_creation(context)
        elif context.position_creation is not None or context.allocation_creation is not None:
            _fail(
                OnlyTradeExecutionPlanningErrorCode.UNEXPECTED_CREATION_AUTHORITY,
                "SELL CLOSE cannot carry creation authority",
            )


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
        risk.runtime_id != update.runtime_id
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
    if account is not None and (
        account.runtime_id != update.runtime_id
        or account.account_id != update.account_id
        or account.order_id != update.order_id
    ):
        _fail(OnlyTradeExecutionPlanningErrorCode.SCOPE_MISMATCH, "Account Reservation scope disagrees")
    if strategy is not None and (
        strategy.key != context.strategy_ledger_before.key or strategy.order_id != update.order_id
    ):
        _fail(OnlyTradeExecutionPlanningErrorCode.SCOPE_MISMATCH, "Strategy Reservation scope disagrees")


def _validate_close_authority(context: OnlyTradeExecutionPlanningContext) -> None:
    position = context.position_before
    allocation = context.allocation_before
    reservation = _require_position_reservation(context)
    quantity = context.update.fill.quantity.value
    if position is None:
        _fail(OnlyTradeExecutionPlanningErrorCode.CLOSE_POSITION_REQUIRED, "active Position is required")
    if allocation is None:
        _fail(OnlyTradeExecutionPlanningErrorCode.CLOSE_ALLOCATION_REQUIRED, "Cluster Allocation is required")
    if position.status is not OnlyPositionStatus.OPEN or position.average_open_price is None:
        _fail(OnlyTradeExecutionPlanningErrorCode.CLOSE_POSITION_REQUIRED, "Position must be OPEN")
    if position.total_quantity.value < quantity:
        _fail(OnlyTradeExecutionPlanningErrorCode.CLOSE_POSITION_INSUFFICIENT, "Position quantity is insufficient")
    if allocation.total_quantity.value < quantity:
        _fail(OnlyTradeExecutionPlanningErrorCode.CLOSE_ALLOCATION_INSUFFICIENT, "Allocation quantity is insufficient")
    if reservation.remaining_quantity.value < quantity:
        _fail(
            OnlyTradeExecutionPlanningErrorCode.CLOSE_POSITION_RESERVATION_INSUFFICIENT,
            "Position Reservation quantity is insufficient",
        )
    if reservation.state not in {
        OnlyPositionReservationState.ACTIVE,
        OnlyPositionReservationState.PARTIALLY_CONSUMED,
    }:
        _fail(OnlyTradeExecutionPlanningErrorCode.INVALID_RESERVATION_STATE, "Position Reservation is terminal")
    scope = context.position_scope
    if (
        reservation.runtime_id != context.update.runtime_id
        or reservation.account_id != context.update.account_id
        or reservation.cluster_id != context.order_before.cluster_id
        or reservation.instrument_id != context.order_before.instrument_id
        or reservation.order_id != context.order_before.order_id
        or reservation.position_side is not scope.position_side
        or reservation.position_mode is not scope.position_mode
        or position.key != scope.position_key
        or allocation.key != scope.allocation_key
    ):
        _fail(OnlyTradeExecutionPlanningErrorCode.SCOPE_MISMATCH, "Close Position authority scope disagrees")


def _close_cost_authority(
    context: OnlyTradeExecutionPlanningContext,
    trade: OnlyPlannedTrade,
) -> OnlyAttributedCloseCostAuthority:
    position = context.position_before
    allocation = context.allocation_before
    reservation = context.position_reservation_before
    if position is None or allocation is None or reservation is None:
        _fail(
            OnlyTradeExecutionPlanningErrorCode.MISSING_BEFORE_STATE,
            "Close cost attribution requires Position, Allocation and Reservation authority",
        )
    assert position is not None and allocation is not None and reservation is not None
    try:
        return only_build_attributed_close_cost_authority(
            position_before=position,
            allocation_before=allocation,
            position_reservation=reservation,
            aggregate_allocation_quantity_before=context.aggregate_allocation_quantity_before,
            aggregate_allocation_cumulative_cost_before=(context.aggregate_allocation_cumulative_cost_before),
            trade=trade,
        )
    except ValueError as exc:
        if "MULTI_CLUSTER_CLOSE_UNALLOCATED_COST_UNSUPPORTED" in str(exc):
            _fail(
                OnlyTradeExecutionPlanningErrorCode.MULTI_CLUSTER_CLOSE_UNALLOCATED_COST_UNSUPPORTED,
                str(exc),
            )
        raise


def _require_account_reservation(
    context: OnlyTradeExecutionPlanningContext,
) -> OnlyAccountCashReservationExecutionState:
    value = context.account_cash_reservation_before
    if value is None:
        _fail(OnlyTradeExecutionPlanningErrorCode.MISSING_BEFORE_STATE, "Account cash Reservation is required")
    assert isinstance(value, OnlyAccountCashReservationExecutionState)
    return value


def _require_strategy_reservation(
    context: OnlyTradeExecutionPlanningContext,
) -> OnlyStrategyCashReservationExecutionState:
    value = context.strategy_cash_reservation_before
    if value is None:
        _fail(OnlyTradeExecutionPlanningErrorCode.MISSING_BEFORE_STATE, "Strategy cash Reservation is required")
    assert isinstance(value, OnlyStrategyCashReservationExecutionState)
    return value


def _require_position_reservation(
    context: OnlyTradeExecutionPlanningContext,
) -> OnlyPositionReservationExecutionState:
    value = context.position_reservation_before
    if value is None:
        _fail(
            OnlyTradeExecutionPlanningErrorCode.CLOSE_POSITION_RESERVATION_REQUIRED,
            "Position Reservation is required",
        )
    assert isinstance(value, OnlyPositionReservationExecutionState)
    return value


def _settlement_instruction(
    context: OnlyTradeExecutionPlanningContext,
    trade: OnlyPlannedTrade,
    position_after: object,
    allocation_after: object,
) -> OnlySettlementInstruction:
    from .execution_state import OnlyAllocationExecutionState, OnlyPositionExecutionState

    if not isinstance(position_after, OnlyPositionExecutionState) or not isinstance(
        allocation_after, OnlyAllocationExecutionState
    ):
        raise TypeError("Settlement instruction requires final Position and Allocation authority")
    position_cycle = (
        context.position_creation.cycle if context.position_creation is not None else context.position_cycle
    )
    allocation_cycle = (
        context.allocation_creation.cycle if context.allocation_creation is not None else context.allocation_cycle
    )
    if position_cycle < 1 or allocation_cycle < 1:
        _fail(
            OnlyTradeExecutionPlanningErrorCode.REDUCTION_INVARIANT_FAILED,
            "Settlement instruction requires final lifecycle cycles",
        )
    schedule = context.trade_instruction.settlement_schedule
    cash_credit = trade.side is OnlyOrderSide.SELL
    account_amount = OnlyMoney(
        trade.gross_notional.amount - trade.fee_charges.amount + trade.fee_rebates.amount
        if cash_credit
        else trade.gross_notional.amount + trade.fee_charges.amount - trade.fee_rebates.amount,
        trade.gross_notional.currency,
    )
    net_cash_flow = account_amount if cash_credit else OnlyMoney(-account_amount.amount, account_amount.currency)
    identity = context.trade_instruction.compiled_identity
    provisional = OnlySettlementInstruction(
        instruction_id=only_settlement_instruction_id({"provisional": context.fill_authority.identity}),
        runtime_id=trade.runtime_id,
        account_id=trade.account_id,
        cluster_id=trade.cluster_id,
        instrument_id=trade.instrument_id,
        order_id=trade.order_id,
        trade_id=trade.trade_id,
        position_id=position_after.position_id,
        position_cycle=position_cycle,
        allocation_id=allocation_after.allocation_id,
        allocation_cycle=allocation_cycle,
        side=trade.side,
        trade_quantity=trade.quantity,
        gross_notional=trade.gross_notional,
        net_cash_flow=net_cash_flow,
        trading_day=trade.trading_day,
        schedule=schedule,
        asset_leg=OnlyAssetSettlementLeg(
            OnlySettlementLegDirection.CREDIT if trade.side is OnlyOrderSide.BUY else OnlySettlementLegDirection.DEBIT,
            trade.quantity,
            schedule.asset_booked_on,
            schedule.asset_trade_available_on,
            schedule.legal_settlement_on,
        ),
        cash_leg=OnlyCashSettlementLeg(
            OnlySettlementLegDirection.CREDIT if cash_credit else OnlySettlementLegDirection.DEBIT,
            trade.gross_notional,
            account_amount,
            schedule.cash_booked_on,
            schedule.cash_trade_available_on,
            schedule.cash_withdrawable_on,
            schedule.legal_settlement_on,
        ),
        market_profile_id=identity.profile_id,
        market_profile_version=identity.profile_version,
        compiled_rule_fingerprint=identity.compiled_rules_fingerprint,
        reference_fingerprint=identity.reference_fingerprint,
        content_fingerprint="0" * 64,
    )
    fingerprinted = replace(
        provisional,
        content_fingerprint=only_settlement_instruction_content_fingerprint(provisional),
    )
    return replace(
        fingerprinted,
        instruction_id=only_settlement_instruction_id(only_instruction_identity_payload(fingerprinted)),
    )


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
    schedule = instruction.settlement_schedule
    authority = "|".join(
        (
            schedule.policy_id,
            schedule.asset_booked_on.value.isoformat(),
            schedule.asset_trade_available_on.value.isoformat(),
            schedule.cash_booked_on.value.isoformat(),
            schedule.cash_trade_available_on.value.isoformat(),
            schedule.cash_withdrawable_on.value.isoformat(),
            schedule.legal_settlement_on.value.isoformat(),
            instruction.compiled_identity.compiled_rules_fingerprint,
            instruction.position_instruction.position_side,
            instruction.position_instruction.position_effect.value,
        )
    )
    return f"TINSTR-{hashlib.sha256(authority.encode('utf-8')).hexdigest()}"


def _schedule_values(components: tuple[OnlyFeeApplicationComponent, ...], field: str) -> tuple[str, ...]:
    return tuple(sorted(str(getattr(item.identity, field)) for item in components))


def _sum_fee(currency: OnlyCurrency, components: tuple[OnlyFeeApplicationComponent, ...]) -> OnlyMoney:
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
            after.ledger_cash,
            market_value,
            after.realized_pnl,
            unrealized,
            after.fees,
            after.ledger_cash + market_value,
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
    stage_equity = after.ledger_cash + stage_market
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
                after.ledger_cash,
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
        OnlyRuntimeProjectionComponent.ACCOUNT,
        OnlyRuntimeProjectionComponent.ACCOUNT_CASH_RESERVATION,
        OnlyRuntimeProjectionComponent.STRATEGY_CASH_RESERVATION,
        OnlyRuntimeProjectionComponent.RISK,
    }
    return context.update.ts_init if intent.component in initialized_components else context.update.ts_event


def _event_initialized_at(
    context: OnlyTradeExecutionPlanningContext,
    intent: OnlyExecutionEventIntent,
) -> OnlyTimestamp:
    event_time_components = {
        OnlyRuntimeProjectionComponent.POSITION,
        OnlyRuntimeProjectionComponent.STRATEGY_LEDGER,
    }
    return context.update.ts_event if intent.component in event_time_components else context.update.ts_init


def _fail(code: OnlyTradeExecutionPlanningErrorCode, message: str) -> NoReturn:
    raise OnlyTradeExecutionPlanningError(code, message)


__all__ = ["OnlyTradeExecutionTransactionPlanner"]
