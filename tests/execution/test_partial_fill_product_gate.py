from dataclasses import replace
from decimal import Decimal

import pytest

from onlyalpha.domain.value import OnlyQuantity
from onlyalpha.execution import (
    OnlyTradeExecutionPlanningError,
    OnlyTradeExecutionPlanningErrorCode,
    OnlyTradeExecutionTransactionPlanner,
    only_capture_execution_fill_authority,
)
from tests.execution.support.generic_t0_trade_harness import (
    OnlyTestGenericT0Scenario,
    _environment,
    _prepare_environment,
    _trade_update,
    only_test_real_trade_planning_context,
)
from tests.execution.support.manager_authority_digest import only_test_runtime_authority_digest


def test_product_partial_fill_fails_closed_before_commit_or_manager_mutation() -> None:
    scenario = OnlyTestGenericT0Scenario("partial-product-gate")
    env = _environment(scenario)
    _prepare_environment(env, scenario)
    update = _trade_update(env, scenario)
    partial_fill = replace(update.fill, quantity=OnlyQuantity(Decimal("1"), update.fill.quantity.precision))
    partial = replace(update, fill=partial_fill)
    context = only_test_real_trade_planning_context(env, partial)
    context = replace(
        context,
        fill_authority=only_capture_execution_fill_authority(env.runtime.execution_transaction_query, partial),
    )
    before = only_test_runtime_authority_digest(env)
    with pytest.raises(OnlyTradeExecutionPlanningError) as raised:
        OnlyTradeExecutionTransactionPlanner().prepare(context)
    assert raised.value.code is OnlyTradeExecutionPlanningErrorCode.PARTIAL_FILL_ACCOUNTING_NOT_READY
    assert only_test_runtime_authority_digest(env) == before
    assert env.runtime.execution_transaction_query.records(env.runtime.config.runtime_id) == ()


def test_product_whole_fill_still_builds_complete_transaction() -> None:
    scenario = OnlyTestGenericT0Scenario("whole-product-path")
    env = _environment(scenario)
    _prepare_environment(env, scenario)
    update = _trade_update(env, scenario)
    prepared = OnlyTradeExecutionTransactionPlanner().prepare(only_test_real_trade_planning_context(env, update))
    assert prepared.fact_draft.terminal_fill
    assert prepared.fact_draft.fill_index == 1
