from dataclasses import replace
from decimal import Decimal

import pytest

from onlyalpha.account.enums import OnlyAccountType
from onlyalpha.account.identifiers import OnlyAccountFeeId
from onlyalpha.account.manager import OnlyAccountManager
from onlyalpha.account.models import OnlyAccountConfig, OnlyAccountFee, OnlyAccountValuation
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyRuntimeId, OnlyTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.runtime.reconciliation import (
    OnlyCommittedTradeFeeAttribution,
    OnlyRuntimeLedgerReconciliationService,
    OnlyRuntimeLedgerReconciliationStatus,
)
from onlyalpha.strategy_ledger.enums import OnlyStrategyFeeType
from onlyalpha.strategy_ledger.identifiers import OnlyStrategyFeeEntryId
from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey
from onlyalpha.strategy_ledger.manager import OnlyStrategyLedgerManager
from onlyalpha.strategy_ledger.models import OnlyStrategyFeeEntry

RUNTIME = OnlyRuntimeId("reconciliation-runtime")
ACCOUNT = OnlyAccountId("shared-account")
CNY = OnlyCurrency("CNY", 2)


def test_reconciliation_public_imports() -> None:
    from onlyalpha.runtime import (
        OnlyRuntimeLedgerReconciliationResult,
        OnlyRuntimeLedgerReconciliationService,
        OnlyRuntimeLedgerReconciliationStatus,
    )

    assert OnlyRuntimeLedgerReconciliationResult.__name__.startswith("Only")
    assert OnlyRuntimeLedgerReconciliationService.__name__.startswith("Only")
    assert OnlyRuntimeLedgerReconciliationStatus.MATCHED == "MATCHED"


def _state() -> tuple[OnlyAccountManager, OnlyStrategyLedgerManager]:
    accounts = OnlyAccountManager(RUNTIME)
    accounts.create_account(
        OnlyAccountConfig(
            RUNTIME,
            ACCOUNT,
            "virtual",
            OnlyAccountType.CASH,
            CNY,
            OnlyMoney(Decimal("1000.00"), CNY),
        ),
        OnlyTimestamp(0),
    )
    ledgers = OnlyStrategyLedgerManager(RUNTIME)
    for cluster_id, capital in (("a", "400.00"), ("b", "600.00")):
        key = OnlyStrategyLedgerKey(RUNTIME, ACCOUNT, OnlyClusterId(cluster_id), CNY)
        ledgers.create_ledger(key, OnlyMoney(Decimal(capital), CNY), OnlyTimestamp(0))
        ledgers.activate_ledger(key, OnlyTimestamp(0))
    return accounts, ledgers


def _reconcile(
    accounts: OnlyAccountManager,
    ledgers: OnlyStrategyLedgerManager,
    committed_trade_fees: tuple[OnlyCommittedTradeFeeAttribution, ...] = (),
):
    return OnlyRuntimeLedgerReconciliationService().reconcile(
        account=accounts.require_snapshot(ACCOUNT),
        account_initial_equity=OnlyMoney(Decimal("1000.00"), CNY),
        ledgers=ledgers.list_ledgers(),
        committed_trade_fees=committed_trade_fees,
        ts_event=OnlyTimestamp(1),
    )


def test_initial_and_final_fixed_capital_state_reconciles() -> None:
    accounts, ledgers = _state()
    result = _reconcile(accounts, ledgers)
    assert result.status is OnlyRuntimeLedgerReconciliationStatus.MATCHED
    assert result.differences == ()


def test_account_only_fee_produces_structured_differences_without_mutating_ledgers() -> None:
    accounts, ledgers = _state()
    before = ledgers.list_ledgers()
    accounts.apply_fee(
        OnlyAccountFee(
            OnlyAccountFeeId("account-only-fee"),
            RUNTIME,
            ACCOUNT,
            OnlyMoney(Decimal("10.00"), CNY),
            OnlyTimestamp(1),
        )
    )
    result = _reconcile(accounts, ledgers)
    assert result.status is OnlyRuntimeLedgerReconciliationStatus.MISMATCHED
    assert {item.field for item in result.differences} == {"cash_balance", "fees", "equity"}
    assert all(item.cluster_ids == (OnlyClusterId("a"), OnlyClusterId("b")) for item in result.differences)
    assert ledgers.list_ledgers() == before


def test_missing_ledger_valuation_is_detected() -> None:
    accounts, ledgers = _state()
    accounts.apply_valuation(
        OnlyAccountValuation(
            RUNTIME,
            ACCOUNT,
            OnlyMoney(Decimal("100.00"), CNY),
            OnlyMoney(Decimal("100.00"), CNY),
            OnlyTimestamp(1),
            1,
        )
    )
    result = _reconcile(accounts, ledgers)
    assert {item.field for item in result.differences} == {
        "position_market_value",
        "unrealized_pnl",
        "equity",
    }


