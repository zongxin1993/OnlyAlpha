from decimal import Decimal

from onlyalpha.execution import OnlyRuntimeProjectionComponent
from tests.execution.support.generic_t0_trade_harness import only_test_multi_cluster_close_context


def test_allocation_consumes_shared_attributed_close_cost() -> None:
    _, _, prepared = only_test_multi_cluster_close_context(close_quantity="400")
    projection = next(
        item for item in prepared.projections if item.identity.component is OnlyRuntimeProjectionComponent.ALLOCATION
    )

    assert projection.after.total_quantity.value == Decimal("600")
    assert projection.after.cumulative_open_price_quantity == Decimal("6000.00")
    assert projection.after.average_open_price is not None
    assert projection.after.average_open_price.value == Decimal("10.00")
    assert projection.realized_pnl_delta == prepared.fact_draft.realized_pnl_delta
