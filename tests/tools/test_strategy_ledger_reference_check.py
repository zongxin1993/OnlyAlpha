from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def outputs() -> list[dict[str, object]]:
    rows = [
        json.loads(line) for line in (ROOT / "test-data/strategy-ledger/valuation-v1.jsonl").read_text().splitlines()
    ]
    return [
        {"case": row["case"], "cluster": trade["cluster"], **trade["expected"]}
        for row in rows
        for trade in row["trades"]
    ]


def test_native_ledger_literals_do_not_load_legacy_backend() -> None:
    code = """
import builtins,json,runpy,sys
original=builtins.__import__
def guarded(name,*args,**kwargs):
    assert name!='onlyalpha' and not name.startswith('onlyalpha.'),name
    return original(name,*args,**kwargs)
builtins.__import__=guarded
module=runpy.run_path(sys.argv[1])
module['compare_native_outputs'](json.load(sys.stdin))
"""
    result = subprocess.run(
        [sys.executable, "-B", "-I", "-c", code, str(ROOT / "scripts/strategy_ledger_reference_check.py")],
        input=json.dumps(outputs()),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_ledger_literals_refuse_missing_reordered_or_wrong_cluster_cost() -> None:
    from scripts.strategy_ledger_reference_check import compare_native_outputs

    good = outputs()
    wrong = copy.deepcopy(good)
    wrong[0]["position_cost"] = "200.00"
    for bad in (good[:-1], list(reversed(good)), wrong):
        with pytest.raises(ValueError):
            compare_native_outputs(bad)
