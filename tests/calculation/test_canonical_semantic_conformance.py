from decimal import Decimal

from onlyalpha_plugin_operators.registration import ADD, DIVIDE, MULTIPLY, SUBTRACT, resolve_operator
from onlyalpha_plugin_operators.semantics import evaluate

from onlyalpha.calculation import OnlyCalculationReference, OnlyCanonicalValueSemanticsV1
from onlyalpha.calculation.definition import OnlyNumericDefinition


def test_operator_arithmetic_delegates_canonical_value_semantics() -> None:
    canonical = OnlyCanonicalValueSemanticsV1(
        OnlyNumericDefinition("DECIMAL", 28, Decimal("0.000000000001"), "ROUND_HALF_EVEN")
    )
    left = (Decimal("2.125"), Decimal("-2"), Decimal("0"), None)
    right = (Decimal("4"), Decimal("3"), Decimal("0"), Decimal("1"))
    for definition, operation in (
        (ADD, "add"),
        (SUBTRACT, "sub"),
        (MULTIPLY, "mul"),
        (DIVIDE, "div"),
    ):
        resolved = resolve_operator(
            definition,
            {},
            left=OnlyCalculationReference(None, "left", "left"),
            right=OnlyCalculationReference(None, "right", "right"),
        )
        actual = evaluate(resolved, {"left": left, "right": right})["value"]
        expected = tuple(getattr(canonical, operation)(a, b) for a, b in zip(left, right, strict=True))
        assert actual == expected
