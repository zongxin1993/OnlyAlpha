from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from packaging.requirements import Requirement

from scripts import version_sync as release
from tests.tools.test_release_units import graph as graph
from tests.tools.test_release_units import write


def check(root: Path) -> None:
    release.check_versions(root, test_distribution_paths=())


def quant_asset_plugin(graph: Path, plugin: str) -> Path:
    for path in graph.rglob("*"):
        if path.is_file():
            path.write_text(path.read_text().replace("onlyalpha-plugin-test", "onlyalpha-plugin-" + plugin))
    (graph / "plugs/onlyalpha-plugin-test").rename(graph / ("plugs/onlyalpha-plugin-" + plugin))
    return graph / f"plugs/onlyalpha-plugin-{plugin}/src/onlyalpha_plugin_{plugin}"


@pytest.fixture
def operators(graph: Path) -> Path:
    package = quant_asset_plugin(graph, "operators")
    write(graph, str((package / "metadata.py").relative_to(graph)), 'DISTRIBUTION_VERSION = "0.2.0"\n')
    write(
        graph,
        str((package / "provider.py").relative_to(graph)),
        "from onlyalpha_plugin_operators.metadata import DISTRIBUTION_VERSION\n"
        "from onlyalpha.quant_assets import OnlyDistributionProviderSource, OnlyQuantAssetProvider, OnlyQuantAssetProviderManifest\n"
        "def quant_asset_provider():\n"
        "    return OnlyQuantAssetProvider(\n"
        "        OnlyQuantAssetProviderManifest(\n"
        '            source=OnlyDistributionProviderSource("onlyalpha-plugin-operators", DISTRIBUTION_VERSION),\n'
        "        ),\n"
        "    )\n",
    )
    return package


@pytest.mark.parametrize("keyword", [False, True])
def test_operators_metadata_is_the_checked_distribution_projection(graph: Path, operators: Path, keyword: bool) -> None:
    if keyword:
        path = operators / "provider.py"
        path.write_text(
            path.read_text().replace(", DISTRIBUTION_VERSION)", ", distribution_version=DISTRIBUTION_VERSION)")
        )
    check(graph)
    assert release.load_release_units(graph)["plugin-operators"] == "0.2.0"


@pytest.mark.parametrize("fault", ["wrong", "missing", "duplicate", "nonliteral", "augmented", "annotated"])
def test_operator_distribution_projection_requires_one_exact_version(graph: Path, operators: Path, fault: str) -> None:
    path = operators / "metadata.py"
    if fault == "missing":
        path.unlink()
    elif fault == "wrong":
        path.write_text('DISTRIBUTION_VERSION = "0.1.0"\n')
    elif fault == "duplicate":
        path.write_text(path.read_text() * 2)
    else:
        rebound = {
            "nonliteral": 'DISTRIBUTION_VERSION = str("0.1.0")\n',
            "augmented": 'DISTRIBUTION_VERSION += "+unexpected"\n',
            "annotated": 'DISTRIBUTION_VERSION: str = "0.1.0"\n',
        }
        path.write_text(path.read_text() + rebound[fault])
    with pytest.raises(release.VersionSyncError, match="quant asset distribution provenance mismatch"):
        check(graph)


@pytest.mark.parametrize("fault", ["literal", "alias", "rebind", "parameter", "other-module", "unused-call", "missing"])
def test_operator_provider_must_use_the_unaliased_projection(graph: Path, operators: Path, fault: str) -> None:
    path = operators / "provider.py"
    source = path.read_text()
    if fault == "literal":
        source = source.replace(", DISTRIBUTION_VERSION)", ', "0.2.0")')
    elif fault == "alias":
        source = source.replace("import DISTRIBUTION_VERSION", "import DISTRIBUTION_VERSION as VERSION")
        source = source.replace(", DISTRIBUTION_VERSION)", ", VERSION)")
    elif fault == "rebind":
        source += '\nDISTRIBUTION_VERSION = "0.2.0"\n'
    elif fault == "parameter":
        source = source.replace(
            "def quant_asset_provider():", 'def quant_asset_provider(DISTRIBUTION_VERSION="0.2.0"):'
        )
    elif fault == "other-module":
        source = source.replace("onlyalpha_plugin_operators.metadata", "onlyalpha_plugin_indicators.metadata")
    elif fault == "unused-call":
        source = "from onlyalpha.quant_assets import OnlyDistributionProviderSource as SourceAlias\n" + source
        source = source.replace("source=OnlyDistributionProviderSource(", "source=SourceAlias(")
        source = source.replace(", DISTRIBUTION_VERSION)", ', "0.1.0")')
        source += '\nunused = OnlyDistributionProviderSource("onlyalpha-plugin-operators", DISTRIBUTION_VERSION)\n'
    else:
        path.unlink()
    if fault != "missing":
        path.write_text(source)
    with pytest.raises(release.VersionSyncError, match="quant asset distribution provenance mismatch"):
        check(graph)


