from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from packaging.requirements import Requirement
from tomlkit import parse


def _load_version_sync() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts/version_sync.py"
    spec = importlib.util.spec_from_file_location("onlyalpha_version_sync", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


VERSION_SYNC = _load_version_sync()
VersionSyncError = VERSION_SYNC.VersionSyncError
check_versions = VERSION_SYNC.check_versions
rewrite_internal_requirement = VERSION_SYNC.rewrite_internal_requirement
rewrite_workspace = VERSION_SYNC.rewrite_workspace

FIXTURE_PATH = Path("test-data/external_plugins/onlyalpha_test_plugin/pyproject.toml")


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _workspace(
    tmp_path: Path,
    *,
    a_name: str = "onlyalpha-market-a",
    a_version: str = "0.3.7",
    b_version: str = "0.3.7",
    b_dependencies: tuple[str, ...] = ("onlyalpha==0.3.7", "onlyalpha-market-a==0.3.7", "pandas>=2"),
    b_optional_dependencies: tuple[str, ...] = (),
    fixture_version: str = "0.1.0",
    fixture_dependency: str = "onlyalpha==0.3.7",
) -> Path:
    dependency_lines = ",\n    ".join(repr(value) for value in b_dependencies)
    optional_section = ""
    if b_optional_dependencies:
        optional_lines = ",\n    ".join(repr(value) for value in b_optional_dependencies)
        optional_section = f"\n[project.optional-dependencies]\nfeature = [\n    {optional_lines},\n]\n"

    _write(
        tmp_path / "pyproject.toml",
        """[project]
name = "onlyalpha"
version = "0.3.7"
dependencies = []

[tool.uv.workspace]
members = ["packages/a", "packages/b"]
""",
    )
    _write(tmp_path / "README.md", "# Documentation without release metadata\n")
    _write(
        tmp_path / "packages/onlyalpha-web-console/package.json",
        '{"name":"onlyalpha-web","private":true,"version":"0.3.7"}\n',
    )
    _write(
        tmp_path / "packages/onlyalpha-web-console/package-lock.json",
        '{"name":"onlyalpha-web","version":"0.3.7","packages":{"":{"version":"0.3.7"}}}\n',
    )
    _write(
        tmp_path / "packages/a/pyproject.toml",
        f"""[project]
name = {a_name!r}
version = {a_version!r}
dependencies = ["onlyalpha==0.3.7"]
""",
    )
    _write(
        tmp_path / "packages/b/pyproject.toml",
        f"""[project]
name = "onlyalpha-plugin-b"
version = {b_version!r}
dependencies = [
    {dependency_lines},
]
{optional_section}""",
    )
    _write(
        tmp_path / FIXTURE_PATH,
        f"""[project]
name = "onlyalpha-test-plugin"
version = {fixture_version!r}
dependencies = [{fixture_dependency!r}]
""",
    )
    _write(
        tmp_path / "test-data/runtime_factor_provider/pyproject.toml",
        '[project]\nname = "onlyalpha-test-factor-provider"\nversion = "0.9.9"\ndependencies = ["onlyalpha==0.3.7", "onlyalpha-market-a==0.3.7"]\n',
    )
    return tmp_path


def _failure(tmp_path: Path) -> str:
    with pytest.raises(VersionSyncError) as exc_info:
        check_versions(tmp_path)
    return str(exc_info.value)


def test_valid_workspace_release_graph_passes(tmp_path: Path) -> None:
    check_versions(_workspace(tmp_path))


def test_readme_is_not_a_version_authority_and_may_be_absent(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    readme = root / "README.md"
    readme.write_text("| Version | `stale-and-ignored` |\n", encoding="utf-8")
    check_versions(root)
    readme.unlink()
    check_versions(root)


def test_stale_internal_edge_fails(tmp_path: Path) -> None:
    root = _workspace(
        tmp_path,
        b_dependencies=("onlyalpha==0.3.7", "onlyalpha-market-a==0.3.6"),
    )
    message = _failure(root)
    assert "onlyalpha-market-a" in message
    assert "expected '==0.3.7'" in message
    assert "==0.3.6" in message


def test_wrong_formal_distribution_version_fails(tmp_path: Path) -> None:
    message = _failure(_workspace(tmp_path, a_version="0.3.6"))
    assert "expected version '0.3.7'" in message
    assert "found '0.3.6'" in message


@pytest.mark.parametrize("dependency", ["onlyalpha-market-a>=0.3.7", "onlyalpha-market-a"])
def test_non_exact_internal_dependency_fails(tmp_path: Path, dependency: str) -> None:
    message = _failure(_workspace(tmp_path, b_dependencies=("onlyalpha==0.3.7", dependency)))
    assert "internal dependency 'onlyalpha-market-a'" in message
    assert "expected '==0.3.7'" in message


def test_external_dependency_is_unchanged_and_valid(tmp_path: Path) -> None:
    root = _workspace(tmp_path, b_dependencies=("onlyalpha==0.3.7", "pandas>=2"))
    check_versions(root)
    rewrite_workspace(root, "0.3.8")
    document = parse((root / "packages/b/pyproject.toml").read_text(encoding="utf-8"))
    assert list(document["project"]["dependencies"]) == ["onlyalpha==0.3.8", "pandas>=2"]


def test_dependency_groups_are_outside_release_graph(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    path = root / "packages/b/pyproject.toml"
    path.write_text(
        path.read_text(encoding="utf-8") + '\n[dependency-groups]\ndev = ["onlyalpha-market-a==0.1.0"]\n',
        encoding="utf-8",
    )

    check_versions(root)
    rewrite_workspace(root, "0.3.8")

    document = parse(path.read_text(encoding="utf-8"))
    assert list(document["dependency-groups"]["dev"]) == ["onlyalpha-market-a==0.1.0"]


def test_stale_optional_internal_dependency_fails(tmp_path: Path) -> None:
    root = _workspace(tmp_path, b_optional_dependencies=("onlyalpha-market-a==0.3.6",))
    message = _failure(root)
    assert "onlyalpha-market-a" in message
    assert "==0.3.6" in message


def test_duplicate_canonical_distribution_name_fails(tmp_path: Path) -> None:
    root = _workspace(tmp_path, a_name="OnlyAlpha_Plugin_B")
    message = _failure(root)
    assert "duplicate canonical distribution name 'onlyalpha-plugin-b'" in message


def test_missing_workspace_member_pyproject_fails(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    (root / "packages/a/pyproject.toml").unlink()
    message = _failure(root)
    assert "missing workspace member pyproject.toml" in message


def test_invalid_requirement_fails(tmp_path: Path) -> None:
    root = _workspace(tmp_path, b_dependencies=("onlyalpha==0.3.7", "not a valid ???"))
    message = _failure(root)
    assert "invalid requirement" in message


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("name", '""', "missing project.name"),
        ("version", '"not-a-version"', "invalid project.version"),
    ],
)
def test_invalid_distribution_identity_fails(
    tmp_path: Path,
    field: str,
    value: str,
    expected: str,
) -> None:
    root = _workspace(tmp_path)
    path = root / "packages/a/pyproject.toml"
    document = parse(path.read_text(encoding="utf-8"))
    document["project"][field] = parse(f"value = {value}\n")["value"]
    path.write_text(VERSION_SYNC.dumps(document), encoding="utf-8")
    assert expected in _failure(root)


def test_fixture_version_is_independent(tmp_path: Path) -> None:
    check_versions(_workspace(tmp_path, fixture_version="99.4"))


def test_stale_fixture_reference_to_formal_distribution_fails(tmp_path: Path) -> None:
    root = _workspace(tmp_path, fixture_dependency="onlyalpha==0.3.6")
    message = _failure(root)
    assert str(FIXTURE_PATH) in message
    assert "==0.3.6" in message


def test_direct_url_internal_dependency_fails(tmp_path: Path) -> None:
    root = _workspace(
        tmp_path,
        b_dependencies=("onlyalpha==0.3.7", "onlyalpha-market-a @ file:///tmp/market-a"),
    )
    message = _failure(root)
    assert "direct URL" in message


def test_rewrite_internal_requirement_preserves_extras_and_marker() -> None:
    rewritten = rewrite_internal_requirement(
        'OnlyAlpha-Market-A[foo]>=0.3; python_version >= "3.12"',
        formal_distribution_names=frozenset({"onlyalpha-market-a"}),
        version="0.3.8",
    )
    requirement = Requirement(rewritten)
    assert requirement.name == "OnlyAlpha-Market-A"
    assert requirement.extras == {"foo"}
    assert str(requirement.specifier) == "==0.3.8"
    assert str(requirement.marker) == 'python_version >= "3.12"'


def test_set_rewrites_complete_graph_and_preserves_external_dependencies(tmp_path: Path) -> None:
    root = _workspace(
        tmp_path,
        b_optional_dependencies=('onlyalpha-market-a[feature]>=0.3; python_version >= "3.12"',),
        fixture_version="7.9",
    )

    readme_before = (root / "README.md").read_text(encoding="utf-8")
    rewrite_workspace(root, "0.3.8")
    check_versions(root)

    for relative_path in (Path("pyproject.toml"), Path("packages/a/pyproject.toml"), Path("packages/b/pyproject.toml")):
        document = parse((root / relative_path).read_text(encoding="utf-8"))
        assert document["project"]["version"] == "0.3.8"

    b_document = parse((root / "packages/b/pyproject.toml").read_text(encoding="utf-8"))
    assert "onlyalpha-market-a==0.3.8" in b_document["project"]["dependencies"]
    assert "pandas>=2" in b_document["project"]["dependencies"]
    optional = Requirement(str(b_document["project"]["optional-dependencies"]["feature"][0]))
    assert optional.extras == {"feature"}
    assert str(optional.specifier) == "==0.3.8"
    assert optional.marker is not None

    fixture = parse((root / FIXTURE_PATH).read_text(encoding="utf-8"))
    assert fixture["project"]["version"] == "7.9"
    assert list(fixture["project"]["dependencies"]) == ["onlyalpha==0.3.8"]
    assert (root / "README.md").read_text(encoding="utf-8") == readme_before
    web_package = (root / "packages/onlyalpha-web-console/package.json").read_text(encoding="utf-8")
    web_lock = (root / "packages/onlyalpha-web-console/package-lock.json").read_text(encoding="utf-8")
    assert '\n    "version": "0.3.8"' in web_package
    assert '\n    "version": "0.3.8"' in web_lock
    assert '\n  "version": "0.3.8"' not in web_package
    assert '\n  "version": "0.3.8"' not in web_lock


def test_quant_asset_provider_distribution_version_is_checked_and_rewritten(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    provider_path = root / VERSION_SYNC.QUANT_ASSET_PROVIDER_PATHS[0]
    _write(
        provider_path,
        'manifest = Provider(\n    distribution_version="0.3.6",\n)\n',
    )

    message = _failure(root)
    assert "quant asset distribution_version expected '0.3.7'" in message

    rewrite_workspace(root, "0.3.8")
    check_versions(root)
    assert 'distribution_version="0.3.8"' in provider_path.read_text(encoding="utf-8")


def test_set_versions_locks_then_checks_complete_graph(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _workspace(tmp_path)
    calls: list[tuple[list[str], Path, bool]] = []

    def fake_run(command: list[str], *, cwd: Path, check: bool) -> None:
        calls.append((command, cwd, check))

    monkeypatch.setattr(VERSION_SYNC.subprocess, "run", fake_run)
    VERSION_SYNC.set_versions("0.3.8", root)

    assert calls == [(["uv", "lock", "--python", "3.12"], root, True)]
    check_versions(root)


@pytest.mark.parametrize(
    ("base", "level", "expected"),
    [
        ("0.9.9", "patch", "0.9.10"),
        ("0.9.10", "minor", "0.10.0"),
        ("0.10.7", "major", "1.0.0"),
        ("1.2.3", "patch", "1.2.4"),
        ("1.2.3", "minor", "1.3.0"),
        ("1.2.3", "major", "2.0.0"),
    ],
)
def test_release_increment_resets_lower_components(base: str, level: str, expected: str) -> None:
    assert VERSION_SYNC.next_release_version(base, level) == expected
    assert (
        VERSION_SYNC.check_release_transition(base, expected, level)
        == f"OnlyAlpha release: {base} -> {expected} ({level})"
    )


@pytest.mark.parametrize(
    "base", ["0.9", "v0.9.10", "00.9.10", "0.09.10", "0.9.010", "0.9.10rc1", "0.9.10+build", "0.9.10\n"]
)
def test_release_increment_refuses_noncanonical_number(base: str) -> None:
    with pytest.raises(VersionSyncError, match="canonical X.Y.Z"):
        VERSION_SYNC.next_release_version(base)


@pytest.mark.parametrize("candidate", ["0.9.10", "0.9.9", "0.9.12", "0.10.0", "0.9.11rc1"])
def test_release_transition_refuses_stale_skipped_or_unselected_numbers(candidate: str) -> None:
    with pytest.raises(VersionSyncError, match="requires 0.9.10 -> 0.9.11"):
        VERSION_SYNC.check_release_transition("0.9.10", candidate)


def test_unknown_release_level_is_not_an_increment() -> None:
    with pytest.raises(VersionSyncError, match="unknown release level"):
        VERSION_SYNC.next_release_version("0.9.10", "force")


def _release_context(level: str = "minor") -> dict[str, Any]:
    return {
        "repository": {"owner": {"login": "owner", "type": "User"}},
        "pull_request": {"labels": [{"name": f"release:{level}"}], "head": {"sha": "current"}},
        "events": [{"id": 1, "event": "labeled", "label": {"name": f"release:{level}"}, "actor": {"login": "owner"}}],
        "reviews": [],
    }


@pytest.mark.parametrize("level", ["minor", "major", "patch"])
def test_release_level_accepts_explicit_owner_selection(level: str) -> None:
    assert VERSION_SYNC.release_level_from_context(_release_context(level)) == level


def test_release_level_defaults_to_patch_without_labels() -> None:
    assert VERSION_SYNC.release_level_from_context({"pull_request": {"labels": []}, "events": []}) == "patch"


def test_non_owner_label_does_not_authorize_minor() -> None:
    context = _release_context()
    context["events"][0]["actor"]["login"] = "other"
    with pytest.raises(VersionSyncError, match="explicit Owner action"):
        VERSION_SYNC.release_level_from_context(context)


@pytest.mark.parametrize(
    "state,head", [("DISMISSED", "current"), ("CHANGES_REQUESTED", "current"), ("APPROVED", "old")]
)
def test_missing_current_owner_approval_is_not_permission(state: str, head: str) -> None:
    context = _release_context()
    context["events"] = []
    context["reviews"] = [{"user": {"login": "owner"}, "state": state, "commit_id": head}]
    with pytest.raises(VersionSyncError, match="explicit Owner action"):
        VERSION_SYNC.release_level_from_context(context)


@pytest.mark.parametrize("level", ["minor", "major"])
def test_generic_owner_approval_does_not_authorize_exceptional_release(level: str) -> None:
    context = _release_context(level)
    context["events"][0]["actor"]["login"] = "other"
    context["reviews"] = [{"user": {"login": "owner"}, "state": "APPROVED", "commit_id": "current"}]
    with pytest.raises(VersionSyncError, match="explicit Owner action"):
        VERSION_SYNC.release_level_from_context(context)


def test_removed_and_readded_label_does_not_inherit_owner_action() -> None:
    context = _release_context()
    context["events"] += [
        {"id": 2, "event": "unlabeled", "label": {"name": "release:minor"}, "actor": {"login": "other"}},
        {"id": 3, "event": "labeled", "label": {"name": "release:minor"}, "actor": {"login": "other"}},
    ]
    with pytest.raises(VersionSyncError, match="explicit Owner action"):
        VERSION_SYNC.release_level_from_context(context)


def test_conflicting_labels_and_organization_owner_fail_closed() -> None:
    context = _release_context()
    context["pull_request"]["labels"].append({"name": "release:major"})
    with pytest.raises(VersionSyncError, match="conflicting"):
        VERSION_SYNC.release_level_from_context(context)
    context = _release_context()
    context["repository"]["owner"]["type"] = "Organization"
    with pytest.raises(VersionSyncError, match="human repository Owner"):
        VERSION_SYNC.release_level_from_context(context)


def test_git_transition_reads_exact_base_and_checks_graph(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _workspace(tmp_path)
    calls: list[list[str]] = []

    def observe(command: list[str], *, cwd: Path, text: bool) -> str:
        assert cwd == root and text is True
        calls.append(command)
        return "a" * 40 + "\n" if command[1] == "rev-parse" else '[project]\nversion = "0.3.6"\n'

    monkeypatch.setattr(VERSION_SYNC.subprocess, "check_output", observe)
    assert (
        VERSION_SYNC.check_transition_from_git("origin/master", "patch", root)
        == "OnlyAlpha release: 0.3.6 -> 0.3.7 (patch)"
    )
    assert calls == [
        ["git", "rev-parse", "--verify", "--end-of-options", "origin/master^{commit}"],
        ["git", "show", "a" * 40 + ":pyproject.toml"],
    ]
    rewrite_workspace(root, "0.3.8")
    with pytest.raises(VersionSyncError, match="requires 0.3.6 -> 0.3.7"):
        VERSION_SYNC.check_transition_from_git("origin/master", "patch", root)


def test_next_cli_is_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _workspace(tmp_path)
    before = {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    monkeypatch.setattr(VERSION_SYNC, "ROOT", root)
    monkeypatch.setattr(VERSION_SYNC.sys, "argv", ["version_sync.py", "next", "--level", "minor"])
    assert VERSION_SYNC.main() == 0
    assert capsys.readouterr().out == "0.4.0\n"
    assert {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()} == before


def test_release_workflow_is_read_only_and_reports_exact_merge_transition() -> None:
    path = Path(__file__).resolve().parents[2] / ".github/workflows/release-version.yml"
    yaml = importlib.import_module("yaml")
    workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"pull_request"}
    assert "closed" in workflow["on"]["pull_request"]["types"]
    assert all(value == "read" for value in workflow["permissions"].values())
    job = workflow["jobs"]["transition"]
    assert "merged == true" in job["if"]
    steps = job["steps"]
    checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
    assert "merge_commit_sha" in checkout["with"]["ref"]
    assert "head.sha" in checkout["with"]["ref"]
    assert checkout["with"]["persist-credentials"] == "false"
    scripts = "\n".join(step.get("run", "") for step in steps)
    assert '--base-ref "$BASE_SHA"' in scripts
    assert "git fetch" not in scripts
    assert "report-merge" in scripts
    notice_index = next(i for i, step in enumerate(steps) if "--notice-only" in step.get("run", ""))
    history_index = next(i for i, step in enumerate(steps) if step.get("uses", "").startswith("actions/github-script@"))
    assert notice_index < history_index
    assert '--summary-file "$GITHUB_STEP_SUMMARY"' in scripts
    assert not any(token in scripts for token in ("git push", "git commit", "git tag", "gh pr merge"))


def _merged_context() -> dict[str, Any]:
    context = _release_context()
    context["pull_request"].update({"merged": True, "merge_commit_sha": "merged"})
    context["events"].append({"id": 2, "event": "merged", "commit_id": "merged"})
    return context


def test_merge_selection_uses_history_before_exact_occurrence_not_current_labels() -> None:
    context = _merged_context()
    context["pull_request"]["labels"] = []
    context["events"].append(
        {"id": 3, "event": "unlabeled", "label": {"name": "release:minor"}, "actor": {"login": "owner"}}
    )
    context["reviews"] = [{"state": "DISMISSED"}]
    assert VERSION_SYNC.release_level_from_context(context) == "minor"


def test_post_merge_owner_action_cannot_authorize_earlier_minor() -> None:
    context = _merged_context()
    context["events"][0]["actor"]["login"] = "other"
    context["events"] += [
        {"id": 3, "event": "unlabeled", "label": {"name": "release:minor"}, "actor": {"login": "owner"}},
        {"id": 4, "event": "labeled", "label": {"name": "release:minor"}, "actor": {"login": "owner"}},
    ]
    with pytest.raises(VersionSyncError, match="explicit Owner action"):
        VERSION_SYNC.release_level_from_context(context)


def test_new_post_merge_label_does_not_change_ordinary_patch_selection() -> None:
    context = _merged_context()
    context["events"] = [
        {"id": 1, "event": "merged", "commit_id": "merged"},
        {"id": 2, "event": "labeled", "label": {"name": "release:minor"}, "actor": {"login": "owner"}},
    ]
    assert VERSION_SYNC.release_level_from_context(context) == "patch"


@pytest.mark.parametrize("condition", ["missing", "different", "duplicate", "unordered"])
def test_merge_selection_refuses_incomplete_or_ambiguous_occurrence(condition: str) -> None:
    context = _merged_context()
    if condition == "missing":
        context["events"].pop()
    elif condition == "different":
        context["events"][-1]["commit_id"] = "different"
    elif condition == "duplicate":
        context["events"].append({"id": 3, "event": "merged", "commit_id": "merged"})
    else:
        context["events"].reverse()
    with pytest.raises(VersionSyncError, match="historical release selection|event history"):
        VERSION_SYNC.release_level_from_context(context)


def test_git_transition_refuses_noncanonical_raw_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _workspace(tmp_path)
    path = root / "pyproject.toml"
    path.write_text(path.read_text().replace('version = "0.3.7"', 'version = "0.3.007"'))
    monkeypatch.setattr(
        VERSION_SYNC.subprocess,
        "check_output",
        lambda command, **kwargs: "a" * 40 if command[1] == "rev-parse" else '[project]\nversion="0.3.6"\n',
    )
    with pytest.raises(VersionSyncError, match="canonical X.Y.Z"):
        VERSION_SYNC.check_transition_from_git("origin/master", "patch", root)


def test_merge_report_retains_actual_notice_when_historical_proof_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _workspace(tmp_path)
    summary = tmp_path / "summary.md"
    context_file = tmp_path / "context.json"
    context = _merged_context()
    context["events"].pop()
    context_file.write_text(VERSION_SYNC.json.dumps(context))
    monkeypatch.setattr(VERSION_SYNC, "ROOT", root)
    monkeypatch.setattr(
        VERSION_SYNC.subprocess,
        "check_output",
        lambda command, **kwargs: "a" * 40 if command[1] == "rev-parse" else '[project]\nversion="0.3.6"\n',
    )
    monkeypatch.setattr(
        VERSION_SYNC.sys,
        "argv",
        ["version_sync.py", "report-merge", "--context-file", str(context_file), "--summary-file", str(summary)],
    )
    assert VERSION_SYNC.main() == 1
    output = capsys.readouterr()
    assert "OnlyAlpha merged release: 0.3.6 -> 0.3.7" in output.out
    assert "historical release selection unavailable" in output.err
    assert "0.3.6 -> 0.3.7" in summary.read_text()


@pytest.mark.parametrize("wrong_merge", [False, True])
def test_merge_report_requires_exact_git_occurrence_for_historical_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], wrong_merge: bool
) -> None:
    root = _workspace(tmp_path)
    context = _merged_context()
    context["pull_request"]["merge_commit_sha"] = "other" if wrong_merge else "a" * 40
    context["events"] = [{"id": 1, "event": "merged", "commit_id": context["pull_request"]["merge_commit_sha"]}]
    context_file = tmp_path / "context.json"
    context_file.write_text(VERSION_SYNC.json.dumps(context))
    monkeypatch.setattr(VERSION_SYNC, "ROOT", root)
    monkeypatch.setattr(
        VERSION_SYNC.subprocess,
        "check_output",
        lambda command, **kwargs: "a" * 40 if command[1] == "rev-parse" else '[project]\nversion="0.3.6"\n',
    )
    monkeypatch.setattr(
        VERSION_SYNC.sys, "argv", ["version_sync.py", "report-merge", "--context-file", str(context_file)]
    )
    assert VERSION_SYNC.main() == (1 if wrong_merge else 0)
    output = capsys.readouterr()
    assert "OnlyAlpha merged release: 0.3.6 -> 0.3.7" in output.out
    if wrong_merge:
        assert "different merge" in output.err
    else:
        assert "0.3.6 -> 0.3.7 (patch)" in output.out


def test_runtime_factor_fixture_internal_dependencies_follow_release(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    rewrite_workspace(root, "0.3.8")
    document = parse((root / "test-data/runtime_factor_provider/pyproject.toml").read_text())
    assert document["project"]["version"] == "0.9.9"
    assert document["project"]["dependencies"] == ["onlyalpha==0.3.8", "onlyalpha-market-a==0.3.8"]
    check_versions(root)


def test_stale_runtime_factor_fixture_dependency_is_rejected(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    path = root / "test-data/runtime_factor_provider/pyproject.toml"
    path.write_text(path.read_text().replace("onlyalpha==0.3.7", "onlyalpha==0.3.6"))
    with pytest.raises(VersionSyncError, match="onlyalpha"):
        check_versions(root)


def test_rust_workspace_and_lock_follow_unique_release_authority(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _write(root / "Cargo.toml", '[workspace.package]\nversion="0.3.7"\n')
    _write(
        root / "Cargo.lock",
        'version=4\n[[package]]\nname="onlyalpha-kernel"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-domain"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-clock"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-event"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-market-data-state"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-market-data-construction"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-market-data-delivery"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-market-data-pipeline"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-execution"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-broker"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-fee"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-settlement"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-margin"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-risk"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-strategy-ledger"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-account"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-position"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-order"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-strategy"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-calculation"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-gateway-protocol"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-calculation-worker"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-backtest-driver"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-runtime-persistence"\nversion="0.3.7"\n',
    )
    check_versions(root)
    rewrite_workspace(root, "0.3.8")
    assert parse((root / "Cargo.toml").read_text())["workspace"]["package"]["version"] == "0.3.8"
    assert all(item["version"] == "0.3.8" for item in parse((root / "Cargo.lock").read_text())["package"])
    check_versions(root)
    _write(root / "Cargo.toml", '[workspace.package]\nversion="0.3.6"\n')
    assert "Rust" in _failure(root)


def test_rust_release_check_refuses_missing_lock(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _write(root / "Cargo.toml", '[workspace.package]\nversion="0.3.7"\n')
    assert "Rust" in _failure(root)


def test_rust_release_check_refuses_missing_manifest(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _write(
        root / "Cargo.lock",
        'version=4\n[[package]]\nname="onlyalpha-kernel"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-domain"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-clock"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-event"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-market-data-state"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-market-data-construction"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-market-data-delivery"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-market-data-pipeline"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-execution"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-broker"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-fee"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-settlement"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-margin"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-risk"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-strategy-ledger"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-account"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-position"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-order"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-strategy"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-calculation"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-gateway-protocol"\nversion="0.3.7"\n[[package]]\nname="onlyalpha-calculation-worker"\nversion="0.3.7"\n',
    )
    assert "Rust" in _failure(root)
