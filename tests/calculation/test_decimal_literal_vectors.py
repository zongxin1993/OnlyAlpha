from __future__ import annotations

import csv
import subprocess
import sys
from collections.abc import Mapping
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Protocol, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pytest

from onlyalpha.calculation.definition import OnlyCalculationKind, OnlyCalculationReference, OnlyCalculationTypeReference
from onlyalpha.calculation.registry import OnlyCalculationRegistry, OnlyTradingCalculationBackendResolver
from onlyalpha.research.calculation.backend import OnlyResearchCalculationBackendResolver
from onlyalpha.research.calculation.predicate import only_register_research_predicate_primitives
from onlyalpha.runtime.trading.predicate import only_register_trading_predicate_primitives

ROOT = Path(__file__).resolve().parents[2]


class _Incremental(Protocol):
    def update(self, inputs: Mapping[str, object]) -> dict[str, object]: ...


def test_decimal_literal_vectors_have_an_independent_guard() -> None:
    subprocess.run([sys.executable, str(ROOT / "scripts/decimal_literal_vectors.py"), "--check"], check=True)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("precision", [2, 50])
def test_registered_decimal_literals_preserve_configuration_and_exact_results(reverse: bool, precision: int) -> None:
    with (ROOT / "test-data/predicate/decimal-literal-v1.tsv").open() as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    assert len(rows) == 504
    assert len({row["case_id"] for row in rows}) == len(rows)
    assert {row["type_id"] for row in rows} == {
        f"onlyalpha.predicate.internal.compare.{op}.decimal.literal" for op in ("eq", "ne", "lt", "le", "gt", "ge")
    }
    if reverse:
        rows.reverse()
    registry = OnlyCalculationRegistry()
    only_register_trading_predicate_primitives(registry)
    only_register_research_predicate_primitives(registry)
    bindings = {"left": OnlyCalculationReference(None, "left", "bar.close")}
    with localcontext() as context:
        context.prec = precision
        for row in rows:
            reference = OnlyCalculationTypeReference(OnlyCalculationKind.PREDICATE, row["type_id"], "1")
            literal = Decimal(row["literal"])
            position = row["literal_left"] == "true"
            definition = registry.rematerialize_definition(
                reference, {"literal": literal, "literal_left": position}, bindings
            )
            if not position:
                assert registry.rematerialize_definition(reference, {"literal": literal}, bindings) == definition
            normalized = definition.parameters["literal"]
            assert isinstance(normalized, Decimal)
            assert normalized.as_tuple() == literal.as_tuple()
            assert definition.parameters["literal_left"] is position
            value = None if row["input"] == "null" else Decimal(row["input"])
            expected = {"true": True, "false": False, "null": None}[row["expected"]]
            for _ in range(2):
                backend = cast(
                    _Incremental, OnlyTradingCalculationBackendResolver(registry).create(definition, object())
                )
                for _ in range(2):
                    assert backend.update({"left": value})["value"] is expected

            def representable(item: Decimal | None) -> bool:
                if item is None:
                    return True
                parts = item.as_tuple()
                return (
                    isinstance(parts.exponent, int)
                    and -18 <= parts.exponent <= 0
                    and len(parts.digits) + parts.exponent <= 20
                )

            if representable(value) and representable(literal):
                research = OnlyResearchCalculationBackendResolver(registry).resolve(definition)
                actual = research.provider.execute(
                    definition, {"left": pa.array([value, value], type=pa.decimal128(38, 18))}
                )["value"].to_pylist()
                assert len(actual) == 2
                assert all(item is expected for item in actual)


@pytest.mark.parametrize(
    "parameters", [{}, *({"literal": value} for value in (None, True, False, "NaN", "sNaN", "Infinity", "-Infinity"))]
)
def test_decimal_literal_invalid_configuration_fails_schema(parameters: Mapping[str, object]) -> None:
    registry = OnlyCalculationRegistry()
    only_register_trading_predicate_primitives(registry)
    with pytest.raises((ValueError, ArithmeticError)):
        registry.rematerialize_definition(
            OnlyCalculationTypeReference(
                OnlyCalculationKind.PREDICATE, "onlyalpha.predicate.internal.compare.eq.decimal.literal", "1"
            ),
            parameters,
            {"left": OnlyCalculationReference(None, "left", "bar.close")},
        )


@pytest.mark.parametrize("position", [None, 0, 1, "false", "true"])
def test_decimal_literal_position_requires_a_boolean(position: object) -> None:
    registry = OnlyCalculationRegistry()
    only_register_trading_predicate_primitives(registry)
    with pytest.raises(ValueError):
        registry.rematerialize_definition(
            OnlyCalculationTypeReference(
                OnlyCalculationKind.PREDICATE, "onlyalpha.predicate.internal.compare.eq.decimal.literal", "1"
            ),
            {"literal": Decimal("1.0"), "literal_left": position},
            {"left": OnlyCalculationReference(None, "left", "bar.close")},
        )
