"""Backtest-owned replay plan and deterministic result construction."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime

from onlyalpha.cluster.base import OnlyCluster, OnlyClusterState
from onlyalpha.collector import OnlyBacktestResultCollector
from onlyalpha.config import OnlyRuntimeAssemblyPlan
from onlyalpha.data.models import OnlyHistoricalBarRequest
from onlyalpha.data.ports import OnlyHistoricalDataSource
from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.identifiers import OnlyClusterId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.execution.enums import OnlyExecutionProcessingStatus
from onlyalpha.execution.models import OnlyExecutionProcessingResult
from onlyalpha.factor.snapshot import OnlyFactorSnapshot
from onlyalpha.result.fingerprint import only_result_fingerprint
from onlyalpha.runtime.backtest.result import (
    OnlyBacktestDataSummary,
    OnlyBacktestExecutionSummary,
    OnlyBacktestPerformanceSummary,
    OnlyBacktestResult,
    OnlyBacktestRunSummary,
    OnlyBacktestStatus,
    OnlyClusterResult,
)
from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime


class OnlyBacktestRunPlan:
    def __init__(
        self,
        config: OnlyRuntimeAssemblyPlan,
        source: OnlyHistoricalDataSource,
        request: OnlyHistoricalBarRequest,
        clusters: tuple[OnlyCluster, ...],
    ) -> None:
        self._config = config
        self._source = source
        self._request = request
        self._clusters = clusters
        self._completed = False

        self._runtime: OnlyBacktestRuntime | None = None
        self._collector = OnlyBacktestResultCollector()

    def execute(self, runtime: OnlyBacktestRuntime) -> OnlyBacktestResult:
        if self._completed:
            raise RuntimeError("a configured Backtest Runtime can be run only once")
        self._completed = True
        self._runtime = runtime
        self._collector.start()
        generated = self._source.load_bars(self._request)
        replay = runtime.replay_historical_bars(self._source, self._request)
        runtime.drain_broker_inbound()
        status = (
            OnlyBacktestStatus.FAILED
            if replay.failed
            or replay.rejected
            or any(cluster.state is OnlyClusterState.FAILED for cluster in self._clusters)
            else OnlyBacktestStatus.COMPLETED
        )
        return self._build_result(
            len(generated.records),
            replay.processed,
            replay.duplicate,
            replay.gap_detected,
            status,
        )

    def _build_result(
        self,
        generated_count: int,
        processed_count: int,
        duplicate_count: int,
        gap_count: int,
        status: OnlyBacktestStatus,
    ) -> OnlyBacktestResult:
        runtime = self._require_runtime()
        orders = runtime.order_manager.snapshot_all()
        account_config = self._config.accounts[0]
        positions = runtime.position_manager.snapshot_all()
        allocations = runtime.allocation_manager.snapshot_all()
        ledgers = runtime.strategy_ledger_manager.list_ledgers()
        accounts = runtime.account_manager.list_accounts()
        if len(ledgers) != len(self._clusters) or len(accounts) != 1:
            raise RuntimeError("product Backtest requires one Ledger per Cluster and one shared Account")
        account = accounts[0]
        blocking_execution = tuple(
            item
            for item in runtime.broker_results
            if isinstance(item, OnlyExecutionProcessingResult)
            and (
                item.status is OnlyExecutionProcessingStatus.FAILED
                or (
                    item.status is OnlyExecutionProcessingStatus.RECONCILIATION_REQUIRED
                    and any("ERROR" in summary for summary in item.audit_record.mutation_summary)
                )
            )
        )
        invariant_results = (
            self._invariants(account, ledgers, blocking_execution) if status is OnlyBacktestStatus.COMPLETED else ()
        )
        cluster_results = tuple(
            OnlyClusterResult(
                OnlyClusterId(cluster.config.cluster_id),
                dict(cluster.strategy.build_result_extension()),
                tuple(dict(item.to_dict()) for item in self._factor_snapshots(cluster)),
                tuple(dict(item.to_dict()) for item in cluster.indicator_snapshots),
            )
            for cluster in self._clusters
        )
        quality = tuple(
            sorted(
                {flag.value for record in runtime.market_data_audit_store.records() for flag in record.quality_flags}
            )
        )
        collected = self._collector.seal(runtime, self._clusters)
        trades = runtime.committed_execution_journal.records()
        result = OnlyBacktestResult(
            OnlyBacktestRunSummary(
                self._config.runtime_id,
                status,
                OnlyTimestamp.from_datetime(self._require_start_time()),
                OnlyTimestamp.from_unix_nanos(runtime.clock.timestamp_ns()),
                tuple(OnlyClusterId(cluster.config.cluster_id) for cluster in self._clusters),
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
            ),
            OnlyBacktestPerformanceSummary(
                account_config.initial_cash,
                account.equity,
                account.realized_pnl,
                account.unrealized_pnl,
                account.fees,
                ledgers[0].performance.return_since_start,
                ledgers[0].performance.maximum_drawdown,
            ),
            positions,
            allocations,
            ledgers,
            accounts,
            orders,
            trades,
            cluster_results,
            invariant_results,
            "",
            collected.facts,
            collected.diagnostics,
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
            "factors": (
                [dict(item.to_dict()) for item in self._factor_snapshots(self._clusters[0])]
                if len(self._clusters) == 1
                else {
                    cluster.config.cluster_id: [dict(item.to_dict()) for item in self._factor_snapshots(cluster)]
                    for cluster in self._clusters
                }
            ),
            "indicators": (
                [dict(item.to_dict()) for item in self._clusters[0].indicator_snapshots]
                if len(self._clusters) == 1
                else {
                    cluster.config.cluster_id: [dict(item.to_dict()) for item in cluster.indicator_snapshots]
                    for cluster in self._clusters
                }
            ),
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
        result = replace(result, determinism_fingerprint=fingerprint)
        result_fingerprint = only_result_fingerprint(
            {
                "facts": result.facts,
                "final_positions": result.final_positions,
                "final_allocations": result.final_allocations,
                "final_ledgers": result.final_ledgers,
                "final_accounts": result.final_accounts,
                "diagnostics": result.diagnostics,
            }
        )
        return replace(result, result_fingerprint=result_fingerprint)

    @staticmethod
    def _factor_snapshots(cluster: OnlyCluster) -> tuple[OnlyFactorSnapshot, ...]:
        result = cluster.last_pipeline_result
        return () if result is None else result.factor_snapshots

    def _invariants(
        self,
        account: object,
        ledgers: tuple[object, ...],
        blocking_execution: tuple[OnlyExecutionProcessingResult, ...],
    ) -> tuple[str, ...]:
        from onlyalpha.account.models import OnlyAccountSnapshot
        from onlyalpha.strategy_ledger.models import OnlyStrategyLedgerSnapshot

        if not isinstance(account, OnlyAccountSnapshot) or not all(
            isinstance(ledger, OnlyStrategyLedgerSnapshot) for ledger in ledgers
        ):
            raise TypeError("backtest result requires immutable Account and Ledger snapshots")
        active_risk_reservations = self._require_runtime().risk_service.reservations.snapshot_active()
        checks = {
            "ACCOUNT_EQUITY": account.equity.amount
            == account.cash.cash_balance.amount + account.position_market_value.amount,
            "LEDGER_EQUITY_VIEWS": all(
                ledger.equity.equity_by_cash_view == ledger.equity.equity_by_pnl_view
                for ledger in ledgers
                if isinstance(ledger, OnlyStrategyLedgerSnapshot)
            ),
            "NO_EXECUTION_FAILURE": not blocking_execution,
            "NO_ACTIVE_RISK_RESERVATION": not active_risk_reservations,
            "NO_BLOCKING_RECONCILIATION": not blocking_execution,
        }
        failures = tuple(name for name, passed in checks.items() if not passed)
        if failures:
            execution_failures = tuple(
                {
                    "status": item.status.value,
                    "sequence": item.sequence,
                    "update_type": item.update_type,
                    "order_id": None if item.audit_record.order_id is None else str(item.audit_record.order_id),
                    "instrument_id": None
                    if item.audit_record.instrument_id is None
                    else str(item.audit_record.instrument_id),
                    "failed_step": None if item.failure is None else item.failure.failed_step.value,
                    "exception_type": None if item.failure is None else item.failure.exception_type,
                    "message": None if item.failure is None else item.failure.message,
                    "mutation_summary": item.audit_record.mutation_summary,
                }
                for item in blocking_execution[:10]
            )
            active_reservation_samples = tuple(
                {
                    "order_id": str(item.order_id),
                    "instrument_id": str(item.instrument_id),
                    "order_status": self._require_runtime().order_manager.require_snapshot(item.order_id).status.value,
                    "reserved_quantity": str(item.reserved_quantity.value),
                    "consumed_quantity": None if item.consumed_quantity is None else str(item.consumed_quantity.value),
                }
                for item in active_risk_reservations[:10]
            )
            execution_status_samples = tuple(
                {
                    "status": item.status.value,
                    "order_id": None if item.audit_record.order_id is None else str(item.audit_record.order_id),
                    "update_type": item.update_type,
                    "mutation_summary": item.audit_record.mutation_summary,
                }
                for item in self._require_runtime().broker_results
                if isinstance(item, OnlyExecutionProcessingResult)
            )[-20:]
            raise RuntimeError(
                f"backtest invariant failure: {failures}; "
                f"execution_failure_count={len(blocking_execution)}; "
                f"execution_failure_samples={execution_failures}; "
                f"active_risk_reservation_samples={active_reservation_samples}; "
                f"execution_status_samples={execution_status_samples}"
            )
        return tuple(f"{name}:PASS" for name in checks)

    def _require_runtime(self) -> OnlyBacktestRuntime:
        if self._runtime is None:
            raise RuntimeError("Backtest RunPlan is not executing")
        return self._runtime

    def _require_start_time(self) -> datetime:
        if self._config.start_time is None:
            raise RuntimeError("BACKTEST requires runtime.start_time")
        return self._config.start_time
