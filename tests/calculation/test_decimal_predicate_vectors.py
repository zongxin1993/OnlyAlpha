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


def test_decimal_vector_bytes_have_an_independent_guard() -> None:
    subprocess.run([sys.executable, str(ROOT / "scripts/decimal_predicate_vectors.py"), "--check"], check=True)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("precision", [2, 50])
def test_registered_decimal_comparisons_preserve_exact_values_without_quantizing(reverse: bool, precision: int) -> None:
    with (ROOT / "test-data/predicate/decimal-refs-v1.tsv").open() as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    assert len(rows) == 264
    assert len({row["case_id"] for row in rows}) == len(rows)
    assert {row["type_id"] for row in rows} == {
        f"onlyalpha.predicate.internal.compare.{op}.decimal.refs" for op in ("eq", "ne", "lt", "le", "gt", "ge")
    }
    if reverse:
        rows.reverse()
    registry = OnlyCalculationRegistry()
    only_register_trading_predicate_primitives(registry)
    only_register_research_predicate_primitives(registry)
    with localcontext() as context:
        context.prec = precision
        for type_id in dict.fromkeys(row["type_id"] for row in rows):
            cases = [row for row in rows if row["type_id"] == type_id]
            definition = registry.rematerialize_definition(
                OnlyCalculationTypeReference(OnlyCalculationKind.PREDICATE, type_id, "1"),
                {},
                {key: OnlyCalculationReference(None, key, "bar.close") for key in ("left", "right")},
            )
            inputs = [
                {key: None if row[key] == "null" else Decimal(row[key]) for key in ("left", "right")} for row in cases
            ]
            expected = [{"true": True, "false": False, "null": None}[row["expected"]] for row in cases]
            for _ in range(2):
                backend = cast(
                    _Incremental, OnlyTradingCalculationBackendResolver(registry).create(definition, object())
                )
                for _ in range(2):
                    actual = [backend.update(row)["value"] for row in inputs]
                    assert all(value is want for value, want in zip(actual, expected, strict=True))

            # Explicit common Arrow decimal128(38,18) envelope, without rounding/casts.
            def representable(value: Decimal | None) -> bool:
                if value is None:
                    return True
                parts = value.as_tuple()
                return (
                    isinstance(parts.exponent, int)
                    and -18 <= parts.exponent <= 0
                    and len(parts.digits) + parts.exponent <= 20
                )

            selected = [
                (row, want)
                for row, want in zip(inputs, expected, strict=True)
                if all(representable(value) for value in row.values())
            ]
            assert len(selected) > 0
            research = OnlyResearchCalculationBackendResolver(registry).resolve(definition)
            batch = {
                key: pa.array([row[key] for row, _ in selected], type=pa.decimal128(38, 18))
                for key in ("left", "right")
            }
            actual = research.provider.execute(definition, batch)["value"].to_pylist()
            assert all(value is want for value, (_, want) in zip(actual, selected, strict=True))
