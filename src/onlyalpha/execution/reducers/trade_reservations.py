"""Pure cash and Risk reservation reducers for Generic T0 BUY OPEN."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from onlyalpha.account.enums import OnlyAccountReservationState
from onlyalpha.domain.value import OnlyMoney, OnlyQuantity
from onlyalpha.event.model import OnlyEventSource, OnlyEventType
from onlyalpha.risk.enums import OnlyRiskReservationState
from onlyalpha.strategy_ledger.enums import OnlyStrategyCashReservationStage, OnlyStrategyCashReservationState

from ..execution_state import (
    OnlyAccountCashReservationExecutionState,
    OnlyRiskReservationExecutionState,
    OnlyStrategyCashReservationExecutionState,
)
from ..planned_trade import OnlyPlannedTrade
from ..planning_results import OnlyExecutionEventIntent
from ..projection import (
    OnlyAccountCashReservationExecutionProjection,
    OnlyExecutionProjectionComponent,
    OnlyRiskExecutionProjection,
    OnlyRiskExecutionState,
    OnlyRiskReservationExecutionProjection,
    OnlyStrategyCashReservationExecutionProjection,
)
from ..projection_builder import OnlyExecutionProjectionBuilder


@dataclass(frozen=True, slots=True)
class OnlyAccountCashReservationTradeReduction:
    after: OnlyAccountCashReservationExecutionState
    projection: OnlyAccountCashReservationExecutionProjection
    consumed: OnlyMoney
    released: OnlyMoney
    event_intents: tuple[OnlyExecutionEventIntent, ...]


@dataclass(frozen=True, slots=True)
class OnlyStrategyCashReservationTradeReduction:
    after: OnlyStrategyCashReservationExecutionState
    projection: OnlyStrategyCashReservationExecutionProjection
    consumed: OnlyMoney
    released: OnlyMoney
    event_intents: tuple[OnlyExecutionEventIntent, ...]


@dataclass(frozen=True, slots=True)
class OnlyRiskReservationTradeReduction:
    after: OnlyRiskReservationExecutionState
    projection: OnlyRiskReservationExecutionProjection


@dataclass(frozen=True, slots=True)
class OnlyRiskTradeReduction:
    after: OnlyRiskExecutionState
    projection: OnlyRiskExecutionProjection
    event_intents: tuple[OnlyExecutionEventIntent, ...]


class OnlyAccountCashReservationTradeReducer:
    def reduce(
        self,
        before: OnlyAccountCashReservationExecutionState,
        trade: OnlyPlannedTrade,
        *,
        projection_sequence: int,
    ) -> OnlyAccountCashReservationTradeReduction:
        cost = trade.settled_notional + trade.authoritative_fee
        available = before.remaining_amount.amount
        if cost.amount > available:
            raise ValueError("Account cash Reservation is smaller than authoritative Trade cost")
        remaining = available - cost.amount
        released = OnlyMoney(remaining, cost.currency)
        after = replace(
            before,
            consumed_amount=OnlyMoney(before.consumed_amount.amount + cost.amount, cost.currency),
            remaining_amount=OnlyMoney(Decimal(0), cost.currency),
            state=(OnlyAccountReservationState.CONSUMED if remaining == 0 else OnlyAccountReservationState.RELEASED),
            updated_at=trade.ts_init,
            version=before.version + 1,
        )
        builder = OnlyExecutionProjectionBuilder()
        projection = OnlyAccountCashReservationExecutionProjection(
            builder.identity(
                component=OnlyExecutionProjectionComponent.ACCOUNT_CASH_RESERVATION,
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
            _intent(
                OnlyExecutionProjectionComponent.ACCOUNT_CASH_RESERVATION, "ACCOUNT_CASH_RESERVATION_CONSUMED", after
            )
        ]
        if released.amount:
            intents.append(
                _intent(
                    OnlyExecutionProjectionComponent.ACCOUNT_CASH_RESERVATION,
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
        *,
        projection_sequence: int,
    ) -> OnlyStrategyCashReservationTradeReduction:
        cost = trade.settled_notional + trade.authoritative_fee
        available = before.remaining_amount.amount
        if cost.amount > available:
            raise ValueError("Strategy cash Reservation is smaller than authoritative Trade cost")
        remaining = available - cost.amount
        released = OnlyMoney(remaining, cost.currency)
        after = replace(
            before,
            consumed_amount=OnlyMoney(before.consumed_amount.amount + cost.amount, cost.currency),
            remaining_amount=OnlyMoney(Decimal(0), cost.currency),
            state=(
                OnlyStrategyCashReservationState.CONSUMED
                if remaining == 0
                else OnlyStrategyCashReservationState.RELEASED
            ),
            stage=(before.stage if remaining == 0 else OnlyStrategyCashReservationStage.RELEASED),
            updated_at=trade.ts_init,
            version=before.version + 1,
        )
        builder = OnlyExecutionProjectionBuilder()
        projection = OnlyStrategyCashReservationExecutionProjection(
            builder.identity(
                component=OnlyExecutionProjectionComponent.STRATEGY_CASH_RESERVATION,
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
                OnlyExecutionProjectionComponent.STRATEGY_CASH_RESERVATION, "STRATEGY_CASH_RESERVATION_CONSUMED", after
            )
        ]
        if released.amount:
            intents.append(
                _intent(
                    OnlyExecutionProjectionComponent.STRATEGY_CASH_RESERVATION,
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
        remaining_notional = OnlyMoney(
            before.remaining_notional.amount - trade.gross_notional.amount,
            before.remaining_notional.currency,
        )
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
            state=(
                OnlyRiskReservationState.CONSUMED if remaining_quantity.value == 0 else OnlyRiskReservationState.ACTIVE
            ),
            updated_at=trade.ts_init,
            version=before.version + 1,
        )
        builder = OnlyExecutionProjectionBuilder()
        projection = OnlyRiskReservationExecutionProjection(
            builder.identity(
                component=OnlyExecutionProjectionComponent.RISK_RESERVATION,
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
        return OnlyRiskReservationTradeReduction(after, projection)


class OnlyRiskTradeReducer:
    def reduce(
        self,
        before: OnlyRiskExecutionState,
        reservation_after: OnlyRiskReservationExecutionState,
        trade: OnlyPlannedTrade,
        *,
        projection_sequence: int,
    ) -> OnlyRiskTradeReduction:
        if reservation_after.remaining_notional is None:
            raise ValueError("Generic cash Risk state requires notional exposure")
        after = replace(
            before,
            quantity_exposure=reservation_after.remaining_quantity,
            notional_exposure=reservation_after.remaining_notional,
            updated_at=trade.ts_init,
            version=before.version + 1,
        )
        builder = OnlyExecutionProjectionBuilder()
        projection = OnlyRiskExecutionProjection(
            builder.identity(
                component=OnlyExecutionProjectionComponent.RISK,
                entity_key=f"{after.cluster_id}:{after.account_id}:{after.instrument_id}:{after.order_id}",
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
            (_intent(OnlyExecutionProjectionComponent.RISK, "RISK_STATE_UPDATED", after),),
        )


def _intent(component: OnlyExecutionProjectionComponent, event_type: str, payload: object) -> OnlyExecutionEventIntent:
    encoded = payload.to_dict() if hasattr(payload, "to_dict") else payload
    return OnlyExecutionEventIntent(
        component, OnlyEventType(event_type), encoded, OnlyEventSource("execution.trade_planner")
    )


__all__ = [name for name in globals() if name.startswith("Only")]
