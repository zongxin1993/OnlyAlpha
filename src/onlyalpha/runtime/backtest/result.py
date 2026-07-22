"""Immutable product backtest result and deterministic exporters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.account.models import OnlyAccountSnapshot
from onlyalpha.account.performance import OnlyAccountEquityPoint, OnlyRuntimePortfolioPerformanceSummary
from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyRate
from onlyalpha.execution.committed import OnlyCommittedExecutionFact
from onlyalpha.position.models import OnlyPositionAllocationSnapshot, OnlyPositionSnapshot
from onlyalpha.result.diagnostics import OnlyBacktestDiagnostics
from onlyalpha.result.records import OnlyBacktestFacts
from onlyalpha.runtime.reconciliation import OnlyRuntimeLedgerReconciliationResult
from onlyalpha.strategy_ledger.identifiers import OnlyStrategyLedgerId
from onlyalpha.strategy_ledger.models import OnlyStrategyLedgerEquityPoint, OnlyStrategyLedgerSnapshot


class OnlyBacktestStatus(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class OnlyBacktestRunSummary:
    runtime_id: OnlyRuntimeId
    status: OnlyBacktestStatus
    start_time: OnlyTimestamp
    end_time: OnlyTimestamp
    cluster_ids: tuple[OnlyClusterId, ...]
    failure: str | None = None


@dataclass(frozen=True, slots=True)
class OnlyBacktestDataSummary:
    data_source_id: str
    data_version: str
    generated_bar_count: int
    processed_bar_count: int
    duplicate_count: int
    gap_count: int
    quality_flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OnlyBacktestExecutionSummary:
    order_count: int
    rejected_order_count: int
    trade_count: int


@dataclass(frozen=True, slots=True)
class OnlyClusterPerformanceSummary:
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    ledger_id: OnlyStrategyLedgerId
    currency: OnlyCurrency
    initial_equity: OnlyMoney
    final_equity: OnlyMoney
    realized_pnl: OnlyMoney
    unrealized_pnl: OnlyMoney
    net_pnl: OnlyMoney
    fees: OnlyMoney
    return_since_start: OnlyRate | None
    current_drawdown: OnlyRate
    maximum_drawdown: OnlyRate
    trade_count: int
    winning_trade_count: int
    losing_trade_count: int
    win_rate: OnlyRate | None
    profit_factor: OnlyRate | None
    valuation_count: int
    quality_flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OnlyClusterResult:
    cluster_id: OnlyClusterId
    performance: OnlyClusterPerformanceSummary
    strategy_result_extension: dict[str, object]
    factor_results: tuple[dict[str, object], ...]
    indicator_diagnostics: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class OnlyBacktestResult:
    run: OnlyBacktestRunSummary
    data: OnlyBacktestDataSummary
    execution: OnlyBacktestExecutionSummary
    runtime_performance: OnlyRuntimePortfolioPerformanceSummary
    final_positions: tuple[OnlyPositionSnapshot, ...]
    final_allocations: tuple[OnlyPositionAllocationSnapshot, ...]
    final_ledgers: tuple[OnlyStrategyLedgerSnapshot, ...]
    final_account: OnlyAccountSnapshot
    orders: tuple[OnlyOrderSnapshot, ...]
    trades: tuple[OnlyCommittedExecutionFact, ...]
    cluster_results: tuple[OnlyClusterResult, ...]
    account_equity_timeline: tuple[OnlyAccountEquityPoint, ...]
    cluster_equity_timelines: tuple[tuple[OnlyStrategyLedgerEquityPoint, ...], ...]
    reconciliation: OnlyRuntimeLedgerReconciliationResult
    invariant_results: tuple[str, ...]
    determinism_fingerprint: str
    facts: OnlyBacktestFacts = OnlyBacktestFacts()
    diagnostics: OnlyBacktestDiagnostics = OnlyBacktestDiagnostics()
    result_fingerprint: str = ""

    @property
    def status(self) -> OnlyBacktestStatus:
        return self.run.status

    @property
    def runtime_id(self) -> OnlyRuntimeId:
        return self.run.runtime_id

    @property
    def runtime_type(self) -> str:
        return "BACKTEST"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 3,
            "run": {
                "runtime_id": str(self.run.runtime_id),
                "status": self.run.status.value,
                "start_time_ns": self.run.start_time.unix_nanos,
                "end_time_ns": self.run.end_time.unix_nanos,
                "cluster_ids": [str(item) for item in self.run.cluster_ids],
                "failure": self.run.failure,
            },
            "data": {
                "data_source_id": self.data.data_source_id,
                "data_version": self.data.data_version,
                "generated_bar_count": self.data.generated_bar_count,
                "processed_bar_count": self.data.processed_bar_count,
                "duplicate_count": self.data.duplicate_count,
                "gap_count": self.data.gap_count,
                "quality_flags": list(self.data.quality_flags),
            },
            "execution": {
                "order_count": self.execution.order_count,
                "rejected_order_count": self.execution.rejected_order_count,
                "trade_count": self.execution.trade_count,
            },
            "runtime_performance": {
                "runtime_id": str(self.runtime_performance.runtime_id),
                "account_id": str(self.runtime_performance.account_id),
                "authority": self.runtime_performance.authority,
                "currency": self.runtime_performance.currency.to_dict(),
                "initial_equity": self.runtime_performance.initial_equity.to_dict(),
                "final_equity": self.runtime_performance.final_equity.to_dict(),
                "realized_pnl": self.runtime_performance.realized_pnl.to_dict(),
                "unrealized_pnl": self.runtime_performance.unrealized_pnl.to_dict(),
                "net_pnl": self.runtime_performance.net_pnl.to_dict(),
                "fees": self.runtime_performance.fees.to_dict(),
                "external_cash_flow": self.runtime_performance.external_cash_flow.to_dict(),
                "return_since_start": (
                    None
                    if self.runtime_performance.return_since_start is None
                    else self.runtime_performance.return_since_start.to_dict()
                ),
                "current_drawdown": self.runtime_performance.current_drawdown.to_dict(),
                "maximum_drawdown": self.runtime_performance.maximum_drawdown.to_dict(),
                "high_water_mark": self.runtime_performance.high_water_mark.to_dict(),
                "valuation_count": self.runtime_performance.valuation_count,
                "quality_flags": list(self.runtime_performance.quality_flags),
            },
            "final_positions": [item.to_dict() for item in self.final_positions],
            "final_allocations": [item.to_dict() for item in self.final_allocations],
            "final_ledgers": [item.to_dict() for item in self.final_ledgers],
            "final_account": self.final_account.to_dict(),
            "orders": [item.to_dict() for item in self.orders],
            "trades": [item.to_dict() for item in self.trades],
            "cluster_results": [
                {
                    "cluster_id": str(item.cluster_id),
                    "cluster_performance": {
                        "runtime_id": str(item.performance.runtime_id),
                        "account_id": str(item.performance.account_id),
                        "cluster_id": str(item.performance.cluster_id),
                        "ledger_id": str(item.performance.ledger_id),
                        "currency": item.performance.currency.to_dict(),
                        "initial_equity": item.performance.initial_equity.to_dict(),
                        "final_equity": item.performance.final_equity.to_dict(),
                        "realized_pnl": item.performance.realized_pnl.to_dict(),
                        "unrealized_pnl": item.performance.unrealized_pnl.to_dict(),
                        "net_pnl": item.performance.net_pnl.to_dict(),
                        "fees": item.performance.fees.to_dict(),
                        "return_since_start": (
                            None
                            if item.performance.return_since_start is None
                            else item.performance.return_since_start.to_dict()
                        ),
                        "current_drawdown": item.performance.current_drawdown.to_dict(),
                        "maximum_drawdown": item.performance.maximum_drawdown.to_dict(),
                        "trade_count": item.performance.trade_count,
                        "winning_trade_count": item.performance.winning_trade_count,
                        "losing_trade_count": item.performance.losing_trade_count,
                        "win_rate": None if item.performance.win_rate is None else item.performance.win_rate.to_dict(),
                        "profit_factor": (
                            None if item.performance.profit_factor is None else item.performance.profit_factor.to_dict()
                        ),
                        "valuation_count": item.performance.valuation_count,
                        "quality_flags": list(item.performance.quality_flags),
                    },
                    "strategy_result_extension": item.strategy_result_extension,
                    "factor_results": list(item.factor_results),
                    "indicator_diagnostics": list(item.indicator_diagnostics),
                }
                for item in self.cluster_results
            ],
            "account_equity_timeline": [
                {
                    "sequence": item.sequence,
                    "runtime_id": str(item.runtime_id),
                    "account_id": str(item.account_id),
                    "ts_event_ns": item.ts_event.unix_nanos,
                    "trading_day": None if item.trading_day is None else str(item.trading_day),
                    "currency": item.currency.to_dict(),
                    "cash": item.cash.to_dict(),
                    "position_market_value": item.position_market_value.to_dict(),
                    "realized_pnl": item.realized_pnl.to_dict(),
                    "unrealized_pnl": item.unrealized_pnl.to_dict(),
                    "fees": item.fees.to_dict(),
                    "equity": item.equity.to_dict(),
                    "external_cash_flow": item.external_cash_flow.to_dict(),
                    "source": item.source.value,
                    "account_version": item.account_version,
                    "quality_flags": list(item.quality_flags),
                }
                for item in self.account_equity_timeline
            ],
            "cluster_equity_timelines": [
                [point.to_dict() for point in timeline] for timeline in self.cluster_equity_timelines
            ],
            "reconciliation": {
                "runtime_id": str(self.reconciliation.runtime_id),
                "account_id": str(self.reconciliation.account_id),
                "status": self.reconciliation.status.value,
                "ts_event_ns": self.reconciliation.ts_event.unix_nanos,
                "differences": [
                    {
                        "field": difference.field,
                        "account_value": difference.account_value.to_dict(),
                        "ledger_total": difference.ledger_total.to_dict(),
                        "difference": difference.difference.to_dict(),
                        "cluster_ids": [str(cluster_id) for cluster_id in difference.cluster_ids],
                    }
                    for difference in self.reconciliation.differences
                ],
            },
            "invariant_results": list(self.invariant_results),
            "determinism_fingerprint": self.determinism_fingerprint,
            "result_fingerprint": self.result_fingerprint,
            "fact_counts": {
                "signals": len(self.facts.signals),
                "order_requests": len(self.facts.order_requests),
                "orders": len(self.facts.orders),
                "executions": len(self.facts.executions),
                "positions": len(self.facts.positions),
                "accounts": len(self.facts.accounts),
                "equity": len(self.facts.equity),
            },
            "diagnostics": {
                "failure_count": self.diagnostics.total_failure_count,
                "warning_count": len(self.diagnostics.warnings),
                "first_failure": (
                    None
                    if self.diagnostics.first_failure is None
                    else {
                        "stage": self.diagnostics.first_failure.stage.value,
                        "exception_type": self.diagnostics.first_failure.exception_type,
                        "message": self.diagnostics.first_failure.message,
                        "sequence": self.diagnostics.first_failure.sequence,
                    }
                ),
            },
        }
