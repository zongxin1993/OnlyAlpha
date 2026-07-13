from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal

from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity


def test_instrument_validation_and_explicit_quantization(equity: OnlyInstrument) -> None:
    price = OnlyPrice(Decimal("10.03"), 2)
    assert not equity.is_valid_price(price)
    assert equity.quantize_price(price, rounding=ROUND_HALF_EVEN) == OnlyPrice(Decimal("10.05"), 2)
    quantity = OnlyQuantity(Decimal("199"), 0)
    assert equity.quantize_quantity(quantity, rounding=ROUND_DOWN) == OnlyQuantity(Decimal("199"), 0)
