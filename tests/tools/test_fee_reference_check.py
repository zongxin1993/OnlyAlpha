"""Verifier transcripts only; actual Fee applications run in the native canonical lane."""

from __future__ import annotations

import builtins
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import fee_reference_check as check


def transcript(monkeypatch: pytest.MonkeyPatch, mutation: str = "") -> None:
    def invoke(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        payload = json.loads(kwargs["input"])
        fixture = payload["fixture"]
        scope = fixture["catalog"]["schedules"][1]["rules"][0]["scope"]
        expected = next(case["expected"] for case in fixture["cases"] if case["scope"] == scope)
        start = payload.get("offset", 0)
        end = start + payload.get("count", len(expected) - start)
        applications = [{"charges": value} for value in expected[start:end]]
        checkpoint = {"scope": scope, "count": end}
        if mutation == "application" and start == 0:
            applications[0]["charges"] = "999.00"
        elif mutation == "suffix" and start == 1:
            applications[0]["charges"] = "999.00"
        elif mutation == "checkpoint" and start == 1:
            checkpoint["count"] = 4
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps({"applications": applications, "checkpoint": checkpoint})
        )

    monkeypatch.setattr("scripts.fee_reference_check.subprocess.run", invoke)


def test_native_fee_checker_does_not_load_legacy_backend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    transcript(monkeypatch)
    original = builtins.__import__

    def guarded(name: str, *args: Any, **kwargs: Any) -> Any:
        assert name != "onlyalpha" and not name.startswith("onlyalpha."), name
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    check.compare_native(check.ROOT, tmp_path / "checker-transcript")


@pytest.mark.parametrize("mutation", ["application", "suffix", "checkpoint"])
def test_fee_checker_refuses_wrong_application_or_continuation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutation: str
) -> None:
    transcript(monkeypatch, mutation)
    with pytest.raises(AssertionError):
        check.compare_native(check.ROOT, tmp_path / "checker-transcript")
