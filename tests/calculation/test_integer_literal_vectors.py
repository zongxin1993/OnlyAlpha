from __future__ import annotations

import csv
import io
import subprocess
import sys
from pathlib import Path
from typing import Protocol, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pytest

from onlyalpha.calculation.definition import OnlyCalculationKind, OnlyCalculationReference, OnlyCalculationTypeReference
from onlyalpha.calculation.registry import OnlyCalculationRegistry, OnlyTradingCalculationBackendResolver
from onlyalpha.research.calculation.backend import OnlyResearchCalculationBackendResolver
from onlyalpha.research.calculation.predicate import only_register_research_predicate_primitives
from onlyalpha.runtime.trading.predicate import only_register_trading_predicate_primitives


class _Incremental(Protocol):
    def update(self, inputs: dict[str, object]) -> dict[str, object]: ...


ROOT = Path(__file__).resolve().parents[2]


def test_integer_literal_vector_bytes_have_an_independent_guard() -> None:
    subprocess.run([sys.executable, str(ROOT / "scripts/integer_literal_vectors.py"), "--check"], check=True)


@pytest.mark.parametrize("reverse", [False, True])
def test_registered_integer_literals_preserve_exact_parameters_and_order(reverse: bool) -> None:
    rows = list(
        csv.DictReader(io.StringIO((ROOT / "test-data/predicate/integer-literal-v1.tsv").read_text()), delimiter="\t")
    )
    assert len(rows) == 408
    assert len({row["case_id"] for row in rows}) == len(rows)
    assert {row["type_id"] for row in rows} == {
        f"onlyalpha.predicate.internal.compare.{op}.integer.literal" for op in ("eq", "ne", "lt", "le", "gt", "ge")
    }
    if reverse:
        rows.reverse()
    registry = OnlyCalculationRegistry()
    only_register_trading_predicate_primitives(registry)
    only_register_research_predicate_primitives(registry)
    for row in rows:
        literal = int(row["literal"])
        literal_left = row["literal_left"] == "true"
        value = None if row["input"] == "null" else int(row["input"])
        expected = {"true": True, "false": False, "null": None}[row["expected"]]
        reference = OnlyCalculationTypeReference(OnlyCalculationKind.PREDICATE, row["type_id"], "1")
        bindings = {"left": OnlyCalculationReference(None, "left", "bar.close")}
        definition = registry.rematerialize_definition(
            reference, {"literal": literal, "literal_left": literal_left}, bindings
        )
        assert dict(definition.parameters) == {"literal": literal, "literal_left": literal_left}
        if not literal_left:
            default = registry.rematerialize_definition(reference, {"literal": literal}, bindings)
            assert default == definition
        for _ in range(2):
            backend = cast(_Incremental, OnlyTradingCalculationBackendResolver(registry).create(definition, object()))
            for _ in range(2):
                assert backend.update({"left": value})["value"] is expected
        if -(2**63) <= literal < 2**63 and (value is None or -(2**63) <= value < 2**63):
            research = OnlyResearchCalculationBackendResolver(registry).resolve(definition)
            actual = research.provider.execute(definition, {"left": pa.array([value, value], type=pa.int64())})[
                "value"
            ].to_pylist()
            assert all(item is expected for item in actual)


@pytest.mark.parametrize(
    "parameters", [{}, {"literal": None}, {"literal": True}, {"literal": 1.5}, {"literal": 0, "literal_left": "true"}]
)
def test_integer_literal_parameter_admission_rejects_missing_or_wrong_values(parameters: dict[str, object]) -> None:
    registry = OnlyCalculationRegistry()
    only_register_trading_predicate_primitives(registry)
    for op in ("eq", "ne", "lt", "le", "gt", "ge"):
        with pytest.raises((ValueError, TypeError)):
            registry.rematerialize_definition(
                OnlyCalculationTypeReference(
                    OnlyCalculationKind.PREDICATE, f"onlyalpha.predicate.internal.compare.{op}.integer.literal", "1"
                ),
                parameters,
                {"left": OnlyCalculationReference(None, "left", "bar.close")},
            )
