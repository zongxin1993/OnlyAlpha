from dataclasses import replace

import pytest

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.execution import (
    OnlyTradeExecutionPlanningError,
    OnlyTradeExecutionPlanningErrorCode,
    OnlyTradeExecutionTransactionPlanner,
)

from .factories.trade_planning_factory import only_test_generic_t0_trade_planning_context


def test_context_rejects_unsupported_side_with_stable_error() -> None:
    context = only_test_generic_t0_trade_planning_context()
    changed = replace(context, order_before=replace(context.order_before, side=OnlyOrderSide.SELL))
    with pytest.raises(OnlyTradeExecutionPlanningError) as captured:
        OnlyTradeExecutionTransactionPlanner().prepare(changed)
    assert captured.value.code is OnlyTradeExecutionPlanningErrorCode.UNSUPPORTED_ORDER_SIDE


def test_context_rejects_missing_creation_authority() -> None:
    context = only_test_generic_t0_trade_planning_context(position_creation=None)
    with pytest.raises(OnlyTradeExecutionPlanningError) as captured:
        OnlyTradeExecutionTransactionPlanner().prepare(context)
    assert captured.value.code is OnlyTradeExecutionPlanningErrorCode.MISSING_CREATION_AUTHORITY
