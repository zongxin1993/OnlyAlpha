from onlyalpha.execution import OnlyExecutionProjectionComponent
from tests.execution.support.generic_t0_trade_harness import only_test_generic_t0_long_close_context


def test_long_close_strategy_ledger_matches_account_economics() -> None:
    _, _, prepared = only_test_generic_t0_long_close_context()
    account = next(
        item for item in prepared.projections if item.identity.component is OnlyExecutionProjectionComponent.ACCOUNT
    )
    ledger = next(
        item
        for item in prepared.projections
        if item.identity.component is OnlyExecutionProjectionComponent.STRATEGY_LEDGER
    )

    assert ledger.after.cash_balance - ledger.before.cash_balance == prepared.fact_draft.net_cash_inflow
    assert ledger.after.fees - ledger.before.fees == prepared.fact_draft.authoritative_fee_total
    assert ledger.after.realized_pnl - ledger.before.realized_pnl == prepared.fact_draft.realized_pnl_delta
    assert ledger.after.cash_balance == account.after.cash_balance
    assert ledger.after.position_market_value == account.after.position_market_value
    assert ledger.after.cash_reserved == ledger.before.cash_reserved


def test_long_close_ledger_records_sell_settlement_and_fee_entries() -> None:
    _, _, prepared = only_test_generic_t0_long_close_context()
    projection = next(
        item
        for item in prepared.projections
        if item.identity.component is OnlyExecutionProjectionComponent.STRATEGY_LEDGER
    )
    new_cash_entries = projection.after.cash_entries[len(projection.before.cash_entries) :]
    new_fee_entries = projection.after.fee_entries[len(projection.before.fee_entries) :]

    assert tuple(item.entry_type.value for item in new_cash_entries) == ("SELL_SETTLEMENT", "FEE")
    assert len(new_fee_entries) == 1
    assert new_fee_entries[0].amount == prepared.fact_draft.authoritative_fee_total
