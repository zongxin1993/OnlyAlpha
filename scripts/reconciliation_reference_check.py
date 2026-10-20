"""Independent native literals and actual Python Runtime Ledger comparator vectors."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any


def compare_native(root: Path, outputs: list[dict[str, Any]]) -> None:
    from onlyalpha.account.enums import OnlyAccountType
    from onlyalpha.account.manager import OnlyAccountManager
    from onlyalpha.account.models import OnlyAccountConfig
    from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyRuntimeId, OnlyTradeId
    from onlyalpha.domain.time import OnlyTimestamp
    from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
    from onlyalpha.runtime.reconciliation import (
        OnlyCommittedTradeFeeAttribution,
        OnlyRuntimeLedgerReconciliationService,
    )
    from onlyalpha.strategy_ledger.enums import OnlyStrategyFeeType
    from onlyalpha.strategy_ledger.identifiers import OnlyStrategyFeeEntryId
    from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey
    from onlyalpha.strategy_ledger.manager import OnlyStrategyLedgerManager
    from onlyalpha.strategy_ledger.models import OnlyStrategyFeeEntry

    vectors = [
        json.loads(line) for line in (root / "test-data/execution/reconciliation-v1.jsonl").read_text().splitlines()
    ]
    if len(outputs) != len(vectors):
        raise ValueError("RECONCILIATION_REFERENCE_CARDINALITY")
    currency = OnlyCurrency("CNY", 2)

    def money(raw: str) -> OnlyMoney:
        return OnlyMoney(Decimal(raw), currency)

    with localcontext() as context:
        context.prec = 4096
        for v, output in zip(vectors, outputs, strict=True):
            expected = {key: v[key] for key in ("case", "totals", "status", "difference_fields")}
            if output != expected:
                raise ValueError("RECONCILIATION_LITERAL_VECTOR_MISMATCH")
            if not v["python_common"]:
                continue  # Native exact residuals cannot be certified by Python monetary rounding.
            runtime, account_id = OnlyRuntimeId("reference-runtime"), OnlyAccountId("reference-account")
            a = v["account"]
            accounts = OnlyAccountManager(runtime)
            accounts.create_account(
                OnlyAccountConfig(
                    runtime, account_id, "virtual", OnlyAccountType.CASH, currency, money(a["initial_equity"])
                ),
                OnlyTimestamp(0),
            )
            account = accounts.require_snapshot(account_id)
            account = replace(
                account,
                cash=replace(
                    account.cash,
                    ledger_cash=money(a["ledger_cash"]),
                    trade_available_cash=money(a["ledger_cash"]),
                    withdrawable_cash=money(a["ledger_cash"]),
                ),
                available_margin=money(a["ledger_cash"]),
                position_market_value=money(a["position_market_value"]),
                realized_pnl=money(a["realized_pnl"]),
                unrealized_pnl=money(a["unrealized_pnl"]),
                fees=money(a["fees"]),
                equity=money(a["equity"]),
            )
            manager = OnlyStrategyLedgerManager(runtime)
            for row in v["ledgers"]:
                key = OnlyStrategyLedgerKey(runtime, account_id, OnlyClusterId(row["cluster"]), currency)
                manager.create_ledger(key, money(row["initial_equity"]), OnlyTimestamp(0))
                manager.activate_ledger(key, OnlyTimestamp(0))
            raw = {row["cluster"]: row for row in v["ledgers"]}
            ledgers = []
            for ledger in manager.list_ledgers():
                row = raw[str(ledger.key.cluster_id)]
                entries = tuple(
                    OnlyStrategyFeeEntry(
                        OnlyStrategyFeeEntryId(f"fee-{trade['trade']}"),
                        ledger.key,
                        money(trade["fee"]),
                        OnlyStrategyFeeType.COMMISSION,
                        OnlyTradeId(trade["trade"]),
                        None,
                        OnlyTimestamp(1),
                        OnlyTimestamp(1),
                        1,
                    )
                    for trade in v["trades"]
                    if trade["cluster"] == row["cluster"]
                )
                ledgers.append(
                    replace(
                        ledger,
                        cash=replace(ledger.cash, ledger_cash=money(row["ledger_cash"])),
                        pnl=replace(
                            ledger.pnl,
                            realized_pnl=money(row["realized_pnl"]),
                            unrealized_pnl=money(row["unrealized_pnl"]),
                            fees=money(row["fees"]),
                        ),
                        equity=replace(
                            ledger.equity,
                            position_market_value=money(row["position_market_value"]),
                            equity=money(row["equity"]),
                        ),
                        fee_entries=entries,
                    )
                )
            result = OnlyRuntimeLedgerReconciliationService().reconcile(
                account=account,
                account_initial_equity=money(a["initial_equity"]),
                ledgers=tuple(ledgers),
                committed_trade_fees=tuple(
                    OnlyCommittedTradeFeeAttribution(
                        OnlyTradeId(t["trade"]), OnlyClusterId(t["cluster"]), money(t["fee"])
                    )
                    for t in v["trades"]
                ),
                ts_event=OnlyTimestamp(1),
            )
            if result.status.value != v["status"] or [d.field for d in result.differences] != v["difference_fields"]:
                raise ValueError("RECONCILIATION_PYTHON_COMMON_MISMATCH")
