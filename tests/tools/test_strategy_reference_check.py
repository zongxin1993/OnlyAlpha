"""Independent decision literals; the native bridge runner owns actual execution."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest


def test_strategy_comparer_imports_without_legacy_backend() -> None:
    code = """
import builtins, json
original = builtins.__import__
def guarded(name, *args, **kwargs):
    assert name != "onlyalpha" and not name.startswith("onlyalpha."), name
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from scripts.strategy_reference_check import compare_reference
rows = [{"minute": i, "eligibility": True, "entry": i > 3, "exit": False} for i in range(3, 7)]
compare_reference("STRATEGY_DECISIONS_JSON " + json.dumps(rows))
"""
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "reordered", "entry", "exit"])
def test_strategy_comparer_rejects_incomplete_or_wrong_decisions(mutation: str) -> None:
    from scripts.strategy_reference_check import compare_reference

    rows = [{"minute": i, "eligibility": True, "entry": i > 3, "exit": False} for i in range(3, 7)]
    if mutation == "reordered":
        rows.reverse()
    elif mutation in {"entry", "exit"}:
        rows[0][mutation] = not rows[0][mutation]
    output = "STRATEGY_DECISIONS_JSON " + json.dumps(rows)
    if mutation == "missing":
        output = "no native output"
    elif mutation == "duplicate":
        output += "\n" + output
    with pytest.raises((AssertionError, ValueError)):
        compare_reference(output)
