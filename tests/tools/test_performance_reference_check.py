import json
from pathlib import Path

import pytest

from scripts.performance_reference_check import compare_native

ROOT = Path(__file__).resolve().parents[2]


def outputs():
    return [
        {"case": v["case"], "summary": v["expected"]}
        for v in (
            json.loads(line) for line in (ROOT / "test-data/account/performance-v1.jsonl").read_text().splitlines()
        )
    ]


def test_actual_python_common_and_independent_native_literals():
    compare_native(ROOT, outputs())


def test_missing_reordered_and_wrong_values_are_not_equivalence():
    rows = outputs()
    for bad in [rows[:-1], list(reversed(rows))]:
        with pytest.raises(ValueError):
            compare_native(ROOT, bad)
    rows[0]["summary"]["final_equity"] = "999.00"
    with pytest.raises(ValueError):
        compare_native(ROOT, rows)
