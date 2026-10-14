from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_web_unit_keeps_coverage_but_writes_artifacts_outside_readonly_source(monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    suite = importlib.import_module("scripts.web_suite")
    calls: list[tuple[tuple[str, ...], Path]] = []

    def run(command: tuple[str, ...], **kwargs: object) -> SimpleNamespace:
        cwd = kwargs["cwd"]
        assert isinstance(cwd, Path)
        calls.append((command, cwd))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(suite.subprocess, "run", run)
    assert suite.main(["unit"]) == 0
    assert calls == [
        (
            ("npm", "run", "test:coverage", "--", "--coverage.reportsDirectory=../../test-results/web-coverage"),
            suite.WEB,
        )
    ]


def test_web_unit_failure_is_not_swallowed_or_followed_by_build(monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    suite = importlib.import_module("scripts.web_suite")
    monkeypatch.setattr(suite, "static", lambda: None)
    calls: list[tuple[str, ...]] = []

    def run(command: tuple[str, ...], **kwargs: object) -> SimpleNamespace:
        calls.append(command)
        return SimpleNamespace(returncode=9)

    monkeypatch.setattr(suite.subprocess, "run", run)
    with pytest.raises(SystemExit) as failure:
        suite.main(["all"])
    assert failure.value.code == 9
    assert len(calls) == 1 and calls[0][:3] == ("npm", "run", "test:coverage")
