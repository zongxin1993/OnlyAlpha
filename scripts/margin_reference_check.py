"""Independent native collateral amounts and exact prefix-recovery checks."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def cases(root: Path = ROOT) -> list[dict[str, Any]]:
    fixture = json.loads((root / "test-data/margin/common-v1.json").read_text())
    result = []
    for mode, isolation, side in (
        ("CROSS", None, "LONG"),
        ("CROSS", None, "SHORT"),
        ("ISOLATED", "instrument-long", "LONG"),
        ("ISOLATED", "instrument-short", "SHORT"),
    ):
        template = copy.deepcopy(fixture["reserve"])
        template.update(mode=mode, isolation=isolation, position_side=side)
        steps = [
            dict(action="RESERVE", quantity="4", amount="100.00", maintenance="0.00"),
            dict(action="OCCUPY", quantity="2", amount="60.00", maintenance="48.00"),
            dict(action="RELEASE_RESERVED", quantity="2", amount="40.00", maintenance="0.00"),
            dict(action="RELEASE_OCCUPIED", quantity="1", amount="30.00", maintenance="24.00"),
            dict(action="RELEASE_OCCUPIED", quantity="1", amount="30.00", maintenance="24.00"),
        ]
        result.append(dict(config=fixture["config"], template=template, steps=steps))
    return result


EXPECTED = [
    ["100.00", "0.00", "0.00", "0.00"],
    ["40.00", "60.00", "0.00", "48.00"],
    ["0.00", "60.00", "40.00", "48.00"],
    ["0.00", "30.00", "70.00", "24.00"],
    ["0.00", "0.00", "100.00", "0.00"],
]
FIELDS = ("reserved", "occupied", "released", "maintenance")


def compare_native(root: Path, executable: Path) -> None:

    def invoke(frame: dict[str, Any]) -> dict[str, Any]:
        response = subprocess.run(
            [str(executable)], input=json.dumps(frame), text=True, capture_output=True, check=True
        )
        value: dict[str, Any] = json.loads(response.stdout)
        return value

    for case in cases(root):
        result = invoke(case)
        assert [[s[k] for k in FIELDS] for s in result["snapshots"]] == EXPECTED
        assert result["snapshots"][-1]["status"] == "CLOSED"
        initial = invoke(dict(case, steps=case["steps"][:2]))
        resumed = invoke(dict(case, checkpoint=initial["checkpoint"], steps=case["steps"][2:]))
        assert resumed["checkpoint"] == result["checkpoint"]
        assert resumed["snapshots"] == result["snapshots"][2:]
    print(
        f"MARGIN_NATIVE_REFERENCE: PASS artifact_sha256={hashlib.sha256(executable.read_bytes()).hexdigest()}",
        flush=True,
    )
