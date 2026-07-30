"""Exact cumulative-cost authority for average-cost long closes."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from onlyalpha.domain.value import OnlyQuantity


@dataclass(frozen=True, slots=True)
class OnlyCloseCostBasisReduction:
    """One exact reduction of cumulative open price × quantity."""

    quantity_before: OnlyQuantity
    fill_quantity: OnlyQuantity
    quantity_after: OnlyQuantity
    cumulative_open_price_quantity_before: Decimal
    released_open_price_quantity: Decimal
    cumulative_open_price_quantity_after: Decimal
    terminal_position_close: bool


def only_reduce_average_cost_close(
    *,
    cumulative_open_price_quantity_before: Decimal,
    quantity_before: OnlyQuantity,
    fill_quantity: OnlyQuantity,
) -> OnlyCloseCostBasisReduction:
    """Release an exact proportional cost share, with a terminal all-remainder rule."""

    cumulative_before = cumulative_open_price_quantity_before
    if not cumulative_before.is_finite() or cumulative_before < 0:
        raise ValueError("Close cumulative cost must be finite and non-negative")
    if fill_quantity.precision != quantity_before.precision:
        raise ValueError("Close quantity precision disagrees with Position")
    if quantity_before.value <= 0 or fill_quantity.value <= 0:
        raise ValueError("Close quantities must be positive")
    if fill_quantity.value > quantity_before.value:
        raise ValueError("Close quantity exceeds Position quantity")

    terminal = fill_quantity.value == quantity_before.value
    quantity_after = OnlyQuantity(
        quantity_before.value - fill_quantity.value,
        quantity_before.precision,
    )
    if terminal:
        released = cumulative_before
        cumulative_after = Decimal(0)
    else:
        significant_digits = max(1, len(cumulative_before.as_tuple().digits))
        precision = max(
            36,
            significant_digits + 12,
            quantity_before.precision + fill_quantity.precision + 18,
        )
        with localcontext() as context:
            context.prec = precision
            context.rounding = ROUND_HALF_EVEN
            released = cumulative_before * fill_quantity.value / quantity_before.value
            cumulative_after = cumulative_before - released
        if released < 0 or cumulative_after < 0:
            raise ValueError("Close cost reduction created a negative amount")

    return OnlyCloseCostBasisReduction(
        quantity_before=quantity_before,
        fill_quantity=fill_quantity,
        quantity_after=quantity_after,
        cumulative_open_price_quantity_before=cumulative_before,
        released_open_price_quantity=released,
        cumulative_open_price_quantity_after=cumulative_after,
        terminal_position_close=terminal,
    )


__all__ = ["OnlyCloseCostBasisReduction", "only_reduce_average_cost_close"]
