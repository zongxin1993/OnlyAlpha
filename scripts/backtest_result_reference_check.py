"""Independent Result literals, native canonical bytes and actual Python Result common behavior."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def python_common(vector: dict[str, Any]) -> dict[str, Any]:
    from onlyalpha.account.enums import OnlyAccountType
    from onlyalpha.account.manager import OnlyAccountManager
    from onlyalpha.account.models import OnlyAccountConfig
    from onlyalpha.account.performance import OnlyAccountPerformanceProjector, OnlyAccountValuationSource
    from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyRuntimeId
    from onlyalpha.domain.time import OnlyTimestamp
    from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
    from onlyalpha.result.business_projection import only_backtest_business_projection
    from onlyalpha.result.fingerprint import only_result_fingerprint
    from onlyalpha.runtime.backtest.result import (
        OnlyBacktestDataSummary,
        OnlyBacktestExecutionSummary,
        OnlyBacktestResult,
        OnlyBacktestRunSummary,
        OnlyBacktestStatus,
        OnlyClusterPerformanceSummary,
        OnlyClusterResult,
    )
    from onlyalpha.runtime.reconciliation import OnlyRuntimeLedgerReconciliationService
    from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey
    from onlyalpha.strategy_ledger.manager import OnlyStrategyLedgerManager

    runtime, account_id = OnlyRuntimeId("runtime"), OnlyAccountId("account")
    currency, start, end = OnlyCurrency("CNY", 2), OnlyTimestamp(0), OnlyTimestamp(100)

    def money(raw: str) -> OnlyMoney:
        return OnlyMoney(Decimal(raw), currency)

    accounts = OnlyAccountManager(runtime)
    account = accounts.create_account(
        OnlyAccountConfig(runtime, account_id, "virtual", OnlyAccountType.CASH, currency, money(vector["initial"])),
        start,
    )
    projector = OnlyAccountPerformanceProjector(runtime)
    projector.record(account, OnlyAccountValuationSource.ACCOUNT_CREATED)
    ledgers = OnlyStrategyLedgerManager(runtime)
    clusters = []
    timelines = []
    for name, capital in sorted(vector["capitals"].items()):
        key = OnlyStrategyLedgerKey(runtime, account_id, OnlyClusterId(name), currency)
        ledgers.create_ledger(key, money(capital), start)
        ledger = ledgers.activate_ledger(key, start)
        perf = ledger.performance
        clusters.append(
            OnlyClusterResult(
                key.cluster_id,
                OnlyClusterPerformanceSummary(
                    runtime,
                    account_id,
                    key.cluster_id,
                    ledger.ledger_id,
                    currency,
                    ledger.capital.initial_capital,
                    ledger.equity.equity,
                    ledger.pnl.realized_pnl,
                    ledger.pnl.unrealized_pnl,
                    ledger.pnl.net_pnl,
                    ledger.pnl.fees,
                    ledger.equity.return_since_start,
                    ledger.equity.drawdown,
                    ledger.equity.maximum_drawdown,
                    perf.trade_count,
                    perf.winning_trade_count,
                    perf.losing_trade_count,
                    perf.win_rate,
                    perf.profit_factor,
                    ledgers.valuation_count(key),
                    ledger.quality_flags,
                ),
                {},
                (),
                (),
            )
        )
        timelines.append(ledgers.equity_timeline(key))
    snapshots = ledgers.list_ledgers()
    reconciliation = OnlyRuntimeLedgerReconciliationService().reconcile(
        account=account,
        account_initial_equity=money(vector["initial"]),
        ledgers=snapshots,
        committed_trade_fees=(),
        ts_event=end,
    )
    result = OnlyBacktestResult(
        run=OnlyBacktestRunSummary(
            runtime, OnlyBacktestStatus.COMPLETED, start, end, tuple(c.cluster_id for c in clusters)
        ),
        data=OnlyBacktestDataSummary("immutable-source", "immutable-version", 0, 0, 0, 0, ()),
        execution=OnlyBacktestExecutionSummary(0, 0, 0),
        runtime_performance=projector.summarize(account_id),
        final_positions=(),
        final_allocations=(),
        final_ledgers=snapshots,
        final_account=account,
        orders=(),
        trades=(),
        cluster_results=tuple(clusters),
        account_equity_timeline=projector.timeline(account_id),
        cluster_equity_timelines=tuple(timelines),
        reconciliation=reconciliation,
        invariant_results=(),
        determinism_fingerprint="",
    )
    # Exercise the actual public Result serializer and canonical business projection.
    serialized = result.to_dict()
    assert serialized["run"]["status"] == "COMPLETED"  # type: ignore[index]
    assert only_result_fingerprint(only_backtest_business_projection(result)) != only_result_fingerprint(
        only_backtest_business_projection(replace(result, run=replace(result.run, status=OnlyBacktestStatus.FAILED)))
    )
    p = result.runtime_performance
    rate = p.return_since_start
    return {
        "status": result.status.value,
        "order_count": result.execution.order_count,
        "trade_count": result.execution.trade_count,
        "initial_equity": format(p.initial_equity.amount, ".2f"),
        "final_equity": format(p.final_equity.amount, ".2f"),
        "fees": format(p.fees.amount, ".2f"),
        "return_since_start": None if rate is None else format(rate.value, ".8f"),
        "cluster_equities": {str(s.key.cluster_id): format(s.equity.equity.amount, ".2f") for s in snapshots},
    }


def compare_native(root: Path, outputs: list[dict[str, Any]]) -> None:
    vectors = [
        json.loads(line) for line in (root / "test-data/execution/backtest-result-v1.jsonl").read_text().splitlines()
    ]
    if len(outputs) != len(vectors):
        raise ValueError("BACKTEST_RESULT_REFERENCE_CARDINALITY")
    with localcontext() as context:
        context.prec = 4096
        for vector, output in zip(vectors, outputs, strict=True):
            if output["case"] != vector["case"] or output["observed"] != vector["expected"]:
                raise ValueError("BACKTEST_RESULT_LITERAL_MISMATCH")
            content = dict(output["result"])
            identity = content.pop("id")
            if identity != "BTR-" + _digest(content):
                raise ValueError("BACKTEST_RESULT_CONTENT_IDENTITY")
            result_fp = content.pop("result_fingerprint")
            determinism = content.pop("determinism_fingerprint")
            if result_fp != determinism or result_fp != _digest(content):
                raise ValueError("BACKTEST_RESULT_BUSINESS_IDENTITY")
            if vector["python_common"] and python_common(vector) != vector["expected"]:
                raise ValueError("BACKTEST_RESULT_PYTHON_COMMON_MISMATCH")
