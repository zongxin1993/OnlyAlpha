"""Cross-component economic invariants for prepared execution transactions."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide

from .projection import (
    OnlyAccountCashReservationExecutionProjection,
    OnlyAccountExecutionProjection,
    OnlyAllocationExecutionProjection,
    OnlyExecutionProjection,
    OnlyFeeExecutionProjection,
    OnlyMarginExecutionProjection,
    OnlyMarginReservationExecutionProjection,
    OnlyOrderExecutionProjection,
    OnlyPositionExecutionProjection,
    OnlyPositionReservationExecutionProjection,
    OnlyRiskReservationExecutionProjection,
    OnlySettlementExecutionProjection,
    OnlyStrategyCashReservationExecutionProjection,
    OnlyStrategyLedgerExecutionProjection,
)

if TYPE_CHECKING:
    from .transaction import OnlyPreparedExecutionTransaction


class OnlyPreparedExecutionEconomicInvariantValidator:
    """Reject a prepared transaction whose facts and authority states disagree."""

    def validate(self, prepared: OnlyPreparedExecutionTransaction) -> None:
        fact = prepared.fact_draft
        order = _one(prepared.projections, OnlyOrderExecutionProjection)
        position = _one(prepared.projections, OnlyPositionExecutionProjection)
        allocation = _one(prepared.projections, OnlyAllocationExecutionProjection)
        settlement = _one(prepared.projections, OnlySettlementExecutionProjection)
        fee = _one(prepared.projections, OnlyFeeExecutionProjection)
        account = _one(prepared.projections, OnlyAccountExecutionProjection)
        ledger = _one(prepared.projections, OnlyStrategyLedgerExecutionProjection)

        if (
            order.after.order_id != fact.order_id
            or order.fill.order_id != fact.order_id
            or order.fill.quantity != fact.fill_quantity
            or order.fill.price != fact.fill_price
            or order.after.status != fact.order_status_after
            or order.after.filled_quantity != fact.cumulative_filled_quantity
            or order.after.remaining_quantity != fact.remaining_quantity
            or order.broker_update_id != fact.broker_update_id
        ):
            raise ValueError("Order projection contradicts execution fact")

        position_before = Decimal(0) if position.before is None else position.before.total_quantity.value
        position_delta = position.after.total_quantity.value - position_before
        allocation_before = Decimal(0) if allocation.before is None else allocation.before.total_quantity.value
        allocation_delta = allocation.after.total_quantity.value - allocation_before
        if position_delta != fact.position_quantity_delta:
            raise ValueError("Position projection quantity delta contradicts execution fact")
        if allocation_delta != fact.allocation_quantity_delta:
            raise ValueError("Allocation projection quantity delta contradicts execution fact")
        expected_sign = Decimal(1) if _increases_position(fact.order_side, fact.offset) else Decimal(-1)
        if position_delta != expected_sign * fact.fill_quantity.value:
            raise ValueError("Position projection direction/offset contradicts execution fact")
        if position.realized_pnl_delta != fact.position_realized_pnl_delta:
            raise ValueError("Position projection realized PnL contradicts execution fact")
        if allocation.realized_pnl_delta != fact.realized_pnl_delta:
            raise ValueError("Allocation projection realized PnL contradicts execution fact")
        position_fee_before = Decimal(0) if position.before is None else position.before.fees.amount
        allocation_fee_before = Decimal(0) if allocation.before is None else allocation.before.fees.amount
        if position.after.fees.amount - position_fee_before != fact.authoritative_fee_total.amount:
            raise ValueError("Position projection cumulative fee contradicts execution fact")
        if allocation.after.fees.amount - allocation_fee_before != fact.authoritative_fee_total.amount:
            raise ValueError("Allocation projection cumulative fee contradicts execution fact")

        if (
            fee.after.authoritative_total != fact.authoritative_fee_total
            or fee.after.fee_breakdown != fact.fee_breakdown
            or fee.after.instruction.instruction_id != fact.fee_instruction_id
            or fee.after.instruction.trade_id != str(fact.trade_id)
        ):
            raise ValueError("Fee projection contradicts execution fact")

        if account.after.cash_balance.amount - account.before.cash_balance.amount != fact.account_cash_delta.amount:
            raise ValueError("Account projection cash delta contradicts execution fact")
        if account.after.fees.amount - account.before.fees.amount != fact.account_fee_delta.amount:
            raise ValueError("Account projection fee delta contradicts execution fact")
        if (
            account.after.realized_pnl.amount - account.before.realized_pnl.amount
            != fact.account_realized_pnl_delta.amount
        ):
            raise ValueError("Account projection realized PnL contradicts execution fact")
        if ledger.after.cash_balance.amount - ledger.before.cash_balance.amount != fact.ledger_cash_delta.amount:
            raise ValueError("Strategy Ledger projection cash delta contradicts execution fact")
        if ledger.after.fees.amount - ledger.before.fees.amount != fact.ledger_fee_delta.amount:
            raise ValueError("Strategy Ledger projection fee delta contradicts execution fact")
        if (
            ledger.after.realized_pnl.amount - ledger.before.realized_pnl.amount
            != fact.ledger_realized_pnl_delta.amount
        ):
            raise ValueError("Strategy Ledger projection realized PnL contradicts execution fact")

        state = settlement.after
        if (
            state.instruction_id != fact.settlement_instruction_id
            or state.source_trade_id != str(fact.trade_id)
            or state.source_order_id != fact.order_id
            or state.account_id != fact.account_id
            or state.instrument_id != fact.instrument_id
            or state.asset_available_on != fact.asset_available_on
            or state.cash_trade_available_on != fact.cash_available_on
            or state.legal_settlement_on != fact.legal_settlement_date
            or state.asset_quantity != fact.fill_quantity.value
            or state.cash_amount != fact.settled_notional
        ):
            raise ValueError("Settlement projection contradicts execution fact")

        margins = tuple(
            item
            for item in prepared.projections
            if isinstance(item, OnlyMarginExecutionProjection | OnlyMarginReservationExecutionProjection)
        )
        if fact.margin_instruction_id is None and margins:
            raise ValueError("execution without Margin instruction cannot contain Margin projections")
        if fact.margin_instruction_id is not None and not margins:
            raise ValueError("execution with Margin instruction requires Margin projections")
        if fact.margin_instruction_id is not None:
            margin = _one(prepared.projections, OnlyMarginExecutionProjection).after
            margin_reservation = _one(prepared.projections, OnlyMarginReservationExecutionProjection).after
            if (
                margin.instruction_id != fact.margin_instruction_id
                or margin.action != fact.margin_action
                or margin.currency != fact.currency.code
                or margin.amount != (fact.margin_amount.amount if fact.margin_amount is not None else None)
                or margin_reservation.order_id != fact.order_id
                or margin_reservation.currency != fact.currency
            ):
                raise ValueError("Margin projections contradict execution fact")

        self._validate_cash_reservations(prepared)
        self._validate_risk_reservations(prepared)
        self._validate_scope(prepared)

    @staticmethod
    def _validate_cash_reservations(prepared: OnlyPreparedExecutionTransaction) -> None:
        fact = prepared.fact_draft
        account = _one(prepared.projections, OnlyAccountCashReservationExecutionProjection)
        strategy = _one(prepared.projections, OnlyStrategyCashReservationExecutionProjection)
        for label, projection in (("Account", account), ("Strategy", strategy)):
            before_consumed = Decimal(0) if projection.before is None else projection.before.consumed_amount.amount
            consumed_delta = projection.after.consumed_amount.amount - before_consumed
            if projection.after.order_id != fact.order_id or consumed_delta != -fact.cash_delta.amount:
                raise ValueError(f"{label} cash Reservation consumption contradicts execution fact")
        position_reservations = tuple(
            item for item in prepared.projections if isinstance(item, OnlyPositionReservationExecutionProjection)
        )
        for position_projection in position_reservations:
            before_remaining = (
                Decimal(0)
                if position_projection.before is None
                else position_projection.before.remaining_quantity.value
            )
            consumed = before_remaining - position_projection.after.remaining_quantity.value
            if position_projection.after.order_id != fact.order_id or consumed != fact.fill_quantity.value:
                raise ValueError("Position Reservation consumption contradicts execution fact")

    @staticmethod
    def _validate_risk_reservations(prepared: OnlyPreparedExecutionTransaction) -> None:
        fact = prepared.fact_draft
        reservations = tuple(
            item for item in prepared.projections if isinstance(item, OnlyRiskReservationExecutionProjection)
        )
        for projection in reservations:
            before_quantity = Decimal(0) if projection.before is None else projection.before.consumed_quantity.value
            consumed_quantity = projection.after.consumed_quantity.value - before_quantity
            before_notional = (
                Decimal(0)
                if projection.before is None or projection.before.consumed_notional is None
                else projection.before.consumed_notional.amount
            )
            consumed_notional = (
                Decimal(0)
                if projection.after.consumed_notional is None
                else projection.after.consumed_notional.amount - before_notional
            )
            if (
                projection.after.order_id != fact.order_id
                or consumed_quantity != fact.fill_quantity.value
                or consumed_notional != fact.gross_notional.amount
            ):
                raise ValueError("Risk Reservation consumption contradicts execution fact")

    @staticmethod
    def _validate_scope(prepared: OnlyPreparedExecutionTransaction) -> None:
        fact = prepared.fact_draft
        order = _one(prepared.projections, OnlyOrderExecutionProjection).after
        position = _one(prepared.projections, OnlyPositionExecutionProjection).after
        allocation = _one(prepared.projections, OnlyAllocationExecutionProjection).after
        account = _one(prepared.projections, OnlyAccountExecutionProjection).after
        ledger = _one(prepared.projections, OnlyStrategyLedgerExecutionProjection).after
        if (
            order.runtime_id != fact.runtime_id
            or order.cluster_id != fact.cluster_id
            or order.account_id != fact.account_id
            or order.instrument_id != fact.instrument_id
            or position.key.runtime_id != fact.runtime_id
            or position.key.account_id != fact.account_id
            or position.key.instrument_id != fact.instrument_id
            or allocation.key.runtime_id != fact.runtime_id
            or allocation.key.account_id != fact.account_id
            or allocation.key.cluster_id != fact.cluster_id
            or allocation.key.instrument_id != fact.instrument_id
            or account.runtime_id != fact.runtime_id
            or account.account_id != fact.account_id
            or ledger.key.runtime_id != fact.runtime_id
            or ledger.key.account_id != fact.account_id
            or ledger.key.cluster_id != fact.cluster_id
            or ledger.key.base_currency != fact.currency
        ):
            raise ValueError("execution Projection scope contradicts execution fact")


def _one[ProjectionT: OnlyExecutionProjection](
    projections: tuple[OnlyExecutionProjection, ...], projection_type: type[ProjectionT]
) -> ProjectionT:
    matches = tuple(item for item in projections if isinstance(item, projection_type))
    if len(matches) != 1:
        raise ValueError(f"prepared execution requires exactly one {projection_type.__name__}")
    return matches[0]


def _increases_position(side: OnlyOrderSide, offset: OnlyOffset) -> bool:
    del side
    return offset in {OnlyOffset.NONE, OnlyOffset.OPEN}


__all__ = ["OnlyPreparedExecutionEconomicInvariantValidator"]
