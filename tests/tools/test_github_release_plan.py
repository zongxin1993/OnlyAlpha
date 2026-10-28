from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.github_release_plan import plan_releases


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def commit(root: Path, version: str, frontend: str = "0.9.0") -> str:
    (root / "pyproject.toml").write_text(
        '[project]\nname="onlyalpha"\nversion="0.7.0"\n[tool.uv.workspace]\nmembers=[]\n'
    )
    (root / "Cargo.toml").write_text(f'[workspace]\nmembers=[]\n[workspace.package]\nversion="{version}"\n')
    backend = root / "packages/backend/Cargo.toml"
    backend.parent.mkdir(parents=True, exist_ok=True)
    backend.write_text('[package]\nname="onlyalpha-backend"\nversion="0.7.0"\n')
    web = root / "packages/frontend/package.json"
    web.parent.mkdir(parents=True, exist_ok=True)
    web.write_text('{"version":"' + frontend + '"}')
    git(root, "add", ".")
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
        {"unit": "libs", "previous_version": "0.9.12", "version": "0.9.13", "tag": "libs-v0.9.13", "sha": patch},
        {"unit": "libs", "previous_version": "0.9.13", "version": "0.10.0", "tag": "libs-v0.10.0", "sha": minor},
    ]
    assert plan_releases(repository, after, after) == []


def test_product_directory_cutover_preserves_exact_historical_versions(repository: Path) -> None:
    commit(repository, "0.9.12")
    for current, original in (("backend", "onlyalpha-http-server"), ("frontend", "onlyalpha-web-console")):
        git(repository, "mv", f"packages/{current}", f"packages/{original}")
    git(
        repository,
        "-c",
        "user.name=Release test",
        "-c",
        "user.email=release@example.invalid",
        "commit",
        "-m",
        "original product paths",
    )
    before = git(repository, "rev-parse", "HEAD")
    for current, original in (("backend", "onlyalpha-http-server"), ("frontend", "onlyalpha-web-console")):
        git(repository, "mv", f"packages/{original}", f"packages/{current}")
    git(
        repository,
        "-c",
        "user.name=Release test",
        "-c",
        "user.email=release@example.invalid",
        "commit",
        "-m",
        "product package cutover",
    )
    assert plan_releases(repository, before, git(repository, "rev-parse", "HEAD")) == []


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
    import yaml  # type: ignore[import-untyped]  # The installed PyYAML has no bundled stubs.

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


def test_frontend_release_does_not_publish_unchanged_libraries(repository: Path) -> None:
    before = commit(repository, "0.9.12")
    after = commit(repository, "0.9.12", "0.9.1")
    assert plan_releases(repository, before, after) == [
        {"unit": "frontend", "previous_version": "0.9.0", "version": "0.9.1", "tag": "frontend-v0.9.1", "sha": after}
    ]


def test_initial_agent_inventory_does_not_publish_and_later_bump_is_exact(repository: Path) -> None:
    before = commit(repository, "0.9.12")
    manifest = repository / "packages/agent/pyproject.toml"
    manifest.parent.mkdir()
    manifest.write_text('[project]\nname="onlyalpha-agent"\nversion="0.1.0"\n')
    root = repository / "pyproject.toml"
    root.write_text(root.read_text().replace("members=[]", 'members=["packages/agent"]'))

    def save():
        git(repository, "add", ".")
        git(
            repository,
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "Agent version",
        )
        return git(repository, "rev-parse", "HEAD")

    initial = save()
    assert plan_releases(repository, before, initial) == []
    manifest.write_text(manifest.read_text().replace("0.1.0", "0.1.1"))
    after = save()
    assert plan_releases(repository, initial, after) == [
        {"unit": "agent", "previous_version": "0.1.0", "version": "0.1.1", "tag": "agent-v0.1.1", "sha": after}
    ]
    root.write_text(root.read_text().replace('members=["packages/agent"]', "members=[]"))
    removed = save()
    with pytest.raises(ValueError, match="inventory"):
        plan_releases(repository, after, removed)
