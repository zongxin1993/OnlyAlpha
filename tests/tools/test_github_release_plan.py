from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.github_release_plan import plan_releases


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def commit(root: Path, version: str) -> str:
    (root / "pyproject.toml").write_text(f'[project]\nname = "onlyalpha"\nversion = "{version}"\n')
    git(root, "add", "pyproject.toml")
    git(
        root,
        "-c",
        "user.name=Release test",
        "-c",
        "user.email=release@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        version,
    )
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-b", "master")
    return tmp_path


def test_all_version_changes_are_bound_to_their_exact_commits(repository: Path) -> None:
    before = commit(repository, "0.9.12")
    commit(repository, "0.9.12")
    patch = commit(repository, "0.9.13")
    minor = commit(repository, "0.10.0")
    after = commit(repository, "0.10.0")
    assert plan_releases(repository, before, after) == [
        {"previous_version": "0.9.12", "version": "0.9.13", "tag": "v0.9.13", "sha": patch},
        {"previous_version": "0.9.13", "version": "0.10.0", "tag": "v0.10.0", "sha": minor},
    ]
    assert plan_releases(repository, after, after) == []


@pytest.mark.parametrize("version", ["0.9.11", "0.9.15", "00.9.13", "0.9.13rc1"])
def test_invalid_transitions_fail_closed(repository: Path, version: str) -> None:
    before = commit(repository, "0.9.12")
    after = commit(repository, version)
    with pytest.raises(ValueError):
        plan_releases(repository, before, after)


def test_missing_and_reversed_push_boundaries_fail_closed(repository: Path) -> None:
    before = commit(repository, "0.9.12")
    after = commit(repository, "0.9.13")
    for start, end in [("0" * 40, after), (after, before), ("master", after)]:
        with pytest.raises(ValueError):
            plan_releases(repository, start, end)


def test_side_parent_is_not_a_first_parent_push_boundary(repository: Path) -> None:
    commit(repository, "0.9.12")
    git(repository, "checkout", "-b", "side")
    side = commit(repository, "0.9.13")
    git(repository, "checkout", "master")
    commit(repository, "0.9.12")
    git(
        repository,
        "-c",
        "user.name=Release test",
        "-c",
        "user.email=release@example.invalid",
        "merge",
        "--no-ff",
        "side",
        "-m",
        "merge",
    )
    after = git(repository, "rev-parse", "HEAD")
    with pytest.raises(ValueError, match="first-parent"):
        plan_releases(repository, side, after)


def test_merge_publishes_the_mainline_occurrence(repository: Path) -> None:
    before = commit(repository, "0.9.12")
    git(repository, "checkout", "-b", "feature")
    commit(repository, "0.9.13")
    git(repository, "checkout", "master")
    git(
        repository,
        "-c",
        "user.name=Release test",
        "-c",
        "user.email=release@example.invalid",
        "merge",
        "--no-ff",
        "feature",
        "-m",
        "merge",
    )
    after = git(repository, "rev-parse", "HEAD")
    assert plan_releases(repository, before, after)[0]["sha"] == after


def test_release_workflow_limits_write_access_to_trusted_master_push() -> None:
    import yaml

    root = Path(__file__).resolve().parents[2]
    workflow = yaml.load((root / ".github/workflows/github-release.yml").read_text(), Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"push"}
    assert workflow["on"]["push"]["branches"] == ["master"]
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["publish"]
    assert job["permissions"] == {"contents": "write"}
    assert "github.sha" in job["concurrency"]["group"]
    assert job["concurrency"]["cancel-in-progress"] == "false"
    checkout = next(step for step in job["steps"] if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["ref"] == "${{ github.event.after }}"
    assert checkout["with"]["persist-credentials"] == "false"
    assert checkout["with"]["fetch-depth"] == "0"
