from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from onlyalpha.analytics import OnlyBacktestAnalyticsService
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.result.records import (
    OnlyBacktestFacts,
    OnlyEquityResultRecord,
    OnlyExecutionResultRecord,
    OnlyOrderResultRecord,
)


@dataclass(frozen=True)
class OnlyPerformanceFixture:
    initial_equity: OnlyMoney
    final_equity: OnlyMoney


@dataclass(frozen=True)
class OnlyResultFixture:
    facts: OnlyBacktestFacts
    performance: OnlyPerformanceFixture
    result_fingerprint: str


def _equity(sequence: int, value: str) -> OnlyEquityResultRecord:
    return OnlyEquityResultRecord(
        sequence=sequence,
        ts_event=datetime(2026, 1, sequence, tzinfo=UTC),
        trading_day=date(2026, 1, sequence),
        runtime_id="runtime-1",
        account_id="account-1",
        cluster_id=None,
        currency="CNY",
        cash=Decimal(value),
        market_value=Decimal("0"),
        equity=Decimal(value),
        realized_pnl=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        commission=Decimal("0"),
        fees=Decimal("0"),
        gross_exposure=Decimal("0"),
        net_exposure=Decimal("0"),
        position_count=0,
        complete=True,
    )


def test_analysis_calculates_return_and_recovered_drawdown() -> None:
    currency = OnlyCurrency("CNY", 2)
    result = OnlyResultFixture(
        OnlyBacktestFacts(equity=(_equity(1, "100"), _equity(2, "80"), _equity(3, "110"))),
        OnlyPerformanceFixture(OnlyMoney(Decimal("100"), currency), OnlyMoney(Decimal("110"), currency)),
        "result-fingerprint",
    )

    analysis = OnlyBacktestAnalyticsService().analyze(result)

    assert analysis.performance.net_profit == Decimal("10")
    assert analysis.performance.total_return == Decimal("0.1")
    assert analysis.drawdown.max_drawdown_amount == Decimal("-20")
    assert analysis.drawdown.max_drawdown_ratio == Decimal("-0.2")
    assert analysis.drawdown.recovered is True
    assert analysis.drawdown.recovery_time == datetime(2026, 1, 3, tzinfo=UTC)
    assert analysis.trades.trade_count == 0
    assert analysis.analysis_fingerprint


def test_analysis_zero_initial_equity_and_single_snapshot_are_explicit() -> None:
    currency = OnlyCurrency("CNY", 2)
    result = OnlyResultFixture(
        OnlyBacktestFacts(equity=(_equity(1, "0"),)),
        OnlyPerformanceFixture(OnlyMoney(Decimal("0"), currency), OnlyMoney(Decimal("0"), currency)),
        "result-fingerprint",
    )

    analysis = OnlyBacktestAnalyticsService().analyze(result)

    assert analysis.performance.total_return is None
    assert "ZERO_INITIAL_EQUITY" in analysis.warnings
    assert "INSUFFICIENT_EQUITY_CURVE" in analysis.warnings


def test_order_and_execution_statistics_use_formal_facts() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    order = OnlyOrderResultRecord(
        sequence=1,
        order_id="order-1",
        request_id="request-1",
        runtime_id="runtime-1",
        cluster_id="cluster-1",
        strategy_id="strategy-1",
        account_id="account-1",
        instrument_id="TEST.XSHG",
        side="BUY",
        offset="OPEN",
        order_type="MARKET",
        requested_quantity=Decimal("10"),
        filled_quantity=Decimal("10"),
        remaining_quantity=Decimal("0"),
        status="FILLED",
        submitted_at=now,
        accepted_at=now,
        completed_at=now,
    )
    execution = OnlyExecutionResultRecord(
        sequence=2,
        execution_id="execution-1",
        order_id="order-1",
        request_id="request-1",
        runtime_id="runtime-1",
        cluster_id="cluster-1",
        strategy_id="strategy-1",
        account_id="account-1",
        instrument_id="TEST.XSHG",
        side="BUY",
        offset="OPEN",
        quantity=Decimal("10"),
        price=Decimal("2"),
        turnover=Decimal("20"),
        commission=Decimal("0.1"),
        fees=Decimal("0.2"),
        slippage=Decimal("0.3"),
        ts_event=now,
        trading_day=date(2026, 1, 1),
        venue="virtual",
        position_side="LONG",
        position_effect="OPEN",
    )
    currency = OnlyCurrency("CNY", 2)
    result = OnlyResultFixture(
        OnlyBacktestFacts(orders=(order,), executions=(execution,), equity=(_equity(3, "100"),)),
        OnlyPerformanceFixture(OnlyMoney(Decimal("100"), currency), OnlyMoney(Decimal("100"), currency)),
        "result-fingerprint",
    )

    analysis = OnlyBacktestAnalyticsService().analyze(result)

    assert analysis.orders.submitted_count == analysis.orders.accepted_count == analysis.orders.filled_count == 1
    assert analysis.executions.execution_count == analysis.executions.buy_execution_count == 1
    assert analysis.executions.gross_turnover == Decimal("20")
    assert analysis.executions.commission == Decimal("0.1")
    assert analysis.executions.fees == Decimal("0.2")