def test_operator_rewrite_updates_the_actual_projection_and_preserves_other_units(graph: Path, operators: Path) -> None:
    before_provider = (operators / "provider.py").read_bytes()
    before_units = release.load_release_units(graph)
    release.rewrite_unit(graph, "plugin-operators", "0.2.1", test_distribution_paths=())
    check(graph)
    assert (operators / "metadata.py").read_text() == 'DISTRIBUTION_VERSION = "0.2.1"\n'
    assert (operators / "provider.py").read_bytes() == before_provider
    assert release.load_release_units(graph) == {**before_units, "plugin-operators": "0.2.1"}
    assert "onlyalpha-plugin-operators==0.2.1" in (graph / "pyproject.toml").read_text()


def test_indicator_literal_projection_is_checked_and_rewritten(graph: Path) -> None:
    package = quant_asset_plugin(graph, "indicators")
    path = package / "provider.py"
    write(
        graph,
        str(path.relative_to(graph)),
        'source = Source(\n    distribution_version="0.2.0",\n)\n',
    )
    check(graph)
    release.rewrite_unit(graph, "plugin-indicators", "0.2.1", test_distribution_paths=())
    check(graph)
    assert 'distribution_version="0.2.1",' in path.read_text()
    path.write_text(path.read_text().replace('"0.2.1"', '"0.2.0"'))
    with pytest.raises(release.VersionSyncError, match="quant asset distribution provenance mismatch"):
        check(graph)
    path.unlink()
    with pytest.raises(release.VersionSyncError, match="quant asset distribution provenance mismatch"):
        check(graph)


@pytest.mark.parametrize(("level", "expected"), [("patch", "0.9.10"), ("minor", "0.10.0"), ("major", "1.0.0")])
def test_release_increment_resets_lower_components(level: str, expected: str) -> None:
    assert release.next_release_version("0.9.9", level) == expected
    assert expected in release.check_release_transition("0.9.9", expected, level)


@pytest.mark.parametrize(
    "version", ["0.9", "v0.9.10", "00.9.10", "0.09.10", "0.9.010", "0.9.10rc1", "0.9.10+build", "0.9.10\n"]
)
def test_release_increment_refuses_noncanonical_numbers(version: str) -> None:
    with pytest.raises(release.VersionSyncError, match="canonical X.Y.Z"):
        release.next_release_version(version)


@pytest.mark.parametrize("version", ["0.9.9", "0.9.8", "0.9.11", "0.10.0"])
def test_stale_skipped_or_unselected_increment_fails(version: str) -> None:
    with pytest.raises(release.VersionSyncError):
        release.check_release_transition("0.9.9", version)


def test_rewrite_preserves_external_requirements_extras_and_markers() -> None:
    raw = 'OnlyAlpha-Market-A[foo]>=0.3; python_version >= "3.12"'
    value = release.rewrite_internal_requirement(
        raw, formal_distribution_names=frozenset({"onlyalpha-market-a"}), version="0.4.0"
    )
    requirement = Requirement(value)
    assert requirement.extras == {"foo"} and str(requirement.specifier) == "==0.4.0"
    assert str(requirement.marker) == 'python_version >= "3.12"'
    assert (
        release.rewrite_internal_requirement("pandas>=2", formal_distribution_names=frozenset(), version="0.4.0")
        == "pandas>=2"
    )


@pytest.mark.parametrize(
    "dependency", ["onlyalpha>=0.7", "onlyalpha", "onlyalpha==0.6.0", "onlyalpha @ file:///tmp/onlyalpha"]
)
def test_internal_edges_pin_the_target_version(graph: Path, dependency: str) -> None:
    p = graph / "plugs/onlyalpha-plugin-test/pyproject.toml"
    p.write_text(p.read_text().replace("onlyalpha==0.7.0", dependency))
    with pytest.raises(release.VersionSyncError, match="internal dependency"):
        check(graph)


def test_optional_internal_edge_is_checked(graph: Path) -> None:
    p = graph / "pyproject.toml"
    p.write_text(p.read_text() + '\n[project.optional-dependencies]\nx = ["onlyalpha-plugin-test==0.1.0"]\n')
    with pytest.raises(release.VersionSyncError, match="internal dependency"):
        check(graph)


def test_missing_manifest_and_lock_are_refused(graph: Path) -> None:
    (graph / "Cargo.lock").unlink()
    with pytest.raises(release.VersionSyncError, match="lock"):
        check(graph)
    (graph / "plugs/onlyalpha-plugin-test/pyproject.toml").unlink()
    with pytest.raises(release.VersionSyncError):
        check(graph)


