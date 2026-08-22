from __future__ import annotations

from copy import deepcopy

import pytest
from onlyalpha_api.research.schema import (
    ResearchCalculationGraphDto,
    ResearchGraphDefinitionDto,
    ResearchGraphReferenceDto,
)
from pydantic import ValidationError

A = "a" * 64
B = "b" * 64


def _definition() -> dict[str, object]:
    return {
        "schema_version": 2,
        "kind": "INDICATOR",
        "type_id": "test.indicator",
        "semantic_version": "1",
        "parameters": {},
        "inputs": [],
        "input_bindings": {},
        "outputs": [],
        "warmup": {
            "minimum_observations": 1,
            "ready_condition": "ready",
            "pre_ready_output": "NULL",
            "initialization": "UPSTREAM",
        },
        "missing_values": "PROPAGATE",
        "timestamp": "EVENT_TIME",
        "numeric": {"representation": "DECIMAL", "precision": 12, "output_quantum": None, "rounding": "HALF_EVEN"},
        "factor_kind": None,
        "extensions": {},
    }


def test_graph_transport_validators_fail_closed_for_ambiguous_or_dangling_topology() -> None:
    for values in (
        {"node_fingerprint": None, "output_name": "close", "source": None},
        {"node_fingerprint": A, "output_name": "value", "source": "bar.close"},
    ):
        with pytest.raises(ValidationError, match="exactly one"):
            ResearchGraphReferenceDto.model_validate(values)

    duplicate_ports = _definition()
    duplicate_ports["inputs"] = [
        {
            "name": "x",
            "data_type": "DECIMAL",
            "nullable": True,
            "dimensions": [],
            "semantic_type": "VALUE",
            "unit": None,
        },
        {
            "name": "x",
            "data_type": "DECIMAL",
            "nullable": True,
            "dimensions": [],
            "semantic_type": "VALUE",
            "unit": None,
        },
    ]
    duplicate_ports["input_bindings"] = {"x": {"node_fingerprint": None, "output_name": "close", "source": "bar.close"}}
    with pytest.raises(ValidationError, match="ports must be unique"):
        ResearchGraphDefinitionDto.model_validate(duplicate_ports)

    factor_mismatch = _definition()
    factor_mismatch["factor_kind"] = "TIME_SERIES"
    with pytest.raises(ValidationError, match="factor_kind"):
        ResearchGraphDefinitionDto.model_validate(factor_mismatch)

    node = {"node_fingerprint": A, "definition": _definition(), "alias": None}
    with pytest.raises(ValidationError, match="nodes must be unique"):
        ResearchCalculationGraphDto.model_validate({"schema_version": 1, "nodes": [node, deepcopy(node)]})

    dependent = _definition()
    dependent["inputs"] = [
        {
            "name": "x",
            "data_type": "DECIMAL",
            "nullable": True,
            "dimensions": [],
            "semantic_type": "VALUE",
            "unit": None,
        }
    ]
    dependent["input_bindings"] = {"x": {"node_fingerprint": B, "output_name": "value", "source": None}}
    with pytest.raises(ValidationError, match="dependency is missing"):
        ResearchCalculationGraphDto.model_validate(
            {"schema_version": 1, "nodes": [{"node_fingerprint": A, "definition": dependent, "alias": None}]}
        )
