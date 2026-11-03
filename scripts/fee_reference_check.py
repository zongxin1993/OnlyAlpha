"""Independent native Fee application amounts and exact checkpoint continuation."""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def cases(root: Path = ROOT) -> list[tuple[dict[str, Any], list[str]]]:
    fixture = json.loads((root / "test-data/fee/common-v1.json").read_text())
    result = []
    for case in fixture["cases"]:
        selected = copy.deepcopy(fixture)
        selected["catalog"]["schedules"][1]["rules"][0]["scope"] = case["scope"]
        result.append((selected, case["expected"]))
    return result


def compare_native(root: Path, executable: Path) -> None:
    def invoke(payload: dict[str, Any]) -> dict[str, Any]:
        result = subprocess.run(
            [str(executable)], input=json.dumps(payload), text=True, capture_output=True, check=True
        )
        decoded: dict[str, Any] = json.loads(result.stdout)
        return decoded

    for fixture, expected in cases(root):
        full = invoke({"fixture": fixture})
        assert [r["charges"] for r in full["applications"]] == expected
        first = invoke({"fixture": fixture, "count": 1})
        resumed = invoke({"fixture": fixture, "checkpoint": first["checkpoint"], "offset": 1})
        assert [r["charges"] for r in first["applications"] + resumed["applications"]] == expected
        assert resumed["checkpoint"] == full["checkpoint"]
    print("FEE_NATIVE_REFERENCE: PASS", flush=True)
