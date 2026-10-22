"""Current Strategy source identities; no Freeze or execution admission."""

import json
from pathlib import Path
from typing import Any

import pytest

from onlyalpha.strategy.revision import OnlyStrategyRevision

ROWS = [
    json.loads(line)
    for line in (Path(__file__).resolve().parents[2] / "test-data/strategy/product-sources-v1.jsonl")
    .read_text()
    .splitlines()
]


@pytest.mark.parametrize("row", ROWS, ids=[r["case"] for r in ROWS])
def test_current_strategy_source_identity(row: dict[str, Any]) -> None:
    source = OnlyStrategyRevision.from_dict(row["record"])
    assert source.to_dict() == row["record"]
    assert str(source.strategy_fingerprint) == row["fingerprint"]
