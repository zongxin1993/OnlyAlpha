from decimal import Decimal

from examples.domain_conformance.fixtures.instruments import build_instruments
from onlyalpha.domain.account import OnlyPnLCalculator
from onlyalpha.domain.enums import OnlyPositionDirection
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity


def test_linear_and_inverse_pnl_use_settlement_currency() -> None:
    instruments = build_instruments()
    linear = OnlyPnLCalculator.unrealized(
        instruments["linear_perpetual"],
        OnlyPositionDirection.LONG,
        OnlyQuantity(Decimal("2"), 0),
        OnlyPrice(Decimal("100.00"), 2),
        OnlyPrice(Decimal("110.00"), 2),
    )
    inverse = OnlyPnLCalculator.unrealized(
        instruments["inverse_perpetual"],
        OnlyPositionDirection.LONG,
        OnlyQuantity(Decimal("100"), 0),
        OnlyPrice(Decimal("10000.00"), 2),
        OnlyPrice(Decimal("11000.00"), 2),
    )
    assert linear.currency == instruments["linear_perpetual"].settlement_currency
    assert inverse.currency == instruments["inverse_perpetual"].settlement_currency
    assert linear.amount == Decimal("20.00000000")
    assert inverse.amount == Decimal("0.00090909")
