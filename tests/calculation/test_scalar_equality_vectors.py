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


def scalar(token: str) -> bool | str | None:
    if token.startswith("utf8:"):
        return bytes.fromhex(token[5:]).decode("utf-8")
    return {"true": True, "false": False, "null": None}[token]


def test_scalar_equality_bytes_are_independently_guarded() -> None:
    subprocess.run([sys.executable, str(ROOT / "scripts/scalar_equality_vectors.py"), "--check"], check=True)


@pytest.mark.parametrize("reverse", [False, True])
def test_registered_equality_preserves_typed_values_exact_unicode_and_missing(reverse: bool) -> None:
    rows = list(
        csv.DictReader(io.StringIO((ROOT / "test-data/predicate/scalar-equality-v1.tsv").read_text()), delimiter="\t")
    )
    assert len(rows) == 250
    assert len({row["case_id"] for row in rows}) == len(rows)
    assert {row["type_id"] for row in rows} == {
        f"onlyalpha.predicate.internal.compare.{op}.{family}.{layout}"
        for family in ("boolean", "string")
        for op in ("eq", "ne")
        for layout in ("refs", "literal")
    }
    if reverse:
        rows.reverse()
    registry = OnlyCalculationRegistry()
    only_register_trading_predicate_primitives(registry)
    only_register_research_predicate_primitives(registry)
    for row in rows:
        literal = row["type_id"].endswith(".literal")
        names = ("left",) if literal else ("left", "right")
        inputs = {name: scalar(row[name]) for name in names}
        parameters = (
            {"literal": scalar(row["literal"]), "literal_left": row["literal_left"] == "true"} if literal else {}
        )
        reference = OnlyCalculationTypeReference(OnlyCalculationKind.PREDICATE, row["type_id"], "1")
        bindings = {name: OnlyCalculationReference(None, name, "bar.close") for name in names}
        definition = registry.rematerialize_definition(reference, parameters, bindings)
        assert dict(definition.parameters) == parameters
        if literal and not parameters["literal_left"]:
            assert (
                registry.rematerialize_definition(reference, {"literal": parameters["literal"]}, bindings) == definition
            )
        expected = {"true": True, "false": False, "null": None}[row["expected"]]
        for _ in range(2):
            backend = cast(_Incremental, OnlyTradingCalculationBackendResolver(registry).create(definition, object()))
            for _ in range(2):
                assert backend.update(inputs)["value"] is expected
        arrow_type = pa.bool_() if ".boolean." in row["type_id"] else pa.string()
        research = OnlyResearchCalculationBackendResolver(registry).resolve(definition)
        actual = research.provider.execute(
            definition, {name: pa.array([value, value], type=arrow_type) for name, value in inputs.items()}
        )["value"].to_pylist()
        assert len(actual) == 2
        assert all(value is expected for value in actual)
