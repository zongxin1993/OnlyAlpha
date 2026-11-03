from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_native_execution_comparison_does_not_load_legacy_backend() -> None:
    code = """
import builtins,runpy,sys
original=builtins.__import__
def guarded(name,*args,**kwargs):
    assert name!='onlyalpha' and not name.startswith('onlyalpha.'),name
    return original(name,*args,**kwargs)
builtins.__import__=guarded
module=runpy.run_path(sys.argv[1])
module['compare_native_outputs'](module['EXPECTED'])
"""
    result = subprocess.run(
        [sys.executable, "-B", "-I", "-c", code, str(ROOT / "scripts/execution_reference_check.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("mutation", ["missing", "reordered", "cash_delta", "fees", "cost_after", "quantity_after"])
def test_independent_execution_values_refuse_changed_outputs(mutation: str) -> None:
    from scripts.execution_reference_check import EXPECTED, compare_native_outputs

    rows = copy.deepcopy(EXPECTED)
    if mutation == "missing":
        rows.pop()
    elif mutation == "reordered":
        rows.reverse()
    else:
        rows[0][mutation] = "99999"
    with pytest.raises(ValueError):
        compare_native_outputs(rows)
