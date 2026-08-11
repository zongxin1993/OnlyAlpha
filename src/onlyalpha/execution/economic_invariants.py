"""Cross-component economic invariants for prepared execution transactions."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import TYPE_CHECKING

from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide
from onlyalpha.transaction.enums import OnlyRuntimeOperationKind
from onlyalpha.transaction.projection import (
    OnlyAccountCashReservationExecutionProjection,
    OnlyAccountExecutionProjection,
    OnlyAllocationExecutionProjection,
    OnlyFeeApplicationProjection,
    OnlyMarginExecutionProjection,
    OnlyMarginReservationExecutionProjection,
    OnlyOrderAcceptedExecutionProjection,
    OnlyOrderExecutionProjection,
    OnlyOrderFeeAccrualProjection,
    OnlyOrderTerminalExecutionProjection,
    OnlyPositionExecutionProjection,
    OnlyPositionReservationExecutionProjection,
    OnlyRiskExecutionProjection,
    OnlyRiskReservationExecutionProjection,
    OnlyRuntimeProjection,
    OnlySettlementExecutionProjection,
    OnlyStrategyCashReservationExecutionProjection,
    OnlyStrategyLedgerExecutionProjection,
)

from .reservation_presence import OnlyExecutionReservationPresence, only_expected_execution_reservations
from .trade_fact import OnlyCommittedExecutionFactDraft

if TYPE_CHECKING:
    from onlyalpha.transaction.transaction import OnlyPreparedRuntimeTransaction


class OnlyPreparedExecutionEconomicInvariantValidator:
    """Reject a prepared transaction whose facts and authority states disagree."""

    def validate(self, prepared: OnlyPreparedRuntimeTransaction) -> None:
        if prepared.operation_kind is OnlyRuntimeOperationKind.ORDER_ACCEPTED:
            self._validate_accepted(prepared)
            return
        if prepared.operation_kind is OnlyRuntimeOperationKind.ORDER_TERMINAL:
            self._validate_terminal(prepared)
            return
        fact = _trade_fact(prepared)
        order = _one(prepared.projections, OnlyOrderExecutionProjection)
        position = _one(prepared.projections, OnlyPositionExecutionProjection)
        allocation = _one(prepared.projections, OnlyAllocationExecutionProjection)
        settlement = _one(prepared.projections, OnlySettlementExecutionProjection)
        fee = _one(prepared.projections, OnlyFeeApplicationProjection)
        fee_accrual = _one(prepared.projections, OnlyOrderFeeAccrualProjection)
        account = _one(prepared.projections, OnlyAccountExecutionProjection)
        ledger = _one(prepared.projections, OnlyStrategyLedgerExecutionProjection)
        presence = only_expected_execution_reservations(
            market_product_id=fact.market_product_id,
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
        net_fee = fact.fee_total_charges.amount - fact.fee_total_rebates.amount
        if position.after.fees.amount - position_fee_before != net_fee:
            raise ValueError("Position projection cumulative fee contradicts execution fact")
        if allocation.after.fees.amount - allocation_fee_before != net_fee:
            raise ValueError("Allocation projection cumulative fee contradicts execution fact")

        if (
            fee.after.total_charges != fact.fee_total_charges
            or fee.after.total_rebates != fact.fee_total_rebates
            or fee.after.application != fact.fee_application
            or fee.after.application.application_id != fact.fee_application_id
            or fee.after.application.trade_id != fact.trade_id
            or fee.after.application.local_finality.value != fact.fee_status
        ):
            raise ValueError("Fee projection contradicts execution fact")
        if (
            fee_accrual.after.cumulative_charges != fact.order_cumulative_fee_charges_after
            or fee_accrual.after.cumulative_rebates != fact.order_cumulative_fee_rebates_after
            or fee.after.total_charges != fact.incremental_fee_charges
            or fee.after.total_rebates != fact.incremental_fee_rebates
        ):
            raise ValueError("Order fee accrual projection contradicts execution fact")

        if account.after.ledger_cash.amount - account.before.ledger_cash.amount != fact.account_cash_delta.amount:
            raise ValueError("Account projection cash delta contradicts execution fact")
        if account.after.fees.amount - account.before.fees.amount != fact.account_fee_delta.amount:
            raise ValueError("Account projection fee delta contradicts execution fact")
        if (
            account.after.realized_pnl.amount - account.before.realized_pnl.amount
            != fact.account_realized_pnl_delta.amount
        ):
            raise ValueError("Account projection realized PnL contradicts execution fact")
        if ledger.after.ledger_cash.amount - ledger.before.ledger_cash.amount != fact.ledger_cash_delta.amount:
            raise ValueError("Strategy Ledger projection cash delta contradicts execution fact")
        if ledger.after.fees.amount - ledger.before.fees.amount != fact.ledger_fee_delta.amount:
            raise ValueError("Strategy Ledger projection fee delta contradicts execution fact")
        if (
            ledger.after.realized_pnl.amount - ledger.before.realized_pnl.amount
            != fact.ledger_realized_pnl_delta.amount
        ):
            raise ValueError("Strategy Ledger projection realized PnL contradicts execution fact")
        expected_cash_delta = (
            -(fact.settled_notional.amount + fact.fee_total_charges.amount - fact.fee_total_rebates.amount)
            if fact.order_side is OnlyOrderSide.BUY
            else fact.settled_notional.amount - fact.fee_total_charges.amount + fact.fee_total_rebates.amount
        )
        if fact.cash_delta.amount != expected_cash_delta:
            raise ValueError("execution Fact cash delta contradicts authoritative trade cost")
        if fact.order_side is OnlyOrderSide.SELL and (
            fact.gross_cash_inflow != fact.gross_notional
            or fact.net_cash_inflow.amount
            != fact.gross_notional.amount - fact.incremental_fee_charges.amount + fact.incremental_fee_rebates.amount
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
        if fact.position_effect.value == "CLOSE":
            if position.before is None or allocation.before is None:
                raise ValueError("Close cost authority requires Position and Allocation before states")
            position_released = (
                position.before.cumulative_open_price_quantity - position.after.cumulative_open_price_quantity
            )
            allocation_released = (
                allocation.before.cumulative_open_price_quantity - allocation.after.cumulative_open_price_quantity
            )
            if not (position_released == allocation_released == fact.released_open_price_quantity):
                raise ValueError("attributed close cost contradicts Position or Allocation Projection")
            _validate_close_average(
                "Position",
                position.after.total_quantity.value,
                position.after.cumulative_open_price_quantity,
                position.after.average_open_price,
            )
            _validate_close_average(
                "Allocation",
                allocation.after.total_quantity.value,
                allocation.after.cumulative_open_price_quantity,
                allocation.after.average_open_price,
            )
            quantum = Decimal(1).scaleb(-fact.currency.precision)
            expected_realized = (
                (fact.fill_price.value * fact.fill_quantity.value - fact.released_open_price_quantity)
                * fact.contract_multiplier.value
            ).quantize(quantum, rounding=ROUND_HALF_EVEN)
            if (
                fact.realized_pnl_delta.amount != expected_realized
                or fact.position_realized_pnl_delta != fact.realized_pnl_delta
                or fact.allocation_realized_pnl_delta != fact.realized_pnl_delta
                or fact.account_realized_pnl_delta != fact.realized_pnl_delta
                or fact.ledger_realized_pnl_delta != fact.realized_pnl_delta
            ):
                raise ValueError("attributed close realized PnL authority is inconsistent")

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
    def _validate_accepted(prepared: OnlyPreparedRuntimeTransaction) -> None:
        from .accepted_fact import OnlyCommittedOrderAcceptedFactDraft

        fact = prepared.fact_draft
        if not isinstance(fact, OnlyCommittedOrderAcceptedFactDraft):
            raise ValueError("Accepted transaction requires Accepted Fact")
        order = _one(prepared.projections, OnlyOrderAcceptedExecutionProjection)
        components = tuple(item.identity.component.value for item in prepared.projections)
        expected = (
            ("ORDER", "STRATEGY_LEDGER", "STRATEGY_CASH_RESERVATION")
            if order.before.side is OnlyOrderSide.BUY
            else ("ORDER", "POSITION", "POSITION_RESERVATION")
        )
        if components != expected:
            raise ValueError("Accepted transaction projection set is incomplete")
        if (
            order.accepted_identity != fact.accepted_identity
            or order.broker_update_id != fact.broker_update_id
            or order.after.venue_order_id != fact.venue_order_id
            or order.after.quantity != order.before.quantity
            or order.after.filled_quantity != order.before.filled_quantity
            or order.after.remaining_quantity != order.before.remaining_quantity
        ):
            raise ValueError("Accepted Order projection contradicts fact")
        if order.before.side is OnlyOrderSide.BUY:
            ledger = _one(prepared.projections, OnlyStrategyLedgerExecutionProjection)
            cash_reservation = _one(prepared.projections, OnlyStrategyCashReservationExecutionProjection)
            if (
                cash_reservation.before is None
                or cash_reservation.before.remaining_amount != cash_reservation.after.remaining_amount
                or cash_reservation.before.consumed_amount != cash_reservation.after.consumed_amount
                or ledger.before.ledger_cash != ledger.after.ledger_cash
                or ledger.before.cash_reserved != ledger.after.cash_reserved
                or ledger.before.fees != ledger.after.fees
            ):
                raise ValueError("BUY Accepted changed economic cash authority")
        else:
            position = _one(prepared.projections, OnlyPositionExecutionProjection)
            position_reservation = _one(prepared.projections, OnlyPositionReservationExecutionProjection)
            if (
                position_reservation.before is None
                or position_reservation.before.remaining_quantity != position_reservation.after.remaining_quantity
                or position.before is None
                or position.before.total_quantity != position.after.total_quantity
                or position.before.risk_reserved_quantity.value - position.after.risk_reserved_quantity.value
                != position_reservation.before.remaining_quantity.value
            ):
                raise ValueError("SELL Accepted hold release authority is inconsistent")

    @staticmethod
    def _validate_terminal(prepared: OnlyPreparedRuntimeTransaction) -> None:
        from .terminal_fact import (
            OnlyCommittedTerminalExecutionFactDraft,
            OnlyTerminalEconomicReleaseKind,
        )

        fact = prepared.fact_draft
        if not isinstance(fact, OnlyCommittedTerminalExecutionFactDraft):
            raise ValueError("terminal transaction requires Terminal Fact")
        order = _one(prepared.projections, OnlyOrderTerminalExecutionProjection)
        risk_reservation = _one(prepared.projections, OnlyRiskReservationExecutionProjection)
        risk = _one(prepared.projections, OnlyRiskExecutionProjection)
        if risk_reservation.before is None:
            raise ValueError("terminal transaction requires Risk Reservation authority")
        risk_released = risk_reservation.before.remaining_quantity
        if (
            order.terminal_identity != fact.terminal_identity
            or order.broker_update_id != fact.broker_update_id
            or order.after.status is not fact.terminal_status
            or order.after.filled_quantity != fact.filled_quantity_before
            or order.after.remaining_quantity != fact.order_remaining_quantity
            or risk_released != fact.risk_released_quantity
            or risk_reservation.after.remaining_quantity.value != 0
            or risk_reservation.after.consumed_quantity != risk_reservation.before.consumed_quantity
            or risk.after.active_order_count - risk.before.active_order_count != fact.active_order_count_delta
            or risk.after.cluster_active_order_count - risk.before.cluster_active_order_count
            != fact.cluster_active_order_count_delta
            or risk.after.reserved_quantity != risk.before.reserved_quantity - risk_released.value
        ):
            raise ValueError("terminal projections contradict Terminal Fact")
        components = tuple(item.identity.component.value for item in prepared.projections)
        if fact.economic_release_kind is OnlyTerminalEconomicReleaseKind.CASH_RESERVATION:
            expected = (
                "ORDER",
                "ACCOUNT",
                "STRATEGY_LEDGER",
                "ACCOUNT_CASH_RESERVATION",
                "STRATEGY_CASH_RESERVATION",
                "RISK_RESERVATION",
                "RISK",
            )
            if components != expected:
                raise ValueError("BUY terminal projection set is incomplete")
            account = _one(prepared.projections, OnlyAccountExecutionProjection)
            ledger = _one(prepared.projections, OnlyStrategyLedgerExecutionProjection)
            account_reservation = _one(prepared.projections, OnlyAccountCashReservationExecutionProjection)
            strategy_reservation = _one(prepared.projections, OnlyStrategyCashReservationExecutionProjection)
            release = fact.reservation_released_cash
            if (
                release is None
                or account_reservation.before is None
                or strategy_reservation.before is None
                or account_reservation.before.remaining_amount != release
                or strategy_reservation.before.remaining_amount != release
                or account_reservation.after.remaining_amount.amount != 0
                or strategy_reservation.after.remaining_amount.amount != 0
                or account.before.order_reserved_cash.amount - account.after.order_reserved_cash.amount
                != release.amount
                or ledger.before.cash_reserved.amount - ledger.after.cash_reserved.amount != release.amount
                or account.before.ledger_cash != account.after.ledger_cash
                or ledger.before.ledger_cash != ledger.after.ledger_cash
            ):
                raise ValueError("BUY terminal cash conservation failed")
        else:
            if components not in {
                ("ORDER", "POSITION", "ALLOCATION", "POSITION_RESERVATION", "RISK_RESERVATION", "RISK"),
                ("ORDER", "ALLOCATION", "POSITION_RESERVATION", "RISK_RESERVATION", "RISK"),
            }:
                raise ValueError("SELL terminal projection set is incomplete")
            allocation = _one(prepared.projections, OnlyAllocationExecutionProjection)
            reservation = _one(prepared.projections, OnlyPositionReservationExecutionProjection)
            release_quantity = fact.reservation_released_quantity
            if (
                release_quantity is None
                or reservation.before is None
                or reservation.before.remaining_quantity != release_quantity
                or reservation.after.remaining_quantity.value != 0
                or allocation.before is None
                or allocation.before.risk_reserved_quantity.value - allocation.after.risk_reserved_quantity.value
                != release_quantity.value
            ):
                raise ValueError("SELL terminal Allocation/Reservation conservation failed")

    @staticmethod
    def _validate_cash_reservations(prepared: OnlyPreparedRuntimeTransaction) -> None:
        fact = _trade_fact(prepared)
        accounts = _all(prepared.projections, OnlyAccountCashReservationExecutionProjection)
        strategies = _all(prepared.projections, OnlyStrategyCashReservationExecutionProjection)
        if accounts or strategies:
            account = accounts[0]
            strategy = strategies[0]
            actual_consumption = fact.settled_notional.amount + fact.fee_total_charges.amount
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
    def _validate_risk_reservations(prepared: OnlyPreparedRuntimeTransaction) -> None:
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
    def _validate_scope(prepared: OnlyPreparedRuntimeTransaction) -> None:
        fact = _trade_fact(prepared)
        order = _one(prepared.projections, OnlyOrderExecutionProjection).after
        position = _one(prepared.projections, OnlyPositionExecutionProjection).after
        allocation = _one(prepared.projections, OnlyAllocationExecutionProjection).after
        account = _one(prepared.projections, OnlyAccountExecutionProjection).after
        ledger = _one(prepared.projections, OnlyStrategyLedgerExecutionProjection).after
        fee = _one(prepared.projections, OnlyFeeApplicationProjection).after
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
            or fee.application.subject.runtime_id != fact.runtime_id
            or fee.application.subject.cluster_id != fact.cluster_id
            or fee.application.subject.account_id != fact.account_id
            or fee.application.subject.order_id != fact.order_id
            or fee.application.trade_id != fact.trade_id
            or any(
                record.account_id != fact.account_id
                or record.order_id != fact.order_id
                or record.trade_id != fact.trade_id
                or record.incremental_amount.currency != fact.currency
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
        prepared: OnlyPreparedRuntimeTransaction, presence: OnlyExecutionReservationPresence
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
    def _validate_margin_account(prepared: OnlyPreparedRuntimeTransaction) -> None:
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


def _one[ProjectionT: OnlyRuntimeProjection](
    projections: tuple[OnlyRuntimeProjection, ...], projection_type: type[ProjectionT]
) -> ProjectionT:
    matches = tuple(item for item in projections if isinstance(item, projection_type))
    if len(matches) != 1:
        raise ValueError(f"prepared execution requires exactly one {projection_type.__name__}")
    return matches[0]


def _validate_close_average(
    component: str,
    quantity: Decimal,
    cumulative_cost: Decimal,
    average: object,
) -> None:
    from onlyalpha.domain.value import OnlyPrice

    if quantity == 0:
        if cumulative_cost != 0 or average is not None:
            raise ValueError(f"{component} terminal close cost authority is not zero")
        return
    if not isinstance(average, OnlyPrice):
        raise ValueError(f"{component} remaining close average is missing")
    expected = (cumulative_cost / quantity).quantize(
        Decimal(1).scaleb(-average.precision),
        rounding=ROUND_HALF_EVEN,
    )
    if average.value != expected:
        raise ValueError(f"{component} remaining close average contradicts exact cost")


def _trade_fact(prepared: OnlyPreparedRuntimeTransaction) -> OnlyCommittedExecutionFactDraft:
    fact = prepared.fact_draft
    if not isinstance(fact, OnlyCommittedExecutionFactDraft):
        raise ValueError("Trade execution requires a Trade Fact")
    return fact


def _all[ProjectionT: OnlyRuntimeProjection](
    projections: tuple[OnlyRuntimeProjection, ...], projection_type: type[ProjectionT]
) -> tuple[ProjectionT, ...]:
    return tuple(item for item in projections if isinstance(item, projection_type))


def _increases_position(side: OnlyOrderSide, offset: OnlyOffset) -> bool:
    del side
    return offset in {OnlyOffset.NONE, OnlyOffset.OPEN}


__all__ = ["OnlyPreparedExecutionEconomicInvariantValidator"]
