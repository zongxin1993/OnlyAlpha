"""Small pure reducers shared by durable Broker lifecycle planners."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from onlyalpha.account.enums import OnlyAccountReservationState
from onlyalpha.broker.updates import OnlyBrokerOrderAcceptedUpdate, OnlyBrokerOrderRejectedUpdate
from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMoney, OnlyQuantity
from onlyalpha.position.enums import OnlyPositionReservationStage, OnlyPositionReservationState
from onlyalpha.risk.enums import OnlyRiskReleaseReason, OnlyRiskReservationState
from onlyalpha.strategy_ledger.enums import (
    OnlyStrategyCashEntryType,
    OnlyStrategyCashReservationStage,
    OnlyStrategyCashReservationState,
)
from onlyalpha.strategy_ledger.identifiers import OnlyStrategyCashEntryId
from onlyalpha.strategy_ledger.models import OnlyStrategyCashEntry

from .execution_state import (
    OnlyAccountCashReservationExecutionState,
    OnlyAccountExecutionState,
    OnlyAllocationExecutionState,
    OnlyOrderExecutionState,
    OnlyPositionExecutionState,
    OnlyPositionReservationExecutionState,
    OnlyRiskExecutionState,
    OnlyRiskReservationExecutionState,
    OnlyStrategyCashReservationExecutionState,
    OnlyStrategyLedgerExecutionState,
)
from .terminal_identity import OnlyBrokerOrderTerminalUpdate, OnlyExecutionTerminalAuthority


def only_reduce_order_accepted(
    before: OnlyOrderExecutionState,
    update: OnlyBrokerOrderAcceptedUpdate,
) -> OnlyOrderExecutionState:
    if update.order_id != before.order_id or update.runtime_id != before.runtime_id:
        raise ValueError("Accepted update scope disagrees with Order")
    if before.venue_order_id not in {None, update.venue_order_id}:
        raise ValueError("Accepted Venue Order identity conflicts with Order")
    if before.last_external_sequence is not None and update.source_sequence <= before.last_external_sequence:
        raise ValueError("Accepted Broker sequence must advance")
    if before.status not in {
        OnlyOrderStatus.SUBMITTED,
        OnlyOrderStatus.ACCEPTED,
        OnlyOrderStatus.PARTIALLY_FILLED,
        OnlyOrderStatus.PENDING_CANCEL,
    }:
        raise ValueError("Order state does not accept Broker acknowledgement")
    return replace(
        before,
        venue_order_id=update.venue_order_id,
        status=OnlyOrderStatus.ACCEPTED if before.status is OnlyOrderStatus.SUBMITTED else before.status,
        accepted_at=update.ts_init if before.status is OnlyOrderStatus.SUBMITTED else before.accepted_at,
        updated_at=max(before.updated_at, update.ts_init),
        version=before.version + 1,
        last_external_sequence=update.source_sequence,
    )


def only_reduce_order_terminal(
    before: OnlyOrderExecutionState,
    update: OnlyBrokerOrderTerminalUpdate,
    authority: OnlyExecutionTerminalAuthority,
) -> OnlyOrderExecutionState:
    status = authority.terminal_status
    if update.order_id != before.order_id or update.runtime_id != before.runtime_id:
        raise ValueError("Terminal update scope disagrees with Order")
    allowed = {
        OnlyOrderStatus.SUBMITTED,
        OnlyOrderStatus.ACCEPTED,
        OnlyOrderStatus.PARTIALLY_FILLED,
        OnlyOrderStatus.PENDING_CANCEL,
    }
    if status is OnlyOrderStatus.EXPIRED:
        allowed.remove(OnlyOrderStatus.SUBMITTED)
    if before.status not in allowed:
        raise ValueError("Order state does not accept this terminal operation")
    if before.last_external_sequence is not None and update.source_sequence <= before.last_external_sequence:
        raise ValueError("Terminal Broker sequence must advance")
    return replace(
        before,
        status=status,
        updated_at=update.ts_event,
        cancelled_at=update.ts_event if status is OnlyOrderStatus.CANCELLED else before.cancelled_at,
        rejected_at=update.ts_event if status is OnlyOrderStatus.REJECTED else before.rejected_at,
        expired_at=update.ts_event if status is OnlyOrderStatus.EXPIRED else before.expired_at,
        rejection=update.rejection if isinstance(update, OnlyBrokerOrderRejectedUpdate) else before.rejection,
        version=before.version + 1,
        last_external_sequence=update.source_sequence,
    )


def only_reduce_position_hold_release(
    before: OnlyPositionExecutionState,
    quantity: OnlyQuantity,
) -> OnlyPositionExecutionState:
    if quantity.precision != before.risk_reserved_quantity.precision:
        raise ValueError("Position hold release precision mismatch")
    if quantity.value <= 0 or quantity.value > before.risk_reserved_quantity.value:
        raise ValueError("Position hold release would underflow")
    return replace(
        before,
        risk_reserved_quantity=OnlyQuantity(
            before.risk_reserved_quantity.value - quantity.value,
            before.risk_reserved_quantity.precision,
        ),
        version=before.version + 1,
    )


def only_reduce_allocation_hold_release(
    before: OnlyAllocationExecutionState,
    quantity: OnlyQuantity,
) -> OnlyAllocationExecutionState:
    if quantity.precision != before.risk_reserved_quantity.precision:
        raise ValueError("Allocation hold release precision mismatch")
    if quantity.value <= 0 or quantity.value > before.risk_reserved_quantity.value:
        raise ValueError("Allocation hold release would underflow")
    return replace(
        before,
        risk_reserved_quantity=OnlyQuantity(
            before.risk_reserved_quantity.value - quantity.value,
            before.risk_reserved_quantity.precision,
        ),
        version=before.version + 1,
    )


def only_reduce_position_reservation_acknowledged(
    before: OnlyPositionReservationExecutionState,
    update: OnlyBrokerOrderAcceptedUpdate,
) -> OnlyPositionReservationExecutionState:
    if before.order_id != update.order_id:
        raise ValueError("Position Reservation ACK scope mismatch")
    if before.stage is not OnlyPositionReservationStage.SENT_TO_BROKER:
        raise ValueError("Position Reservation ACK requires SENT_TO_BROKER stage")
    if before.state not in {
        OnlyPositionReservationState.ACTIVE,
        OnlyPositionReservationState.PARTIALLY_CONSUMED,
    }:
        raise ValueError("Position Reservation ACK requires active remaining authority")
    return replace(
        before,
        stage=OnlyPositionReservationStage.BROKER_ACKNOWLEDGED,
        updated_at=update.ts_init,
        version=before.version + 1,
    )


def only_reduce_strategy_cash_reservation_acknowledged(
    before: OnlyStrategyCashReservationExecutionState,
    update: OnlyBrokerOrderAcceptedUpdate,
) -> OnlyStrategyCashReservationExecutionState:
    if before.order_id != update.order_id:
        raise ValueError("Strategy cash Reservation ACK scope mismatch")
    if before.stage is not OnlyStrategyCashReservationStage.SENT_TO_BROKER:
        raise ValueError("Strategy cash Reservation ACK requires SENT_TO_BROKER stage")
    return replace(
        before,
        stage=OnlyStrategyCashReservationStage.BROKER_ACKNOWLEDGED,
        updated_at=update.ts_init,
        version=before.version + 1,
    )


def only_reduce_strategy_ledger_reservation_acknowledged(
    before: OnlyStrategyLedgerExecutionState,
    update: OnlyBrokerOrderAcceptedUpdate,
) -> OnlyStrategyLedgerExecutionState:
    return replace(before, updated_at=update.ts_init, version=before.version + 1)


def only_reduce_account_cash_reservation_terminal(
    before: OnlyAccountCashReservationExecutionState,
    timestamp: OnlyTimestamp,
) -> OnlyAccountCashReservationExecutionState:
    if before.state is OnlyAccountReservationState.RELEASED:
        raise ValueError("Account cash Reservation is already released")
    return replace(
        before,
        remaining_amount=OnlyMoney(Decimal(0), before.remaining_amount.currency),
        state=OnlyAccountReservationState.RELEASED,
        updated_at=timestamp,
        version=before.version + 1,
    )


def only_reduce_account_terminal_release(
    before: OnlyAccountExecutionState,
    release: OnlyMoney,
    timestamp: OnlyTimestamp,
) -> OnlyAccountExecutionState:
    if release.currency != before.base_currency or release.amount <= 0:
        raise ValueError("Account terminal cash release is invalid")
    reserved = before.order_reserved_cash - release
    if reserved.amount < 0:
        raise ValueError("Account terminal cash release would underflow")
    available = before.ledger_cash - reserved
    available_margin = before.available_margin
    if available_margin is not None:
        if before.reserved_margin is None or before.occupied_margin is None:
            raise ValueError("Account Margin authority is incomplete")
        available_margin = (
            before.ledger_cash
            - reserved
            - before.unsettled_receivable_cash
            - before.reserved_margin
            - before.occupied_margin
        )
    return replace(
        before,
        order_reserved_cash=reserved,
        trade_available_cash=available,
        withdrawable_cash=available - before.unsettled_receivable_cash,
        available_margin=available_margin,
        updated_at=timestamp,
        version=before.version + 1,
    )


def only_reduce_strategy_cash_reservation_terminal(
    before: OnlyStrategyCashReservationExecutionState,
    timestamp: OnlyTimestamp,
) -> OnlyStrategyCashReservationExecutionState:
    if before.state is OnlyStrategyCashReservationState.RELEASED:
        raise ValueError("Strategy cash Reservation is already released")
    return replace(
        before,
        remaining_amount=OnlyMoney(Decimal(0), before.remaining_amount.currency),
        state=OnlyStrategyCashReservationState.RELEASED,
        stage=OnlyStrategyCashReservationStage.RELEASED,
        updated_at=timestamp,
        version=before.version + 1,
    )


def only_reduce_strategy_ledger_terminal_release(
    before: OnlyStrategyLedgerExecutionState,
    reservation: OnlyStrategyCashReservationExecutionState,
    timestamp: OnlyTimestamp,
) -> OnlyStrategyLedgerExecutionState:
    release = reservation.remaining_amount
    if release.amount <= 0 or release.currency != before.key.base_currency:
        raise ValueError("Strategy Ledger terminal release is invalid")
    reserved = before.cash_reserved - release
    if reserved.amount < 0:
        raise ValueError("Strategy Ledger terminal release would underflow")
    sequence = max((item.sequence for item in before.cash_entries), default=0) + 1
    entry = OnlyStrategyCashEntry(
        OnlyStrategyCashEntryId(f"SCASH-{before.ledger_id}-{sequence:010d}"),
        before.key.runtime_id,
        before.key.account_id,
        before.key.cluster_id,
        before.key.base_currency,
        release,
        OnlyStrategyCashEntryType.ORDER_RESERVATION_RELEASE,
        reservation.order_id,
        None,
        reservation.reservation_id,
        None,
        timestamp,
        timestamp,
        sequence,
    )
    return replace(
        before,
        cash_reserved=reserved,
        cash_available=before.ledger_cash - reserved,
        cash_entries=before.cash_entries + (entry,),
        updated_at=timestamp,
        version=before.version + 1,
    )


def only_reduce_position_reservation_terminal(
    before: OnlyPositionReservationExecutionState,
    timestamp: OnlyTimestamp,
) -> OnlyPositionReservationExecutionState:
    if before.released_quantity is None or before.remaining_quantity.value <= 0:
        raise ValueError("Position Reservation has no releasable remaining authority")
    return replace(
        before,
        remaining_quantity=OnlyQuantity(Decimal(0), before.quantity.precision),
        released_quantity=OnlyQuantity(
            before.released_quantity.value + before.remaining_quantity.value,
            before.quantity.precision,
        ),
        stage=OnlyPositionReservationStage.RELEASED,
        state=OnlyPositionReservationState.RELEASED,
        updated_at=timestamp,
        version=before.version + 1,
    )


def only_reduce_risk_reservation_terminal(
    before: OnlyRiskReservationExecutionState,
    release_reason: OnlyRiskReleaseReason,
    timestamp: OnlyTimestamp,
) -> OnlyRiskReservationExecutionState:
    released_quantity = before.released_quantity or OnlyQuantity(Decimal(0), before.reserved_quantity.precision)
    released_notional = (
        None
        if before.reserved_notional is None
        else before.released_notional or OnlyMoney(Decimal(0), before.reserved_notional.currency)
    )
    return replace(
        before,
        remaining_quantity=OnlyQuantity(Decimal(0), before.reserved_quantity.precision),
        remaining_notional=(
            None
            if before.remaining_notional is None
            else OnlyMoney(
                before.remaining_notional.amount - before.remaining_notional.amount,
                before.remaining_notional.currency,
            )
        ),
        released_quantity=OnlyQuantity(
            released_quantity.value + before.remaining_quantity.value,
            before.reserved_quantity.precision,
        ),
        released_notional=(
            None
            if released_notional is None or before.remaining_notional is None
            else released_notional + before.remaining_notional
        ),
        state=OnlyRiskReservationState.RELEASED,
        release_reason=release_reason,
        updated_at=timestamp,
        version=before.version + 1,
    )


def only_reduce_terminal_risk_snapshot(
    before: OnlyRiskExecutionState,
    reservation_before: OnlyRiskReservationExecutionState,
    timestamp: OnlyTimestamp,
) -> OnlyRiskExecutionState:
    if before.active_order_count < 1 or before.cluster_active_order_count < 1:
        raise ValueError("Risk active Order count would underflow")
    released_notional = Decimal(0)
    if reservation_before.remaining_notional is not None:
        released_notional = reservation_before.remaining_notional.amount
    reserved_notional = before.reserved_notional
    remaining_notional = before.remaining_order_notional
    if reserved_notional is not None:
        reserved_notional = OnlyMoney(reserved_notional.amount - released_notional, reserved_notional.currency)
    if remaining_notional is not None:
        remaining_notional = OnlyMoney(remaining_notional.amount - released_notional, remaining_notional.currency)
    return replace(
        before,
        ts_event=timestamp,
        ts_init=timestamp,
        active_order_count=before.active_order_count - 1,
        cluster_active_order_count=before.cluster_active_order_count - 1,
        reserved_quantity=before.reserved_quantity - reservation_before.remaining_quantity.value,
        reserved_notional=reserved_notional,
        remaining_order_notional=remaining_notional,
        version=before.version + 1,
    )


__all__ = [name for name in globals() if name.startswith("only_reduce_")]
