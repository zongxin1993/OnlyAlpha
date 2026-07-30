from dataclasses import replace

import pytest

from onlyalpha.execution import (
    OnlyTradeExecutionPlanningContext,
    OnlyTradeExecutionPlanningError,
    OnlyTradeExecutionPlanningErrorCode,
    OnlyTradeExecutionTransactionPlanner,
)
from tests.execution.factories.trade_planning_factory import only_test_generic_t0_trade_planning_context
from tests.execution.support.generic_t0_trade_harness import only_test_generic_t0_long_close_context


def _assert_code(context: OnlyTradeExecutionPlanningContext, code: OnlyTradeExecutionPlanningErrorCode) -> None:
    with pytest.raises(OnlyTradeExecutionPlanningError) as caught:
        OnlyTradeExecutionTransactionPlanner().prepare(context)
    assert caught.value.code is code


def test_long_close_requires_position_allocation_and_position_reservation_authority() -> None:
    _, context, _ = only_test_generic_t0_long_close_context()

    _assert_code(replace(context, position_before=None), OnlyTradeExecutionPlanningErrorCode.CLOSE_POSITION_REQUIRED)
    _assert_code(
        replace(context, allocation_before=None),
        OnlyTradeExecutionPlanningErrorCode.CLOSE_ALLOCATION_REQUIRED,
    )
    _assert_code(
        replace(context, position_reservation_before=None),
        OnlyTradeExecutionPlanningErrorCode.CLOSE_POSITION_RESERVATION_REQUIRED,
    )


def test_long_close_forbids_cash_reservation_authority() -> None:
    _, context, _ = only_test_generic_t0_long_close_context()
    open_context = only_test_generic_t0_trade_planning_context()

    _assert_code(
        replace(context, account_cash_reservation_before=open_context.account_cash_reservation_before),
        OnlyTradeExecutionPlanningErrorCode.CLOSE_CASH_RESERVATION_FORBIDDEN,
    )


def test_long_close_accepts_fill_smaller_than_order_remainder() -> None:
    _, context, prepared = only_test_generic_t0_long_close_context(
        open_quantity="1000",
        close_quantity="1000",
        fill_quantity="300",
    )

    assert context.update.fill.quantity.value == 300
    assert prepared.fact_draft.cumulative_filled_quantity.value == 300
    assert prepared.fact_draft.remaining_quantity.value == 700
    assert not prepared.fact_draft.terminal_fill
