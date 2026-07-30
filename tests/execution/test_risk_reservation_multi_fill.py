from onlyalpha.execution.reducers import OnlyRiskReservationTradeReducer
from onlyalpha.risk.enums import OnlyRiskReservationState
from tests.execution.support.multi_fill_reductions import only_test_two_fill_trades


def test_risk_reservation_consumes_quantity_and_notional_incrementally() -> None:
    context, first_trade, second_trade = only_test_two_fill_trades()
    reducer = OnlyRiskReservationTradeReducer()
    first = reducer.reduce(
        context.risk_reservation_before,
        first_trade,
        terminal_fill=False,
        projection_sequence=11,
    )
    assert first.after.state is OnlyRiskReservationState.ACTIVE
    assert first.after.remaining_quantity.value == 70
    assert first.consumed_quantity_delta.value == 30
    assert first.consumed_notional_delta.amount == 300

    final = reducer.reduce(first.after, second_trade, terminal_fill=True, projection_sequence=11)
    assert final.after.state is OnlyRiskReservationState.CONSUMED
    assert final.after.remaining_quantity.value == 0
    assert final.after.consumed_quantity == final.after.reserved_quantity
