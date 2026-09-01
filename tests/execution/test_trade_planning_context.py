from dataclasses import replace

import pytest

from onlyalpha.execution import (
    OnlyExecutionCapability,
    OnlyExecutionCapabilityResolver,
    OnlyExecutionReservationShape,
    OnlyExecutionSupportContext,
    OnlyTradeExecutionPlanningError,
    OnlyTradeExecutionPlanningErrorCode,
    OnlyTradeExecutionTransactionPlanner,
)
from onlyalpha.transaction import OnlyRuntimeOperationKind

from .factories.trade_planning_factory import only_test_generic_t0_trade_planning_context


def test_planner_rejects_unsupported_decision_as_routing_invariant() -> None:
    context = only_test_generic_t0_trade_planning_context()
    unsupported = OnlyExecutionCapabilityResolver().resolve(
        OnlyExecutionSupportContext(
            operation_kind=OnlyRuntimeOperationKind.TRADE_FILL,
            account_type=context.account_before.account_type,
            order_type=context.order_before.order_type,
            order_side=context.order_before.side,
            offset=context.order_before.offset,
            position_side=context.position_scope.position_side,
            position_effect=context.position_scope.position_effect,
            position_mode=context.position_scope.position_mode,
            close_scope=context.position_scope.close_scope,
            exposure_constraint=context.position_scope.exposure_constraint,
            has_margin=False,
            account_ledger_parity=False,
            reservations=OnlyExecutionReservationShape(True, True, False, False, True),
        )
    )
    assert unsupported.capability is OnlyExecutionCapability.UNSUPPORTED
    changed = replace(context, support_decision=unsupported)
    with pytest.raises(OnlyTradeExecutionPlanningError) as captured:
        OnlyTradeExecutionTransactionPlanner().prepare(changed)
    assert captured.value.code is OnlyTradeExecutionPlanningErrorCode.CAPABILITY_ROUTING_INVARIANT_FAILED


def test_context_rejects_missing_creation_authority() -> None:
    context = only_test_generic_t0_trade_planning_context(position_creation=None)
    with pytest.raises(OnlyTradeExecutionPlanningError) as captured:
        OnlyTradeExecutionTransactionPlanner().prepare(context)
    assert captured.value.code is OnlyTradeExecutionPlanningErrorCode.MISSING_CREATION_AUTHORITY
