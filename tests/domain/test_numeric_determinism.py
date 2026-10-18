"""Independent regression cases for the owner-selected Domain arithmetic policy."""

from decimal import ROUND_DOWN, ROUND_UP, Decimal, Inexact, localcontext

import pytest

from onlyalpha.domain.account import OnlyBalance
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPercentage, OnlyPrice, OnlyQuantity


@pytest.mark.parametrize("precision", [3, 28, 50])
def test_value_arithmetic_ignores_ambient_precision_rounding_and_traps(precision: int) -> None:
    currency = OnlyCurrency("USD", 2)
    with localcontext() as context:
        context.prec = precision
        context.rounding = ROUND_UP
        context.traps[Inexact] = True
        assert (OnlyMoney(Decimal("999"), currency) + OnlyMoney(Decimal("2"), currency)).amount == Decimal("1001")
        assert (OnlyQuantity(Decimal("999"), 0) + OnlyQuantity(Decimal("2"), 0)).value == Decimal("1001")
        assert (OnlyMoney(Decimal("1001"), currency) - OnlyMoney(Decimal("999"), currency)).amount == Decimal("2")
        assert OnlyPercentage(Decimal("12345.67"), 2).as_rate.value == Decimal("123.4567")
        OnlyBalance(
            currency,
            OnlyMoney(Decimal("1001"), currency),
            OnlyMoney(Decimal("999"), currency),
            OnlyMoney(Decimal("2"), currency),
        )


def test_huge_integral_values_are_not_narrowed() -> None:
    value = Decimal("9" * 100)
    with localcontext() as context:
        context.prec = 3
        assert (OnlyQuantity(value, 0) + OnlyQuantity(Decimal(1), 0)).value == Decimal("1" + "0" * 100)


def test_arithmetic_helpers_have_explicit_division_and_rounding() -> None:
    from onlyalpha.domain.numeric import only_add, only_divide, only_multiply, only_quantize, only_remainder

    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_UP
        context.traps[Inexact] = True
        assert only_add(Decimal("999"), Decimal("2")) == Decimal("1001")
        assert only_multiply(Decimal("999"), Decimal("999")) == Decimal("998001")
        assert only_divide(Decimal(1), Decimal(3)) == Decimal("0.3333333333333333333333333333")
        assert only_divide(Decimal(1), Decimal(2**100)) == Decimal(
            "7.888609052210118054117285652827862296732064351090230047702789306640625E-31"
        )
        assert only_quantize(Decimal("12345.675"), Decimal("0.01")) == Decimal("12345.68")
        assert only_quantize(Decimal("12345.675"), Decimal("0.01"), rounding=ROUND_DOWN) == Decimal("12345.67")
        assert only_remainder(Decimal("123456789.01"), Decimal("0.01")) == 0


def test_increment_validation_and_quantization_ignore_ambient_context(equity) -> None:
    from onlyalpha.domain.enums import OnlyOrderSide
    from onlyalpha.domain.market_rules import OnlyLotSizeRule

    with localcontext() as context:
        context.prec = 3
        context.traps[Inexact] = True
        price = OnlyPrice(Decimal("123456789.01"), 2)
        assert equity.validates_price(price)
        assert equity.quantize_price(price, rounding=ROUND_DOWN) == price
        assert OnlyLotSizeRule(Decimal("0.01"), Decimal("0.01")).validates(
            OnlyOrderSide.BUY, OnlyQuantity(price.value, 2)
        )


@pytest.mark.parametrize("precision", [3, 28, 50])
def test_pnl_and_fee_schedule_use_explicit_economic_rounding(precision: int) -> None:
    from datetime import UTC, datetime

    from onlyalpha.domain.account import OnlyPnLCalculator
    from onlyalpha.domain.enums import OnlyLiquiditySide, OnlyPositionDirection
    from onlyalpha.domain.market_rules import OnlyFeeSchedule
    from onlyalpha.domain.value import OnlyRate
    from tests.domain.conformance.support.instruments import build_instruments

    instruments = build_instruments()
    currency = OnlyCurrency("USD", 2)
    schedule = OnlyFeeSchedule(
        "test",
        OnlyRate(Decimal("0.00125"), 5),
        OnlyRate(Decimal("0.0025"), 4),
        OnlyMoney(Decimal(0), currency),
        datetime(2020, 1, 1, tzinfo=UTC),
    )
    with localcontext() as context:
        context.prec = precision
        context.rounding = ROUND_UP
        context.traps[Inexact] = True
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
        assert linear.amount == Decimal("20.00000000")
        assert inverse.amount == Decimal("0.00090909")
        assert schedule.calculate(OnlyMoney(Decimal("12345.67"), currency), OnlyLiquiditySide.MAKER).amount == Decimal(
            "15.43"
        )
        assert schedule.calculate(OnlyMoney(Decimal("12345.67"), currency), OnlyLiquiditySide.TAKER).amount == Decimal(
            "30.86"
        )


def test_exact_operations_cannot_silently_underflow_or_emit_unrecoverable_values() -> None:
    from onlyalpha.domain.errors import OnlyValidationError
    from onlyalpha.domain.numeric import only_multiply

    assert only_multiply(Decimal("1E-999999999999999999"), Decimal("0.01")) == Decimal("1E-1000000000000000001")
    with pytest.raises(OnlyValidationError):
        only_multiply(Decimal("1E+999999999999999999"), Decimal("1E+1"))
