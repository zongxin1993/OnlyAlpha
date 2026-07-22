"""Immutable product backtest result and deterministic exporters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.account.models import OnlyAccountSnapshot
from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyClusterId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMoney, OnlyRate
from onlyalpha.execution.committed import OnlyCommittedExecutionFact
from onlyalpha.position.models import OnlyPositionAllocationSnapshot, OnlyPositionSnapshot
from onlyalpha.result.diagnostics import OnlyBacktestDiagnostics
from onlyalpha.result.records import OnlyBacktestFacts
from onlyalpha.strategy_ledger.models import OnlyStrategyLedgerSnapshot


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
class OnlyClusterResult:
    cluster_id: OnlyClusterId
    strategy_result_extension: dict[str, object]
    factor_results: tuple[dict[str, object], ...]
    indicator_diagnostics: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class OnlyBacktestPerformanceSummary:
    initial_equity: OnlyMoney
    final_equity: OnlyMoney
    realized_pnl: OnlyMoney
    unrealized_pnl: OnlyMoney
    fees: OnlyMoney
    return_since_start: OnlyRate | None
    maximum_drawdown: OnlyRate


@dataclass(frozen=True, slots=True)
class OnlyBacktestResult:
    run: OnlyBacktestRunSummary
    data: OnlyBacktestDataSummary
    execution: OnlyBacktestExecutionSummary
    performance: OnlyBacktestPerformanceSummary
    final_positions: tuple[OnlyPositionSnapshot, ...]
    final_allocations: tuple[OnlyPositionAllocationSnapshot, ...]
    final_ledgers: tuple[OnlyStrategyLedgerSnapshot, ...]
    final_accounts: tuple[OnlyAccountSnapshot, ...]
    orders: tuple[OnlyOrderSnapshot, ...]
    trades: tuple[OnlyCommittedExecutionFact, ...]
    cluster_results: tuple[OnlyClusterResult, ...]
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
            "schema_version": 2,
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
            "performance": {
                "initial_equity": self.performance.initial_equity.to_dict(),
                "final_equity": self.performance.final_equity.to_dict(),
                "realized_pnl": self.performance.realized_pnl.to_dict(),
                "unrealized_pnl": self.performance.unrealized_pnl.to_dict(),
                "fees": self.performance.fees.to_dict(),
                "return_since_start": (
                    None
                    if self.performance.return_since_start is None
                    else self.performance.return_since_start.to_dict()
                ),
                "maximum_drawdown": self.performance.maximum_drawdown.to_dict(),
            },
            "final_positions": [item.to_dict() for item in self.final_positions],
            "final_allocations": [item.to_dict() for item in self.final_allocations],
            "final_ledgers": [item.to_dict() for item in self.final_ledgers],
            "final_accounts": [item.to_dict() for item in self.final_accounts],
            "orders": [item.to_dict() for item in self.orders],
            "trades": [item.to_dict() for item in self.trades],
            "cluster_results": [
                {
                    "cluster_id": str(item.cluster_id),
                    "strategy_result_extension": item.strategy_result_extension,
                    "factor_results": list(item.factor_results),
                    "indicator_diagnostics": list(item.indicator_diagnostics),
                }
                for item in self.cluster_results
            ],
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
