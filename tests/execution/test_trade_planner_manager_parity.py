from decimal import Decimal

from onlyalpha.execution import (
    OnlyAccountExecutionProjection,
    OnlyAllocationExecutionProjection,
    OnlyOrderExecutionProjection,
    OnlyPositionExecutionProjection,
    OnlyStrategyLedgerExecutionProjection,
    OnlyTradeExecutionTransactionPlanner,
)

from .factories.trade_planning_factory import only_test_generic_t0_trade_planning_context


def test_reducer_after_states_match_generic_t0_manager_formulas() -> None:
    context = only_test_generic_t0_trade_planning_context()
    prepared = OnlyTradeExecutionTransactionPlanner().prepare(context)
    order = _one(prepared.projections, OnlyOrderExecutionProjection).after
    position = _one(prepared.projections, OnlyPositionExecutionProjection).after
    allocation = _one(prepared.projections, OnlyAllocationExecutionProjection).after
    account = _one(prepared.projections, OnlyAccountExecutionProjection).after
    ledger = _one(prepared.projections, OnlyStrategyLedgerExecutionProjection).after
    assert order.filled_quantity == context.order_before.quantity
    assert position.total_quantity == context.update.fill.quantity
    assert allocation.total_quantity == position.total_quantity
    assert account.cash_balance.amount == context.account_before.cash_balance.amount - Decimal("20.00")
    assert ledger.cash_balance == account.cash_balance
    assert ledger.position_market_value == account.position_market_value


def _one(items: tuple[object, ...], expected: type):
    return next(item for item in items if isinstance(item, expected))
