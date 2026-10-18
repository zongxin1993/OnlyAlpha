"""Immutable decimal financial value objects."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Self

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.enums import OnlyCurrencyType
from onlyalpha.domain.errors import OnlyCurrencyMismatchError, OnlyValidationError
from onlyalpha.domain.numeric import only_add, only_divide, only_subtract

ONLY_MAX_PRECISION = 18


def only_decimal(value: Decimal | int | str) -> Decimal:
    """Convert an exact input to a finite Decimal; floats are intentionally rejected."""
    if isinstance(value, float | bool):
        raise OnlyValidationError("binary float is not accepted by financial value objects")
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise OnlyValidationError(f"invalid decimal value: {value!r}") from exc
    if not result.is_finite():
        raise OnlyValidationError("financial values must be finite")
    return result


def only_precision(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):
        raise OnlyValidationError("financial values must have finite precision")
    return max(0, -exponent)


def _validate_precision(value: Decimal, precision: int) -> None:
    if not 0 <= precision <= ONLY_MAX_PRECISION:
        raise OnlyValidationError(f"precision must be between 0 and {ONLY_MAX_PRECISION}")
    if only_precision(value) > precision:
        raise OnlyValidationError("value exceeds declared precision")


@dataclass(frozen=True, slots=True)
class OnlyCurrency(OnlyDomainModel):
    """Currency identity including code, precision and currency category."""

    code: str
    precision: int = 2
    currency_type: OnlyCurrencyType = OnlyCurrencyType.FIAT

    def __post_init__(self) -> None:
        code = self.code.strip().upper()
        if not 1 <= len(code) <= 12 or not code.isalnum():
            raise OnlyValidationError("currency code must contain 1 to 12 alphanumeric characters")
        if not 0 <= self.precision <= ONLY_MAX_PRECISION:
            raise OnlyValidationError("currency precision is outside the supported range")
        object.__setattr__(self, "code", code)


@dataclass(frozen=True, slots=True)
class OnlyPrice(OnlyDomainModel):
    """Signed price value with display/serialization precision."""

    value: Decimal
    precision: int

    def __post_init__(self) -> None:
        value = only_decimal(self.value)
        _validate_precision(value, self.precision)
        object.__setattr__(self, "value", value)


@dataclass(frozen=True, slots=True)
class OnlyQuantity(OnlyDomainModel):
    """Non-negative quantity with explicit precision and no implicit unit conversion."""

    value: Decimal
    precision: int

    def __post_init__(self) -> None:
        value = only_decimal(self.value)
        _validate_precision(value, self.precision)
        if value < 0:
            raise OnlyValidationError("quantity cannot be negative")
        object.__setattr__(self, "value", value)

    def __add__(self, other: Self) -> Self:
        precision = max(self.precision, other.precision)
        return type(self)(only_add(self.value, other.value), precision)

    def __sub__(self, other: Self) -> Self:
        if other.value > self.value:
            raise OnlyValidationError("quantity subtraction cannot produce a negative value")
        precision = max(self.precision, other.precision)
        return type(self)(only_subtract(self.value, other.value), precision)


@dataclass(frozen=True, slots=True)
class OnlyMoney(OnlyDomainModel):
    """Signed monetary amount strictly bound to one Currency."""

    amount: Decimal
    currency: OnlyCurrency

    def __post_init__(self) -> None:
        amount = only_decimal(self.amount)
        _validate_precision(amount, self.currency.precision)
        object.__setattr__(self, "amount", amount)

    def __add__(self, other: Self) -> Self:
        self._require_currency(other)
        return type(self)(only_add(self.amount, other.amount), self.currency)

    def __sub__(self, other: Self) -> Self:
        self._require_currency(other)
        return type(self)(only_subtract(self.amount, other.amount), self.currency)

    def _require_currency(self, other: Self) -> None:
        if self.currency != other.currency:
            raise OnlyCurrencyMismatchError(
                f"currency conversion required: {self.currency.code} != {other.currency.code}"
            )


@dataclass(frozen=True, slots=True)
class OnlyRate(OnlyDomainModel):
    """Signed dimensionless decimal rate."""

    value: Decimal
    precision: int = 8

    def __post_init__(self) -> None:
        value = only_decimal(self.value)
        _validate_precision(value, self.precision)
        object.__setattr__(self, "value", value)


@dataclass(frozen=True, slots=True)
class OnlyPercentage(OnlyDomainModel):
    """Percentage points, where 100 represents one hundred percent."""

    value: Decimal
    precision: int = 8

    def __post_init__(self) -> None:
        value = only_decimal(self.value)
        _validate_precision(value, self.precision)
        object.__setattr__(self, "value", value)

    @property
    def as_rate(self) -> OnlyRate:
        return OnlyRate(only_divide(self.value, Decimal("100")), min(ONLY_MAX_PRECISION, self.precision + 2))


@dataclass(frozen=True, slots=True)
class OnlyMultiplier(OnlyDomainModel):
    """Strictly positive contract or conversion multiplier."""

    value: Decimal
    precision: int = 8

    def __post_init__(self) -> None:
        value = only_decimal(self.value)
        _validate_precision(value, self.precision)
        if value <= 0:
            raise OnlyValidationError("multiplier must be positive")
        object.__setattr__(self, "value", value)
