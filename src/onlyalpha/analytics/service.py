"""Pure deterministic analytics service."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import cast

from onlyalpha.analytics.models import (
    OnlyBacktestAnalysis,
    OnlyClusterAnalysis,
    OnlyDrawdownAnalysis,
    OnlyDrawdownPoint,
    OnlyExecutionAnalysis,
    OnlyExposureAnalysis,
    OnlyOrderAnalysis,
    OnlyPerformanceAnalysis,
    OnlyTradeAnalysis,
    OnlyTradeRecord,
)
from onlyalpha.analytics.ports import OnlyBacktestResultView, OnlyClusterResultView
from onlyalpha.analytics.trade_builder import OnlyTradeBuilder, OnlyTradeMatchingPolicy
from onlyalpha.result.fingerprint import only_result_fingerprint
from onlyalpha.result.records import OnlyExecutionResultRecord
from onlyalpha.strategy_ledger.models import OnlyStrategyLedgerEquityPoint


class OnlyBacktestAnalyticsService:
    def analyze(self, result: OnlyBacktestResultView) -> OnlyBacktestAnalysis:
        warnings: list[str] = []
        build = OnlyTradeBuilder().build(result.facts.executions, OnlyTradeMatchingPolicy.FIFO)
        warnings.extend(build.warnings)
        trades = self._trades(build.trades, warnings)
        performance = self._performance(result, warnings)
        drawdown = self._drawdown(result, warnings)
        orders = self._orders(result)
        executions = self._executions(result, warnings)
        exposure = self._exposure(result, warnings)
        cluster_analyses = self._clusters(result)
        projection = {
            "result_fingerprint": result.result_fingerprint,
            "analytics_schema_version": 2,
            "trade_matching_policy": OnlyTradeMatchingPolicy.FIFO.value,
            "performance": performance,
            "trades": trades,
            "drawdown": drawdown,
            "orders": orders,
            "executions": executions,
            "exposure": exposure,
            "cluster_analyses": cluster_analyses,
            "warnings": tuple(sorted(set(warnings))),
        }
        fingerprint = only_result_fingerprint(projection)
        return OnlyBacktestAnalysis(
            performance,
            trades,
            drawdown,
            orders,
            executions,
            exposure,
            cluster_analyses,
            tuple(sorted(set(warnings))),
            fingerprint,
        )

    @staticmethod
    def _performance(result: OnlyBacktestResultView, warnings: list[str]) -> OnlyPerformanceAnalysis:
        initial = result.runtime_performance.initial_equity.amount
        ending = result.runtime_performance.final_equity.amount
        currencies = {
            result.runtime_performance.initial_equity.currency.code,
            result.runtime_performance.final_equity.currency.code,
        }
        currency = next(iter(currencies)) if len(currencies) == 1 else None
        if currency is None:
            warnings.append("MULTI_CURRENCY_AGGREGATION_UNAVAILABLE")
        total_return = (
            None
            if result.runtime_performance.return_since_start is None
            else result.runtime_performance.return_since_start.value
        )
        warnings.extend(result.runtime_performance.quality_flags)
        return OnlyPerformanceAnalysis(currency, initial, ending, ending - initial, total_return)

    @staticmethod
    def _trades(trades: tuple[OnlyTradeRecord, ...], warnings: list[str]) -> OnlyTradeAnalysis:
        pnl = tuple(item.net_pnl for item in trades)
        wins = tuple(value for value in pnl if value > 0)
        losses = tuple(value for value in pnl if value < 0)
        breakeven = tuple(value for value in pnl if value == 0)
        count = len(trades)
        if wins and not losses:
            warnings.append("NO_GROSS_LOSS")
        durations = tuple(item.holding_duration for item in trades)
        return OnlyTradeAnalysis(
            trades,
            count,
            len(wins),
            len(losses),
            len(breakeven),
            None if count == 0 else Decimal(len(wins)) / Decimal(count),
            sum(wins, Decimal(0)),
            sum(losses, Decimal(0)),
            sum(pnl, Decimal(0)),
            None if count == 0 else sum(pnl, Decimal(0)) / Decimal(count),
            None if not wins else sum(wins, Decimal(0)) / Decimal(len(wins)),
            None if not losses else sum(losses, Decimal(0)) / Decimal(len(losses)),
            None if not wins else max(wins),
            None if not losses else min(losses),
            None if not losses else sum(wins, Decimal(0)) / abs(sum(losses, Decimal(0))),
            None if not durations else sum(durations, timedelta()) / len(durations),
            None if not durations else max(durations),
        )

    @staticmethod
    def _drawdown(result: OnlyBacktestResultView, warnings: list[str]) -> OnlyDrawdownAnalysis:
        equity = result.account_equity_timeline
        if len(equity) < 2:
            warnings.append("INSUFFICIENT_EQUITY_CURVE")
        points: list[OnlyDrawdownPoint] = []
        peak: Decimal | None = None
        peak_time = None
        worst: OnlyDrawdownPoint | None = None
        worst_peak_time = None
        recovery_time = None
        for item in equity:
            value = item.equity.amount
            if peak is None or value > peak:
                peak = value
                peak_time = item.ts_event.to_datetime()
            amount = value - peak
            ratio = None if peak == 0 else value / peak - Decimal(1)
            point = OnlyDrawdownPoint(item.ts_event.to_datetime(), value, peak, amount, ratio)
            points.append(point)
            if worst is None or amount < worst.drawdown_amount:
                worst = point
                worst_peak_time = peak_time
                recovery_time = None
            elif worst.drawdown_amount < 0 and recovery_time is None and value >= worst.running_peak:
                recovery_time = item.ts_event.to_datetime()
        if worst is None:
            return OnlyDrawdownAnalysis((), None, None, None, None, None, None, None)
        recovered = None if worst.drawdown_amount == 0 else recovery_time is not None
        return OnlyDrawdownAnalysis(
            tuple(points),
            worst.drawdown_amount,
            worst.drawdown_ratio,
            worst_peak_time,
            worst.ts_event,
            recovery_time,
            recovered,
            points[-1].drawdown_amount,
        )

    @staticmethod
    def _orders(result: OnlyBacktestResultView) -> OnlyOrderAnalysis:
        records = result.facts.orders
        statuses = tuple(item.status for item in records)
        terminal = {"FILLED", "REJECTED", "CANCELLED", "EXPIRED", "FAILED"}
        return OnlyOrderAnalysis(
            len(statuses),
            sum(item.accepted_at is not None for item in records),
            statuses.count("REJECTED"),
            statuses.count("CANCELLED"),
            statuses.count("EXPIRED"),
            statuses.count("FILLED"),
            statuses.count("PARTIALLY_FILLED"),
            sum(item not in terminal for item in statuses),
        )

    @staticmethod
    def _executions(result: OnlyBacktestResultView, warnings: list[str]) -> OnlyExecutionAnalysis:
        executions = result.facts.executions
        buys = tuple(item for item in executions if item.side == "BUY")
        sells = tuple(item for item in executions if item.side == "SELL")
        buy_turnover = sum((item.turnover for item in buys), Decimal(0))
        sell_turnover = sum((item.turnover for item in sells), Decimal(0))
        if any(item.slippage is None for item in executions):
            warnings.append("UNKNOWN_EXECUTION_SLIPPAGE")
        return OnlyExecutionAnalysis(
            len(executions),
            len(buys),
            len(sells),
            sum((item.quantity for item in buys), Decimal(0)),
            sum((item.quantity for item in sells), Decimal(0)),
            buy_turnover,
            sell_turnover,
            buy_turnover + sell_turnover,
            sum((item.commission for item in executions), Decimal(0)),
            sum((item.fees for item in executions), Decimal(0)),
            sum((item.slippage for item in executions if item.slippage is not None), Decimal(0)),
        )

    @staticmethod
    def _exposure(result: OnlyBacktestResultView, warnings: list[str]) -> OnlyExposureAnalysis:
        records = tuple(
            item for item in result.facts.equity if item.gross_exposure is not None and item.net_exposure is not None
        )
        if not records:
            warnings.append("EXPOSURE_UNAVAILABLE")
            return OnlyExposureAnalysis(None, None, None, None, None)
        gross = tuple(item.gross_exposure for item in records if item.gross_exposure is not None)
        net = tuple(item.net_exposure for item in records if item.net_exposure is not None)
        return OnlyExposureAnalysis(
            max(gross),
            sum(gross, Decimal(0)) / Decimal(len(gross)),
            max(net),
            sum(net, Decimal(0)) / Decimal(len(net)),
            Decimal(sum(item > 0 for item in gross)) / Decimal(len(gross)),
        )

    def _clusters(self, result: OnlyBacktestResultView) -> tuple[OnlyClusterAnalysis, ...]:
        timelines: dict[str, tuple[OnlyStrategyLedgerEquityPoint, ...]] = {}
        for timeline in result.cluster_equity_timelines:
            if not timeline:
                continue
            cluster_id = str(timeline[0].key.cluster_id)
            if cluster_id in timelines:
                raise ValueError(f"duplicate Cluster equity timeline: {cluster_id}")
            if any(str(point.key.cluster_id) != cluster_id for point in timeline):
                raise ValueError(f"mixed Cluster equity timeline: {cluster_id}")
            timelines[cluster_id] = timeline
        analyses: list[OnlyClusterAnalysis] = []
        cluster_results = tuple(cast(OnlyClusterResultView, item) for item in result.cluster_results)
        for cluster_result in sorted(cluster_results, key=lambda item: str(item.cluster_id)):
            cluster_id = str(cluster_result.cluster_id)
            performance = cluster_result.performance
            cluster_timeline = timelines.get(cluster_id)
            if cluster_timeline is None:
                raise ValueError(f"missing Cluster equity timeline: {cluster_id}")
            executions = tuple(item for item in result.facts.executions if item.cluster_id == cluster_id)
            cluster_warnings: list[str] = list(performance.quality_flags)
            build = OnlyTradeBuilder().build(executions, OnlyTradeMatchingPolicy.FIFO)
            cluster_warnings.extend(build.warnings)
            trades = self._trades(build.trades, cluster_warnings)
            execution_analysis = self._execution_records(executions, cluster_warnings)
            points: list[OnlyDrawdownPoint] = []
            peak: Decimal | None = None
            for item in cluster_timeline:
                peak = item.equity.amount if peak is None else max(peak, item.equity.amount)
                amount = item.equity.amount - peak
                ratio = None if peak == 0 else item.equity.amount / peak - Decimal(1)
                points.append(OnlyDrawdownPoint(item.ts_event.to_datetime(), item.equity.amount, peak, amount, ratio))
            drawdown = OnlyDrawdownAnalysis(
                tuple(points),
                None if not points else min(item.drawdown_amount for item in points),
                performance.maximum_drawdown.value,
                None,
                None,
                None,
                None,
                None if not points else points[-1].drawdown_amount,
            )
            market_values = tuple(item.position_market_value.amount for item in cluster_timeline)
            exposure = OnlyExposureAnalysis(
                max(market_values),
                sum(market_values, Decimal(0)) / Decimal(len(market_values)),
                max(market_values),
                sum(market_values, Decimal(0)) / Decimal(len(market_values)),
                Decimal(sum(item != 0 for item in market_values)) / Decimal(len(market_values)),
            )
            analyses.append(
                OnlyClusterAnalysis(
                    cluster_id,
                    str(performance.ledger_id),
                    OnlyPerformanceAnalysis(
                        performance.currency.code,
                        performance.initial_equity.amount,
                        performance.final_equity.amount,
                        performance.net_pnl.amount,
                        None if performance.return_since_start is None else performance.return_since_start.value,
                    ),
                    trades,
                    drawdown,
                    execution_analysis,
                    exposure,
                    performance.net_pnl.amount,
                    tuple(sorted(set(cluster_warnings))),
                )
            )
        return tuple(analyses)

    @staticmethod
    def _execution_records(
        executions: tuple[OnlyExecutionResultRecord, ...], warnings: list[str]
    ) -> OnlyExecutionAnalysis:
        buys = tuple(item for item in executions if item.side == "BUY")
        sells = tuple(item for item in executions if item.side == "SELL")
        buy_turnover = sum((item.turnover for item in buys), Decimal(0))
        sell_turnover = sum((item.turnover for item in sells), Decimal(0))
        if any(item.slippage is None for item in executions):
            warnings.append("UNKNOWN_EXECUTION_SLIPPAGE")
        return OnlyExecutionAnalysis(
            len(executions),
            len(buys),
            len(sells),
            sum((item.quantity for item in buys), Decimal(0)),
            sum((item.quantity for item in sells), Decimal(0)),
            buy_turnover,
            sell_turnover,
            buy_turnover + sell_turnover,
            sum((item.commission for item in executions), Decimal(0)),
            sum((item.fees for item in executions), Decimal(0)),
            sum((item.slippage for item in executions if item.slippage is not None), Decimal(0)),
        )
