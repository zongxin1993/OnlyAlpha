"""Verifier transcripts only; native maturity and recovery run separately in Compose."""

from __future__ import annotations

import builtins
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import settlement_reference_check as check


def transcript(monkeypatch: pytest.MonkeyPatch, mutation: str = "") -> None:
    def invoke(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        payload = json.loads(kwargs["input"])
        fixture = payload["fixture"]
        case = next(item for item in check.cases() if item["fixture"] == fixture)
        completed = bool(payload["advances"]) or payload.get("checkpoint", {}).get("complete", False)
        checkpoint: dict[str, Any] = {"complete": completed, "instructions": {"id": {"status": "COMPLETED"}}}
        due = [{"effective_on": day, "transition": axis} for day, axis in case["due"]]
        result: dict[str, Any] = {
            "instruction": {"schedule": case["expected"].copy(), "cash_flow": case["cash_flow"]},
            "initial": {"status": case["status"]},
            "due": [] if completed else due,
            "effects": [
                {
                    "asset_quantity": "4" if fixture["side"] == "BUY" else "0",
                    "cash_amount": "47.00" if fixture["side"] == "SELL" else "0.00",
                }
            ],
            "checkpoint": checkpoint,
        }
        if mutation == "schedule":
            result["instruction"]["schedule"]["asset_booked"] = "2026-10-24"
        elif mutation == "cash_flow":
            result["instruction"]["cash_flow"] = "0.00"
        elif mutation == "status":
            result["initial"]["status"] = "PENDING"
        elif mutation == "due" and due and not completed:
            result["due"] = list(reversed(due))
        elif mutation == "effect" and payload["advances"]:
            result["effects"][0]["asset_quantity"] = "99"
        elif mutation == "checkpoint" and "checkpoint" in payload and payload["advances"]:
            checkpoint["complete"] = False
        elif mutation == "closed" and payload.get("checkpoint", {}).get("complete"):
            checkpoint["instructions"]["id"]["status"] = "PENDING"
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(result))

    monkeypatch.setattr("scripts.settlement_reference_check.subprocess.run", invoke)


def test_settlement_checker_does_not_load_legacy_backend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    transcript(monkeypatch)
    original = builtins.__import__

    def guarded(name: str, *args: Any, **kwargs: Any) -> Any:
        assert name != "onlyalpha" and not name.startswith("onlyalpha."), name
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    check.compare_native(check.ROOT, tmp_path / "checker-transcript")


@pytest.mark.parametrize("mutation", ["schedule", "cash_flow", "status", "due", "effect", "checkpoint", "closed"])
def test_settlement_checker_rejects_wrong_values_or_recovery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutation: str
) -> None:
    transcript(monkeypatch, mutation)
    with pytest.raises(AssertionError):
        check.compare_native(check.ROOT, tmp_path / "checker-transcript")
