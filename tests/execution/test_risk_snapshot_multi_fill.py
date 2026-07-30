from dataclasses import replace

from onlyalpha.execution.reducers import OnlyRiskReservationTradeReducer, OnlyRiskTradeReducer
from tests.execution.support.multi_fill_reductions import only_test_two_fill_trades


def test_risk_snapshot_decrements_active_counts_only_on_terminal_fill() -> None:
    context, first_trade, second_trade = only_test_two_fill_trades()
    reservation_reducer = OnlyRiskReservationTradeReducer()
    risk_reducer = OnlyRiskTradeReducer()
    assert context.risk_reservation_before.reserved_notional is not None
    risk_before = replace(
        context.risk_before,
        reserved_notional=context.risk_reservation_before.reserved_notional,
        remaining_order_notional=context.risk_reservation_before.reserved_notional,
    )
    first_reservation = reservation_reducer.reduce(
        context.risk_reservation_before,
        first_trade,
        terminal_fill=False,
        projection_sequence=11,
    )
    first = risk_reducer.reduce(
        risk_before,
        first_reservation,
        first_trade,
        False,
        projection_sequence=12,
    )
    assert first.after.active_order_count == risk_before.active_order_count
    assert first.after.cluster_active_order_count == risk_before.cluster_active_order_count
    assert first.after.remaining_order_notional is not None
    assert risk_before.remaining_order_notional is not None
    assert first.after.remaining_order_notional.amount == risk_before.remaining_order_notional.amount - 300

    final_reservation = reservation_reducer.reduce(
        first_reservation.after,
        second_trade,
        terminal_fill=True,
        projection_sequence=11,
    )
    final = risk_reducer.reduce(
        first.after,
        final_reservation,
        second_trade,
        True,
        projection_sequence=12,
    )
    assert final.after.active_order_count == risk_before.active_order_count - 1
    assert final.after.cluster_active_order_count == risk_before.cluster_active_order_count - 1
    assert final.after.reserved_quantity == 0
