from decimal import Decimal

from onlyalpha.execution import OnlyRuntimeProjectionComponent
from tests.execution.support.generic_t0_trade_harness import only_test_generic_t0_long_close_context


def test_long_close_consumes_position_reservation_in_same_projection_batch() -> None:
    _, _, prepared = only_test_generic_t0_long_close_context()
    projection = next(
        item
        for item in prepared.projections
        if item.identity.component is OnlyRuntimeProjectionComponent.POSITION_RESERVATION
    )

    assert projection.before is not None
    assert projection.after.remaining_quantity.value == Decimal(0)
    assert projection.before.remaining_quantity.value - projection.after.remaining_quantity.value == Decimal("100")
    assert projection.after.state.value == "CONSUMED"
    assert prepared.fact_draft.position_reservation_consumed_delta.value == Decimal("100")


def test_long_close_projection_batch_contains_no_cash_reservations() -> None:
    _, _, prepared = only_test_generic_t0_long_close_context()
    components = {item.identity.component for item in prepared.projections}

    assert OnlyRuntimeProjectionComponent.POSITION_RESERVATION in components
    assert OnlyRuntimeProjectionComponent.ACCOUNT_CASH_RESERVATION not in components
    assert OnlyRuntimeProjectionComponent.STRATEGY_CASH_RESERVATION not in components
