"""Generic T0 planning contexts sourced from real Manager snapshots."""

from __future__ import annotations

from dataclasses import replace

from onlyalpha.execution import (
    OnlyPreparedExecutionTransaction,
    OnlyTradeExecutionPlanningContext,
    OnlyTradeExecutionTransactionPlanner,
)

from ..support.generic_t0_trade_harness import (
    OnlyTestGenericT0Scenario,
    _environment,
    _prepare_environment,
    _trade_update,
    only_test_real_trade_planning_context,
)


def only_test_generic_t0_trade_planning_context(**changes: object) -> OnlyTradeExecutionPlanningContext:
    scenario = OnlyTestGenericT0Scenario("unit-context")
    env = _environment(scenario)
    _prepare_environment(env, scenario)
    context = only_test_real_trade_planning_context(env, _trade_update(env, scenario))
    return replace(context, **changes)


def only_test_generic_t0_planned_trade():
    context = only_test_generic_t0_trade_planning_context()
    return OnlyTradeExecutionTransactionPlanner._planned_trade(context)


def only_test_generic_t0_expected_reductions():
    return only_test_generic_t0_prepared_transaction().projections


def only_test_generic_t0_prepared_transaction() -> OnlyPreparedExecutionTransaction:
    return OnlyTradeExecutionTransactionPlanner().prepare(only_test_generic_t0_trade_planning_context())


__all__ = [name for name in globals() if name.startswith("only_test_")]
