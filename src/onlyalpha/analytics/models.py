"""Immutable analytics outputs; values remain Decimal and provider-neutral."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class OnlyTradeRecord:
    trade_id: str
    cluster_id: str
    strategy_id: str
    account_id: str
    instrument_id: str
    direction: str
    quantity: Decimal
    entry_time: datetime
    exit_time: datetime
    entry_price: Decimal
    exit_price: Decimal
    gross_pnl: Decimal
    commission: Decimal
    fees: Decimal
    net_pnl: Decimal
    holding_duration: timedelta
    entry_execution_id: str
    exit_execution_id: str
    entry_order_id: str
    exit_order_id: str


@dataclass(frozen=True, slots=True)
class OnlyTradeAnalysis:
    trades: tuple[OnlyTradeRecord, ...]
    trade_count: int
    winning_trade_count: int
    losing_trade_count: int
    breakeven_trade_count: int
    win_rate: Decimal | None
    gross_profit: Decimal
    gross_loss: Decimal
    net_trade_pnl: Decimal
    average_trade_pnl: Decimal | None
    average_win: Decimal | None
    average_loss: Decimal | None
    largest_win: Decimal | None
    largest_loss: Decimal | None
    profit_factor: Decimal | None
    average_holding_duration: timedelta | None
    maximum_holding_duration: timedelta | None


@dataclass(frozen=True, slots=True)
class OnlyPerformanceAnalysis:
    currency: str | None
    initial_equity: Decimal
    ending_equity: Decimal
    net_profit: Decimal
    total_return: Decimal | None
    annualized_return: None = None
    annualized_volatility: None = None
    sharpe_ratio: None = None
    sortino_ratio: None = None
    calmar_ratio: None = None


@dataclass(frozen=True, slots=True)
class OnlyDrawdownPoint:
    ts_event: datetime
    equity: Decimal
    running_peak: Decimal
    drawdown_amount: Decimal
    drawdown_ratio: Decimal | None


@dataclass(frozen=True, slots=True)
class OnlyDrawdownAnalysis:
    points: tuple[OnlyDrawdownPoint, ...]
    max_drawdown_amount: Decimal | None
    max_drawdown_ratio: Decimal | None
    max_drawdown_peak_time: datetime | None
    max_drawdown_trough_time: datetime | None
    recovery_time: datetime | None
    recovered: bool | None
    current_drawdown: Decimal | None


@dataclass(frozen=True, slots=True)
class OnlyOrderAnalysis:
    submitted_count: int
    accepted_count: int
    rejected_count: int
    cancelled_count: int
    expired_count: int
    filled_count: int
    partially_filled_count: int
    open_count: int


@dataclass(frozen=True, slots=True)
class OnlyExecutionAnalysis:
    execution_count: int
    buy_execution_count: int
    sell_execution_count: int
    buy_quantity: Decimal
    sell_quantity: Decimal
    buy_turnover: Decimal
    sell_turnover: Decimal
    gross_turnover: Decimal
    commission: Decimal
    fees: Decimal
    slippage_cost: Decimal


@dataclass(frozen=True, slots=True)
class OnlyExposureAnalysis:
    maximum_gross_exposure: Decimal | None
    average_gross_exposure: Decimal | None
    maximum_net_exposure: Decimal | None
    average_net_exposure: Decimal | None
    time_in_market_ratio: Decimal | None


@dataclass(frozen=True, slots=True)
class OnlyBacktestAnalysis:
    performance: OnlyPerformanceAnalysis
    trades: OnlyTradeAnalysis
    drawdown: OnlyDrawdownAnalysis
    orders: OnlyOrderAnalysis
    executions: OnlyExecutionAnalysis
    exposure: OnlyExposureAnalysis
    warnings: tuple[str, ...]
    analysis_fingerprint: str
