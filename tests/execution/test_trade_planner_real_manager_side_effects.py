from onlyalpha.execution import OnlyTradeExecutionTransactionPlanner

from .support.generic_t0_trade_harness import (
    OnlyTestGenericT0Scenario,
    _environment,
    _prepare_environment,
    _trade_update,
    only_test_real_trade_planning_context,
)
from .support.manager_authority_digest import only_test_runtime_authority_digest


def test_planner_changes_no_real_manager_repository_store_journal_or_event_authority() -> None:
    scenario = OnlyTestGenericT0Scenario("side-effects")
    env = _environment(scenario)
    _prepare_environment(env, scenario)
    context = only_test_real_trade_planning_context(env, _trade_update(env, scenario))
    before = only_test_runtime_authority_digest(env)

    prepared = OnlyTradeExecutionTransactionPlanner().prepare(context)

    assert prepared.projections
    assert only_test_runtime_authority_digest(env) == before
