from dataclasses import replace

import pytest

from onlyalpha.execution.reducers import OnlyStrategyCashReservationTradeReducer
from onlyalpha.strategy_ledger.enums import OnlyStrategyCashReservationStage, OnlyStrategyCashReservationState
from tests.execution.support.multi_fill_reductions import only_test_two_fill_trades


def test_strategy_cash_reservation_keeps_stage_until_final_release() -> None:
    context, first_trade, second_trade = only_test_two_fill_trades()
    reducer = OnlyStrategyCashReservationTradeReducer()
    before = context.strategy_cash_reservation_before
    first = reducer.reduce(before, first_trade, terminal_fill=False, projection_sequence=10)
    assert first.after.state is OnlyStrategyCashReservationState.PARTIALLY_CONSUMED
    assert first.after.stage is before.stage
    assert first.released_delta.amount == 0

    final = reducer.reduce(first.after, second_trade, terminal_fill=True, projection_sequence=10)
    assert final.after.state is OnlyStrategyCashReservationState.RELEASED
    assert final.after.stage is OnlyStrategyCashReservationStage.RELEASED
    assert final.released_delta.amount > 0

    exact_trade = replace(second_trade, settled_notional=first.after.remaining_amount)
    exact = reducer.reduce(first.after, exact_trade, terminal_fill=True, projection_sequence=10)
    assert exact.after.state is OnlyStrategyCashReservationState.CONSUMED
    assert exact.after.stage is first.after.stage
    assert exact.released_delta.amount == 0

    cost = first_trade.settled_notional + first_trade.fee_charges - first_trade.fee_rebates
    exhausted = replace(
        first.after,
        reserved_amount=first.after.consumed_amount + cost,
        remaining_amount=cost,
    )
    with pytest.raises(ValueError, match="STRATEGY_RESERVATION_INSUFFICIENT"):
        reducer.reduce(
            exhausted,
            first_trade,
            terminal_fill=False,
            projection_sequence=10,
        )
