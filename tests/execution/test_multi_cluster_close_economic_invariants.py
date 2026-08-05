from dataclasses import replace
from decimal import Decimal

import pytest

from onlyalpha.domain.value import OnlyMoney, OnlyPrice
from onlyalpha.execution import (
    OnlyAllocationExecutionProjection,
    OnlyPositionExecutionProjection,
    OnlyPreparedExecutionEconomicInvariantValidator,
    only_execution_state_hash,
    only_with_execution_projection_hash,
)
from tests.execution.support.generic_t0_trade_harness import only_test_multi_cluster_close_context


def _prepared_with_projection(updated: object):
    _, _, prepared = only_test_multi_cluster_close_context(close_quantity="400")
    projections = tuple(updated if isinstance(item, type(updated)) else item for item in prepared.projections)
    return replace(prepared, projections=projections, authority_hash="", payload_hash="")


def _replace_after(projection: object, after: object):
    identity = replace(
        projection.identity,  # type: ignore[attr-defined]
        result_state_hash=only_execution_state_hash(after),  # type: ignore[arg-type]
        payload_hash="0" * 64,
    )
    return only_with_execution_projection_hash(
        replace(projection, identity=identity, after=after)  # type: ignore[call-overload]
    )


def test_position_released_cost_mismatch_fails_closed() -> None:
    _, _, prepared = only_test_multi_cluster_close_context(close_quantity="400")
    position = next(item for item in prepared.projections if isinstance(item, OnlyPositionExecutionProjection))
    invalid = _replace_after(
        position,
        replace(
            position.after,
            cumulative_open_price_quantity=position.after.cumulative_open_price_quantity + Decimal("1.00"),
        ),
    )

    with pytest.raises(ValueError, match="cost"):
        OnlyPreparedExecutionEconomicInvariantValidator().validate(_prepared_with_projection(invalid))


def test_allocation_released_cost_mismatch_fails_closed() -> None:
    _, _, prepared = only_test_multi_cluster_close_context(close_quantity="400")
    allocation = next(item for item in prepared.projections if isinstance(item, OnlyAllocationExecutionProjection))
    invalid = _replace_after(
        allocation,
        replace(
            allocation.after,
            cumulative_open_price_quantity=allocation.after.cumulative_open_price_quantity + Decimal("1.00"),
        ),
    )

    with pytest.raises(ValueError, match="cost"):
        OnlyPreparedExecutionEconomicInvariantValidator().validate(_prepared_with_projection(invalid))


def test_fact_released_cost_mismatch_fails_closed() -> None:
    _, _, prepared = only_test_multi_cluster_close_context(close_quantity="400")
    with pytest.raises(ValueError, match="cost"):
        OnlyPreparedExecutionEconomicInvariantValidator().validate(
            replace(
                prepared,
                fact_draft=replace(
                    prepared.fact_draft,
                    released_open_price_quantity=(prepared.fact_draft.released_open_price_quantity + Decimal("1.00")),
                ),
                authority_hash="",
                payload_hash="",
            )
        )


def test_realized_pnl_mismatch_fails_closed() -> None:
    _, _, prepared = only_test_multi_cluster_close_context(close_quantity="400")
    currency = prepared.fact_draft.currency
    wrong = OnlyMoney(prepared.fact_draft.realized_pnl_delta.amount + Decimal("1.00"), currency)
    with pytest.raises(ValueError, match="PnL"):
        OnlyPreparedExecutionEconomicInvariantValidator().validate(
            replace(
                prepared,
                fact_draft=replace(
                    prepared.fact_draft,
                    realized_pnl_delta=wrong,
                    position_realized_pnl_delta=wrong,
                    allocation_realized_pnl_delta=wrong,
                    account_realized_pnl_delta=wrong,
                    ledger_realized_pnl_delta=wrong,
                ),
                authority_hash="",
                payload_hash="",
            )
        )


def test_remaining_average_mismatch_fails_closed() -> None:
    _, _, prepared = only_test_multi_cluster_close_context(close_quantity="400")
    position = next(item for item in prepared.projections if isinstance(item, OnlyPositionExecutionProjection))
    invalid = _replace_after(
        position,
        replace(position.after, average_open_price=OnlyPrice(Decimal("11.24"), 2)),
    )

    with pytest.raises(ValueError, match="average"):
        OnlyPreparedExecutionEconomicInvariantValidator().validate(_prepared_with_projection(invalid))
