from decimal import (
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    Clamped,
    Decimal,
    DivisionByZero,
    FloatOperation,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
    Subnormal,
    Underflow,
    getcontext,
    localcontext,
)

import pytest

from onlyalpha.calculation import (
    ONLY_DECIMAL_EXECUTION_POLICY_V1,
    OnlyNumericDefinition,
    only_decimal_context,
    only_decimal_execution_semantic_dependency,
    only_quantize_decimal,
)

_SIGNALS = (
    InvalidOperation,
    FloatOperation,
    DivisionByZero,
    Overflow,
    Underflow,
    Subnormal,
    Inexact,
    Rounded,
    Clamped,
)


def test_decimal_execution_policy_v1_is_exact_and_content_addressed() -> None:
    policy = ONLY_DECIMAL_EXECUTION_POLICY_V1
    assert policy.policy_id == "onlyalpha.decimal.execution"
    assert policy.semantic_version == "1"
    assert (policy.emin, policy.emax, policy.capitals, policy.clamp) == (-999999, 999999, 1, 0)
    assert policy.trapped_signals == ("DivisionByZero", "InvalidOperation", "Overflow")
    assert policy.fingerprint == "3d3121619656961d4c985e82cc5a88139b4139065af415caac346a041df29f32"
    dependency = only_decimal_execution_semantic_dependency()
    assert (dependency.dependency_id, dependency.semantic_version, dependency.artifact_fingerprint) == (
        policy.policy_id,
        policy.semantic_version,
        policy.fingerprint,
    )


def test_decimal_context_constructs_every_execution_field_explicitly() -> None:
    context = only_decimal_context(OnlyNumericDefinition("DECIMAL", 28, Decimal("0.000000000001"), "ROUND_HALF_EVEN"))
    assert (context.prec, context.rounding) == (28, ROUND_HALF_EVEN)
    assert (context.Emin, context.Emax, context.capitals, context.clamp) == (-999999, 999999, 1, 0)
    assert {signal.__name__ for signal, trapped in context.traps.items() if trapped} == {
        "InvalidOperation",
        "DivisionByZero",
        "Overflow",
    }
    assert set(context.flags) == set(_SIGNALS)
    assert not any(context.flags.values())


def test_quantization_ignores_hostile_context_and_preserves_caller_flags() -> None:
    numeric = OnlyNumericDefinition("DECIMAL", 28, Decimal("0.000000000001"), "ROUND_HALF_EVEN")
    expected = only_quantize_decimal(numeric, Decimal("0.3333333333333333333333333333"))
    with localcontext() as caller:
        caller.prec = 4
        caller.rounding = ROUND_DOWN
        caller.Emin = -5
        caller.Emax = 5
        caller.clamp = 1
        for signal in _SIGNALS:
            caller.traps[signal] = signal in {Inexact, Rounded, Underflow, Subnormal}
            caller.flags[signal] = True
        flags_before = dict(caller.flags)
        assert only_quantize_decimal(numeric, Decimal("0.3333333333333333333333333333")) == expected
        assert dict(getcontext().flags) == flags_before


def test_unrepresentable_result_has_the_same_deterministic_failure_under_hostile_context() -> None:
    numeric = OnlyNumericDefinition("DECIMAL", 28, Decimal("0.000000000001"), "ROUND_HALF_EVEN")

    def failure(hostile: bool) -> tuple[object, ...]:
        with localcontext() as caller:
            if hostile:
                caller.prec = 2
                caller.rounding = ROUND_DOWN
                caller.Emin = -2
                caller.Emax = 2
                caller.clamp = 1
                caller.traps[Inexact] = True
                caller.flags[Rounded] = True
            with pytest.raises(InvalidOperation) as captured:
                only_quantize_decimal(numeric, Decimal("1E1000000"))
            return captured.value.args

    assert failure(False) == failure(True)
