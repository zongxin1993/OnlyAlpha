from onlyalpha.execution import OnlyExecutionProjectionComponent, OnlyTradeExecutionTransactionPlanner

from .factories.trade_planning_factory import only_test_generic_t0_trade_planning_context


def test_generic_t0_buy_open_builds_complete_prepared_transaction() -> None:
    prepared = OnlyTradeExecutionTransactionPlanner().prepare(only_test_generic_t0_trade_planning_context())
    assert tuple(item.identity.component for item in prepared.projections) == (
        OnlyExecutionProjectionComponent.ORDER,
        OnlyExecutionProjectionComponent.POSITION,
        OnlyExecutionProjectionComponent.ALLOCATION,
        OnlyExecutionProjectionComponent.SETTLEMENT,
        OnlyExecutionProjectionComponent.FEE,
        OnlyExecutionProjectionComponent.ACCOUNT,
        OnlyExecutionProjectionComponent.STRATEGY_LEDGER,
        OnlyExecutionProjectionComponent.ACCOUNT_CASH_RESERVATION,
        OnlyExecutionProjectionComponent.STRATEGY_CASH_RESERVATION,
        OnlyExecutionProjectionComponent.RISK_RESERVATION,
        OnlyExecutionProjectionComponent.RISK,
        OnlyExecutionProjectionComponent.VALUATION,
    )
    assert len(prepared.preconditions) == len(prepared.projections)
    assert tuple(item.projection_sequence for item in (p.identity for p in prepared.projections)) == tuple(range(1, 13))


def test_planner_does_not_mutate_context_authority() -> None:
    context = only_test_generic_t0_trade_planning_context()
    before = context
    OnlyTradeExecutionTransactionPlanner().prepare(context)
    assert context == before
