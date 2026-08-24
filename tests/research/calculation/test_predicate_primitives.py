from __future__ import annotations

from decimal import Decimal

import pyarrow as pa

from onlyalpha.calculation import OnlyCalculationReference, OnlyCalculationRegistry
from onlyalpha.research.calculation import OnlyResearchCalculationBackendResolver
from onlyalpha.research.calculation.predicate import (
    only_register_research_predicate_primitives,
    only_research_predicate_type_reference,
)


def _execute(
    registry: OnlyCalculationRegistry,
    name: str,
    inputs: dict[str, pa.Array],
    parameters: dict[str, object] | None = None,
) -> list[object]:
    reference = only_research_predicate_type_reference(name)
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
    assert registry.resolve_type(only_research_predicate_type_reference("terminal.entry_signal")) in definitions


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
