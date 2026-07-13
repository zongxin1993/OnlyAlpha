from datetime import UTC, date, datetime, time
from decimal import Decimal

from onlyalpha.domain.account import OnlyAccount, OnlyBalance, OnlyPortfolio
from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyBookType,
    OnlyMarginMode,
    OnlyPriceType,
    OnlySessionType,
)
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyInstrumentId, OnlyVenueId
from onlyalpha.domain.market import OnlyBar, OnlyBarSpecification, OnlyBarType, OnlyOrderBook, OnlyOrderBookLevel
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity


def test_multicurrency_account_has_no_implicit_portfolio_conversion() -> None:
    usd, btc = OnlyCurrency("USD", 2), OnlyCurrency("BTC", 8)
    balances = (
        OnlyBalance(
            usd, OnlyMoney(Decimal("100.00"), usd), OnlyMoney(Decimal("80.00"), usd), OnlyMoney(Decimal("20.00"), usd)
        ),
        OnlyBalance(
            btc,
            OnlyMoney(Decimal("1.00000000"), btc),
            OnlyMoney(Decimal("1.00000000"), btc),
            OnlyMoney(Decimal("0.00000000"), btc),
        ),
    )
    account = OnlyAccount(
        OnlyAccountId("a"), None, OnlyMarginMode.CASH, balances, (), None, datetime(2026, 1, 1, tzinfo=UTC)
    )
    portfolio = OnlyPortfolio((account,), None, None, datetime(2026, 1, 1, tzinfo=UTC))
    assert OnlyPortfolio.from_json(portfolio.to_json()) == portfolio


def test_bar_order_book_and_calendar_invariants(instrument_id: OnlyInstrumentId) -> None:
    start = datetime(2026, 1, 5, 1, 30, tzinfo=UTC)
    bar = OnlyBar(
        bar_type=OnlyBarType(
            instrument_id,
            OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
            OnlyAggregationSource.EXTERNAL,
        ),
        open=OnlyPrice(Decimal("10.00"), 2),
        high=OnlyPrice(Decimal("10.20"), 2),
        low=OnlyPrice(Decimal("9.90"), 2),
        close=OnlyPrice(Decimal("10.10"), 2),
        volume=OnlyQuantity(Decimal("100"), 0),
        quote_volume=None,
        turnover=None,
        trade_count=5,
        open_interest=None,
        bar_start=start,
        bar_end=start.replace(minute=31),
        ts_event=start.replace(minute=31),
        ts_init=start.replace(minute=31),
        is_closed=True,
        revision=0,
        adjustment_type=OnlyAdjustmentType.RAW,
        trading_day=start.date(),
        session_type=OnlySessionType.REGULAR,
    )
    assert OnlyBar.from_json(bar.to_json()) == bar
    book = OnlyOrderBook(
        instrument_id,
        OnlyBookType.L2,
        (OnlyOrderBookLevel(OnlyPrice(Decimal("10.00"), 2), OnlyQuantity(Decimal("2"), 0)),),
        (OnlyOrderBookLevel(OnlyPrice(Decimal("10.01"), 2), OnlyQuantity(Decimal("3"), 0)),),
        1,
        start,
    )
    assert book.bids[0].price.value < book.asks[0].price.value
    calendar = OnlyTradingCalendar(
        "XSHG",
        OnlyVenueId("XSHG"),
        "Asia/Shanghai",
        (OnlyTradingSession("continuous", time(9, 30), time(15, 0)),),
        (date(2026, 1, 1),),
    )
    assert calendar.is_open_at(datetime(2026, 1, 5, 2, 0, tzinfo=UTC))
    crossed = OnlyOrderBook(
        instrument_id,
        OnlyBookType.L2,
        (OnlyOrderBookLevel(OnlyPrice(Decimal("10.02"), 2), OnlyQuantity(Decimal("1"), 0)),),
        (OnlyOrderBookLevel(OnlyPrice(Decimal("10.01"), 2), OnlyQuantity(Decimal("1"), 0)),),
        2,
        start,
    )
    assert crossed.is_crossed
    overnight = OnlyTradingSession("night", time(21), time(2, 30))
    assert overnight.crosses_midnight and overnight.contains(time(1))