def test_currency_mismatch_fails_instead_of_using_a_default_cluster() -> None:
    accounts, _ = _state()
    usd = OnlyCurrency("USD", 2)
    ledgers = OnlyStrategyLedgerManager(RUNTIME)
    key = OnlyStrategyLedgerKey(RUNTIME, ACCOUNT, OnlyClusterId("a"), usd)
    ledgers.create_ledger(key, OnlyMoney(Decimal("1000.00"), usd), OnlyTimestamp(0))
    with pytest.raises(ValueError, match="currency differs"):
        _reconcile(accounts, ledgers)


def test_wrong_cluster_fee_attribution_is_detected_even_when_aggregate_totals_match() -> None:
    accounts, ledgers = _state()
    trade_id = OnlyTradeId("trade-a")
    fee = OnlyMoney(Decimal("10.00"), CNY)
    accounts.apply_fee(
        OnlyAccountFee(
            OnlyAccountFeeId("account-fee"),
            RUNTIME,
            ACCOUNT,
            fee,
            OnlyTimestamp(1),
            trade_id,
        )
    )
    wrong_key = ledgers.require_key(
        runtime_id=RUNTIME,
        account_id=ACCOUNT,
        cluster_id=OnlyClusterId("b"),
        currency=CNY,
    )
    ledgers.apply_fee(
        wrong_key,
        OnlyStrategyFeeEntry(
            OnlyStrategyFeeEntryId("wrong-cluster-fee"),
            wrong_key,
            fee,
            OnlyStrategyFeeType.COMMISSION,
            trade_id,
            None,
            OnlyTimestamp(1),
            OnlyTimestamp(1),
            1,
        ),
    )

    result = _reconcile(
        accounts,
        ledgers,
        (OnlyCommittedTradeFeeAttribution(trade_id, OnlyClusterId("a"), fee),),
    )

    assert {item.field for item in result.differences} == {"trade_fee_attribution:trade-a"}
    assert result.differences[0].cluster_ids == (OnlyClusterId("a"), OnlyClusterId("b"))


def test_missing_ledger_fee_is_reported_by_total_and_trade_attribution() -> None:
    accounts, ledgers = _state()
    trade_id = OnlyTradeId("trade-a")
    fee = OnlyMoney(Decimal("10.00"), CNY)
    accounts.apply_fee(
        OnlyAccountFee(
            OnlyAccountFeeId("account-fee"),
            RUNTIME,
            ACCOUNT,
            fee,
            OnlyTimestamp(1),
            trade_id,
        )
    )

    result = _reconcile(
        accounts,
        ledgers,
        (OnlyCommittedTradeFeeAttribution(trade_id, OnlyClusterId("a"), fee),),
    )

    assert {item.field for item in result.differences} == {
        "cash_balance",
        "fees",
        "equity",
        "trade_fee_attribution:trade-a",
    }


def test_fixed_capital_profit_and_loss_sum_to_account_portfolio_result() -> None:
    accounts, ledgers = _state()
    account = accounts.require_snapshot(ACCOUNT)
    account_final = replace(
        account,
        cash=replace(
            account.cash,
            cash_balance=OnlyMoney(Decimal("1030.00"), CNY),
            available_cash=OnlyMoney(Decimal("1030.00"), CNY),
        ),
        realized_pnl=OnlyMoney(Decimal("30.00"), CNY),
        equity=OnlyMoney(Decimal("1030.00"), CNY),
    )
    finals = []
    for ledger in ledgers.list_ledgers():
        pnl = Decimal("40.00") if str(ledger.key.cluster_id) == "a" else Decimal("-10.00")
        final_equity = ledger.capital.initial_capital.amount + pnl
        finals.append(
            replace(
                ledger,
                cash=replace(
                    ledger.cash,
                    cash_balance=OnlyMoney(final_equity, CNY),
                    cash_available=OnlyMoney(final_equity, CNY),
                ),
                pnl=replace(
                    ledger.pnl,
                    realized_pnl=OnlyMoney(pnl, CNY),
                    net_pnl=OnlyMoney(pnl, CNY),
                ),
                equity=replace(
                    ledger.equity,
                    cash_balance=OnlyMoney(final_equity, CNY),
                    cash_available=OnlyMoney(final_equity, CNY),
                    realized_pnl=OnlyMoney(pnl, CNY),
                    net_pnl=OnlyMoney(pnl, CNY),
                    equity=OnlyMoney(final_equity, CNY),
                    equity_by_cash_view=OnlyMoney(final_equity, CNY),
                    equity_by_pnl_view=OnlyMoney(final_equity, CNY),
                ),
            )
        )

    result = OnlyRuntimeLedgerReconciliationService().reconcile(
        account=account_final,
        account_initial_equity=OnlyMoney(Decimal("1000.00"), CNY),
        ledgers=tuple(finals),
        committed_trade_fees=(),
        ts_event=OnlyTimestamp(2),
    )

    assert [item.equity.equity.amount for item in finals] == [Decimal("440.00"), Decimal("590.00")]
    assert account_final.equity.amount == Decimal("1030.00")
    assert account_final.realized_pnl.amount == Decimal("30.00")
    assert (account_final.equity.amount / account.equity.amount) - Decimal(1) == Decimal("0.03")
    assert result.status is OnlyRuntimeLedgerReconciliationStatus.MATCHED
