"""Cross-component economic invariants for prepared execution transactions."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide

from .enums import OnlyExecutionOperationKind
from .projection import (
    OnlyAccountCashReservationExecutionProjection,
    OnlyAccountExecutionProjection,
    OnlyAllocationExecutionProjection,
    OnlyExecutionProjection,
    OnlyFeeExecutionProjection,
    OnlyMarginExecutionProjection,
    OnlyMarginReservationExecutionProjection,
    OnlyOrderExecutionProjection,
    OnlyOrderFeeAccrualExecutionProjection,
    OnlyOrderTerminalExecutionProjection,
    OnlyPositionExecutionProjection,
    OnlyPositionReservationExecutionProjection,
    OnlyRiskExecutionProjection,
    OnlyRiskReservationExecutionProjection,
    OnlySettlementExecutionProjection,
    OnlyStrategyCashReservationExecutionProjection,
    OnlyStrategyLedgerExecutionProjection,
)
from .reservation_presence import OnlyExecutionReservationPresence, only_expected_execution_reservations
from .transaction import OnlyCommittedExecutionFactDraft

if TYPE_CHECKING:
    from .transaction import OnlyPreparedExecutionTransaction


class OnlyPreparedExecutionEconomicInvariantValidator:
    """Reject a prepared transaction whose facts and authority states disagree."""

    def validate(self, prepared: OnlyPreparedExecutionTransaction) -> None:
        if prepared.operation_kind is OnlyExecutionOperationKind.ORDER_TERMINAL:
            self._validate_terminal(prepared)
            return
        fact = _trade_fact(prepared)
        order = _one(prepared.projections, OnlyOrderExecutionProjection)
        position = _one(prepared.projections, OnlyPositionExecutionProjection)
        allocation = _one(prepared.projections, OnlyAllocationExecutionProjection)
        settlement = _one(prepared.projections, OnlySettlementExecutionProjection)
        fee = _one(prepared.projections, OnlyFeeExecutionProjection)
        fee_accrual = _one(prepared.projections, OnlyOrderFeeAccrualExecutionProjection)
        account = _one(prepared.projections, OnlyAccountExecutionProjection)
        ledger = _one(prepared.projections, OnlyStrategyLedgerExecutionProjection)
        presence = only_expected_execution_reservations(
            market_profile_id=fact.market_profile_id,
            side=fact.order_side,
            offset=fact.offset,
            position_effect=fact.position_effect,
            margin_instruction_present=fact.margin_instruction_id is not None,
        )
        self._validate_reservation_presence(prepared, presence)

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
        if allocation.realized_pnl_delta != fact.allocation_realized_pnl_delta:
            raise ValueError("Allocation projection realized PnL authority contradicts execution fact")
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
            or fee.after.fee_breakdown.status.value != fact.fee_status
        ):
            raise ValueError("Fee projection contradicts execution fact")
        if (
            fee_accrual.after.cumulative_charged_fee != fact.order_cumulative_fee_after
            or fee.after.authoritative_total != fact.incremental_fee_total
        ):
            raise ValueError("Order fee accrual projection contradicts execution fact")

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
        expected_cash_delta = (
            -(fact.settled_notional.amount + fact.authoritative_fee_total.amount)
            if fact.order_side is OnlyOrderSide.BUY
            else fact.settled_notional.amount - fact.authoritative_fee_total.amount
        )
        if fact.cash_delta.amount != expected_cash_delta:
            raise ValueError("execution Fact cash delta contradicts authoritative trade cost")
        if fact.order_side is OnlyOrderSide.SELL and (
            fact.gross_cash_inflow != fact.gross_notional
            or fact.net_cash_inflow.amount != fact.gross_notional.amount - fact.incremental_fee_total.amount
            or fact.net_cash_inflow != fact.account_cash_delta
        ):
            raise ValueError("SELL execution cash inflow authority is inconsistent")
        if (
            fact.position_quantity_before != position_before
            or fact.position_quantity_after != position.after.total_quantity.value
        ):
            raise ValueError("Position before/after quantity authority contradicts Projection")
        if (
            fact.allocation_quantity_before != allocation_before
            or fact.allocation_quantity_after != allocation.after.total_quantity.value
        ):
            raise ValueError("Allocation before/after quantity authority contradicts Projection")
        if (
            fact.position_cumulative_open_price_quantity_before
            != (Decimal(0) if position.before is None else position.before.cumulative_open_price_quantity)
            or fact.position_cumulative_open_price_quantity_after != position.after.cumulative_open_price_quantity
            or fact.allocation_cumulative_open_price_quantity_before
            != (Decimal(0) if allocation.before is None else allocation.before.cumulative_open_price_quantity)
            or fact.allocation_cumulative_open_price_quantity_after != allocation.after.cumulative_open_price_quantity
        ):
            raise ValueError("exact cumulative Position cost contradicts Projection")

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
        margin_fields = (
            fact.margin_action,
            fact.margin_currency,
            fact.margin_amount,
            fact.reserved_margin_delta,
            fact.occupied_margin_delta,
            fact.released_margin_delta,
            fact.maintenance_margin_after,
        )
        if fact.margin_instruction_id is None and (margins or any(value is not None for value in margin_fields)):
            raise ValueError("execution without Margin instruction cannot contain Margin projections")
        if fact.margin_instruction_id is not None:
            if any(value is None for value in margin_fields):
                raise ValueError("execution with Margin instruction requires complete Margin facts")
            margin = _one(prepared.projections, OnlyMarginExecutionProjection).after
            margin_reservation = _one(prepared.projections, OnlyMarginReservationExecutionProjection).after
            if (
                margin.instruction_id != fact.margin_instruction_id
                or margin.action != fact.margin_action
                or margin.currency != fact.currency.code
                or fact.margin_currency != fact.currency
                or margin.amount != (fact.margin_amount.amount if fact.margin_amount is not None else None)
                or margin_reservation.order_id != fact.order_id
                or margin_reservation.currency != fact.currency
                or margin.account_id != fact.account_id
                or margin.instrument_id != fact.instrument_id
                or margin.order_id != fact.order_id
                or margin.trade_id != str(fact.trade_id)
            ):
                raise ValueError("Margin projections contradict execution fact")
            self._validate_margin_account(prepared)
        elif (
            account.after.reserved_margin != account.before.reserved_margin
            or account.after.occupied_margin != account.before.occupied_margin
            or account.after.released_margin != account.before.released_margin
        ):
            raise ValueError("execution without Margin cannot change Account Margin state")

        self._validate_scope(prepared)
        self._validate_cash_reservations(prepared)
        self._validate_risk_reservations(prepared)

    @staticmethod
    def _validate_terminal(prepared: OnlyPreparedExecutionTransaction) -> None:
        from .terminal_fact import OnlyCommittedTerminalExecutionFactDraft

        fact = prepared.fact_draft
        if not isinstance(fact, OnlyCommittedTerminalExecutionFactDraft):
            raise ValueError("terminal transaction requires Terminal Fact")
        if len(prepared.projections) != 4:
            raise ValueError("terminal transaction requires exactly four projections")
        order = _one(prepared.projections, OnlyOrderTerminalExecutionProjection)
        position = _one(prepared.projections, OnlyPositionReservationExecutionProjection)
        risk_reservation = _one(prepared.projections, OnlyRiskReservationExecutionProjection)
        risk = _one(prepared.projections, OnlyRiskExecutionProjection)
        if position.before is None or risk_reservation.before is None:
            raise ValueError("terminal transaction requires existing Reservation authority")
        position_before_consumed = position.before.consumed_quantity
        position_after_consumed = position.after.consumed_quantity
        if position_before_consumed is None or position_after_consumed is None:
            raise ValueError("terminal Position Reservation lacks consumed authority")
        position_before_released = position.before.released_quantity
        position_after_released = position.after.released_quantity
        if position_before_released is None or position_after_released is None:
            raise ValueError("terminal Position Reservation lacks released authority")
        risk_before_released = risk_reservation.before.released_quantity
        risk_after_released = risk_reservation.after.released_quantity
        if risk_before_released is None or risk_after_released is None:
            raise ValueError("terminal Risk Reservation lacks released authority")
        released_notional = (
            Decimal(0)
            if risk_reservation.after.released_notional is None
            else risk_reservation.after.released_notional.amount
        ) - (
            Decimal(0)
            if risk_reservation.before.released_notional is None
            else risk_reservation.before.released_notional.amount
        )
        expected_released_notional = (
            Decimal(0)
            if fact.risk_reservation_released_notional_delta is None
            else fact.risk_reservation_released_notional_delta.amount
        )
        if (
            order.terminal_identity != fact.terminal_identity
            or order.broker_update_id != fact.broker_update_id
            or order.after.status is not fact.terminal_status
            or order.after.filled_quantity != fact.filled_quantity_before
            or order.after.remaining_quantity != fact.order_remaining_quantity
            or position.after.order_id != fact.order_id
            or position_before_consumed != fact.position_reservation_consumed_before
            or position_after_consumed != position_before_consumed
            or position_after_released.value - position_before_released.value
            != fact.position_reservation_released_delta.value
            or position.after.remaining_quantity != fact.position_reservation_remaining_after
            or risk_reservation.after.order_id != fact.order_id
            or risk_reservation.before.consumed_quantity != fact.risk_reservation_consumed_quantity_before
            or risk_reservation.after.consumed_quantity != risk_reservation.before.consumed_quantity
            or risk_after_released.value - risk_before_released.value
            != fact.risk_reservation_released_quantity_delta.value
            or released_notional != expected_released_notional
            or risk_reservation.after.remaining_quantity != fact.risk_reservation_remaining_quantity_after
            or risk.after.active_order_count - risk.before.active_order_count != fact.active_order_count_delta
            or risk.after.cluster_active_order_count - risk.before.cluster_active_order_count
            != fact.cluster_active_order_count_delta
            or risk.after.reserved_quantity
            != risk.before.reserved_quantity - fact.risk_reservation_released_quantity_delta.value
        ):
            raise ValueError("terminal projections contradict Terminal Fact")

    @staticmethod
    def _validate_cash_reservations(prepared: OnlyPreparedExecutionTransaction) -> None:
        fact = _trade_fact(prepared)
        accounts = _all(prepared.projections, OnlyAccountCashReservationExecutionProjection)
        strategies = _all(prepared.projections, OnlyStrategyCashReservationExecutionProjection)
        if accounts or strategies:
            account = accounts[0]
            strategy = strategies[0]
            actual_consumption = fact.settled_notional.amount + fact.authoritative_fee_total.amount
            for label, projection in (("Account", account), ("Strategy", strategy)):
                before_consumed = Decimal(0) if projection.before is None else projection.before.consumed_amount.amount
                consumed_delta = projection.after.consumed_amount.amount - before_consumed
                expected_consumed = (
                    fact.account_reservation_consumed_delta.amount
                    if label == "Account"
                    else fact.strategy_reservation_consumed_delta.amount
                )
                before_remaining = (
                    Decimal(0) if projection.before is None else projection.before.remaining_amount.amount
                )
                released_delta = before_remaining - projection.after.remaining_amount.amount - consumed_delta
                expected_released = (
                    fact.account_reservation_released_delta.amount
                    if label == "Account"
                    else fact.strategy_reservation_released_delta.amount
                )
                if (
                    projection.after.order_id != fact.order_id
                    or consumed_delta != actual_consumption
                    or consumed_delta != expected_consumed
                    or released_delta != expected_released
                ):
                    raise ValueError(f"{label} cash Reservation consumption contradicts execution fact")
            if (
                account.after.runtime_id != fact.runtime_id
                or account.after.account_id != fact.account_id
                or account.after.reserved_amount.currency != fact.currency
                or strategy.after.key.runtime_id != fact.runtime_id
                or strategy.after.key.account_id != fact.account_id
                or strategy.after.key.cluster_id != fact.cluster_id
                or strategy.after.key.base_currency != fact.currency
            ):
                raise ValueError("cash Reservation scope contradicts execution fact")
        position_reservations = _all(prepared.projections, OnlyPositionReservationExecutionProjection)
        for position_projection in position_reservations:
            before_remaining = (
                Decimal(0)
                if position_projection.before is None
                else position_projection.before.remaining_quantity.value
            )
            consumed = before_remaining - position_projection.after.remaining_quantity.value
            if (
                position_projection.after.order_id != fact.order_id
                or position_projection.after.runtime_id != fact.runtime_id
                or position_projection.after.account_id != fact.account_id
                or position_projection.after.cluster_id != fact.cluster_id
                or position_projection.after.instrument_id != fact.instrument_id
                or position_projection.after.position_side != fact.position_side
                or position_projection.after.position_mode != fact.position_mode
                or consumed != fact.fill_quantity.value
                or consumed != fact.position_reservation_consumed_delta.value
            ):
                raise ValueError("Position Reservation consumption contradicts execution fact")

    @staticmethod
    def _validate_risk_reservations(prepared: OnlyPreparedExecutionTransaction) -> None:
        fact = _trade_fact(prepared)
        risk_projection = _one(prepared.projections, OnlyRiskExecutionProjection)
        risk = risk_projection.after
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
            released_notional_before = (
                Decimal(0)
                if projection.before is None or projection.before.released_notional is None
                else projection.before.released_notional.amount
            )
            released_notional = (
                Decimal(0)
                if projection.after.released_notional is None
                else projection.after.released_notional.amount - released_notional_before
            )
            if (
                projection.after.order_id != fact.order_id
                or projection.after.runtime_id != fact.runtime_id
                or projection.after.cluster_id != fact.cluster_id
                or projection.after.account_id != fact.account_id
                or projection.after.instrument_id != fact.instrument_id
                or projection.after.reserved_quantity.value < projection.after.consumed_quantity.value
                or projection.after.reserved_notional is None
                or projection.after.reserved_notional.currency != fact.currency
                or consumed_quantity != fact.fill_quantity.value
                or consumed_notional != fact.gross_notional.amount
                or consumed_quantity != fact.risk_reservation_quantity_consumed_delta.value
                or consumed_notional != fact.risk_reservation_notional_consumed_delta.amount
                or risk.reserved_quantity != risk_projection.before.reserved_quantity - consumed_quantity
                or (
                    risk.reserved_notional is not None
                    and risk_projection.before.reserved_notional is not None
                    and risk.reserved_notional.amount
                    != risk_projection.before.reserved_notional.amount - consumed_notional - released_notional
                )
                or risk.active_order_count != risk_projection.before.active_order_count - int(fact.terminal_fill)
                or risk.cluster_active_order_count
                != risk_projection.before.cluster_active_order_count - int(fact.terminal_fill)
            ):
                raise ValueError("Risk Reservation consumption contradicts execution fact")

    @staticmethod
    def _validate_scope(prepared: OnlyPreparedExecutionTransaction) -> None:
        fact = _trade_fact(prepared)
        order = _one(prepared.projections, OnlyOrderExecutionProjection).after
        position = _one(prepared.projections, OnlyPositionExecutionProjection).after
        allocation = _one(prepared.projections, OnlyAllocationExecutionProjection).after
        account = _one(prepared.projections, OnlyAccountExecutionProjection).after
        ledger = _one(prepared.projections, OnlyStrategyLedgerExecutionProjection).after
        fee = _one(prepared.projections, OnlyFeeExecutionProjection).after
        settlement = _one(prepared.projections, OnlySettlementExecutionProjection).after
        risk = _one(prepared.projections, OnlyRiskExecutionProjection).after
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
            or fee.instruction.runtime_id != str(fact.runtime_id)
            or fee.instruction.cluster_id != str(fact.cluster_id)
            or fee.instruction.account_id != str(fact.account_id)
            or fee.instruction.order_id != str(fact.order_id)
            or fee.instruction.trade_id != str(fact.trade_id)
            or any(
                record.account_id != str(fact.account_id)
                or record.order_id != str(fact.order_id)
                or record.trade_id != str(fact.trade_id)
                or record.amount.currency != fact.currency
                for record in fee.records
            )
            or settlement.account_id != fact.account_id
            or settlement.instrument_id != fact.instrument_id
            or settlement.source_order_id != fact.order_id
            or settlement.source_trade_id != str(fact.trade_id)
            or settlement.cash_amount.currency != fact.currency
            or risk.runtime_id != fact.runtime_id
            or risk.cluster_id != fact.cluster_id
            or risk.account_id != fact.account_id
            or (risk.reserved_notional is not None and risk.reserved_notional.currency != fact.currency)
        ):
            raise ValueError("execution Projection scope contradicts execution fact")

    @staticmethod
    def _validate_reservation_presence(
        prepared: OnlyPreparedExecutionTransaction, presence: OnlyExecutionReservationPresence
    ) -> None:
        requirements = (
            (OnlyAccountCashReservationExecutionProjection, presence.require_account_cash),
            (OnlyStrategyCashReservationExecutionProjection, presence.require_strategy_cash),
            (OnlyPositionReservationExecutionProjection, presence.require_position),
            (OnlyMarginReservationExecutionProjection, presence.require_margin),
            (OnlyRiskReservationExecutionProjection, presence.require_risk),
        )
        for projection_type, required in requirements:
            count = len(_all(prepared.projections, projection_type))
            expected = 1 if required else 0
            if count != expected:
                raise ValueError(f"execution requires exactly {expected} {projection_type.__name__}; received {count}")

    @staticmethod
    def _validate_margin_account(prepared: OnlyPreparedExecutionTransaction) -> None:
        fact = _trade_fact(prepared)
        account = _one(prepared.projections, OnlyAccountExecutionProjection)
        margin = _one(prepared.projections, OnlyMarginExecutionProjection).after
        reservation = _one(prepared.projections, OnlyMarginReservationExecutionProjection).after
        assert fact.reserved_margin_delta is not None
        assert fact.occupied_margin_delta is not None
        assert fact.released_margin_delta is not None
        assert fact.maintenance_margin_after is not None
        if (
            account.before.reserved_margin is None
            or account.before.occupied_margin is None
            or account.before.released_margin is None
            or account.after.reserved_margin is None
            or account.after.occupied_margin is None
            or account.after.released_margin is None
        ):
            raise ValueError("Margin execution requires complete Account Margin states")
        if (
            account.after.reserved_margin.amount - account.before.reserved_margin.amount
            != fact.reserved_margin_delta.amount
            or account.after.occupied_margin.amount - account.before.occupied_margin.amount
            != fact.occupied_margin_delta.amount
            or account.after.released_margin.amount - account.before.released_margin.amount
            != fact.released_margin_delta.amount
            or margin.reserved != reservation.remaining_reserved_amount.amount
            or margin.occupied != reservation.occupied_amount.amount
            or margin.maintenance != reservation.maintenance_amount.amount
            or margin.maintenance != fact.maintenance_margin_after.amount
        ):
            raise ValueError("Margin Fact, Account and Reservation states do not reconcile")


def _one[ProjectionT: OnlyExecutionProjection](
    projections: tuple[OnlyExecutionProjection, ...], projection_type: type[ProjectionT]
) -> ProjectionT:
    matches = tuple(item for item in projections if isinstance(item, projection_type))
    if len(matches) != 1:
        raise ValueError(f"prepared execution requires exactly one {projection_type.__name__}")
    return matches[0]


def _trade_fact(prepared: OnlyPreparedExecutionTransaction) -> OnlyCommittedExecutionFactDraft:
    fact = prepared.fact_draft
    if not isinstance(fact, OnlyCommittedExecutionFactDraft):
        raise ValueError("Trade execution requires a Trade Fact")
    return fact


def _all[ProjectionT: OnlyExecutionProjection](
    projections: tuple[OnlyExecutionProjection, ...], projection_type: type[ProjectionT]
) -> tuple[ProjectionT, ...]:
    return tuple(item for item in projections if isinstance(item, projection_type))


def _increases_position(side: OnlyOrderSide, offset: OnlyOffset) -> bool:
    del side
    return offset in {OnlyOffset.NONE, OnlyOffset.OPEN}


__all__ = ["OnlyPreparedExecutionEconomicInvariantValidator"]
