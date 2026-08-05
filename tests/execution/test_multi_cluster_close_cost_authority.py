from dataclasses import replace
from decimal import Decimal

import pytest

from onlyalpha.execution import (
    OnlyAttributedCloseCostAuthority,
    OnlyRuntimeProjectionComponent,
    OnlyTradeExecutionPlanningError,
    OnlyTradeExecutionTransactionPlanner,
    only_build_attributed_close_cost_authority,
)
from tests.execution.support.generic_t0_trade_harness import only_test_multi_cluster_close_context


def test_close_cost_authority_has_one_public_import_surface() -> None:
    assert OnlyAttributedCloseCostAuthority.__name__ == "OnlyAttributedCloseCostAuthority"
    assert callable(only_build_attributed_close_cost_authority)


def test_cluster_allocation_is_the_only_close_cost_authority() -> None:
    _, _, prepared = only_test_multi_cluster_close_context()

    assert prepared.fact_draft.released_open_price_quantity == Decimal("10000.00")
    assert prepared.fact_draft.realized_pnl_delta.amount == Decimal("3000.00")
    assert prepared.fact_draft.position_cumulative_open_price_quantity_after == Decimal("12000.00")
    assert prepared.fact_draft.allocation_cumulative_open_price_quantity_after == 0


def test_partial_close_rederives_aggregate_position_average() -> None:
    _, _, prepared = only_test_multi_cluster_close_context(close_quantity="400")
    position = next(
        item for item in prepared.projections if item.identity.component is OnlyRuntimeProjectionComponent.POSITION
    )
    allocation = next(
        item for item in prepared.projections if item.identity.component is OnlyRuntimeProjectionComponent.ALLOCATION
    )

    assert prepared.fact_draft.released_open_price_quantity == Decimal("4000.00")
    assert position.after.total_quantity.value == Decimal("1600")
    assert position.after.cumulative_open_price_quantity == Decimal("18000.00")
    assert position.after.average_open_price is not None
    assert position.after.average_open_price.value == Decimal("11.25")
    assert allocation.after.total_quantity.value == Decimal("600")
    assert allocation.after.cumulative_open_price_quantity == Decimal("6000.00")


def test_close_fails_when_aggregate_cost_has_no_allocation_authority() -> None:
    _, context, _ = only_test_multi_cluster_close_context(close_quantity="400")
    invalid = replace(context, aggregate_allocation_cumulative_cost_before=Decimal("21999.99"))

    with pytest.raises(OnlyTradeExecutionPlanningError, match="MULTI_CLUSTER_CLOSE_UNALLOCATED_COST_UNSUPPORTED"):
        OnlyTradeExecutionTransactionPlanner().prepare(invalid)


def test_multi_fill_releases_exact_allocation_cost_without_tail() -> None:
    released = Decimal(0)
    pnl = Decimal(0)
    remaining = ("1000", "700", "300")
    fills = (("300", "11.00"), ("400", "13.00"), ("300", "9.00"))
    for allocation_before, (quantity, price) in zip(remaining, fills, strict=True):
        _, context, prepared = only_test_multi_cluster_close_context(
            close_quantity=allocation_before,
            fill_quantity=quantity,
            fill_price=price,
        )
        allocation_cost = Decimal(allocation_before) * Decimal("10")
        prepared = OnlyTradeExecutionTransactionPlanner().prepare(
            replace(
                context,
                allocation_before=replace(
                    context.allocation_before,
                    total_quantity=replace(context.allocation_before.total_quantity, value=Decimal(allocation_before)),
                    settled_quantity=replace(
                        context.allocation_before.settled_quantity, value=Decimal(allocation_before)
                    ),
                    cumulative_open_price_quantity=allocation_cost,
                ),
            )
        )
        released += prepared.fact_draft.released_open_price_quantity
        pnl += prepared.fact_draft.realized_pnl_delta.amount

    assert released == Decimal("10000.00")
    assert pnl == Decimal("1200.00")
