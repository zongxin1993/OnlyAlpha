from decimal import Decimal

from onlyalpha.execution import OnlyRuntimeProjectionComponent
from tests.execution.support.generic_t0_trade_harness import only_test_generic_t0_long_close_context


def _position_projection(open_quantity: str, close_quantity: str):
    _, _, prepared = only_test_generic_t0_long_close_context(
        open_quantity=open_quantity,
        close_quantity=close_quantity,
    )
    return next(
        item for item in prepared.projections if item.identity.component is OnlyRuntimeProjectionComponent.POSITION
    )


def test_long_close_position_reducer_preserves_remaining_average_and_releases_exact_cost() -> None:
    projection = _position_projection("200", "100")

    assert projection.before is not None
    assert projection.after.total_quantity.value == Decimal("100")
    assert projection.after.average_open_price == projection.before.average_open_price
    assert projection.after.cumulative_open_price_quantity == Decimal("1000.00")
    assert projection.realized_pnl_delta.amount == Decimal("200.00")


def test_long_close_position_reducer_closes_zero_quantity_lifecycle() -> None:
    projection = _position_projection("100", "100")

    assert projection.after.total_quantity.value == 0
    assert projection.after.average_open_price is None
    assert projection.after.cumulative_open_price_quantity == 0
    assert projection.after.closed_at is not None
    assert projection.after.status.value == "CLOSED"
