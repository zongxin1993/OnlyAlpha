"""Single canonical Backtest business-result projection."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from .diagnostics import OnlyBacktestDiagnostics


class OnlyBacktestBusinessResultView(Protocol):
    @property
    def run(self) -> object: ...

    @property
    def data(self) -> object: ...

    @property
    def execution(self) -> object: ...

    @property
    def runtime_performance(self) -> object: ...

    @property
    def final_positions(self) -> object: ...

    @property
    def final_allocations(self) -> object: ...

    @property
    def final_ledgers(self) -> object: ...

    @property
    def final_account(self) -> object: ...

    @property
    def orders(self) -> object: ...

    @property
    def trades(self) -> object: ...

    @property
    def cluster_results(self) -> object: ...

    @property
    def account_equity_timeline(self) -> object: ...

    @property
    def cluster_equity_timelines(self) -> object: ...

    @property
    def reconciliation(self) -> object: ...

    @property
    def invariant_results(self) -> object: ...

    @property
    def facts(self) -> object: ...

    @property
    def diagnostics(self) -> OnlyBacktestDiagnostics: ...


def only_backtest_business_projection(result: OnlyBacktestBusinessResultView) -> Mapping[str, object]:
    """Return every stable business field and no recovery/transport metadata."""

    return {
        "account_equity_timeline": result.account_equity_timeline,
        "cluster_equity_timelines": result.cluster_equity_timelines,
        "cluster_results": result.cluster_results,
        "data": result.data,
        "diagnostics": {
            "failures": result.diagnostics.failures,
            "total_failure_count": result.diagnostics.total_failure_count,
            "truncated": result.diagnostics.truncated,
            "warnings": result.diagnostics.warnings,
        },
        "execution": result.execution,
        "facts": result.facts,
        "final_account": result.final_account,
        "final_allocations": result.final_allocations,
        "final_ledgers": result.final_ledgers,
        "final_positions": result.final_positions,
        "invariant_results": result.invariant_results,
        "orders": result.orders,
        "reconciliation": result.reconciliation,
        "run": result.run,
        "runtime_performance": result.runtime_performance,
        "trades": result.trades,
    }