def test_mixed_language_plugin_has_one_version_authority(graph: Path) -> None:
    p = graph / "plugs/onlyalpha-plugin-test/pyproject.toml"
    p.write_text(p.read_text().replace('version = "0.2.0"', 'version = "0.2.1"'))
    with pytest.raises(release.VersionSyncError, match="expected version"):
        check(graph)


def test_fixture_version_stays_independent_but_incoming_edge_changes(graph: Path) -> None:
    fixture = Path("test-data/fixture/pyproject.toml")
    path = graph / fixture
    path.parent.mkdir(parents=True)
    path.write_text('[project]\nname="fixture"\nversion="99.4"\ndependencies=["onlyalpha==0.7.0"]\n')
    release.rewrite_unit(graph, "backend", "0.7.1", test_distribution_paths=(fixture,))
    release.check_versions(graph, test_distribution_paths=(fixture,))
    text = path.read_text()
    assert 'version="99.4"' in text and "onlyalpha==0.7.1" in text


def test_lib_bump_does_not_bump_backend_or_plugin(graph: Path) -> None:
    release.rewrite_unit(graph, "libs", "0.4.1", test_distribution_paths=())
    check(graph)
    assert release.load_release_units(graph) == {
        "libs": "0.4.1",
        "backend": "0.7.0",
        "frontend": "0.9.0",
        "plugin-test": "0.2.0",
    }


def context(level: str = "minor") -> dict[str, Any]:
    label = f"release:frontend:{level}"
    return {
        "repository": {"owner": {"type": "User", "login": "owner"}},
        "pull_request": {"labels": [{"name": label}]},
        "events": [{"id": 1, "event": "labeled", "label": {"name": label}, "actor": {"login": "owner"}}],
    }


@pytest.mark.parametrize("level", ["patch", "minor", "major"])
def test_owner_can_select_each_unit_level(level: str) -> None:
    assert release.release_selections_from_context(context(level)) == {"frontend": level}


@pytest.mark.parametrize("condition", ["non-owner", "generic-approval", "organization", "readded"])
def test_minor_requires_the_actual_owner_label_action(condition: str) -> None:
    value = context()
    if condition == "organization":
        value["repository"]["owner"]["type"] = "Organization"
    elif condition == "readded":
        value["events"] += [
            {"id": 2, "event": "unlabeled", "label": {"name": "release:frontend:minor"}, "actor": {"login": "other"}},
            {"id": 3, "event": "labeled", "label": {"name": "release:frontend:minor"}, "actor": {"login": "other"}},
        ]
    else:
        value["events"][0]["actor"]["login"] = "other"
        value["reviews"] = [{"user": {"login": "owner"}, "state": "APPROVED"}]
    with pytest.raises(release.VersionSyncError):
        release.release_selections_from_context(value)


@pytest.mark.parametrize(
    "label", ["release:patch", "release:unknown:patch", "release:frontend:force", "release:frontend:major"]
)
def test_unknown_or_conflicting_selection_fails(label: str) -> None:
    value = context()
    value["pull_request"]["labels"].append({"name": label})
    with pytest.raises(release.VersionSyncError):
        release.release_selections_from_context(value)


def test_multiple_units_can_be_selected_independently() -> None:
    value = context()
    value["pull_request"]["labels"].append({"name": "release:backend:patch"})
    assert release.release_selections_from_context(value) == {"frontend": "minor", "backend": "patch"}


def test_merge_selection_uses_events_before_the_exact_merge() -> None:
    value = context()
    value["pull_request"].update(merged=True, merge_commit_sha="a" * 40, labels=[])
    value["events"] += [
        {"id": 2, "event": "merged", "commit_id": "a" * 40},
        {"id": 3, "event": "unlabeled", "label": {"name": "release:frontend:minor"}, "actor": {"login": "other"}},
    ]
    assert release.release_selections_from_context(value) == {"frontend": "minor"}
    value["events"] = value["events"][1:]
    assert release.release_selections_from_context(value) == {}


@pytest.mark.parametrize("condition", ["missing", "duplicate", "unordered"])
def test_incomplete_history_cannot_authorize_a_merge(condition: str) -> None:
    value = context()
    value["pull_request"].update(merged=True, merge_commit_sha="a" * 40)
    if condition != "missing":
        value["events"].append({"id": 2, "event": "merged", "commit_id": "a" * 40})
    if condition == "duplicate":
        value["events"].append({"id": 3, "event": "merged", "commit_id": "a" * 40})
    if condition == "unordered":
        value["events"].reverse()
    with pytest.raises(release.VersionSyncError):
        release.release_selections_from_context(value)


def test_only_selected_changed_units_can_advance() -> None:
    base = {"libs": "0.4.0", "frontend": "0.9.0"}
    assert release.validate_transitions(base, base, {}) == []
    for selected in ({}, {"libs": "patch"}, {"frontend": "minor"}):
        with pytest.raises(release.VersionSyncError):
            release.validate_transitions(base, {**base, "frontend": "0.9.1"}, selected)
    assert release.validate_transitions(base, {**base, "frontend": "0.9.1"}, {"frontend": "patch"})


