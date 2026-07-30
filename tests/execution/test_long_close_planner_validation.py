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


def test_long_close_rejects_fill_smaller_than_order_remainder() -> None:
    _, context, _ = only_test_generic_t0_long_close_context()
    smaller_fill = replace(
        context.update.fill,
        quantity=replace(context.update.fill.quantity, value=context.update.fill.quantity.value / 2),
    )
    changed = replace(context, update=replace(context.update, fill=smaller_fill))

    _assert_code(changed, OnlyTradeExecutionPlanningErrorCode.PARTIAL_CLOSE_NOT_READY)
