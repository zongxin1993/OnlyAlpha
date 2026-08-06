from dataclasses import replace

import pytest

from onlyalpha.account.enums import OnlyAccountReservationState
from onlyalpha.execution.reducers import OnlyAccountCashReservationTradeReducer
from tests.execution.support.multi_fill_reductions import only_test_two_fill_trades


def test_account_cash_reservation_partial_exact_consume_release_and_insufficient() -> None:
    context, first_trade, second_trade = only_test_two_fill_trades()
    reducer = OnlyAccountCashReservationTradeReducer()
    before = context.account_cash_reservation_before
    first = reducer.reduce(before, first_trade, terminal_fill=False, projection_sequence=9)
    assert first.after.state is OnlyAccountReservationState.PARTIALLY_CONSUMED
    assert first.consumed_delta.amount == first_trade.settled_notional.amount
    assert first.released_delta.amount == 0
    assert first.after.remaining_amount.amount > 0
    assert tuple(item.event_type.value for item in first.event_intents) == ("ACCOUNT_CASH_RESERVATION_CONSUMED",)

    final = reducer.reduce(first.after, second_trade, terminal_fill=True, projection_sequence=9)
    assert final.after.state is OnlyAccountReservationState.RELEASED
    assert final.after.remaining_amount.amount == 0
    assert final.released_delta.amount > 0
    assert tuple(item.event_type.value for item in final.event_intents)[-1] == "ACCOUNT_CASH_RESERVATION_RELEASED"

    exact_trade = replace(second_trade, settled_notional=first.after.remaining_amount)
    exact = reducer.reduce(first.after, exact_trade, terminal_fill=True, projection_sequence=9)
    assert exact.after.state is OnlyAccountReservationState.CONSUMED
    assert exact.released_delta.amount == 0
    assert len(exact.event_intents) == 1

    cost = first_trade.settled_notional + first_trade.fee_charges - first_trade.fee_rebates
    exhausted = replace(
        first.after,
        reserved_amount=first.after.consumed_amount + cost,
        remaining_amount=cost,
    )
    with pytest.raises(ValueError, match="ACCOUNT_RESERVATION_INSUFFICIENT"):
        reducer.reduce(
            exhausted,
            first_trade,
            terminal_fill=False,
            projection_sequence=9,
        )
