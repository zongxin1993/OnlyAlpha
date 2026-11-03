"""Check native performance output against independent literal vectors."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def compare_native(root: Path, outputs: list[dict[str, Any]]) -> None:
    vectors = [json.loads(line) for line in (root / "test-data/account/performance-v1.jsonl").read_text().splitlines()]
    if len(outputs) != len(vectors):
        raise ValueError("PERFORMANCE_REFERENCE_CARDINALITY")
    for vector, output in zip(vectors, outputs, strict=True):
        if output != {"case": vector["case"], "summary": vector["expected"]}:
            raise ValueError("PERFORMANCE_LITERAL_MISMATCH")
