"""Immutable product backtest result and deterministic exporters."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from onlyalpha.account.models import OnlyAccountSnapshot
from onlyalpha.broker.models import OnlyBrokerTradeSnapshot
from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyClusterId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMoney, OnlyRate
from onlyalpha.position.models import OnlyPositionAllocationSnapshot, OnlyPositionSnapshot
from onlyalpha.strategies.macd import OnlyMacdSignal
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
    golden_cross_count: int
    death_cross_count: int
    blocked_t1_exit_count: int


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
    trades: tuple[OnlyBrokerTradeSnapshot, ...]
    signals: tuple[OnlyMacdSignal, ...]
    invariant_results: tuple[str, ...]
    determinism_fingerprint: str

    @property
    def status(self) -> OnlyBacktestStatus:
        return self.run.status

    @property
    def runtime_id(self) -> OnlyRuntimeId:
        return self.run.runtime_id

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
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
                "golden_cross_count": self.execution.golden_cross_count,
                "death_cross_count": self.execution.death_cross_count,
                "blocked_t1_exit_count": self.execution.blocked_t1_exit_count,
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
            "signals": [
                {
                    "sequence": item.sequence,
                    "signal_type": item.signal_type,
                    "ts_event_ns": item.ts_event.unix_nanos,
                    "dif": item.dif,
                    "dea": item.dea,
                    "order_request_id": None if item.order_request_id is None else str(item.order_request_id),
                }
                for item in self.signals
            ],
            "invariant_results": list(self.invariant_results),
            "determinism_fingerprint": self.determinism_fingerprint,
        }

    def save(self, output: str | Path) -> None:
        """Write the stable public result set without Manager access."""

        output_path = Path(output)
        output_path.mkdir(parents=True, exist_ok=True)
        self._write_json(output_path / "result.json", self.to_dict())
        self._write_json(output_path / "orders.json", [item.to_dict() for item in self.orders])
        self._write_json(output_path / "trades.json", [item.to_dict() for item in self.trades])
        self._write_json(output_path / "positions.json", [item.to_dict() for item in self.final_positions])
        self._write_json(output_path / "allocations.json", [item.to_dict() for item in self.final_allocations])
        self._write_json(output_path / "ledgers.json", [item.to_dict() for item in self.final_ledgers])
        self._write_json(output_path / "accounts.json", [item.to_dict() for item in self.final_accounts])
        with (output_path / "equity.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(("point", "equity", "currency"))
            writer.writerow(
                ("initial", self.performance.initial_equity.amount, self.performance.initial_equity.currency.code)
            )
            writer.writerow(
                ("final", self.performance.final_equity.amount, self.performance.final_equity.currency.code)
            )
        (output_path / "run_report.md").write_text(self._markdown_report(), encoding="utf-8")

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    def _markdown_report(self) -> str:
        return "\n".join(
            (
                "# OnlyAlpha MACD Backtest Run",
                "",
                f"- Status: {self.status.value}",
                f"- Runtime: {self.runtime_id}",
                f"- Bars: {self.data.processed_bar_count}",
                f"- Orders: {self.execution.order_count}",
                f"- Trades: {self.execution.trade_count}",
                f"- Final equity: {self.performance.final_equity.amount} {self.performance.final_equity.currency.code}",
                f"- Fingerprint: `{self.determinism_fingerprint}`",
                f"- Invariants: {', '.join(self.invariant_results)}",
                "",
            )
        )
