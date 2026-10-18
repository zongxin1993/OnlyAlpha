"""Domain arithmetic policy: exact finite operations, explicit 28-digit division.

No operation inherits thread-local Decimal precision, traps, rounding or limits.
Only non-terminating division rounds; business quantization remains explicit.
"""

from collections.abc import Callable
from decimal import (
    MAX_EMAX,
    MIN_EMIN,
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
)
from fractions import Fraction
from typing import cast

from onlyalpha.domain.errors import OnlyValidationError

ONLY_DIVISION_PRECISION = 28
ONLY_NUMERIC_POLICY = "domain-exact-28-half-even-v1"


def _context(precision: int, rounding: str = ROUND_HALF_EVEN, *, exact: bool = False) -> Context:
    return Context(
        prec=max(1, precision),
        rounding=rounding,
        Emin=MIN_EMIN,
        Emax=MAX_EMAX,
        clamp=0,
        traps=[InvalidOperation, DivisionByZero, Overflow, *([Inexact] if exact else [])],
    )


def _checked(operation: Callable[[], Decimal]) -> Decimal:
    try:
        return operation()
    except (DecimalException, ValueError, TypeError) as error:
        raise OnlyValidationError("DOMAIN_NUMERIC_RANGE_INVALID") from error


def _finite(*values: Decimal) -> None:
    if any(not value.is_finite() for value in values):
        raise OnlyValidationError("domain arithmetic requires finite decimals")


def _span(*values: Decimal) -> int:
    _finite(*values)
    exponent = min(cast(int, value.as_tuple().exponent) for value in values)
    return max(max(value.adjusted() for value in values) - exponent + 2, MIN_EMIN - exponent + 1)


def only_canonical_decimal(value: Decimal) -> Decimal:
    """Exact numerical parameter representation, independent of Decimal context."""
    _finite(value)
    if not value:
        return Decimal(0)
    parts = value.as_tuple()
    digits = list(parts.digits)
    exponent = cast(int, parts.exponent)
    while digits[-1] == 0:
        digits.pop()
        exponent += 1
    return Decimal((parts.sign, tuple(digits), exponent))


def only_add(left: Decimal, right: Decimal) -> Decimal:
    return _checked(lambda: _context(_span(left, right), exact=True).add(left, right))


def only_subtract(left: Decimal, right: Decimal) -> Decimal:
    return _checked(lambda: _context(_span(left, right), exact=True).subtract(left, right))


def only_multiply(left: Decimal, right: Decimal) -> Decimal:
    _finite(left, right)
    exponent = cast(int, left.as_tuple().exponent) + cast(int, right.as_tuple().exponent)
    precision = max(len(left.as_tuple().digits) + len(right.as_tuple().digits), MIN_EMIN - exponent + 1)
    return _checked(lambda: _context(precision, exact=True).multiply(left, right))


def only_divide(left: Decimal, right: Decimal) -> Decimal:
    _finite(left, right)
    if not right:
        raise OnlyValidationError("domain division by zero")
    left_parts, right_parts = left.as_tuple(), right.as_tuple()
    left_coefficient = int(Decimal((left_parts.sign, left_parts.digits, 0)))
    right_coefficient = int(Decimal((right_parts.sign, right_parts.digits, 0)))
    exponent = cast(int, left_parts.exponent) - cast(int, right_parts.exponent)
    ratio = Fraction(left_coefficient, right_coefficient)
    denominator = ratio.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        rounded = _checked(
            lambda: _context(ONLY_DIVISION_PRECISION).divide(Decimal(ratio.numerator), Decimal(ratio.denominator))
        )
        parts = rounded.as_tuple()
        return _checked(
            lambda: Decimal(
                (parts.sign, parts.digits, cast(int, parts.exponent) + exponent),
                context=_context(len(parts.digits), exact=True),
            )
        )
    scale = max(twos, fives)
    coefficient = ratio.numerator * 2 ** (scale - twos) * 5 ** (scale - fives)
    output_exponent = exponent - scale if coefficient else 0
    while output_exponent < 0 and coefficient % 10 == 0:
        coefficient //= 10
        output_exponent += 1
    digits = Decimal(abs(coefficient)).as_tuple().digits
    return _checked(
        lambda: Decimal((int(coefficient < 0), digits, output_exponent), context=_context(len(digits), exact=True))
    )


def only_remainder(left: Decimal, right: Decimal) -> Decimal:
    return _checked(lambda: _context(_span(left, right), exact=True).remainder(left, right))


def only_quantize(value: Decimal, quantum: Decimal, *, rounding: str = ROUND_HALF_EVEN) -> Decimal:
    return _checked(lambda: _context(_span(value, quantum), rounding).quantize(value, quantum))


def only_increment(value: Decimal, increment: Decimal, *, rounding: str) -> Decimal:
    """Round the exact rational number of increments, without a rounded quotient."""
    _finite(value, increment)
    if increment <= 0:
        raise OnlyValidationError("increment must be positive")
    ratio = Fraction(value) / Fraction(increment)
    numerator, denominator = Decimal(ratio.numerator), Decimal(ratio.denominator)
    context = _context(len(numerator.as_tuple().digits) + len(denominator.as_tuple().digits) + 2, rounding)
    units = context.divide(numerator, denominator).to_integral_value(rounding=rounding, context=context)
    return only_multiply(units, increment)
