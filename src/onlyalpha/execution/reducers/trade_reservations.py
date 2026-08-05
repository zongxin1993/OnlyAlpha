"""Pure cash and Risk reservation reducers for Generic T0 BUY OPEN."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from onlyalpha.account.enums import OnlyAccountReservationState
from onlyalpha.domain.value import OnlyMoney, OnlyQuantity
from onlyalpha.event.model import OnlyEventSource, OnlyEventType
from onlyalpha.position.enums import OnlyPositionReservationState
from onlyalpha.risk.enums import OnlyRiskReservationState
from onlyalpha.strategy_ledger.enums import OnlyStrategyCashReservationStage, OnlyStrategyCashReservationState
from onlyalpha.transaction.projection import (
    OnlyAccountCashReservationExecutionProjection,
    OnlyPositionReservationExecutionProjection,
    OnlyRiskExecutionProjection,
    OnlyRiskReservationExecutionProjection,
    OnlyRuntimeProjectionComponent,
    OnlyStrategyCashReservationExecutionProjection,
)
from onlyalpha.transaction.projection_builder import OnlyRuntimeProjectionBuilder

from ..execution_state import (
    OnlyAccountCashReservationExecutionState,
    OnlyPositionReservationExecutionState,
    OnlyRiskExecutionState,
    OnlyRiskReservationExecutionState,
    OnlyStrategyCashReservationExecutionState,
)
from ..planned_trade import OnlyPlannedTrade
from ..planning_results import OnlyExecutionEventIntent


@dataclass(frozen=True, slots=True)
class OnlyAccountCashReservationTradeReduction:
    after: OnlyAccountCashReservationExecutionState
    projection: OnlyAccountCashReservationExecutionProjection
    consumed_delta: OnlyMoney
    released_delta: OnlyMoney
    event_intents: tuple[OnlyExecutionEventIntent, ...]


@dataclass(frozen=True, slots=True)
class OnlyStrategyCashReservationTradeReduction:
    after: OnlyStrategyCashReservationExecutionState
    projection: OnlyStrategyCashReservationExecutionProjection
    consumed_delta: OnlyMoney
    released_delta: OnlyMoney
    event_intents: tuple[OnlyExecutionEventIntent, ...]


@dataclass(frozen=True, slots=True)
class OnlyRiskReservationTradeReduction:
    after: OnlyRiskReservationExecutionState
    projection: OnlyRiskReservationExecutionProjection
    consumed_quantity_delta: OnlyQuantity
    consumed_notional_delta: OnlyMoney
    released_notional_delta: OnlyMoney


@dataclass(frozen=True, slots=True)
class OnlyRiskTradeReduction:
    after: OnlyRiskExecutionState
    projection: OnlyRiskExecutionProjection
    event_intents: tuple[OnlyExecutionEventIntent, ...]


@dataclass(frozen=True, slots=True)
class OnlyPositionReservationTradeReduction:
    after: OnlyPositionReservationExecutionState
    projection: OnlyPositionReservationExecutionProjection
    consumed_quantity_delta: OnlyQuantity
    event_intents: tuple[OnlyExecutionEventIntent, ...]


class OnlyPositionReservationTradeReducer:
    def reduce(
        self,
        before: OnlyPositionReservationExecutionState,
        trade: OnlyPlannedTrade,
        terminal_fill: bool,
        *,
        projection_sequence: int,
    ) -> OnlyPositionReservationTradeReduction:
        if before.consumed_quantity is None:
            raise ValueError("Position Reservation consumed authority is missing")
        if before.remaining_quantity.value < trade.quantity.value:
            raise ValueError("CLOSE_POSITION_RESERVATION_INSUFFICIENT")
        remaining = OnlyQuantity(
            before.remaining_quantity.value - trade.quantity.value,
            before.remaining_quantity.precision,
        )
        if terminal_fill and remaining.value != 0:
            raise ValueError("CLOSE_POSITION_RESERVATION_INSUFFICIENT")
        after = replace(
            before,
            remaining_quantity=remaining,
            consumed_quantity=OnlyQuantity(
                before.consumed_quantity.value + trade.quantity.value,
                before.quantity.precision,
            ),
            state=(
                OnlyPositionReservationState.CONSUMED
                if remaining.value == 0
                else OnlyPositionReservationState.PARTIALLY_CONSUMED
            ),
            updated_at=trade.ts_init,
            version=before.version + 1,
        )
        builder = OnlyRuntimeProjectionBuilder()
        projection = OnlyPositionReservationExecutionProjection(
            builder.identity(
                component=OnlyRuntimeProjectionComponent.POSITION_RESERVATION,
                entity_key=str(after.reservation_id),
                before=before,
                after=after,
                projection_sequence=projection_sequence,
            ),
            before,
            after,
        )
        projection = builder.finalize(projection)
        assert isinstance(projection, OnlyPositionReservationExecutionProjection)
        return OnlyPositionReservationTradeReduction(
            after,
            projection,
            trade.quantity,
            (
                _intent(
                    OnlyRuntimeProjectionComponent.POSITION_RESERVATION,
                    "POSITION_RESERVATION_CONSUMED",
                    after,
                ),
            ),
        )


class OnlyAccountCashReservationTradeReducer:
    def reduce(
        self,
        before: OnlyAccountCashReservationExecutionState,
        trade: OnlyPlannedTrade,
        terminal_fill: bool = True,
        *,
        projection_sequence: int,
    ) -> OnlyAccountCashReservationTradeReduction:
        cost = trade.settled_notional + trade.authoritative_fee
        available = before.remaining_amount.amount
        if cost.amount > available:
            raise ValueError("Account cash Reservation is smaller than authoritative Trade cost")
        remaining_after_cost = available - cost.amount
        released = OnlyMoney(remaining_after_cost if terminal_fill else Decimal(0), cost.currency)
        remaining = OnlyMoney(Decimal(0) if terminal_fill else remaining_after_cost, cost.currency)
        if not terminal_fill and remaining.amount <= 0:
            raise ValueError("ACCOUNT_RESERVATION_INSUFFICIENT")
        state = (
            OnlyAccountReservationState.RELEASED
            if released.amount
            else (
                OnlyAccountReservationState.CONSUMED
                if terminal_fill
                else OnlyAccountReservationState.PARTIALLY_CONSUMED
            )
        )
        after = replace(
            before,
            consumed_amount=OnlyMoney(before.consumed_amount.amount + cost.amount, cost.currency),
            remaining_amount=remaining,
            state=state,
            updated_at=trade.ts_init,
            version=before.version + 1 + int(released.amount > 0),
        )
        builder = OnlyRuntimeProjectionBuilder()
        projection = OnlyAccountCashReservationExecutionProjection(
            builder.identity(
                component=OnlyRuntimeProjectionComponent.ACCOUNT_CASH_RESERVATION,
                entity_key=after.reservation_id,
                before=before,
                after=after,
                projection_sequence=projection_sequence,
            ),
            before,
            after,
        )
        projection = builder.finalize(projection)
        assert isinstance(projection, OnlyAccountCashReservationExecutionProjection)
        intents = [
            _intent(OnlyRuntimeProjectionComponent.ACCOUNT_CASH_RESERVATION, "ACCOUNT_CASH_RESERVATION_CONSUMED", after)
        ]
        if released.amount:
            intents.append(
                _intent(
                    OnlyRuntimeProjectionComponent.ACCOUNT_CASH_RESERVATION,
                    "ACCOUNT_CASH_RESERVATION_RELEASED",
                    after,
                )
            )
        return OnlyAccountCashReservationTradeReduction(after, projection, cost, released, tuple(intents))


class OnlyStrategyCashReservationTradeReducer:
    def reduce(
        self,
        before: OnlyStrategyCashReservationExecutionState,
        trade: OnlyPlannedTrade,
        terminal_fill: bool = True,
        *,
        projection_sequence: int,
    ) -> OnlyStrategyCashReservationTradeReduction:
        cost = trade.settled_notional + trade.authoritative_fee
        available = before.remaining_amount.amount
        if cost.amount > available:
            raise ValueError("Strategy cash Reservation is smaller than authoritative Trade cost")
        remaining_after_cost = available - cost.amount
        released = OnlyMoney(remaining_after_cost if terminal_fill else Decimal(0), cost.currency)
        remaining = OnlyMoney(Decimal(0) if terminal_fill else remaining_after_cost, cost.currency)
        if not terminal_fill and remaining.amount <= 0:
            raise ValueError("STRATEGY_RESERVATION_INSUFFICIENT")
        state = (
            OnlyStrategyCashReservationState.RELEASED
            if released.amount
            else (
                OnlyStrategyCashReservationState.CONSUMED
                if terminal_fill
                else OnlyStrategyCashReservationState.PARTIALLY_CONSUMED
            )
        )
        after = replace(
            before,
            consumed_amount=OnlyMoney(before.consumed_amount.amount + cost.amount, cost.currency),
            remaining_amount=remaining,
            state=state,
            stage=(OnlyStrategyCashReservationStage.RELEASED if released.amount else before.stage),
            updated_at=trade.ts_init,
            version=before.version + 1 + int(released.amount > 0),
        )
        builder = OnlyRuntimeProjectionBuilder()
        projection = OnlyStrategyCashReservationExecutionProjection(
            builder.identity(
                component=OnlyRuntimeProjectionComponent.STRATEGY_CASH_RESERVATION,
                entity_key=str(after.reservation_id),
                before=before,
                after=after,
                projection_sequence=projection_sequence,
            ),
            before,
            after,
        )
        projection = builder.finalize(projection)
        assert isinstance(projection, OnlyStrategyCashReservationExecutionProjection)
        intents = [
            _intent(
                OnlyRuntimeProjectionComponent.STRATEGY_CASH_RESERVATION, "STRATEGY_CASH_RESERVATION_CONSUMED", after
            )
        ]
        if released.amount:
            intents.append(
                _intent(
                    OnlyRuntimeProjectionComponent.STRATEGY_CASH_RESERVATION,
                    "STRATEGY_CASH_RESERVATION_RELEASED",
                    after,
                )
            )
        return OnlyStrategyCashReservationTradeReduction(after, projection, cost, released, tuple(intents))


class OnlyRiskReservationTradeReducer:
    def reduce(
        self,
        before: OnlyRiskReservationExecutionState,
        trade: OnlyPlannedTrade,
        terminal_fill: bool = True,
        *,
        projection_sequence: int,
    ) -> OnlyRiskReservationTradeReduction:
        if before.remaining_quantity.value < trade.quantity.value:
            raise ValueError("Risk Reservation quantity is smaller than Fill")
        if before.remaining_notional is None or before.consumed_notional is None:
            raise ValueError("Generic cash Risk Reservation requires notional authority")
        if before.remaining_notional.amount < trade.gross_notional.amount:
            raise ValueError("Risk Reservation notional is smaller than Fill")
        remaining_quantity = OnlyQuantity(
            before.remaining_quantity.value - trade.quantity.value, before.remaining_quantity.precision
        )
        remaining_notional_after_consumption = OnlyMoney(
            before.remaining_notional.amount - trade.gross_notional.amount,
            before.remaining_notional.currency,
        )
        released_notional = OnlyMoney(
            remaining_notional_after_consumption.amount if terminal_fill else Decimal(0),
            before.remaining_notional.currency,
        )
        remaining_notional = OnlyMoney(
            remaining_notional_after_consumption.amount - released_notional.amount,
            before.remaining_notional.currency,
        )
        released_notional_before = before.released_notional
        if released_notional_before is None:
            released_notional_before = OnlyMoney(Decimal(0), before.remaining_notional.currency)
        after = replace(
            before,
            consumed_quantity=OnlyQuantity(
                before.consumed_quantity.value + trade.quantity.value, before.consumed_quantity.precision
            ),
            consumed_notional=OnlyMoney(
                before.consumed_notional.amount + trade.gross_notional.amount,
                before.consumed_notional.currency,
            ),
            remaining_quantity=remaining_quantity,
            remaining_notional=remaining_notional,
            released_notional=OnlyMoney(
                released_notional_before.amount + released_notional.amount,
                released_notional_before.currency,
            ),
            state=(OnlyRiskReservationState.CONSUMED if terminal_fill else OnlyRiskReservationState.ACTIVE),
            updated_at=trade.ts_init,
            version=before.version + 1,
        )
        builder = OnlyRuntimeProjectionBuilder()
        projection = OnlyRiskReservationExecutionProjection(
            builder.identity(
                component=OnlyRuntimeProjectionComponent.RISK_RESERVATION,
                entity_key=str(after.reservation_id),
                before=before,
                after=after,
                projection_sequence=projection_sequence,
            ),
            before,
            after,
        )
        projection = builder.finalize(projection)
        assert isinstance(projection, OnlyRiskReservationExecutionProjection)
        if terminal_fill and remaining_quantity.value != 0:
            raise ValueError("RISK_RESERVATION_INSUFFICIENT")
        return OnlyRiskReservationTradeReduction(
            after,
            projection,
            trade.quantity,
            trade.gross_notional,
            released_notional,
        )


class OnlyRiskTradeReducer:
    def reduce(
        self,
        before: OnlyRiskExecutionState,
        reservation_reduction: OnlyRiskReservationTradeReduction,
        trade: OnlyPlannedTrade,
        terminal_fill: bool,
        *,
        projection_sequence: int,
    ) -> OnlyRiskTradeReduction:
        reserved_quantity = before.reserved_quantity - reservation_reduction.consumed_quantity_delta.value
        if reserved_quantity < 0:
            raise ValueError("Risk reserved quantity underflow")
        reserved_notional = before.reserved_notional
        remaining_order_notional = before.remaining_order_notional
        if reserved_notional is not None:
            if reservation_reduction.consumed_notional_delta.currency != reserved_notional.currency:
                raise ValueError("Risk Snapshot and Reservation notional currencies disagree")
            reserved_notional = OnlyMoney(
                reserved_notional.amount
                - reservation_reduction.consumed_notional_delta.amount
                - reservation_reduction.released_notional_delta.amount,
                reserved_notional.currency,
            )
            if reserved_notional.amount < 0:
                raise ValueError("RISK_RESERVATION_INSUFFICIENT")
            if remaining_order_notional is not None:
                remaining_order_notional = OnlyMoney(
                    remaining_order_notional.amount
                    - reservation_reduction.consumed_notional_delta.amount
                    - reservation_reduction.released_notional_delta.amount,
                    remaining_order_notional.currency,
                )
                if remaining_order_notional.amount < 0:
                    raise ValueError("RISK_REMAINING_NOTIONAL_UNDERFLOW")
        if before.active_order_count < int(terminal_fill) or before.cluster_active_order_count < int(terminal_fill):
            raise ValueError("Risk active Order count underflow")
        after = replace(
            before,
            ts_event=trade.ts_init,
            ts_init=trade.ts_init,
            active_order_count=before.active_order_count - int(terminal_fill),
            cluster_active_order_count=before.cluster_active_order_count - int(terminal_fill),
            reserved_quantity=reserved_quantity,
            reserved_notional=reserved_notional,
            remaining_order_notional=remaining_order_notional,
            version=before.version + 1,
        )
        builder = OnlyRuntimeProjectionBuilder()
        projection = OnlyRiskExecutionProjection(
            builder.identity(
                component=OnlyRuntimeProjectionComponent.RISK,
                entity_key=str(after.cluster_id),
                before=before,
                after=after,
                projection_sequence=projection_sequence,
            ),
            before,
            after,
        )
        projection = builder.finalize(projection)
        assert isinstance(projection, OnlyRiskExecutionProjection)
        return OnlyRiskTradeReduction(
            after,
            projection,
            (_intent(OnlyRuntimeProjectionComponent.RISK, "RISK_STATE_UPDATED", after),),
        )


def _intent(component: OnlyRuntimeProjectionComponent, event_type: str, payload: object) -> OnlyExecutionEventIntent:
    encoded = payload.to_dict() if hasattr(payload, "to_dict") else payload
    return OnlyExecutionEventIntent(
        component, OnlyEventType(event_type), encoded, OnlyEventSource("execution.trade_planner")
    )


__all__ = [name for name in globals() if name.startswith("Only")]
