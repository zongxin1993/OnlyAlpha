from decimal import Decimal

from onlyalpha.execution import OnlyExecutionProjectionComponent
from tests.execution.support.generic_t0_trade_harness import only_test_generic_t0_long_close_context


def test_long_close_fee_is_authoritative_and_incremental() -> None:
    _, _, prepared = only_test_generic_t0_long_close_context()
    fee = next(item for item in prepared.projections if item.identity.component is OnlyExecutionProjectionComponent.FEE)
    accrual = next(
        item
        for item in prepared.projections
        if item.identity.component is OnlyExecutionProjectionComponent.ORDER_FEE_ACCRUAL
    )

    assert fee.after.authoritative_total == prepared.fact_draft.authoritative_fee_total
    assert accrual.after.cumulative_charged_fee == prepared.fact_draft.authoritative_fee_total
    assert sum((record.amount.amount for record in fee.after.records), Decimal(0)) == Decimal("1.20")


def test_long_close_settlement_carries_positive_sale_cash_without_asset_release() -> None:
    _, _, prepared = only_test_generic_t0_long_close_context()
    settlement = next(
        item for item in prepared.projections if item.identity.component is OnlyExecutionProjectionComponent.SETTLEMENT
    )

    assert settlement.after.cash_amount == prepared.fact_draft.gross_cash_inflow
    assert settlement.after.asset_quantity == prepared.fact_draft.fill_quantity.value
    assert settlement.after.trade_cash_released
    assert settlement.after.asset_released
    assert settlement.after.cash_trade_available_on == prepared.fact_draft.cash_available_on
