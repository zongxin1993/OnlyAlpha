from dataclasses import replace
from decimal import Decimal

from onlyalpha.domain.identifiers import OnlyTradeId
from onlyalpha.domain.value import OnlyMoney, OnlyQuantity
from onlyalpha.execution import OnlyTradeExecutionTransactionPlanner
from onlyalpha.execution.planned_trade import OnlyPlannedTrade
from tests.execution.factories.trade_planning_factory import only_test_generic_t0_trade_planning_context


def only_test_two_fill_trades() -> tuple[object, OnlyPlannedTrade, OnlyPlannedTrade]:
    context = only_test_generic_t0_trade_planning_context()
    base = OnlyTradeExecutionTransactionPlanner._planned_trade(context)
    currency = base.fee_charges.currency
    first = replace(
        base,
        trade_id=OnlyTradeId("partial-trade-1"),
        quantity=OnlyQuantity(Decimal("30"), base.quantity.precision),
        gross_notional=OnlyMoney(Decimal("300.00"), currency),
        settled_notional=OnlyMoney(Decimal("300.00"), currency),
    )
    second = replace(
        base,
        trade_id=OnlyTradeId("partial-trade-2"),
        quantity=OnlyQuantity(Decimal("70"), base.quantity.precision),
        gross_notional=OnlyMoney(Decimal("700.00"), currency),
        settled_notional=OnlyMoney(Decimal("700.00"), currency),
        source_sequence=base.source_sequence + 1,
    )
    return context, first, second


__all__ = ["only_test_two_fill_trades"]
