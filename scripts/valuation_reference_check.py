"""Check native Position valuation against independent exact-cost literals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def compare_native(root: Path, outputs: list[dict[str, Any]]) -> None:
    cases = [json.loads(line) for line in (root / "test-data/position/valuation-v1.jsonl").read_text().splitlines()]
    if len(outputs) != len(cases):
        raise ValueError("VALUATION_REFERENCE_CARDINALITY")
    for case, output in zip(cases, outputs, strict=True):
        if output != {key: case[key] for key in ("case", "market", "unrealized")}:
            raise ValueError("VALUATION_LITERAL_VECTOR_MISMATCH")
