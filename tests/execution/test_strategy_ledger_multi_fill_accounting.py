from onlyalpha.execution import OnlyAllocationExecutionProjection, OnlyTradeExecutionTransactionPlanner
from onlyalpha.execution.reducers import OnlyStrategyCashReservationTradeReducer, OnlyStrategyLedgerTradeReducer
from onlyalpha.strategy_ledger.enums import OnlyStrategyCashEntryType
from tests.execution.support.multi_fill_reductions import only_test_two_fill_trades


def test_strategy_ledger_consumes_explicit_deltas_and_releases_only_on_final_fill() -> None:
    context, first_trade, second_trade = only_test_two_fill_trades()
    prepared = OnlyTradeExecutionTransactionPlanner().prepare(context)
    allocation = next(item for item in prepared.projections if isinstance(item, OnlyAllocationExecutionProjection))
    reservation_reducer = OnlyStrategyCashReservationTradeReducer()
    ledger_reducer = OnlyStrategyLedgerTradeReducer()

    first_reservation = reservation_reducer.reduce(
        context.strategy_cash_reservation_before,
        first_trade,
        terminal_fill=False,
        projection_sequence=10,
    )
    first = ledger_reducer.reduce(
        context.strategy_ledger_before,
        first_reservation,
        allocation.before,
        allocation.after,
        first_trade,
        context.valuation_price,
        projection_sequence=8,
    )
    assert first.after.cash_reserved.amount == (
        context.strategy_ledger_before.cash_reserved.amount - first_reservation.consumed_delta.amount
    )
    assert not any(
        item.entry_type is OnlyStrategyCashEntryType.ORDER_RESERVATION_RELEASE for item in first.after.cash_entries
    )

    final_reservation = reservation_reducer.reduce(
        first_reservation.after,
        second_trade,
        terminal_fill=True,
        projection_sequence=10,
    )
    final = ledger_reducer.reduce(
        first.after,
        final_reservation,
        allocation.before,
        allocation.after,
        second_trade,
        context.valuation_price,
        projection_sequence=8,
    )
    releases = [
        item
        for item in final.after.cash_entries
        if item.entry_type is OnlyStrategyCashEntryType.ORDER_RESERVATION_RELEASE
    ]
    assert final.after.cash_reserved.amount == 0
    assert len(releases) == 1
    assert final.after.position_cost.amount == allocation.after.cumulative_open_price_quantity
