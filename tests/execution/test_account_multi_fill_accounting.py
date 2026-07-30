from decimal import Decimal

from onlyalpha.domain.value import OnlyMoney
from onlyalpha.execution.reducers import OnlyAccountCashReservationTradeReducer, OnlyAccountTradeReducer
from tests.execution.support.multi_fill_reductions import only_test_two_fill_trades


def test_account_consumes_explicit_reservation_deltas_for_each_fill() -> None:
    context, first_trade, second_trade = only_test_two_fill_trades()
    reservation_reducer = OnlyAccountCashReservationTradeReducer()
    account_reducer = OnlyAccountTradeReducer()
    zero = OnlyMoney(Decimal(0), first_trade.authoritative_fee.currency)

    first_reservation = reservation_reducer.reduce(
        context.account_cash_reservation_before,
        first_trade,
        terminal_fill=False,
        projection_sequence=9,
    )
    first = account_reducer.reduce(
        context.account_before,
        first_reservation,
        first_trade,
        zero,
        zero,
        projection_sequence=7,
    )
    assert first.after.frozen_cash.amount == (
        context.account_before.frozen_cash.amount - first_reservation.consumed_delta.amount
    )

    final_reservation = reservation_reducer.reduce(
        first_reservation.after,
        second_trade,
        terminal_fill=True,
        projection_sequence=9,
    )
    final = account_reducer.reduce(
        first.after,
        final_reservation,
        second_trade,
        zero,
        zero,
        projection_sequence=7,
    )
    assert final.after.frozen_cash.amount == 0
    assert final.after.cash_balance.amount == context.account_before.cash_balance.amount - Decimal("1000.00")
