from decimal import Decimal

from onlyalpha.execution import OnlyExecutionProjectionComponent
from tests.execution.support.generic_t0_trade_harness import only_test_generic_t0_long_close_context


def test_long_close_allocation_uses_position_realized_pnl_authority() -> None:
    _, _, prepared = only_test_generic_t0_long_close_context(open_quantity="200", close_quantity="100")
    allocation = next(
        item for item in prepared.projections if item.identity.component is OnlyExecutionProjectionComponent.ALLOCATION
    )

    assert allocation.before is not None
    assert allocation.after.total_quantity.value == Decimal("100")
    assert allocation.after.average_open_price == allocation.before.average_open_price
    assert allocation.after.cumulative_open_price_quantity == Decimal("1000.00")
    assert allocation.realized_pnl_delta == prepared.fact_draft.realized_pnl_delta
    assert allocation.after.realized_pnl - allocation.before.realized_pnl == allocation.realized_pnl_delta


def test_long_close_allocation_zero_quantity_clears_cost_authority() -> None:
    _, _, prepared = only_test_generic_t0_long_close_context()
    allocation = next(
        item for item in prepared.projections if item.identity.component is OnlyExecutionProjectionComponent.ALLOCATION
    )

    assert allocation.after.total_quantity.value == 0
    assert allocation.after.average_open_price is None
    assert allocation.after.cumulative_open_price_quantity == 0
    assert allocation.after.closed_at is not None
