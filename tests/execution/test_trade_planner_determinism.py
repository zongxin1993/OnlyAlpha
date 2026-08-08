from dataclasses import replace
from datetime import timedelta

import pytest

from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.execution import OnlyTradeExecutionTransactionPlanner, only_encode_prepared_execution_transaction

from .factories.trade_planning_factory import only_test_generic_t0_trade_planning_context


def _assert_planner_determinism(repetitions: int) -> None:
    context = only_test_generic_t0_trade_planning_context()
    prepared = tuple(OnlyTradeExecutionTransactionPlanner().prepare(context) for _ in range(repetitions))
    encoded = {only_encode_prepared_execution_transaction(item) for item in prepared}
    assert len(encoded) == 1
    assert len({item.transaction_id for item in prepared}) == 1
    assert len({item.authority_hash for item in prepared}) == 1
    assert len({item.payload_hash for item in prepared}) == 1
    assert len({tuple(projection.identity.payload_hash for projection in item.projections) for item in prepared}) == 1
    assert len({tuple(str(event.event_id) for event in item.outbox_events) for item in prepared}) == 1


def test_planner_is_byte_deterministic() -> None:
    _assert_planner_determinism(3)


@pytest.mark.exhaustive
def test_planner_is_byte_deterministic_across_one_hundred_runs() -> None:
    _assert_planner_determinism(100)


def test_prepared_at_changes_payload_but_not_business_authority() -> None:
    context = only_test_generic_t0_trade_planning_context()
    first = OnlyTradeExecutionTransactionPlanner().prepare(context)
    later = OnlyTimestamp.from_datetime(context.prepared_at.to_datetime() + timedelta(seconds=1))
    second = OnlyTradeExecutionTransactionPlanner().prepare(replace(context, prepared_at=later))
    assert first.transaction_id == second.transaction_id
    assert first.authority_hash == second.authority_hash
    assert first.payload_hash != second.payload_hash


def test_mapping_insertion_order_does_not_change_transaction_or_event_bytes() -> None:
    context = only_test_generic_t0_trade_planning_context()
    left_order = replace(context.order_before, metadata={"b": "2", "a": "1"})
    right_order = replace(context.order_before, metadata={"a": "1", "b": "2"})
    left_update = replace(context.update, metadata={"z": "9", "m": "5"})
    right_update = replace(context.update, metadata={"m": "5", "z": "9"})

    left = OnlyTradeExecutionTransactionPlanner().prepare(replace(context, order_before=left_order, update=left_update))
    right = OnlyTradeExecutionTransactionPlanner().prepare(
        replace(context, order_before=right_order, update=right_update)
    )

    assert left == right
    assert only_encode_prepared_execution_transaction(left) == only_encode_prepared_execution_transaction(right)
