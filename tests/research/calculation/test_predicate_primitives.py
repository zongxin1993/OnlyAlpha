from __future__ import annotations

from decimal import Decimal

import pyarrow as pa

from onlyalpha.calculation import (
    OnlyCalculationBackendKind,
    OnlyCalculationReference,
    OnlyCalculationRegistry,
    OnlyCanonicalValueSemanticsV1,
)
from onlyalpha.calculation.definition import OnlyNumericDefinition
from onlyalpha.research.calculation import OnlyResearchCalculationBackendResolver
from onlyalpha.research.calculation.predicate import (
    only_predicate_type_reference,
    only_register_research_predicate_primitives,
)
from onlyalpha.runtime.trading.predicate import only_register_trading_predicate_primitives


def _execute(
    registry: OnlyCalculationRegistry,
    name: str,
    inputs: dict[str, pa.Array],
    parameters: dict[str, object] | None = None,
) -> list[object]:
    reference = only_predicate_type_reference(name)
    bindings = {key: OnlyCalculationReference(None, key, "bar.close") for key in inputs}
    definition = registry.rematerialize_definition(reference, parameters or {}, bindings)
    backend = OnlyResearchCalculationBackendResolver(registry).resolve(definition)
    return backend.provider.execute(definition, inputs)["value"].to_pylist()


def test_predicate_registration_is_complete_idempotent_and_resolvable() -> None:
    registry = OnlyCalculationRegistry()
    only_register_research_predicate_primitives(registry)
    only_register_research_predicate_primitives(registry)

    definitions = registry.type_definitions()
    assert len(definitions) == 38
    assert all(item.type_id.startswith("onlyalpha.predicate.internal.") for item in definitions)
    assert registry.resolve_type(only_predicate_type_reference("terminal.entry_signal")) in definitions


def test_predicate_boolean_and_terminal_primitives_preserve_three_valued_truth() -> None:
    registry = OnlyCalculationRegistry()
    only_register_research_predicate_primitives(registry)
    left = pa.array([True, True, False, False, None, None], type=pa.bool_())
    right = pa.array([True, None, False, None, True, None], type=pa.bool_())

    assert _execute(registry, "boolean.and", {"left": left, "right": right}) == [
        True,
        None,
        False,
        False,
        None,
        None,
    ]
    assert _execute(registry, "boolean.or", {"left": left, "right": right}) == [
        True,
        True,
        False,
        None,
        True,
        None,
    ]
    assert _execute(registry, "boolean.not", {"value": pa.array([True, False, None], type=pa.bool_())}) == [
        False,
        True,
        None,
    ]
    for role in ("eligibility", "entry_signal", "exit_signal"):
        assert _execute(registry, f"terminal.{role}", {"value": left}) == left.to_pylist()


def test_predicate_comparisons_cover_every_operator_layout_and_operand_type() -> None:
    registry = OnlyCalculationRegistry()
    only_register_research_predicate_primitives(registry)
    decimal_values = pa.array([Decimal("1"), Decimal("2"), None], type=pa.decimal128(38, 12))
    decimal_right = pa.array([Decimal("2"), Decimal("2"), Decimal("3")], type=pa.decimal128(38, 12))
    expected = {
        "eq": [False, True, None],
        "ne": [True, False, None],
        "lt": [True, False, None],
        "le": [True, True, None],
        "gt": [False, False, None],
        "ge": [False, True, None],
    }
    for operator, values in expected.items():
        assert (
            _execute(
                registry,
                f"compare.{operator}.decimal.refs",
                {"left": decimal_values, "right": decimal_right},
            )
            == values
        )

    integers = pa.array([1, 2, None], type=pa.int64())
    assert _execute(
        registry,
        "compare.lt.integer.literal",
        {"left": integers},
        {"literal": 2, "literal_left": False},
    ) == [True, False, None]
    assert _execute(
        registry,
        "compare.gt.integer.literal",
        {"left": integers},
        {"literal": 2, "literal_left": True},
    ) == [True, False, None]
    assert _execute(
        registry,
        "compare.ne.string.literal",
        {"left": pa.array(["a", "b", None])},
        {"literal": "b", "literal_left": False},
    ) == [True, False, None]
    assert _execute(
        registry,
        "compare.eq.boolean.refs",
        {
            "left": pa.array([True, False, None]),
            "right": pa.array([True, True, False]),
        },
    ) == [True, False, None]


def _execute_trading(
    registry: OnlyCalculationRegistry,
    name: str,
    rows: tuple[dict[str, object], ...],
    parameters: dict[str, object] | None = None,
) -> list[object]:
    reference = only_predicate_type_reference(name)
    bindings = {key: OnlyCalculationReference(None, key, "bar.close") for key in rows[0]}
    definition = registry.rematerialize_definition(reference, parameters or {}, bindings)
    registration = registry.resolve(
        definition.kind,
        definition.type_id,
        definition.semantic_version,
        OnlyCalculationBackendKind.TRADING,
    )
    backend = registration.provider.create(definition, object())
    return [backend.update(row)["value"] for row in rows]  # type: ignore[union-attr]


def test_research_and_trading_predicates_conform_to_canonical_decimal_and_boolean_semantics() -> None:
    decimals = ((Decimal("1"), Decimal("2")), (Decimal("2"), Decimal("2")), (None, Decimal("3")))
    canonical = OnlyCanonicalValueSemanticsV1(OnlyNumericDefinition())
    for operator in ("eq", "ne", "lt", "le", "gt", "ge"):
        expected = [getattr(canonical, operator)(left, right) for left, right in decimals]
        research = OnlyCalculationRegistry()
        only_register_research_predicate_primitives(research)
        decimal_left = pa.array([left for left, _ in decimals], type=pa.decimal128(38, 12))
        decimal_right = pa.array([right for _, right in decimals], type=pa.decimal128(38, 12))
        assert (
            _execute(research, f"compare.{operator}.decimal.refs", {"left": decimal_left, "right": decimal_right})
            == expected
        )

        trading = OnlyCalculationRegistry()
        only_register_trading_predicate_primitives(trading)
        rows = tuple({"left": left, "right": right} for left, right in decimals)
        assert _execute_trading(trading, f"compare.{operator}.decimal.refs", rows) == expected

    boolean_cases = ((True, None), (None, False), (False, None), (None, None))
    for name, operation in (("and", "and_"), ("or", "or_")):
        expected = [getattr(canonical, operation)(left, right) for left, right in boolean_cases]
        research = OnlyCalculationRegistry()
        only_register_research_predicate_primitives(research)
        left = pa.array([item[0] for item in boolean_cases], type=pa.bool_())
        right = pa.array([item[1] for item in boolean_cases], type=pa.bool_())
        assert _execute(research, f"boolean.{name}", {"left": left, "right": right}) == expected
        trading = OnlyCalculationRegistry()
        only_register_trading_predicate_primitives(trading)
        rows = tuple({"left": left_value, "right": right_value} for left_value, right_value in boolean_cases)
        assert _execute_trading(trading, f"boolean.{name}", rows) == expected
