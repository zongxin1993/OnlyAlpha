"""Formal product assembly and run plan for OnlyBacktestRuntime."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

from onlyalpha.broker.virtual import OnlyFixedCommissionModel, OnlyVirtualBrokerConfig
from onlyalpha.data.models import OnlyHistoricalBarRequest, OnlyHistoricalDataRange
from onlyalpha.data.synthetic import OnlySyntheticHistoricalDataSource
from onlyalpha.domain.enums import OnlyOrderStatus, OnlyRuntimeMode
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.execution.enums import OnlyExecutionProcessingStatus
from onlyalpha.execution.models import OnlyExecutionProcessingResult
from onlyalpha.indicator.base import OnlyIndicatorRegistration, OnlyIndicatorRequirement
from onlyalpha.indicator.macd import OnlyMacdIndicator
from onlyalpha.runtime.backtest.config import OnlyBacktestConfig, OnlyBacktestRuntimeConfig
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


class OnlyBacktestRuntimeAssembler:
    """The sole configuration-to-Runtime product assembly boundary."""

    def build(self, config: OnlyBacktestConfig) -> OnlyBacktestRuntime:
        broker_config = OnlyVirtualBrokerConfig(
            config.broker_gateway_id,
            config.account_id,
            config.base_currency,
            config.initial_cash,
            commission_model=OnlyFixedCommissionModel(config.fixed_commission),
        )
        runtime = OnlyBacktestRuntime(
            OnlyBacktestRuntimeConfig(
                config.engine_id,
                config.runtime_id,
                OnlyRuntimeMode.BACKTEST,
                default_account_id=config.account_id,
                strategy_initial_capital=config.initial_cash.amount,
                strategy_base_currency=config.base_currency,
                virtual_broker_config=broker_config,
            ),
            config.calendar,
            config.start_time,
        )
        runtime.register_instrument(config.instrument)
        runtime.register_indicator(
            OnlyIndicatorRegistration(OnlyMacdIndicator(config.macd), OnlyIndicatorRequirement.REQUIRED)
        )
        strategy = OnlyMacdExampleCluster(config.strategy)
        runtime.add_cluster(config.engine_id, strategy)
        source = OnlySyntheticHistoricalDataSource(config.synthetic_source)
        request = OnlyHistoricalBarRequest(
            f"{config.runtime_id}-synthetic-bars",
            frozenset({config.instrument.instrument_id}),
            frozenset({config.primary_bar_type}),
            OnlyHistoricalDataRange(config.start_time, config.end_time),
            config.synthetic_source.data_version,
            batch_size=config.batch_size,
        )
        plan = _OnlyBacktestRunPlan(config, runtime, source, request, strategy)
        runtime._only_bind_product_runner(plan.run)
        return runtime


class _OnlyBacktestRunPlan:
    def __init__(
        self,
        config: OnlyBacktestConfig,
        runtime: OnlyBacktestRuntime,
        source: OnlySyntheticHistoricalDataSource,
        request: OnlyHistoricalBarRequest,
        strategy: OnlyMacdExampleCluster,
    ) -> None:
        self._config = config
        self._runtime = runtime
        self._source = source
        self._request = request
        self._strategy = strategy
        self._completed = False

    def run(self) -> OnlyBacktestResult:
        if self._completed:
            raise RuntimeError("a configured Backtest Runtime can be run only once")
        self._completed = True
        self._runtime.start()
        try:
            generated = self._source.load_bars(self._request)
            replay = self._runtime.replay_historical_bars(self._source, self._request)
            if replay.failed or replay.rejected:
                raise RuntimeError(f"historical replay failed={replay.failed} rejected={replay.rejected}")
            self._runtime.drain_broker_inbound()
            result = self._build_result(len(generated.records), replay.processed, replay.duplicate, replay.gap_detected)
        finally:
            self._runtime.close()
        return result

    def _build_result(
        self,
        generated_count: int,
        processed_count: int,
        duplicate_count: int,
        gap_count: int,
    ) -> OnlyBacktestResult:
        runtime = self._runtime
        orders = runtime.order_manager.snapshot_all()
        gateway = runtime.broker_gateway
        if gateway is None:
            raise RuntimeError("product backtest requires Virtual Broker")
        trades = gateway.query_trades(self._config.account_id)
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
                OnlyTimestamp.from_datetime(self._config.start_time),
                OnlyTimestamp.from_unix_nanos(runtime.clock.timestamp_ns()),
                (self._config.strategy.cluster_id,),
            ),
            OnlyBacktestDataSummary(
                str(self._config.synthetic_source.source_id),
                str(self._config.synthetic_source.data_version),
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
                self._config.initial_cash,
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
            "NO_ACTIVE_RISK_RESERVATION": not self._runtime.risk_service.reservations.snapshot_active(),
            "NO_BLOCKING_RECONCILIATION": not blocking_execution,
        }
        failures = tuple(name for name, passed in checks.items() if not passed)
        if failures:
            raise RuntimeError(f"backtest invariant failure: {failures}")
        return tuple(f"{name}:PASS" for name in checks)
