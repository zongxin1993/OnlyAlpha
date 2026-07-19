"""Pure deterministic analytics service."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from onlyalpha.analytics.models import (
    OnlyBacktestAnalysis,
    OnlyDrawdownAnalysis,
    OnlyDrawdownPoint,
    OnlyExecutionAnalysis,
    OnlyExposureAnalysis,
    OnlyOrderAnalysis,
    OnlyPerformanceAnalysis,
    OnlyTradeAnalysis,
    OnlyTradeRecord,
)
from onlyalpha.analytics.ports import OnlyBacktestResultView
from onlyalpha.analytics.trade_builder import OnlyTradeBuilder, OnlyTradeMatchingPolicy
from onlyalpha.result.fingerprint import only_result_fingerprint


class OnlyBacktestAnalyticsService:
    def analyze(self, result: OnlyBacktestResultView) -> OnlyBacktestAnalysis:
        warnings: list[str] = []
        build = OnlyTradeBuilder().build(result.facts.executions, OnlyTradeMatchingPolicy.FIFO)
        warnings.extend(build.warnings)
        trades = self._trades(build.trades, warnings)
        performance = self._performance(result, warnings)
        drawdown = self._drawdown(result, warnings)
        orders = self._orders(result)
        executions = self._executions(result)
        exposure = self._exposure(result, warnings)
        projection = {
            "result_fingerprint": result.result_fingerprint,
            "analytics_schema_version": 1,
            "trade_matching_policy": OnlyTradeMatchingPolicy.FIFO.value,
            "performance": performance,
            "trades": trades,
            "drawdown": drawdown,
            "orders": orders,
            "executions": executions,
            "exposure": exposure,
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
            tuple(sorted(set(warnings))),
            fingerprint,
        )

    @staticmethod
    def _performance(result: OnlyBacktestResultView, warnings: list[str]) -> OnlyPerformanceAnalysis:
        initial = result.performance.initial_equity.amount
        ending = result.performance.final_equity.amount
        currencies = {
            result.performance.initial_equity.currency.code,
            result.performance.final_equity.currency.code,
        }
        currency = next(iter(currencies)) if len(currencies) == 1 else None
        if currency is None:
            warnings.append("MULTI_CURRENCY_AGGREGATION_UNAVAILABLE")
        total_return = None if initial == 0 else ending / initial - Decimal(1)
        if initial == 0:
            warnings.append("ZERO_INITIAL_EQUITY")
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
        equity = tuple(item for item in result.facts.equity if item.equity is not None)
        if len(equity) < 2:
            warnings.append("INSUFFICIENT_EQUITY_CURVE")
        points: list[OnlyDrawdownPoint] = []
        peak: Decimal | None = None
        peak_time = None
        worst: OnlyDrawdownPoint | None = None
        worst_peak_time = None
        recovery_time = None
        for item in equity:
            assert item.equity is not None
            if peak is None or item.equity > peak:
                peak = item.equity
                peak_time = item.ts_event
            amount = item.equity - peak
            ratio = None if peak == 0 else item.equity / peak - Decimal(1)
            point = OnlyDrawdownPoint(item.ts_event, item.equity, peak, amount, ratio)
            points.append(point)
            if worst is None or amount < worst.drawdown_amount:
                worst = point
                worst_peak_time = peak_time
                recovery_time = None
            elif worst.drawdown_amount < 0 and recovery_time is None and item.equity >= worst.running_peak:
                recovery_time = item.ts_event
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
    def _executions(result: OnlyBacktestResultView) -> OnlyExecutionAnalysis:
        executions = result.facts.executions
        buys = tuple(item for item in executions if item.side == "BUY")
        sells = tuple(item for item in executions if item.side == "SELL")
        buy_turnover = sum((item.turnover for item in buys), Decimal(0))
        sell_turnover = sum((item.turnover for item in sells), Decimal(0))
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
            sum((item.slippage for item in executions), Decimal(0)),
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
