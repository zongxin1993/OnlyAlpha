"""Independent schedule/initial-state/due vectors and native maturity/restart proof.

Technical controlled facts; component identities and Python schema2 identities are intentionally distinct.
"""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AXES = (
    "asset_booked",
    "asset_trade_available",
    "cash_booked",
    "cash_trade_available",
    "cash_withdrawable",
    "legal_settled",
)


def cases(root: Path = ROOT) -> list[dict[str, Any]]:
    original = json.loads((root / "test-data/settlement/common-v1.json").read_text())
    result = []
    for label, asset, cash, legal, target, side in (
        ("T0", 0, 0, 0, "2026-10-23", "BUY"),
        ("T1", 1, 1, 1, "2026-10-27", "BUY"),
        ("T2-cash", 1, 1, 2, "2026-10-28", "SELL"),
        ("T3", 3, 2, 3, "2026-10-29", "BUY"),
    ):
        fixture = copy.deepcopy(original)
        fixture["side"] = side
        if side == "SELL":
            fixture["gross_notional"] = "48.00"
        fixture["policy"].update(asset_trade_available=asset, cash_withdrawable=cash, legal_settled=legal)
        dates = {0: "2026-10-23", 1: "2026-10-27", 2: "2026-10-28", 3: "2026-10-29"}
        expected = {key: dates[fixture["policy"][key]] for key in AXES}
        # October 24/25 are weekend days; October 26 is the explicit holiday.
        due = {
            "T0": [],
            "T1": [
                ("2026-10-27", "asset_trade_available"),
                ("2026-10-27", "cash_withdrawable"),
                ("2026-10-27", "legal_settled"),
            ],
            "T2-cash": [
                ("2026-10-27", "asset_trade_available"),
                ("2026-10-27", "cash_withdrawable"),
                ("2026-10-28", "legal_settled"),
            ],
            "T3": [
                ("2026-10-28", "cash_withdrawable"),
                ("2026-10-29", "asset_trade_available"),
                ("2026-10-29", "legal_settled"),
            ],
        }[label]
        result.append(
            {
                "label": label,
                "fixture": fixture,
                "expected": expected,
                "target": target,
                "due": due,
                "status": "COMPLETED" if label == "T0" else "PARTIALLY_EFFECTIVE",
                "cash_flow": "47.00" if side == "SELL" else "-41.00",
            }
        )
    return result


def compare_native(root: Path, executable: Path) -> None:
    def invoke(payload: dict[str, Any]) -> dict[str, Any]:
        completed = subprocess.run(
            [str(executable)], input=json.dumps(payload), text=True, capture_output=True, check=True
        )
        result: dict[str, Any] = json.loads(completed.stdout)
        return result

    for case in cases(root):
        fixture = case["fixture"]
        initial = invoke({"fixture": fixture, "advances": []})
        assert initial["instruction"]["schedule"] == case["expected"]
        assert initial["initial"]["status"] == case["status"]
        assert initial["instruction"]["cash_flow"] == case["cash_flow"]
        assert [(item["effective_on"], item["transition"]) for item in initial["due"]] == case["due"]
        steps = [] if case["label"] == "T0" else [{"day": case["target"], "time": 2, "version": 1}]
        full = invoke({"fixture": fixture, "advances": steps})
        if steps:
            effect = full["effects"][0]
            assert effect["asset_quantity"] == ("4" if fixture["side"] == "BUY" else "0")
            assert effect["cash_amount"] == ("47.00" if fixture["side"] == "SELL" else "0.00")
        resumed = invoke({"fixture": fixture, "checkpoint": initial["checkpoint"], "advances": steps})
        assert resumed["checkpoint"] == full["checkpoint"]
        closed = invoke({"fixture": fixture, "checkpoint": full["checkpoint"], "advances": []})
        assert closed["due"] == []
        assert next(iter(closed["checkpoint"]["instructions"].values()))["status"] == "COMPLETED"
    print("SETTLEMENT_NATIVE_INDEPENDENT_VECTORS: PASS")
