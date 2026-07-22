"""Runtime-level reconciliation between the shared Account and Cluster Ledgers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from onlyalpha.account.models import OnlyAccountSnapshot
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyRuntimeId, OnlyTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.strategy_ledger.models import OnlyStrategyLedgerSnapshot


class OnlyRuntimeLedgerReconciliationStatus(StrEnum):
    MATCHED = "MATCHED"
    MISMATCHED = "MISMATCHED"


@dataclass(frozen=True, slots=True)
class OnlyRuntimeLedgerDifference:
    field: str
    account_value: OnlyMoney
    ledger_total: OnlyMoney
    difference: OnlyMoney
    cluster_ids: tuple[OnlyClusterId, ...]


@dataclass(frozen=True, slots=True)
class OnlyRuntimeLedgerReconciliationResult:
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    status: OnlyRuntimeLedgerReconciliationStatus
    differences: tuple[OnlyRuntimeLedgerDifference, ...]
    ts_event: OnlyTimestamp


@dataclass(frozen=True, slots=True)
class OnlyCommittedTradeFeeAttribution:
    trade_id: OnlyTradeId
    cluster_id: OnlyClusterId
    fee: OnlyMoney


class OnlyRuntimeLedgerReconciliationService:
    def reconcile(
        self,
        *,
        account: OnlyAccountSnapshot,
        account_initial_equity: OnlyMoney,
        ledgers: tuple[OnlyStrategyLedgerSnapshot, ...],
        committed_trade_fees: tuple[OnlyCommittedTradeFeeAttribution, ...],
        ts_event: OnlyTimestamp,
    ) -> OnlyRuntimeLedgerReconciliationResult:
        if not ledgers:
            raise ValueError("Runtime reconciliation requires at least one Strategy Ledger")
        clusters = tuple(sorted((ledger.key.cluster_id for ledger in ledgers), key=str))
        if any(ledger.key.runtime_id != account.runtime_id for ledger in ledgers):
            raise ValueError("Strategy Ledger Runtime scope differs from Account")
        if any(ledger.key.account_id != account.account_id for ledger in ledgers):
            raise ValueError("Strategy Ledger Account scope differs from shared Account")
        if any(ledger.key.base_currency != account.base_currency for ledger in ledgers):
            raise ValueError("Strategy Ledger currency differs from Account; FX is unsupported")

        values = (
            ("initial_equity", account_initial_equity, tuple(item.capital.initial_capital for item in ledgers)),
            ("cash_balance", account.cash.cash_balance, tuple(item.cash.cash_balance for item in ledgers)),
            (
                "position_market_value",
                account.position_market_value,
                tuple(item.equity.position_market_value for item in ledgers),
            ),
            ("realized_pnl", account.realized_pnl, tuple(item.pnl.realized_pnl for item in ledgers)),
            ("unrealized_pnl", account.unrealized_pnl, tuple(item.pnl.unrealized_pnl for item in ledgers)),
            ("fees", account.fees, tuple(item.pnl.fees for item in ledgers)),
            ("equity", account.equity, tuple(item.equity.equity for item in ledgers)),
        )
        differences: list[OnlyRuntimeLedgerDifference] = []
        for field, account_value, ledger_values in values:
            total_amount = sum((item.amount for item in ledger_values), Decimal(0))
            if total_amount == account_value.amount:
                continue
            ledger_total = OnlyMoney(total_amount, account.base_currency)
            differences.append(
                OnlyRuntimeLedgerDifference(
                    field,
                    account_value,
                    ledger_total,
                    OnlyMoney(account_value.amount - total_amount, account.base_currency),
                    clusters,
                )
            )
        expected_fees = {item.trade_id: item for item in committed_trade_fees}
        if len(expected_fees) != len(committed_trade_fees):
            raise ValueError("duplicate committed Trade fee attribution")
        actual_fees: dict[tuple[OnlyTradeId, OnlyClusterId], Decimal] = {}
        for ledger in ledgers:
            for entry in ledger.fee_entries:
                if entry.trade_id is None:
                    continue
                scope = (entry.trade_id, ledger.key.cluster_id)
                actual_fees[scope] = actual_fees.get(scope, Decimal(0)) + entry.amount.amount
        for trade_id, expected in expected_fees.items():
            actual = actual_fees.get((trade_id, expected.cluster_id), Decimal(0))
            attributed_clusters = tuple(
                sorted(
                    (
                        cluster_id
                        for (candidate, cluster_id), amount in actual_fees.items()
                        if candidate == trade_id and amount
                    ),
                    key=str,
                )
            )
            if actual == expected.fee.amount and attributed_clusters in {(), (expected.cluster_id,)}:
                continue
            differences.append(
                OnlyRuntimeLedgerDifference(
                    f"trade_fee_attribution:{trade_id}",
                    expected.fee,
                    OnlyMoney(actual, account.base_currency),
                    OnlyMoney(expected.fee.amount - actual, account.base_currency),
                    tuple(sorted(set((expected.cluster_id, *attributed_clusters)), key=str)),
                )
            )
        result = tuple(differences)
        return OnlyRuntimeLedgerReconciliationResult(
            account.runtime_id,
            account.account_id,
            (
                OnlyRuntimeLedgerReconciliationStatus.MATCHED
                if not result
                else OnlyRuntimeLedgerReconciliationStatus.MISMATCHED
            ),
            result,
            ts_event,
        )


__all__ = [
    "OnlyCommittedTradeFeeAttribution",
    "OnlyRuntimeLedgerDifference",
    "OnlyRuntimeLedgerReconciliationResult",
    "OnlyRuntimeLedgerReconciliationService",
    "OnlyRuntimeLedgerReconciliationStatus",
]
