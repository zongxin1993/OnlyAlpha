from decimal import Decimal

import pytest

from onlyalpha.domain.errors import OnlyCurrencyMismatchError, OnlyValidationError
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity


def test_value_dimensions_currency_and_exactness() -> None:
    cny, usd = OnlyCurrency("CNY", 2), OnlyCurrency("USD", 2)
    assert OnlyPrice(Decimal("10.50"), 2) != OnlyQuantity(Decimal("10.50"), 2)
    assert OnlyMoney.from_json(OnlyMoney(Decimal("100.00"), cny).to_json()).amount == Decimal("100.00")
    with pytest.raises(TypeError):
        _ = OnlyPrice(Decimal("10.50"), 2) + OnlyMoney(Decimal("100.00"), cny)  # type: ignore[operator]
    with pytest.raises(OnlyCurrencyMismatchError):
        _ = OnlyMoney(Decimal("100.00"), cny) + OnlyMoney(Decimal("100.00"), usd)
    for invalid in ("NaN", "Infinity", "-Infinity"):
        with pytest.raises(OnlyValidationError):
            OnlyPrice(Decimal(invalid), 2)
