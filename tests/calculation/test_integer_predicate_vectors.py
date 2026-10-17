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


def test_integer_vector_bytes_have_an_independent_guard() -> None:
    subprocess.run([sys.executable, str(ROOT / "scripts/integer_predicate_vectors.py"), "--check"], check=True)


@pytest.mark.parametrize("reverse", [False, True])
def test_registered_integer_comparisons_preserve_exact_large_values_and_order(reverse: bool) -> None:
    rows = list(
        csv.DictReader(io.StringIO((ROOT / "test-data/predicate/integer-refs-v1.tsv").read_text()), delimiter="\t")
    )
    assert len({row["case_id"] for row in rows}) == len(rows)
    assert {row["type_id"] for row in rows} == {
        f"onlyalpha.predicate.internal.compare.{op}.integer.refs" for op in ("eq", "ne", "lt", "le", "gt", "ge")
    }
    if reverse:
        rows.reverse()
    registry = OnlyCalculationRegistry()
    only_register_trading_predicate_primitives(registry)
    only_register_research_predicate_primitives(registry)
    for type_id in dict.fromkeys(row["type_id"] for row in rows):
        cases = [row for row in rows if row["type_id"] == type_id]
        definition = registry.rematerialize_definition(
            OnlyCalculationTypeReference(OnlyCalculationKind.PREDICATE, type_id, "1"),
            {},
            {key: OnlyCalculationReference(None, key, "bar.close") for key in ("left", "right")},
        )
        inputs = [{key: None if row[key] == "null" else int(row[key]) for key in ("left", "right")} for row in cases]
        expected = [{"true": True, "false": False, "null": None}[row["expected"]] for row in cases]
        assert not definition.parameters
        for _ in range(2):
            backend = cast(_Incremental, OnlyTradingCalculationBackendResolver(registry).create(definition, object()))
            for _ in range(2):
                actual = [backend.update(row)["value"] for row in inputs]
                assert all(value is want for value, want in zip(actual, expected, strict=True))
        # Research's existing int64 transport envelope is narrower than Python int.
        selected = [
            (row, want)
            for row, want in zip(inputs, expected, strict=True)
            if all(value is None or -(2**63) <= value < 2**63 for value in row.values())
        ]
        research = OnlyResearchCalculationBackendResolver(registry).resolve(definition)
        batch = {key: pa.array([row[key] for row, _ in selected], type=pa.int64()) for key in ("left", "right")}
        actual = research.provider.execute(definition, batch)["value"].to_pylist()
        assert all(value is want for value, (_, want) in zip(actual, selected, strict=True))
