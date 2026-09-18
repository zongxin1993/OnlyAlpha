from copy import copy, deepcopy
from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from onlyalpha.domain.enums import OnlyCurrencyType
from onlyalpha.domain.errors import OnlyCurrencyMismatchError, OnlyValidationError
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyOrderId
from onlyalpha.domain.value import (
    OnlyCurrency,
    OnlyMoney,
    OnlyMultiplier,
    OnlyPercentage,
    OnlyPrice,
    OnlyQuantity,
    OnlyRate,
)


def test_financial_values_are_typed_immutable_and_json_round_trip() -> None:
    usd = OnlyCurrency("usd", 2, OnlyCurrencyType.FIAT)
    money = OnlyMoney(Decimal("100.25"), usd)
    restored = OnlyMoney.from_json(money.to_json())
    assert restored == money
    assert hash(restored) == hash(money)
    assert copy(money) == money and deepcopy(money) == money
    assert money.to_record()["amount"] == "100.25"
    assert repr(money).startswith("OnlyMoney")
    with pytest.raises(FrozenInstanceError):
        money.amount = Decimal("0")  # type: ignore[misc]
    with pytest.raises(OnlyCurrencyMismatchError):
        money + OnlyMoney(Decimal("1.00"), OnlyCurrency("CNY", 2))


def test_value_dimensions_and_ranges_do_not_mix() -> None:
    assert OnlyPrice(Decimal("-1.25"), 2) != OnlyQuantity(Decimal("1.25"), 2)
    assert OnlyPercentage(Decimal("12.5"), 1).as_rate == OnlyRate(Decimal("0.125"), 3)
    assert OnlyMultiplier(Decimal("10"), 0).value == Decimal("10")
    with pytest.raises(OnlyValidationError):
        OnlyQuantity(Decimal("-1"), 0)
    with pytest.raises(OnlyValidationError):
        OnlyPrice(1.1, 1)  # type: ignore[arg-type]


def test_strong_identifiers_parse_and_do_not_cross_compare() -> None:
    instrument_id = OnlyInstrumentId.parse("BTCUSDT.BINANCE")
    assert str(instrument_id) == "BTCUSDT.BINANCE"
    assert OnlyInstrumentId.from_json(instrument_id.to_json()) == instrument_id
    assert OnlyOrderId("same") != instrument_id
    with pytest.raises(OnlyValidationError):
        OnlyInstrumentId.parse("missing-venue")
