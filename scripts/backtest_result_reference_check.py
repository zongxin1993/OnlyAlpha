"""Check native Result literals and canonical identities without a backend implementation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def compare_native(root: Path, outputs: list[dict[str, Any]]) -> None:
    vectors = [
        json.loads(line) for line in (root / "test-data/execution/backtest-result-v1.jsonl").read_text().splitlines()
    ]
    if len(outputs) != len(vectors):
        raise ValueError("BACKTEST_RESULT_REFERENCE_CARDINALITY")
    for vector, output in zip(vectors, outputs, strict=True):
        if output["case"] != vector["case"] or output["observed"] != vector["expected"]:
            raise ValueError("BACKTEST_RESULT_LITERAL_MISMATCH")
        content = dict(output["result"])
        identity = content.pop("id")
        if identity != "BTR-" + _digest(content):
            raise ValueError("BACKTEST_RESULT_CONTENT_IDENTITY")
        result_fp = content.pop("result_fingerprint")
        determinism = content.pop("determinism_fingerprint")
        if result_fp != determinism or result_fp != _digest(content):
            raise ValueError("BACKTEST_RESULT_BUSINESS_IDENTITY")
