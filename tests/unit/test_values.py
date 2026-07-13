from decimal import Decimal

import pytest

from onlyalpha.core.errors import OnlyValidationError
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity


def test_fixed_point_values_validate_increment_and_currency() -> None:
    cny = OnlyCurrency("cny")
    assert OnlyPrice(Decimal("10.05"), 2, Decimal("0.01")).value == Decimal("10.05")
    assert OnlyQuantity(Decimal("200"), 0, Decimal("100")).value == Decimal("200")
    assert OnlyMoney(Decimal("1.20"), cny) + OnlyMoney(Decimal("2.30"), cny) == OnlyMoney(Decimal("3.50"), cny)

    with pytest.raises(OnlyValidationError):
        OnlyPrice(Decimal("10.03"), 2, Decimal("0.05"))
    with pytest.raises(OnlyValidationError):
        OnlyMoney(Decimal("1"), cny) + OnlyMoney(Decimal("1"), OnlyCurrency("USD"))
