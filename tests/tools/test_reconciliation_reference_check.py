from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.reconciliation_reference_check import compare_native

ROOT = Path(__file__).resolve().parents[2]


def outputs() -> list[dict]:
    cases = [
        json.loads(line) for line in (ROOT / "test-data/execution/reconciliation-v1.jsonl").read_text().splitlines()
    ]
    return [{key: row[key] for key in ("case", "totals", "status", "difference_fields")} for row in cases]


def test_actual_python_common_reference_and_native_literal_corpus() -> None:
    compare_native(ROOT, outputs())


def test_reference_rejects_missing_reordered_and_numerically_wrong_native_outputs() -> None:
    good = outputs()
    wrong = copy.deepcopy(good)
    wrong[1]["totals"]["fees"]["account_value"] = "0.00"
    for bad in (good[:-1], list(reversed(good)), wrong):
        with pytest.raises(ValueError, match="RECONCILIATION_"):
            compare_native(ROOT, bad)
