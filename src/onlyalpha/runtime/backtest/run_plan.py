"""Backtest-owned replay plan and deterministic result construction."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime

from onlyalpha.config import OnlyRunConfig
from onlyalpha.data.models import OnlyHistoricalBarRequest
from onlyalpha.data.ports import OnlyHistoricalDataSource
from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.execution.enums import OnlyExecutionProcessingStatus
from onlyalpha.execution.models import OnlyExecutionProcessingResult
from onlyalpha.runtime.backtest.result import (
    OnlyBacktestDataSummary,
    OnlyBacktestExecutionSummary,
    OnlyBacktestPerformanceSummary,
    OnlyBacktestResult,
    OnlyBacktestRunSummary,
    OnlyBacktestStatus,
)
from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime
from onlyalpha.strategies.macd import OnlyMacdExampleCluster


class OnlyBacktestRunPlan:
    def __init__(
        self,
        config: OnlyRunConfig,
        source: OnlyHistoricalDataSource,
        request: OnlyHistoricalBarRequest,
        strategy: OnlyMacdExampleCluster,
    ) -> None:
        self._config = config
        self._source = source
        self._request = request
        self._strategy = strategy
        self._completed = False

        self._runtime: OnlyBacktestRuntime | None = None

    def execute(self, runtime: OnlyBacktestRuntime) -> OnlyBacktestResult:
        if self._completed:
            raise RuntimeError("a configured Backtest Runtime can be run only once")
        self._completed = True
        self._runtime = runtime
        runtime.start()
        try:
            generated = self._source.load_bars(self._request)
            replay = runtime.replay_historical_bars(self._source, self._request)
            if replay.failed or replay.rejected:
                raise RuntimeError(f"historical replay failed={replay.failed} rejected={replay.rejected}")
            runtime.drain_broker_inbound()
            result = self._build_result(len(generated.records), replay.processed, replay.duplicate, replay.gap_detected)
        finally:
            runtime.close()
        return result

    def _build_result(
        self,
        generated_count: int,
        processed_count: int,
        duplicate_count: int,
        gap_count: int,
    ) -> OnlyBacktestResult:
        runtime = self._require_runtime()
        orders = runtime.order_manager.snapshot_all()
        gateway = runtime.broker_gateway
        if gateway is None:
            raise RuntimeError("product backtest requires Virtual Broker")
        account_config = self._config.accounts[0]
        trades = gateway.query_trades(account_config.account_id)
        positions = runtime.position_manager.snapshot_all()
        allocations = runtime.allocation_manager.snapshot_all()
        ledgers = runtime.strategy_ledger_manager.list_ledgers()
        accounts = runtime.account_manager.list_accounts()
        if len(ledgers) != 1 or len(accounts) != 1:
            raise RuntimeError("single-cluster product demo requires one Ledger and one Account")
        ledger = ledgers[0]
        account = accounts[0]
        blocking_execution = tuple(
            item
            for item in runtime.broker_results
            if isinstance(item, OnlyExecutionProcessingResult)
            and (
                item.status is OnlyExecutionProcessingStatus.FAILED
                or (
                    item.status is OnlyExecutionProcessingStatus.RECONCILIATION_REQUIRED
                    and "WARNING" not in item.audit_record.mutation_summary
                )
            )
        )
        invariant_results = self._invariants(account, ledger, blocking_execution)
        signals = self._strategy.signals
        quality = tuple(
            sorted(
                {flag.value for record in runtime.market_data_audit_store.records() for flag in record.quality_flags}
            )
        )
        result = OnlyBacktestResult(
            OnlyBacktestRunSummary(
                self._config.runtime_id,
                OnlyBacktestStatus.COMPLETED,
                OnlyTimestamp.from_datetime(self._require_start_time()),
                OnlyTimestamp.from_unix_nanos(runtime.clock.timestamp_ns()),
                (self._strategy.strategy_config.cluster_id,),
            ),
            OnlyBacktestDataSummary(
                str(self._source.source_id),
                str(self._config.data_sources[0].data_version),
                generated_count,
                processed_count,
                duplicate_count,
                gap_count,
                quality,
            ),
            OnlyBacktestExecutionSummary(
                len(orders),
                sum(item.status is OnlyOrderStatus.REJECTED for item in orders),
                len(trades),
                sum(item.signal_type == "GOLDEN_CROSS" for item in signals),
                sum(item.signal_type in {"DEATH_CROSS", "PENDING_EXIT"} for item in signals),
                sum(item.signal_type == "DEATH_CROSS_BLOCKED" for item in signals),
            ),
            OnlyBacktestPerformanceSummary(
                account_config.initial_cash,
                account.equity,
                account.realized_pnl,
                account.unrealized_pnl,
                account.fees,
                ledger.performance.return_since_start,
                ledger.performance.maximum_drawdown,
            ),
            positions,
            allocations,
            ledgers,
            accounts,
            orders,
            trades,
            signals,
            invariant_results,
            "",
        )
        projection = result.to_dict()
        projection["determinism_fingerprint"] = ""
        projection["determinism_trace"] = {
            "market_data": [
                (
                    item.audit_id,
                    str(item.update_id),
                    item.source_sequence,
                    item.processing_sequence,
                    item.status.value,
                    item.ts_event.unix_nanos,
                    tuple(sorted(flag.value for flag in item.quality_flags)),
                )
                for item in runtime.market_data_audit_store.records()
            ],
            "clock": [
                (item.index, str(item.update.update_id), item.clock_time_ns, item.result.status.value)
                for item in runtime.historical_replay_service.events
            ],
            "macd": [dict(item.to_dict()) for item in self._strategy.macd_trace],
            "execution": [item.to_dict() for item in runtime.execution_audit_store.records()],
            "events": [
                (
                    str(item.event.event_type),
                    str(item.event.source),
                    int(item.event.sequence),
                    item.event.timestamp_ns,
                    None if item.event.cluster_id is None else str(item.event.cluster_id),
                )
                for item in runtime.event_bus.dispatch_results
            ],
        }
        fingerprint = hashlib.sha256(
            json.dumps(projection, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return replace(result, determinism_fingerprint=fingerprint)

    def _invariants(
        self,
        account: object,
        ledger: object,
        blocking_execution: tuple[OnlyExecutionProcessingResult, ...],
    ) -> tuple[str, ...]:
        from onlyalpha.account.models import OnlyAccountSnapshot
        from onlyalpha.strategy_ledger.models import OnlyStrategyLedgerSnapshot

        if not isinstance(account, OnlyAccountSnapshot) or not isinstance(ledger, OnlyStrategyLedgerSnapshot):
            raise TypeError("backtest result requires immutable Account and Ledger snapshots")
        checks = {
            "ACCOUNT_EQUITY": account.equity.amount
            == account.cash.cash_balance.amount + account.position_market_value.amount,
            "LEDGER_EQUITY_VIEWS": ledger.equity.equity_by_cash_view == ledger.equity.equity_by_pnl_view,
            "NO_EXECUTION_FAILURE": not blocking_execution,
            "NO_ACTIVE_RISK_RESERVATION": not self._require_runtime().risk_service.reservations.snapshot_active(),
            "NO_BLOCKING_RECONCILIATION": not blocking_execution,
        }
        failures = tuple(name for name, passed in checks.items() if not passed)
        if failures:
            raise RuntimeError(f"backtest invariant failure: {failures}")
        return tuple(f"{name}:PASS" for name in checks)

    def _require_runtime(self) -> OnlyBacktestRuntime:
        if self._runtime is None:
            raise RuntimeError("Backtest RunPlan is not executing")
        return self._runtime

    def _require_start_time(self) -> datetime:
        if self._config.start_time is None:
            raise RuntimeError("BACKTEST requires runtime.start_time")
        return self._config.start_time
