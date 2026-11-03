"""Check native Ledger reconciliation output against independent literal vectors."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def compare_native(root: Path, outputs: list[dict[str, Any]]) -> None:
    vectors = [
        json.loads(line) for line in (root / "test-data/execution/reconciliation-v1.jsonl").read_text().splitlines()
    ]
    if len(outputs) != len(vectors):
        raise ValueError("RECONCILIATION_REFERENCE_CARDINALITY")
    for vector, output in zip(vectors, outputs, strict=True):
        expected = {key: vector[key] for key in ("case", "totals", "status", "difference_fields")}
        if output != expected:
            raise ValueError("RECONCILIATION_LITERAL_VECTOR_MISMATCH")
