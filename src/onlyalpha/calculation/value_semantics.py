"""Canonical stateless point-value semantics shared by Calculation adapters."""

from __future__ import annotations

from decimal import Decimal, DivisionByZero, InvalidOperation, localcontext

from .decimal_execution import only_decimal_context, only_quantize_decimal
from .definition import OnlyNumericDefinition


class OnlyCanonicalValueSemanticsV1:
    """Single owner of Private Alpha V1 arithmetic, comparison and missing semantics."""

    def __init__(self, numeric: OnlyNumericDefinition) -> None:
        self.numeric = numeric

    def add(self, a: object, b: object) -> Decimal | None:
        return self._arithmetic("add", a, b)

    def sub(self, a: object, b: object) -> Decimal | None:
        return self._arithmetic("sub", a, b)

    def mul(self, a: object, b: object) -> Decimal | None:
        return self._arithmetic("mul", a, b)

    def div(self, a: object, b: object) -> Decimal | None:
        return self._arithmetic("div", a, b)

    def negate(self, value: object) -> Decimal | None:
        number = self._decimal(value)
        if number is None:
            return None
        with localcontext(only_decimal_context(self.numeric)):
            return only_quantize_decimal(self.numeric, -number)

    def min(self, a: object, b: object) -> Decimal | None:
        pair = self._pair(a, b)
        return None if pair is None else only_quantize_decimal(self.numeric, min(pair))

    def max(self, a: object, b: object) -> Decimal | None:
        pair = self._pair(a, b)
        return None if pair is None else only_quantize_decimal(self.numeric, max(pair))

    def eq(self, a: object, b: object) -> bool | None:
        return self._compare("eq", a, b)

    def ne(self, a: object, b: object) -> bool | None:
        return self._compare("ne", a, b)

    def lt(self, a: object, b: object) -> bool | None:
        return self._compare("lt", a, b)

    def le(self, a: object, b: object) -> bool | None:
        return self._compare("le", a, b)

    def gt(self, a: object, b: object) -> bool | None:
        return self._compare("gt", a, b)

    def ge(self, a: object, b: object) -> bool | None:
        return self._compare("ge", a, b)

    @staticmethod
    def and_(a: object, b: object) -> bool | None:
        left, right = _boolean(a), _boolean(b)
        return False if left is False or right is False else None if left is None or right is None else True

    @staticmethod
    def or_(a: object, b: object) -> bool | None:
        left, right = _boolean(a), _boolean(b)
        return True if left is True or right is True else None if left is None or right is None else False

    @staticmethod
    def not_(value: object) -> bool | None:
        boolean = _boolean(value)
        return None if boolean is None else not boolean

    @staticmethod
    def where(condition: object, when_true: object, when_false: object) -> object:
        boolean = _boolean(condition)
        return when_true if boolean is True else when_false if boolean is False else None

    @staticmethod
    def is_missing(value: object) -> bool:
        return value is None

    @staticmethod
    def coalesce(value: object, fallback: object) -> object:
        return fallback if value is None else value

    def _arithmetic(self, operation: str, a: object, b: object) -> Decimal | None:
        pair = self._pair(a, b)
        if pair is None:
            return None
        left, right = pair
        if operation == "div" and right.is_zero():
            return None
        with localcontext(only_decimal_context(self.numeric)):
            try:
                if operation == "add":
                    result = left + right
                    return only_quantize_decimal(self.numeric, result)
                if operation == "sub":
                    result = left - right
                    return only_quantize_decimal(self.numeric, result)
                if operation == "mul":
                    result = left * right
                    return only_quantize_decimal(self.numeric, result)
                if operation == "div":
                    result = left / right
                    return only_quantize_decimal(self.numeric, result)
            except (DivisionByZero, InvalidOperation) as exc:
                raise ValueError("CANONICAL_VALUE_ARITHMETIC_INVALID") from exc
        raise ValueError("CANONICAL_VALUE_OPERATION_INVALID")

    def _compare(self, operation: str, a: object, b: object) -> bool | None:
        pair = self._pair(a, b)
        if pair is None:
            return None
        left, right = pair
        return {
            "eq": left == right,
            "ne": left != right,
            "lt": left < right,
            "le": left <= right,
            "gt": left > right,
            "ge": left >= right,
        }[operation]

    def _pair(self, a: object, b: object) -> tuple[Decimal, Decimal] | None:
        left, right = self._decimal(a), self._decimal(b)
        return None if left is None or right is None else (left, right)

    @staticmethod
    def _decimal(value: object) -> Decimal | None:
        if value is None:
            return None
        if not isinstance(value, Decimal) or not value.is_finite():
            raise TypeError("CANONICAL_VALUE_DECIMAL_REQUIRED")
        return value


def _boolean(value: object) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    raise TypeError("CANONICAL_VALUE_BOOLEAN_REQUIRED")


__all__ = ["OnlyCanonicalValueSemanticsV1"]
