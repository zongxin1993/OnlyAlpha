from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def outputs() -> list[dict[str, object]]:
    decisions = [json.loads(line) for line in (ROOT / "test-data/risk/decisions-v1.jsonl").read_text().splitlines()]
    reservations = [
        json.loads(line) for line in (ROOT / "test-data/risk/reservations-v1.jsonl").read_text().splitlines()
    ]
    return [
        *[{key: row[key] for key in ("case", "outcome", "observations")} for row in decisions],
        *[{"case": row["case"], **row["expected"]} for row in reservations],
    ]


def test_native_risk_comparison_does_not_load_legacy_backend() -> None:
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
        [sys.executable, "-B", "-I", "-c", code, str(ROOT / "scripts/risk_reference_check.py")],
        input=json.dumps(outputs()),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("mutation", ["missing", "reordered", "decision", "observation", "reservation"])
def test_risk_literals_refuse_changed_decision_or_reservation(mutation: str) -> None:
    from scripts.risk_reference_check import compare_native_outputs

    rows = copy.deepcopy(outputs())
    if mutation == "missing":
        rows.pop()
    elif mutation == "reordered":
        rows.reverse()
    elif mutation == "decision":
        rows[1]["outcome"] = "ACCEPT"
    elif mutation == "observation":
        rows[2]["observations"] = 0
    else:
        rows[3]["released_notional"] = "100.00"
    with pytest.raises(ValueError):
        compare_native_outputs(rows)
