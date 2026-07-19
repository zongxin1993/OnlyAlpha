from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from onlyalpha.analytics import OnlyTradeBuilder
from onlyalpha.result.records import OnlyExecutionResultRecord


def _execution(
    sequence: int,
    execution_id: str,
    side: str,
    offset: str,
    quantity: str,
    price: str,
    commission: str,
) -> OnlyExecutionResultRecord:
    ts_event = datetime(2026, 1, sequence, tzinfo=UTC)
    return OnlyExecutionResultRecord(
        sequence=sequence,
        execution_id=execution_id,
        order_id=f"order-{execution_id}",
        request_id=f"request-{execution_id}",
        runtime_id="runtime-1",
        cluster_id="cluster-1",
        strategy_id="strategy-1",
        account_id="account-1",
        instrument_id="TEST.XSHG",
        side=side,
        offset=offset,
        quantity=Decimal(quantity),
        price=Decimal(price),
        turnover=Decimal(quantity) * Decimal(price),
        commission=Decimal(commission),
        fees=Decimal("0"),
        slippage=Decimal("0"),
        ts_event=ts_event,
        trading_day=date(2026, 1, sequence),
        venue="virtual",
    )


def test_fifo_matches_split_entries_and_allocates_all_fees_exactly() -> None:
    executions = (
        _execution(1, "buy-1", "BUY", "OPEN", "100", "10", "1.00"),
        _execution(2, "buy-2", "BUY", "OPEN", "200", "11", "2.00"),
        _execution(3, "sell-1", "SELL", "CLOSE", "150", "12", "1.50"),
        _execution(4, "sell-2", "SELL", "CLOSE", "150", "13", "1.50"),
    )

    result = OnlyTradeBuilder().build(executions)

    assert [item.quantity for item in result.trades] == [Decimal("100"), Decimal("50"), Decimal("150")]
    assert [item.gross_pnl for item in result.trades] == [Decimal("200"), Decimal("50"), Decimal("300")]
    assert sum((item.commission for item in result.trades), Decimal(0)) == Decimal("6.00")
    assert sum((item.net_pnl for item in result.trades), Decimal(0)) == Decimal("544.00")
    assert result.trades[0].holding_duration == timedelta(days=2)
    assert result.warnings == ()


def test_fifo_reports_unmatched_close_without_inventing_open_lot() -> None:
    result = OnlyTradeBuilder().build((_execution(1, "sell", "SELL", "CLOSE", "10", "12", "1"),))

    assert result.trades == ()
    assert result.warnings == ("UNMATCHED_CLOSE:sell:10",)
