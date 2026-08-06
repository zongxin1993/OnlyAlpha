"""Explicit fee formula terms evaluated with a local Decimal context."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext

from onlyalpha.domain.value import only_decimal
from onlyalpha.fee.models import OnlyFeeBasisValues, OnlyFeeCalculationBasis


@dataclass(frozen=True, slots=True)
class OnlyFeeRateTerm:
    basis: OnlyFeeCalculationBasis
    rate: Decimal

    def __post_init__(self) -> None:
        value = only_decimal(self.rate)
        if value < 0:
            raise ValueError("fee rate cannot be negative")
        object.__setattr__(self, "rate", value)

    def evaluate(self, values: OnlyFeeBasisValues) -> Decimal:
        with localcontext() as context:
            context.prec = 50
            return values.value(self.basis) * self.rate


@dataclass(frozen=True, slots=True)
class OnlyFeePerUnitTerm:
    basis: OnlyFeeCalculationBasis
    amount_per_unit: Decimal

    def __post_init__(self) -> None:
        value = only_decimal(self.amount_per_unit)
        if value < 0:
            raise ValueError("per-unit fee cannot be negative")
        object.__setattr__(self, "amount_per_unit", value)

    def evaluate(self, values: OnlyFeeBasisValues) -> Decimal:
        with localcontext() as context:
            context.prec = 50
            return values.value(self.basis) * self.amount_per_unit


@dataclass(frozen=True, slots=True)
class OnlyFeeFixedTerm:
    amount: Decimal

    def __post_init__(self) -> None:
        value = only_decimal(self.amount)
        if value < 0:
            raise ValueError("fixed fee cannot be negative")
        object.__setattr__(self, "amount", value)

    def evaluate(self, values: OnlyFeeBasisValues) -> Decimal:
        del values
        return self.amount


OnlyFeeFormulaTerm = OnlyFeeRateTerm | OnlyFeePerUnitTerm | OnlyFeeFixedTerm


@dataclass(frozen=True, slots=True)
class OnlyFeeFormula:
    terms: tuple[OnlyFeeFormulaTerm, ...]

    def __post_init__(self) -> None:
        if not self.terms:
            raise ValueError("fee formula cannot be empty")
        if any(not isinstance(item, OnlyFeeRateTerm | OnlyFeePerUnitTerm | OnlyFeeFixedTerm) for item in self.terms):
            raise TypeError("fee formula contains an unsupported term")

    def evaluate(self, values: OnlyFeeBasisValues) -> Decimal:
        with localcontext() as context:
            context.prec = 50
            return sum((item.evaluate(values) for item in self.terms), Decimal(0))

    def payload(self) -> tuple[dict[str, str], ...]:
        result: list[dict[str, str]] = []
        for term in self.terms:
            if isinstance(term, OnlyFeeRateTerm):
                result.append({"kind": "RATE", "basis": term.basis.value, "rate": str(term.rate)})
            elif isinstance(term, OnlyFeePerUnitTerm):
                result.append(
                    {"kind": "PER_UNIT", "basis": term.basis.value, "amount_per_unit": str(term.amount_per_unit)}
                )
            else:
                result.append({"kind": "FIXED", "amount": str(term.amount)})
        return tuple(result)


__all__ = [
    "OnlyFeeFixedTerm",
    "OnlyFeeFormula",
    "OnlyFeeFormulaTerm",
    "OnlyFeePerUnitTerm",
    "OnlyFeeRateTerm",
]
