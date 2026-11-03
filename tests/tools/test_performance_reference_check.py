import builtins
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.performance_reference_check import compare_native

ROOT = Path(__file__).resolve().parents[2]


def outputs() -> list[dict[str, Any]]:
    return [
        {"case": v["case"], "summary": v["expected"]}
        for v in (
            json.loads(line) for line in (ROOT / "test-data/account/performance-v1.jsonl").read_text().splitlines()
        )
    ]


def test_independent_native_literals_do_not_load_legacy_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    original = builtins.__import__

    def guarded(name: str, *args: Any, **kwargs: Any) -> Any:
        assert name != "onlyalpha" and not name.startswith("onlyalpha."), name
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    compare_native(ROOT, outputs())


def test_missing_reordered_and_wrong_values_are_not_equivalence() -> None:
    rows = outputs()
    for bad in [rows[:-1], list(reversed(rows))]:
        with pytest.raises(ValueError):
            compare_native(ROOT, bad)
    rows[0]["summary"]["final_equity"] = "999.00"
    with pytest.raises(ValueError):
        compare_native(ROOT, rows)
