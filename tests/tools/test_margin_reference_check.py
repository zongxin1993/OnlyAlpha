"""Checker transcripts only; the canonical runner exercises the real native executable."""

from __future__ import annotations

import builtins
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import margin_reference_check as check


def producer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutation: str = "") -> Path:
    executable = tmp_path / "checker-transcript"
    executable.write_bytes(b"explicit checker transcript")

    def invoke(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        frame = json.loads(kwargs["input"])
        start = frame.get("checkpoint", {}).get("step", 0)
        end = start + len(frame["steps"])
        snapshots = [
            {**dict(zip(check.FIELDS, row, strict=True)), "status": "CLOSED" if i == 4 else "ACTIVE"}
            for i, row in enumerate(check.EXPECTED)
        ][start:end]
        checkpoint = {"step": end}
        if mutation == "amount" and start == 0:
            snapshots[0]["reserved"] = "999.00"
        elif mutation == "status" and end == 5:
            snapshots[-1]["status"] = "ACTIVE"
        elif mutation == "checkpoint" and start == 2:
            checkpoint["step"] = 6
        elif mutation == "suffix" and start == 2:
            snapshots[0]["occupied"] = "0.00"
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps({"snapshots": snapshots, "checkpoint": checkpoint})
        )

    monkeypatch.setattr("scripts.margin_reference_check.subprocess.run", invoke)
    return executable


def test_native_margin_checker_does_not_load_legacy_backend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    executable = producer(monkeypatch, tmp_path)
    original = builtins.__import__

    def guarded(name: str, *args: Any, **kwargs: Any) -> Any:
        assert name != "onlyalpha" and not name.startswith("onlyalpha."), name
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    check.compare_native(check.ROOT, executable)


@pytest.mark.parametrize("mutation", ["amount", "status", "checkpoint", "suffix"])
def test_margin_checker_refuses_wrong_values_or_recovery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutation: str
) -> None:
    with pytest.raises(AssertionError):
        check.compare_native(check.ROOT, producer(monkeypatch, tmp_path, mutation))


def test_cross_isolated_long_short_cases_remain_explicit() -> None:
    assert [
        (case["template"]["mode"], case["template"]["isolation"], case["template"]["position_side"])
        for case in check.cases()
    ] == [
        ("CROSS", None, "LONG"),
        ("CROSS", None, "SHORT"),
        ("ISOLATED", "instrument-long", "LONG"),
        ("ISOLATED", "instrument-short", "SHORT"),
    ]
