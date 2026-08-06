"""Immutable attributed cost authority for one Cluster-owned close Fill."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyPositionId,
    OnlyRuntimeId,
)
from onlyalpha.domain.value import OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha.position.identifiers import OnlyPositionAllocationId

from .execution_state import (
    OnlyAllocationExecutionState,
    OnlyPositionExecutionState,
    OnlyPositionReservationExecutionState,
)
from .planned_trade import OnlyPlannedTrade


@dataclass(frozen=True, slots=True)
class OnlyAttributedCloseCostAuthority:
    """One immutable conclusion shared by every close accounting projection."""

    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    instrument_id: OnlyInstrumentId
    order_id: OnlyOrderId
    position_id: OnlyPositionId
    allocation_id: OnlyPositionAllocationId
    fill_quantity: OnlyQuantity
    position_quantity_before: OnlyQuantity
    allocation_quantity_before: OnlyQuantity
    position_cumulative_cost_before: Decimal
    allocation_cumulative_cost_before: Decimal
    released_open_price_quantity: Decimal
    position_quantity_after: OnlyQuantity
    allocation_quantity_after: OnlyQuantity
    position_cumulative_cost_after: Decimal
    allocation_cumulative_cost_after: Decimal
    position_average_open_price_after: OnlyPrice | None
    allocation_average_open_price_after: OnlyPrice | None
    realized_pnl_delta: OnlyMoney
    terminal_position_close: bool
    terminal_allocation_close: bool


def only_build_attributed_close_cost_authority(
    *,
    position_before: OnlyPositionExecutionState,
    allocation_before: OnlyAllocationExecutionState,
    position_reservation: OnlyPositionReservationExecutionState,
    aggregate_allocation_quantity_before: Decimal,
    aggregate_allocation_cumulative_cost_before: Decimal,
    trade: OnlyPlannedTrade,
) -> OnlyAttributedCloseCostAuthority:
    """Attribute a close Fill to its Cluster Allocation and derive all after values."""

    from .reducers.close_cost import only_reduce_average_cost_close

    position_key = position_before.key
    allocation_key = allocation_before.key
    if (
        position_key.runtime_id != trade.runtime_id
        or allocation_key.runtime_id != trade.runtime_id
        or position_key.account_id != trade.account_id
        or allocation_key.account_id != trade.account_id
        or allocation_key.cluster_id != trade.cluster_id
        or position_key.instrument_id != trade.instrument_id
        or allocation_key.instrument_id != trade.instrument_id
        or position_key.position_side is not trade.position_side
        or allocation_key.position_side is not trade.position_side
        or position_key.position_mode is not trade.position_mode
        or position_reservation.runtime_id != trade.runtime_id
        or position_reservation.account_id != trade.account_id
        or position_reservation.cluster_id != trade.cluster_id
        or position_reservation.instrument_id != trade.instrument_id
        or position_reservation.order_id != trade.order_id
    ):
        raise ValueError("CLOSE_COST_AUTHORITY_SCOPE_CONFLICT")
    if (
        trade.quantity.value > position_before.total_quantity.value
        or trade.quantity.value > allocation_before.total_quantity.value
        or trade.quantity.value > position_reservation.remaining_quantity.value
    ):
        raise ValueError("CLOSE_COST_AUTHORITY_QUANTITY_INSUFFICIENT")
    if (
        aggregate_allocation_quantity_before != position_before.total_quantity.value
        or aggregate_allocation_cumulative_cost_before != position_before.cumulative_open_price_quantity
    ):
        raise ValueError("MULTI_CLUSTER_CLOSE_UNALLOCATED_COST_UNSUPPORTED")
    if allocation_before.cumulative_open_price_quantity < 0:
        raise ValueError("CLOSE_COST_AUTHORITY_NEGATIVE_ALLOCATION_COST")

    reduction = only_reduce_average_cost_close(
        cumulative_open_price_quantity_before=allocation_before.cumulative_open_price_quantity,
        quantity_before=allocation_before.total_quantity,
        fill_quantity=trade.quantity,
    )
    position_quantity_after = OnlyQuantity(
        position_before.total_quantity.value - trade.quantity.value,
        max(position_before.total_quantity.precision, trade.quantity.precision),
    )
    position_cost_after = position_before.cumulative_open_price_quantity - reduction.released_open_price_quantity
    if position_cost_after < 0:
        raise ValueError("CLOSE_COST_AUTHORITY_POSITION_COST_UNDERFLOW")
    if position_quantity_after.value == 0 and position_cost_after != 0:
        raise ValueError("CLOSE_COST_AUTHORITY_TERMINAL_POSITION_COST_NONZERO")

    position_average = _average_after(
        position_cost_after,
        position_quantity_after,
        position_before.average_open_price,
        trade.price,
    )
    allocation_average = _average_after(
        reduction.cumulative_open_price_quantity_after,
        reduction.quantity_after,
        allocation_before.average_open_price,
        trade.price,
    )
    currency = trade.gross_notional.currency
    quantum = Decimal(1).scaleb(-currency.precision)
    realized = OnlyMoney(
        (
            (trade.price.value * trade.quantity.value - reduction.released_open_price_quantity) * trade.multiplier.value
        ).quantize(quantum, rounding=ROUND_HALF_EVEN),
        currency,
    )
    return OnlyAttributedCloseCostAuthority(
        trade.runtime_id,
        trade.account_id,
        trade.cluster_id,
        trade.instrument_id,
        trade.order_id,
        position_before.position_id,
        allocation_before.allocation_id,
        trade.quantity,
        position_before.total_quantity,
        allocation_before.total_quantity,
        position_before.cumulative_open_price_quantity,
        allocation_before.cumulative_open_price_quantity,
        reduction.released_open_price_quantity,
        position_quantity_after,
        reduction.quantity_after,
        position_cost_after,
        reduction.cumulative_open_price_quantity_after,
        position_average,
        allocation_average,
        realized,
        position_quantity_after.value == 0,
        reduction.terminal_position_close,
    )


def _average_after(
    cumulative_cost: Decimal,
    quantity: OnlyQuantity,
    previous_average: OnlyPrice | None,
    fill_price: OnlyPrice,
) -> OnlyPrice | None:
    if quantity.value == 0:
        if cumulative_cost != 0:
            raise ValueError("CLOSE_COST_AUTHORITY_TERMINAL_COST_NONZERO")
        return None
    precision = max(fill_price.precision, 0 if previous_average is None else previous_average.precision)
    quantum = Decimal(1).scaleb(-precision)
    return OnlyPrice((cumulative_cost / quantity.value).quantize(quantum, rounding=ROUND_HALF_EVEN), precision)


__all__ = ["OnlyAttributedCloseCostAuthority", "only_build_attributed_close_cost_authority"]
