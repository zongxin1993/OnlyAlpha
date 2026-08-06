from onlyalpha.execution import OnlyRuntimeProjectionComponent
from tests.execution.support.generic_t0_trade_harness import only_test_generic_t0_long_close_context


def test_long_close_strategy_ledger_matches_account_economics() -> None:
    _, _, prepared = only_test_generic_t0_long_close_context()
    account = next(
        item for item in prepared.projections if item.identity.component is OnlyRuntimeProjectionComponent.ACCOUNT
    )
    ledger = next(
        item
        for item in prepared.projections
        if item.identity.component is OnlyRuntimeProjectionComponent.STRATEGY_LEDGER
    )

    assert ledger.after.ledger_cash - ledger.before.ledger_cash == prepared.fact_draft.net_cash_inflow
    assert ledger.after.fees - ledger.before.fees == (
        prepared.fact_draft.fee_total_charges - prepared.fact_draft.fee_total_rebates
    )
    assert ledger.after.realized_pnl - ledger.before.realized_pnl == prepared.fact_draft.realized_pnl_delta
    assert ledger.after.ledger_cash == account.after.ledger_cash
    assert ledger.after.position_market_value == account.after.position_market_value
    assert ledger.after.cash_reserved == ledger.before.cash_reserved


def test_long_close_ledger_records_sell_settlement_and_fee_entries() -> None:
    _, _, prepared = only_test_generic_t0_long_close_context()
    projection = next(
        item
        for item in prepared.projections
        if item.identity.component is OnlyRuntimeProjectionComponent.STRATEGY_LEDGER
    )
    new_cash_entries = projection.after.cash_entries[len(projection.before.cash_entries) :]
    new_fee_entries = projection.after.fee_entries[len(projection.before.fee_entries) :]

    assert tuple(item.entry_type.value for item in new_cash_entries) == ("SELL_SETTLEMENT", "FEE")
    assert len(new_fee_entries) == 1
    assert new_fee_entries[0].amount == (prepared.fact_draft.fee_total_charges - prepared.fact_draft.fee_total_rebates)
