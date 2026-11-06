from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts import coverage_acceptance as acceptance

pytestmark = pytest.mark.architecture


def test_current_coverage_runs_full_owners_and_keeps_threshold_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(acceptance, "ROOT", tmp_path)
    calls = []

    def run(command, **options):
        calls.append(command)
        assert options["env"]["COVERAGE_RCFILE"] == str(tmp_path / "pyproject.toml")
        return SimpleNamespace(returncode=2 if command[3] == "json" else 0)

    monkeypatch.setattr(acceptance.subprocess, "run", run)
    assert acceptance.main() == 2
    measured = [command[-1] for command in calls if command[3] == "run"]
    assert measured == ["python-contract", "database", "research-product-certification"]
    assert [command[3] for command in calls[-4:]] == ["combine", "json", "xml", "report"]
    assert not (tmp_path / "src").exists()


def test_current_coverage_stops_at_the_first_failed_actual_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(acceptance, "ROOT", tmp_path)
    calls = []

    def run(command, **options):
        calls.append(command)
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(acceptance.subprocess, "run", run)
    assert acceptance.main() == 7
    assert len(calls) == 1 and calls[0][-1] == "python-contract"
