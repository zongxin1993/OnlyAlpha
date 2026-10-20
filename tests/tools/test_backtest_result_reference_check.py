import json
from pathlib import Path

import pytest

from scripts.backtest_result_reference_check import compare_native, python_common

ROOT = Path(__file__).resolve().parents[2]


def test_actual_python_result_common_literals():
    vectors = [
        json.loads(line) for line in (ROOT / "test-data/execution/backtest-result-v1.jsonl").read_text().splitlines()
    ]
    for vector in vectors:
        if vector["python_common"]:
            assert python_common(vector) == vector["expected"]


def test_missing_native_result_is_not_equivalence():
    with pytest.raises(ValueError, match="CARDINALITY"):
        compare_native(ROOT, [])
