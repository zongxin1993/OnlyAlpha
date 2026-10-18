"""Common Definition semantics; Rust3 and Python2 identities are explicitly distinct."""

import hashlib
import json
from pathlib import Path

import pytest

from onlyalpha.calculation.definition import OnlyCalculationDefinition
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition, OnlyCalculationNodeDefinition

ROWS = [
    json.loads(line)
    for line in (Path(__file__).resolve().parents[2] / "test-data/calculation/definitions-v1.jsonl")
    .read_text()
    .splitlines()
]


@pytest.mark.parametrize("row", ROWS, ids=[row["case"] for row in ROWS])
def test_common_definition_values_roundtrip_and_independent_rust_identity(row: dict[str, object]) -> None:
    record = dict(row["record"])
    assert (
        hashlib.sha256(
            json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        == row["fingerprint"]
    )
    record["schema_version"] = 2
    definition = OnlyCalculationDefinition.from_dict(record)
    assert dict(definition.to_dict()) == record
    assert definition.type_id == "example.mean"
    assert definition.warmup.minimum_observations == 2
    graph = OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(definition, "display"),))
    renamed = OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(definition, "renamed"),))
    assert graph.fingerprint == renamed.fingerprint
    assert graph.ordered_nodes[0].definition == definition


PARAMETER_ROWS = [
    json.loads(line)
    for line in (Path(__file__).resolve().parents[2] / "test-data/calculation/parameters-v1.jsonl")
    .read_text()
    .splitlines()
]


@pytest.mark.parametrize("row", PARAMETER_ROWS, ids=[row["case"] for row in PARAMETER_ROWS])
def test_common_parameter_normalization(row: dict[str, object]) -> None:
    from onlyalpha.calculation.definition import (
        OnlyParameterDefinition,
        OnlyParameterSchema,
        OnlyParameterType,
        only_calculation_scalar_from_dict,
    )

    spec = row["parameter"]
    scalar = only_calculation_scalar_from_dict
    schema = OnlyParameterSchema(
        (
            OnlyParameterDefinition(
                spec["name"],
                OnlyParameterType(spec["parameter_type"]),
                spec["required"],
                scalar(spec["default"]),
                None if spec["minimum"] is None else scalar(spec["minimum"]),
                None if spec["maximum"] is None else scalar(spec["maximum"]),
                tuple(scalar(v) for v in spec["enum_values"]),
                spec["uppercase"],
            ),
        )
    )
    if row["expected"] is None:
        with pytest.raises((ValueError, ArithmeticError)):
            schema.normalize(row["provided"])
    else:
        assert schema.normalize(row["provided"])["value"] == scalar(row["expected"])
