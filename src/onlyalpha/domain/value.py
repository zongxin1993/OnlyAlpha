"""Immutable fixed-point financial values used by the initial skeleton."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Self

from onlyalpha.core.errors import OnlyValidationError


def _decimal(value: Decimal | int | str) -> Decimal:
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise OnlyValidationError(f"invalid decimal value: {value!r}") from exc
    if not result.is_finite():
        raise OnlyValidationError("financial values must be finite")
    return result


@dataclass(frozen=True, slots=True)
class OnlyCurrency:
    """ISO-like uppercase currency code."""

    code: str

    def __post_init__(self) -> None:
        normalized = self.code.strip().upper()
        if not 3 <= len(normalized) <= 8 or not normalized.isalnum():
            raise OnlyValidationError("currency code must contain 3 to 8 alphanumeric characters")
        object.__setattr__(self, "code", normalized)


@dataclass(frozen=True, slots=True)
class OnlyPrice:
    """Non-negative price with declared decimal precision and tick size."""

    value: Decimal
    precision: int
    increment: Decimal

    def __post_init__(self) -> None:
        value, increment = _decimal(self.value), _decimal(self.increment)
        if value < 0 or self.precision < 0 or increment <= 0:
            raise OnlyValidationError("price constraints must be non-negative and increment positive")
        exponent = value.as_tuple().exponent
        if not isinstance(exponent, int) or exponent < -self.precision:
            raise OnlyValidationError("price exceeds declared precision")
        if value % increment != 0:
            raise OnlyValidationError("price is not aligned to its increment")
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "increment", increment)


@dataclass(frozen=True, slots=True)
class OnlyQuantity:
    """Non-negative quantity with declared precision and step size."""

    value: Decimal
    precision: int
    increment: Decimal

    def __post_init__(self) -> None:
        value, increment = _decimal(self.value), _decimal(self.increment)
        if value < 0 or self.precision < 0 or increment <= 0:
            raise OnlyValidationError("quantity constraints must be non-negative and increment positive")
        exponent = value.as_tuple().exponent
        if not isinstance(exponent, int) or exponent < -self.precision:
            raise OnlyValidationError("quantity exceeds declared precision")
        if value % increment != 0:
            raise OnlyValidationError("quantity is not aligned to its increment")
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "increment", increment)


@dataclass(frozen=True, slots=True)
class OnlyMoney:
    """Decimal monetary amount bound to a currency."""

    amount: Decimal
    currency: OnlyCurrency

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", _decimal(self.amount))

    def __add__(self, other: Self) -> Self:
        if self.currency != other.currency:
            raise OnlyValidationError("cannot add money in different currencies")
        return type(self)(self.amount + other.amount, self.currency)
