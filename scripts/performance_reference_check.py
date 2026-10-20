"""Independent native performance literals and actual Python projector common behavior."""

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
    from onlyalpha.account.performance import OnlyAccountPerformanceProjector, OnlyAccountValuationSource
    from onlyalpha.domain.identifiers import OnlyAccountId, OnlyRuntimeId
    from onlyalpha.domain.time import OnlyTimestamp
    from onlyalpha.domain.value import OnlyCurrency, OnlyMoney

    vectors = [json.loads(line) for line in (root / "test-data/account/performance-v1.jsonl").read_text().splitlines()]
    if len(outputs) != len(vectors):
        raise ValueError("PERFORMANCE_REFERENCE_CARDINALITY")
    currency = OnlyCurrency("USD", 2)

    def money(raw: str) -> OnlyMoney:
        return OnlyMoney(Decimal(raw), currency)

    with localcontext() as context:
        context.prec = 4096
        for v, output in zip(vectors, outputs, strict=True):
            if output != {"case": v["case"], "summary": v["expected"]}:
                raise ValueError("PERFORMANCE_LITERAL_MISMATCH")
            if not v["python_common"]:
                continue
            runtime, account = OnlyRuntimeId("runtime"), OnlyAccountId("account")
            manager = OnlyAccountManager(runtime)
            original = manager.create_account(
                OnlyAccountConfig(runtime, account, "virtual", OnlyAccountType.CASH, currency, money(v["initial"])),
                OnlyTimestamp(0),
            )
            projector = OnlyAccountPerformanceProjector(runtime)
            projector.record(original, OnlyAccountValuationSource.ACCOUNT_CREATED)
            equity = Decimal(v["initial"])
            for i, delta in enumerate(v["amounts"], 1):
                equity += Decimal(delta)
                amount = money(str(equity))
                snapshot = replace(
                    original,
                    cash=replace(
                        original.cash, ledger_cash=amount, trade_available_cash=amount, withdrawable_cash=amount
                    ),
                    available_margin=amount,
                    realized_pnl=money(str(equity - Decimal(v["initial"]))),
                    equity=amount,
                    updated_at=OnlyTimestamp(i),
                    version=i,
                )
                projector.record(snapshot, OnlyAccountValuationSource.STATE_CHANGE)
            summary = projector.summarize(account)
            observed = {}
            for key in v["expected"]:
                value = getattr(summary, key)
                if hasattr(value, "amount"):
                    observed[key] = format(value.amount, ".2f")
                    if Decimal(observed[key]) != value.amount:
                        raise ValueError("PERFORMANCE_MONEY_PRECISION")
                elif hasattr(value, "value"):
                    observed[key] = format(value.value, ".8f")
                    if Decimal(observed[key]) != value.value:
                        raise ValueError("PERFORMANCE_RATE_PRECISION")
                else:
                    observed[key] = value
            if observed != v["expected"]:
                raise ValueError("PERFORMANCE_PYTHON_COMMON_MISMATCH")