def test_next_cli_is_read_only(
    graph: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(release, "ROOT", graph)
    monkeypatch.setattr(sys, "argv", ["version_sync.py", "next", "--unit", "frontend", "--level", "minor"])
    # The default root is bound at definition; resolve it explicitly for this CLI test.
    original = release.load_release_units
    monkeypatch.setattr(release, "load_release_units", lambda: original(graph))
    before = (graph / "Cargo.toml").read_bytes()
    assert release.main() == 0
    assert capsys.readouterr().out.strip() == "0.10.0"
    assert (graph / "Cargo.toml").read_bytes() == before


def test_repository_release_graph_matches_actual_manifests() -> None:
    release.check_versions()


def test_workflow_checks_exact_head_base_context_and_permissions() -> None:
    import yaml  # type: ignore[import-untyped]  # The installed PyYAML has no bundled stubs.

    workflow = yaml.load((release.ROOT / ".github/workflows/release-version.yml").read_text(), Loader=yaml.BaseLoader)
    assert workflow["permissions"] == {"contents": "read", "pull-requests": "read", "issues": "read"}
    steps = workflow["jobs"]["transition"]["steps"]
    checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] == "false"
    script = "\n".join(str(step) for step in steps)
    assert "github.paginate" in script and "BASE_SHA" in script and "release-context.json" in script
    assert '--level "$LEVEL"' not in script


def test_merge_report_keeps_actual_unit_notice_when_history_is_missing(
    graph: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    value = context()
    value["pull_request"].update(merged=True, merge_commit_sha="a" * 40)
    context_file = tmp_path / "context.json"
    context_file.write_text(json.dumps(value))
    summary = tmp_path / "summary.md"
    monkeypatch.setattr(
        sys,
        "argv",
        ["version_sync.py", "report-merge", "--context-file", str(context_file), "--summary-file", str(summary)],
    )
    monkeypatch.setattr(
        release, "read_git_release_transition", lambda _: ({"frontend": "0.9.0"}, {"frontend": "0.10.0"})
    )
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: "a" * 40)
    monkeypatch.setattr(release, "check_versions", lambda: None)
    assert release.main() == 1
    assert "frontend" in summary.read_text() and "0.10.0" in summary.read_text()
    assert "Actual release transitions" in capsys.readouterr().out


def test_merge_report_rejects_context_for_a_different_exact_commit(
    graph: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    value = context()
    value["pull_request"].update(merged=True, merge_commit_sha="b" * 40)
    value["events"].append({"id": 2, "event": "merged", "commit_id": "b" * 40})
    context_file = tmp_path / "context.json"
    context_file.write_text(json.dumps(value))
    monkeypatch.setattr(sys, "argv", ["version_sync.py", "report-merge", "--context-file", str(context_file)])
    monkeypatch.setattr(
        release, "read_git_release_transition", lambda _: ({"frontend": "0.9.0"}, {"frontend": "0.10.0"})
    )
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: "a" * 40)
    assert release.main() == 1
    assert "different merge" in capsys.readouterr().err


def test_readme_and_dependency_groups_do_not_become_version_authorities(graph: Path) -> None:
    (graph / "README.md").write_text("release 99.99.99")
    p = graph / "pyproject.toml"
    p.write_text(p.read_text() + '\n[dependency-groups]\ndev=["onlyalpha==99.0.0"]\n')
    release.rewrite_unit(graph, "backend", "0.7.1", test_distribution_paths=())
    assert "onlyalpha==99.0.0" in p.read_text()
    assert (graph / "README.md").read_text() == "release 99.99.99"
    check(graph)


@pytest.mark.parametrize("field,value", [("name", ""), ("version", "not-a-version")])
def test_invalid_distribution_identity_is_refused(graph: Path, field: str, value: str) -> None:
    p = graph / "plugs/onlyalpha-plugin-test/pyproject.toml"
    document = release.read_document(p)
    document["project"][field] = value
    release.write_document(p, document)
    with pytest.raises(release.VersionSyncError):
        check(graph)


def test_duplicate_canonical_name_and_invalid_requirement_are_refused(graph: Path) -> None:
    p = graph / "plugs/onlyalpha-plugin-test/pyproject.toml"
    original = p.read_text()
    p.write_text(original.replace('name = "onlyalpha-plugin-test"', 'name = "OnlyAlpha"'))
    with pytest.raises(release.VersionSyncError, match="duplicate canonical"):
        check(graph)
    p.write_text(original.replace("onlyalpha==0.7.0", "invalid ???"))
    with pytest.raises(release.VersionSyncError, match="invalid requirement"):
        check(graph)
