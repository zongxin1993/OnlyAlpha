from decimal import Decimal

from onlyalpha.execution import OnlyRuntimeProjectionComponent
from tests.execution.support.generic_t0_trade_harness import only_test_generic_t0_long_close_context


def test_long_close_account_receives_net_proceeds_fee_and_realized_pnl_once() -> None:
    _, _, prepared = only_test_generic_t0_long_close_context()
    projection = next(
        item for item in prepared.projections if item.identity.component is OnlyRuntimeProjectionComponent.ACCOUNT
    )
    fact = prepared.fact_draft

    assert projection.after.ledger_cash - projection.before.ledger_cash == fact.net_cash_inflow
    assert projection.after.fees - projection.before.fees == fact.authoritative_fee_total
    assert projection.after.realized_pnl - projection.before.realized_pnl == fact.realized_pnl_delta
    assert fact.gross_cash_inflow.amount == Decimal("1200.00")
    assert fact.net_cash_inflow.amount == Decimal("1198.80")
    assert projection.after.order_reserved_cash == projection.before.order_reserved_cash


def test_long_close_account_trade_available_cash_formula_remains_exact() -> None:
    _, _, prepared = only_test_generic_t0_long_close_context()
    projection = next(
        item for item in prepared.projections if item.identity.component is OnlyRuntimeProjectionComponent.ACCOUNT
    )

    assert projection.after.trade_available_cash.amount == (
        projection.after.ledger_cash.amount
        - projection.after.order_reserved_cash.amount
        - projection.after.unsettled_receivable_cash.amount
    )
