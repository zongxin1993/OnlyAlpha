from decimal import ROUND_HALF_EVEN, Decimal, localcontext

import pytest

from onlyalpha.domain.value import OnlyQuantity
from onlyalpha.execution.reducers.close_cost import only_reduce_average_cost_close


def _quantity(value: str, precision: int = 6) -> OnlyQuantity:
    return OnlyQuantity(Decimal(value), precision)


def test_partial_long_close_releases_exact_proportional_cost() -> None:
    reduction = only_reduce_average_cost_close(
        cumulative_open_price_quantity_before=Decimal("10000.0000000000000000000000000000000001"),
        quantity_before=_quantity("1000"),
        fill_quantity=_quantity("300"),
    )

    assert reduction.quantity_after.value == Decimal("700")
    assert reduction.released_open_price_quantity == Decimal("3000.00000000000000000000000000000000003")
    assert reduction.cumulative_open_price_quantity_after == Decimal("7000.00000000000000000000000000000000007")
    assert not reduction.terminal_position_close


def test_final_long_close_releases_all_remaining_cost_without_tail() -> None:
    first = only_reduce_average_cost_close(
        cumulative_open_price_quantity_before=Decimal("10000.0000000000000000000000000000000001"),
        quantity_before=_quantity("1000"),
        fill_quantity=_quantity("300"),
    )
    second = only_reduce_average_cost_close(
        cumulative_open_price_quantity_before=first.cumulative_open_price_quantity_after,
        quantity_before=first.quantity_after,
        fill_quantity=_quantity("400"),
    )
    final = only_reduce_average_cost_close(
        cumulative_open_price_quantity_before=second.cumulative_open_price_quantity_after,
        quantity_before=second.quantity_after,
        fill_quantity=_quantity("300"),
    )

    with localcontext() as context:
        context.prec = 64
        context.rounding = ROUND_HALF_EVEN
        released_total = sum(
            (
                first.released_open_price_quantity,
                second.released_open_price_quantity,
                final.released_open_price_quantity,
            ),
            Decimal(0),
        )
    assert released_total == Decimal("10000.0000000000000000000000000000000001")
    assert final.cumulative_open_price_quantity_after == 0
    assert final.quantity_after.value == 0
    assert final.terminal_position_close


@pytest.mark.parametrize("fill", ["0", "1000.000001"])
def test_long_close_cost_reducer_fails_closed_for_invalid_fill(fill: str) -> None:
    with pytest.raises(ValueError):
        only_reduce_average_cost_close(
            cumulative_open_price_quantity_before=Decimal("10000"),
            quantity_before=_quantity("1000"),
            fill_quantity=_quantity(fill),
        )
