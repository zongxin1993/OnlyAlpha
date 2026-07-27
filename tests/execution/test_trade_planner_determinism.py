from dataclasses import replace
from datetime import timedelta

from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.execution import OnlyTradeExecutionTransactionPlanner, only_encode_prepared_execution_transaction

from .factories.trade_planning_factory import only_test_generic_t0_trade_planning_context


def test_planner_is_byte_deterministic_across_one_hundred_runs() -> None:
    context = only_test_generic_t0_trade_planning_context()
    encoded = {
        only_encode_prepared_execution_transaction(OnlyTradeExecutionTransactionPlanner().prepare(context))
        for _ in range(100)
    }
    assert len(encoded) == 1


def test_prepared_at_changes_payload_but_not_business_authority() -> None:
    context = only_test_generic_t0_trade_planning_context()
    first = OnlyTradeExecutionTransactionPlanner().prepare(context)
    later = OnlyTimestamp.from_datetime(context.prepared_at.to_datetime() + timedelta(seconds=1))
    second = OnlyTradeExecutionTransactionPlanner().prepare(replace(context, prepared_at=later))
    assert first.transaction_id == second.transaction_id
    assert first.authority_hash == second.authority_hash
    assert first.payload_hash != second.payload_hash
