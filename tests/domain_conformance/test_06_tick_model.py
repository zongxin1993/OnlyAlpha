from datetime import UTC, datetime
from decimal import Decimal

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.identifiers import OnlyTradeId
from onlyalpha.domain.market import OnlyQuoteTick, OnlyTradeTick
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity


def test_quote_and_trade_ticks_are_distinct_and_lossless(instrument_id) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    trade = OnlyTradeTick(
        instrument_id,
        now,
        now,
        1,
        "fixture",
        OnlyPrice(Decimal("10.00"), 2),
        OnlyQuantity(Decimal("1"), 0),
        OnlyOrderSide.BUY,
        OnlyTradeId("t1"),
    )
    quote = OnlyQuoteTick(
        instrument_id,
        now,
        now,
        2,
        "fixture",
        OnlyPrice(Decimal("9.99"), 2),
        OnlyQuantity(Decimal("2"), 0),
        OnlyPrice(Decimal("10.01"), 2),
        OnlyQuantity(Decimal("3"), 0),
    )
    assert type(trade) is not type(quote)
    assert OnlyTradeTick.from_json(trade.to_json()) == trade
    assert OnlyQuoteTick.from_json(quote.to_json()) == quote
