from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from onlyalpha.account.performance import (
    OnlyAccountEquityPoint,
    OnlyAccountValuationSource,
    OnlyRuntimePortfolioPerformanceSummary,
)
from onlyalpha.analytics import OnlyBacktestAnalyticsService
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyRate
from onlyalpha.result.records import (
    OnlyBacktestFacts,
    OnlyEquityResultRecord,
    OnlyExecutionResultRecord,
    OnlyOrderResultRecord,
)


@dataclass(frozen=True)
class OnlyResultFixture:
    facts: OnlyBacktestFacts
    runtime_performance: OnlyRuntimePortfolioPerformanceSummary
    account_equity_timeline: tuple[OnlyAccountEquityPoint, ...]
    result_fingerprint: str
    cluster_results: tuple[object, ...] = ()
    cluster_equity_timelines: tuple[tuple[object, ...], ...] = ()


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


def _point(sequence: int, value: str) -> OnlyAccountEquityPoint:
    currency = OnlyCurrency("CNY", 2)
    money = OnlyMoney(Decimal(value), currency)
    zero = OnlyMoney(Decimal(0), currency)
    return OnlyAccountEquityPoint(
        sequence,
        OnlyRuntimeId("runtime-1"),
        OnlyAccountId("account-1"),
        OnlyTimestamp.from_datetime(datetime(2026, 1, sequence, tzinfo=UTC)),
        None,
        currency,
        money,
        zero,
        zero,
        zero,
        zero,
        money,
        zero,
        OnlyAccountValuationSource.MARKET_VALUATION,
        sequence,
        (),
    )


def _performance(initial: str, final: str) -> OnlyRuntimePortfolioPerformanceSummary:
    currency = OnlyCurrency("CNY", 2)
    initial_money = OnlyMoney(Decimal(initial), currency)
    final_money = OnlyMoney(Decimal(final), currency)
    zero = OnlyMoney(Decimal(0), currency)
    rate = (
        None
        if Decimal(initial) == 0
        else OnlyRate((Decimal(final) / Decimal(initial) - 1).quantize(Decimal("1e-8")), 8)
    )
    return OnlyRuntimePortfolioPerformanceSummary(
        OnlyRuntimeId("runtime-1"),
        OnlyAccountId("account-1"),
        "ACCOUNT",
        currency,
        initial_money,
        final_money,
        zero,
        zero,
        OnlyMoney(Decimal(final) - Decimal(initial), currency),
        zero,
        zero,
        rate,
        OnlyRate(Decimal(0), 8),
        OnlyRate(Decimal(0), 8),
        final_money,
        1,
        ("ZERO_INITIAL_EQUITY",) if Decimal(initial) == 0 else (),
    )


def test_analysis_calculates_return_and_recovered_drawdown() -> None:
    result = OnlyResultFixture(
        OnlyBacktestFacts(equity=(_equity(1, "100"), _equity(2, "80"), _equity(3, "110"))),
        _performance("100", "110"),
        (_point(1, "100"), _point(2, "80"), _point(3, "110")),
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
    result = OnlyResultFixture(
        OnlyBacktestFacts(equity=(_equity(1, "0"),)),
        _performance("0", "0"),
        (_point(1, "0"),),
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
    result = OnlyResultFixture(
        OnlyBacktestFacts(orders=(order,), executions=(execution,), equity=(_equity(3, "100"),)),
        _performance("100", "100"),
        (_point(1, "100"),),
        "result-fingerprint",
    )

    analysis = OnlyBacktestAnalyticsService().analyze(result)

    assert analysis.orders.submitted_count == analysis.orders.accepted_count == analysis.orders.filled_count == 1
    assert analysis.executions.execution_count == analysis.executions.buy_execution_count == 1
    assert analysis.executions.gross_turnover == Decimal("20")
    assert analysis.executions.commission == Decimal("0.1")
    assert analysis.executions.fees == Decimal("0.2")
