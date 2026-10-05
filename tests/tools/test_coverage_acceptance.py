from __future__ import annotations

import subprocess

import pytest

from scripts import coverage_acceptance


def test_global_coverage_preserves_all_canonical_lane_selection_and_policy(tmp_path, monkeypatch):
    monkeypatch.setattr(coverage_acceptance, "ROOT", tmp_path)
    calls = []

    def run(command, *, cwd, env, check):
        calls.append((command, cwd, env, check))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(coverage_acceptance.subprocess, "run", run)
    assert coverage_acceptance.main() == 0
    assert calls[0][0][1:] == ["scripts/embed_build_provenance.py"]
    assert [item[0][-1] for item in calls[1:6]] == [
        "research-postgres",
        "market-data-clickhouse",
        "database-acceptance",
        "recovery",
        "core-full",
    ]
    for command, cwd, env, check in calls[1:6]:
        assert command[1:5] == ["-m", "coverage", "run", "--parallel-mode"]
        assert command[5] == "scripts/test_suite.py"
        assert command[6] == "--no-parallel"
        assert cwd == tmp_path
        assert check is False
        assert env["COVERAGE_RCFILE"] == str(tmp_path / "pyproject.toml")
    assert [item[0][3] for item in calls[6:]] == ["combine", "json", "xml", "report"]
    assert len({item[2]["COVERAGE_FILE"] for item in calls}) == 1
    assert all("--fail-under=0" not in item[0] for item in calls)


@pytest.mark.parametrize("failed_step", range(10))
def test_global_coverage_stops_on_any_lane_merge_report_or_threshold_failure(tmp_path, monkeypatch, failed_step):
    monkeypatch.setattr(coverage_acceptance, "ROOT", tmp_path)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 17 if len(calls) - 1 == failed_step else 0)

    monkeypatch.setattr(coverage_acceptance.subprocess, "run", run)
    assert coverage_acceptance.main() == 17
    assert len(calls) == failed_step + 1


def test_global_coverage_never_combines_old_attempts(tmp_path, monkeypatch):
    monkeypatch.setattr(coverage_acceptance, "ROOT", tmp_path)
    data_files = []

    def run(command, **kwargs):
        data_files.append(kwargs["env"]["COVERAGE_FILE"])
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(coverage_acceptance.subprocess, "run", run)
    assert coverage_acceptance.main() == coverage_acceptance.main() == 1
    assert data_files[0] != data_files[1]


def test_database_carriers_are_restored_when_process_start_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(coverage_acceptance, "ROOT", tmp_path)
    root = tmp_path / "src" / "onlyalpha"
    root.mkdir(parents=True)
    manifest = root / "_build_provenance.json"
    digest = root / "_build_provenance.sha256"
    manifest.write_bytes(b"original")
    failure = OSError("process start failed")

    def run(command, **kwargs):
        manifest.write_bytes(b"database carrier")
        digest.write_bytes(b"database digest")
        raise failure

    monkeypatch.setattr(coverage_acceptance.subprocess, "run", run)
    with pytest.raises(OSError) as raised:
        coverage_acceptance.main()
    assert raised.value is failure
    assert manifest.read_bytes() == b"original"
    assert not digest.exists()


@pytest.mark.parametrize("existing", (False, True))
@pytest.mark.parametrize("failed", (False, True))
def test_database_carriers_are_restored_on_success_and_failure(tmp_path, monkeypatch, existing, failed):
    monkeypatch.setattr(coverage_acceptance, "ROOT", tmp_path)
    root = tmp_path / "src" / "onlyalpha"
    root.mkdir(parents=True)
    paths = [root / name for name in ("_build_provenance.json", "_build_provenance.sha256")]
    if existing:
        for path in paths:
            path.write_bytes(b"original")

    def run(command, **kwargs):
        if command[-1] == "scripts/embed_build_provenance.py":
            for path in paths:
                path.write_bytes(b"database carrier")
        elif command[-1] in ("research-postgres", "market-data-clickhouse", "database-acceptance"):
            assert all(path.read_bytes() == b"database carrier" for path in paths)
            if failed:
                return subprocess.CompletedProcess(command, 19)
        else:
            assert (
                all(path.read_bytes() == b"original" for path in paths)
                if existing
                else not any(path.exists() for path in paths)
            )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(coverage_acceptance.subprocess, "run", run)
    assert coverage_acceptance.main() == (19 if failed else 0)
    assert (
        all(path.read_bytes() == b"original" for path in paths)
        if existing
        else not any(path.exists() for path in paths)
    )
