from onlyalpha.execution import OnlyRuntimeProjectionComponent, OnlyTradeExecutionTransactionPlanner

from .factories.trade_planning_factory import only_test_generic_t0_trade_planning_context


def test_generic_t0_buy_open_builds_complete_prepared_transaction() -> None:
    prepared = OnlyTradeExecutionTransactionPlanner().prepare(only_test_generic_t0_trade_planning_context())
    assert tuple(item.identity.component for item in prepared.projections) == (
        OnlyRuntimeProjectionComponent.ORDER,
        OnlyRuntimeProjectionComponent.POSITION,
        OnlyRuntimeProjectionComponent.ALLOCATION,
        OnlyRuntimeProjectionComponent.SETTLEMENT,
        OnlyRuntimeProjectionComponent.ORDER_FEE_ACCRUAL,
        OnlyRuntimeProjectionComponent.FEE,
        OnlyRuntimeProjectionComponent.ACCOUNT,
        OnlyRuntimeProjectionComponent.STRATEGY_LEDGER,
        OnlyRuntimeProjectionComponent.ACCOUNT_CASH_RESERVATION,
        OnlyRuntimeProjectionComponent.STRATEGY_CASH_RESERVATION,
        OnlyRuntimeProjectionComponent.RISK_RESERVATION,
        OnlyRuntimeProjectionComponent.RISK,
        OnlyRuntimeProjectionComponent.VALUATION,
    )
    assert len(prepared.preconditions) == len(prepared.projections)
    assert tuple(item.projection_sequence for item in (p.identity for p in prepared.projections)) == tuple(range(1, 14))


def test_planner_does_not_mutate_context_authority() -> None:
    context = only_test_generic_t0_trade_planning_context()
    before = context
    OnlyTradeExecutionTransactionPlanner().prepare(context)
    assert context == before
