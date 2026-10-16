from __future__ import annotations

import csv
import io
import subprocess
import sys
from pathlib import Path
from typing import Protocol, cast

import pyarrow as pa  # type: ignore[import-untyped]  # PyArrow ships no type marker.
import pytest

from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationDataType,
    OnlyCalculationKind,
    OnlyCalculationReference,
    OnlyCalculationTypeReference,
    OnlyMissingValuePolicy,
    OnlyPreReadyOutput,
    OnlyTimestampSemantic,
)
from onlyalpha.calculation.implementation import OnlyCalculationStateCapability
from onlyalpha.calculation.registry import OnlyCalculationRegistry, OnlyTradingCalculationBackendResolver
from onlyalpha.research.calculation.backend import OnlyResearchCalculationBackendResolver
from onlyalpha.research.calculation.predicate import only_register_research_predicate_primitives
from onlyalpha.runtime.trading.predicate import only_register_trading_predicate_primitives

_ROOT = Path(__file__).resolve().parents[2]
_CORPUS = _ROOT / "test-data/predicate/boolean-v1.tsv"


class _Incremental(Protocol):
    def update(self, inputs: dict[str, object]) -> dict[str, object]: ...


def _rows() -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(_CORPUS.read_text(encoding="utf-8")), delimiter="\t"))


def test_predicate_vector_bytes_match_independent_truth_table() -> None:
    subprocess.run([sys.executable, str(_ROOT / "scripts/predicate_vectors.py"), "--check"], check=True)
    rows = _rows()
    assert len(rows) == 30
    assert len({row["case_id"] for row in rows}) == 30
    assert {row["semantic_version"] for row in rows} == {"1"}
    assert {row["type_id"] for row in rows} == {
        f"onlyalpha.predicate.internal.{name}"
        for name in (
            "boolean.and",
            "boolean.or",
            "boolean.not",
            "terminal.eligibility",
            "terminal.entry_signal",
            "terminal.exit_signal",
        )
    }


@pytest.mark.parametrize("reverse", [False, True])
def test_registered_predicate_backends_match_recorded_vectors_after_replay(reverse: bool) -> None:
    registry = OnlyCalculationRegistry()
    only_register_trading_predicate_primitives(registry)
    only_register_research_predicate_primitives(registry)
    tokens: dict[str, object] = {"true": True, "false": False, "null": None}
    rows = _rows()
    if reverse:
        rows.reverse()
    # Group without reordering rows inside a semantic type. Repeated rows must not acquire state.
    for type_id in dict.fromkeys(row["type_id"] for row in rows):
        cases = [row for row in rows if row["type_id"] == type_id]
        keys = ("left", "right") if type_id.endswith((".and", ".or")) else ("value",)
        inputs = [dict(zip(keys, [tokens[row["left"]], tokens[row["right"]]], strict=False)) for row in cases]
        reference = OnlyCalculationTypeReference(OnlyCalculationKind.PREDICATE, type_id, "1")
        definition = registry.rematerialize_definition(
            reference, {}, {key: OnlyCalculationReference(None, key, "bar.close") for key in keys}
        )
        registration = registry.resolve(definition.kind, type_id, "1", OnlyCalculationBackendKind.TRADING)
        assert registration.state_capability is OnlyCalculationStateCapability.STATELESS
        assert registration.checkpoint_schema_version is None
        role = type_id.rsplit(".", 1)[-1]
        assert definition.outputs[0].semantic_type == (role.upper() if ".terminal." in type_id else "PREDICATE_VALUE")
        assert definition.type_id == type_id and definition.semantic_version == "1"
        assert not definition.parameters
        assert definition.missing_values is OnlyMissingValuePolicy.PROPAGATE
        assert definition.timestamp is OnlyTimestampSemantic.EVENT_TIME
        assert definition.warmup.minimum_observations == 1
        assert definition.warmup.initialization == "UPSTREAM"
        assert definition.warmup.pre_ready_output is OnlyPreReadyOutput.NULL
        assert all(item.data_type is OnlyCalculationDataType.BOOLEAN and item.nullable for item in definition.inputs)
        assert all(item.data_type is OnlyCalculationDataType.BOOLEAN and item.nullable for item in definition.outputs)
        expected = [tokens[row["expected"]] for row in cases]
        for _ in range(2):  # Fresh instances reproduce the same result; no checkpoint or clock is needed.
            backend = cast(_Incremental, OnlyTradingCalculationBackendResolver(registry).create(definition, object()))
            for _ in range(2):
                actual = [backend.update(row)["value"] for row in inputs]
                assert all(value is want for value, want in zip(actual, expected, strict=True))
            research_registry = OnlyCalculationRegistry()
            only_register_research_predicate_primitives(research_registry)
            research = OnlyResearchCalculationBackendResolver(research_registry).resolve(definition)
            batch = {key: pa.array([row[key] for row in inputs], type=pa.bool_()) for key in keys}
            actual = research.provider.execute(definition, batch)["value"].to_pylist()
            assert all(value is want for value, want in zip(actual, expected, strict=True))


@pytest.mark.parametrize(
    "type_id,version",
    [
        ("onlyalpha.predicate.internal.boolean.and", "2"),
        ("onlyalpha.predicate.internal.boolean.unknown", "1"),
        ("onlyalpha.predicate.internal.terminal.unknown", "1"),
    ],
)
def test_predicate_vector_identity_cannot_resolve_by_fallback(type_id: str, version: str) -> None:
    registry = OnlyCalculationRegistry()
    only_register_trading_predicate_primitives(registry)
    with pytest.raises(ValueError, match="unknown semantic version|unknown calculation type"):
        registry.resolve(OnlyCalculationKind.PREDICATE, type_id, version, OnlyCalculationBackendKind.TRADING)
