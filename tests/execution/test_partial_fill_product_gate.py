from dataclasses import replace
from decimal import Decimal

from onlyalpha.domain.value import OnlyQuantity
from onlyalpha.execution import (
    OnlyTradeExecutionTransactionPlanner,
    only_capture_execution_fill_authority,
    only_decode_prepared_execution_transaction,
    only_encode_prepared_execution_transaction,
)
from tests.execution.support.generic_t0_trade_harness import (
    OnlyTestGenericT0Scenario,
    _environment,
    _prepare_environment,
    _trade_update,
    only_test_real_trade_planning_context,
)
from tests.execution.support.manager_authority_digest import only_test_runtime_authority_digest


def test_product_partial_fill_commits_and_reaches_projection_ready() -> None:
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
    prepared = OnlyTradeExecutionTransactionPlanner().prepare(context)
    assert not prepared.fact_draft.terminal_fill
    assert only_decode_prepared_execution_transaction(only_encode_prepared_execution_transaction(prepared)) == prepared
    assert only_test_runtime_authority_digest(env) == before
    result = env.runtime.execution_processor.process(partial)
    assert result.status.value == "APPLIED", result.failure
    records = env.runtime.execution_transaction_query.records(env.runtime.config.runtime_id)
    assert len(records) == 1
    assert records[0].projection_ready
    assert not records[0].fact.terminal_fill


def test_product_whole_fill_still_builds_complete_transaction() -> None:
    scenario = OnlyTestGenericT0Scenario("whole-product-path")
    env = _environment(scenario)
    _prepare_environment(env, scenario)
    update = _trade_update(env, scenario)
    prepared = OnlyTradeExecutionTransactionPlanner().prepare(only_test_real_trade_planning_context(env, update))
    assert prepared.fact_draft.terminal_fill
    assert prepared.fact_draft.fill_index == 1
