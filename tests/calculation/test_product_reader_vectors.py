"""Current Product Definition2/Graph1 identities from the owning Python models."""

import json
from pathlib import Path
from typing import Any

import pytest

from onlyalpha.calculation.definition import OnlyCalculationDefinition
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition
from onlyalpha.canonical import only_canonical_payload

ROWS = [
    json.loads(line)
    for line in (Path(__file__).resolve().parents[2] / "test-data/calculation/product-readers-v1.jsonl")
    .read_text()
    .splitlines()
]


@pytest.mark.parametrize("row", ROWS, ids=[row["case"] for row in ROWS])
def test_current_product_serializer_and_identity(row: dict[str, Any]) -> None:
    if str(row["case"]).startswith("graph-"):
        graph = OnlyCalculationGraphDefinition.from_dict(row["input"])
        assert graph.to_dict() == row["record"]
        assert graph.fingerprint == row["fingerprint"]
        return
    model = OnlyCalculationDefinition.from_dict(row["input"])
    assert model.to_dict() == row["record"]
    assert model.fingerprint == row["fingerprint"]
    if "semantic" in row:
        assert only_canonical_payload(model.semantic_payload()) == row["semantic"]
