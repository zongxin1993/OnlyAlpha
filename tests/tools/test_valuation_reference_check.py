from __future__ import annotations

import builtins
import copy
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts.valuation_reference_check import compare_native

ROOT = Path(__file__).resolve().parents[2]


def outputs() -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in (ROOT / "test-data/position/valuation-v1.jsonl").read_text().splitlines()]
    return [{key: row[key] for key in ("case", "market", "unrealized")} for row in rows]


def test_native_valuation_literals_do_not_load_legacy_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    original = builtins.__import__

    def guarded(name: str, *args: Any, **kwargs: Any) -> Any:
        assert name != "onlyalpha" and not name.startswith("onlyalpha."), name
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    compare_native(ROOT, outputs())


def test_missing_reordered_and_wrong_native_valuation_is_refused() -> None:
    good = outputs()
    wrong = copy.deepcopy(good)
    wrong[0]["unrealized"] = "999.00"
    for bad in (good[:-1], list(reversed(good)), wrong):
        with pytest.raises(ValueError, match="VALUATION_"):
            compare_native(ROOT, bad)


def test_canonical_lane_refuses_an_empty_native_contract_test(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import rust_kernel_check

    def empty(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout="running 0 tests\n", stderr="")

    monkeypatch.setattr("scripts.rust_kernel_check.subprocess.run", empty)
    with pytest.raises(ValueError, match="VALUATION_ORDER_CONTRACT_OUTPUT"):
        rust_kernel_check.check_valuation_reference(ROOT, {}, "aarch64-unknown-linux-gnu")
