from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts import version_sync as release


def write(root: Path, name: str, value: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


@pytest.fixture
def graph(tmp_path: Path) -> Path:
    write(
        tmp_path,
        "Cargo.toml",
        """[workspace]
members = ["crates/domain", "packages/onlyalpha-http-server", "plugs/onlyalpha-plugin-test"]
[workspace.package]
version = "0.4.0"
""",
    )
    for directory, name, version in (
        ("crates/domain", "onlyalpha-domain", "version.workspace = true"),
        ("packages/onlyalpha-http-server", "onlyalpha-http-server", 'version = "0.7.0"'),
        ("plugs/onlyalpha-plugin-test", "onlyalpha-plugin-test", 'version = "0.2.0"'),
    ):
        write(tmp_path, directory + "/Cargo.toml", f'[package]\nname = "{name}"\n{version}\n')
    write(
        tmp_path,
        "Cargo.lock",
        """version = 4
[[package]]
name = "onlyalpha-domain"
version = "0.4.0"
[[package]]
name = "onlyalpha-http-server"
version = "0.7.0"
[[package]]
name = "onlyalpha-plugin-test"
version = "0.2.0"
""",
    )
    write(
        tmp_path,
        "pyproject.toml",
        """[project]
name = "onlyalpha"
version = "0.7.0"
dependencies = ["onlyalpha-plugin-test==0.2.0"]
[tool.uv.workspace]
members = ["plugs/onlyalpha-plugin-test"]
""",
    )
    write(
        tmp_path,
        "plugs/onlyalpha-plugin-test/pyproject.toml",
        """[project]
name = "onlyalpha-plugin-test"
version = "0.2.0"
dependencies = ["onlyalpha==0.7.0"]
""",
    )
    for name in ("package.json", "package-lock.json"):
        write(
            tmp_path,
            "packages/onlyalpha-web-console/" + name,
            json.dumps({"version": "0.9.0", "packages": {"": {"version": "0.9.0"}}}),
        )
    return tmp_path


def test_independent_versions_and_target_specific_edges_are_valid(graph: Path) -> None:
    release.check_versions(graph, test_distribution_paths=())


def test_frontend_selection_preserves_all_other_units(graph: Path) -> None:
    before = {p.relative_to(graph): p.read_bytes() for p in graph.rglob("*") if p.is_file()}
    release.rewrite_unit(graph, "frontend", "0.9.1", test_distribution_paths=())
    release.check_versions(graph, test_distribution_paths=())
    for path, content in before.items():
        if path.name not in {"package.json", "package-lock.json"}:
            assert (graph / path).read_bytes() == content
    assert (
        json.loads((graph / "packages/onlyalpha-web-console/package-lock.json").read_text())["packages"][""]["version"]
        == "0.9.1"
    )


def test_plugin_selection_updates_only_plugin_identity_and_incoming_pins(graph: Path) -> None:
    release.rewrite_unit(graph, "plugin-test", "0.2.1", test_distribution_paths=())
    release.check_versions(graph, test_distribution_paths=())
    assert "onlyalpha-plugin-test==0.2.1" in (graph / "pyproject.toml").read_text()
    assert 'version = "0.7.0"' in (graph / "pyproject.toml").read_text()
    assert "onlyalpha==0.7.0" in (graph / "plugs/onlyalpha-plugin-test/pyproject.toml").read_text()


def test_mismatched_rust_lock_is_refused(graph: Path) -> None:
    p = graph / "Cargo.lock"
    p.write_text(p.read_text().replace("0.2.0", "0.1.0"))
    with pytest.raises(release.VersionSyncError, match="lock"):
        release.check_versions(graph, test_distribution_paths=())


def test_release_selection_is_explicit_and_scoped() -> None:
    context: dict[str, Any] = {"pull_request": {"labels": []}, "events": []}
    assert release.release_selections_from_context(context) == {}
    context["pull_request"]["labels"] = [{"name": "release:frontend:patch"}]
    assert release.release_selections_from_context(context) == {"frontend": "patch"}


def test_missing_unit_never_falls_back_to_global_rewrite(graph: Path) -> None:
    before = (graph / "Cargo.toml").read_bytes()
    with pytest.raises(release.VersionSyncError):
        release.rewrite_unit(graph, "unknown", "0.4.1", test_distribution_paths=())
    assert (graph / "Cargo.toml").read_bytes() == before


@pytest.mark.parametrize("table", ["{ workspace = false }", "{ other = true }", "{ workspace = 1 }"])
def test_invalid_inherited_version_never_substitutes_library_version(graph: Path, table: str) -> None:
    path = graph / "packages/onlyalpha-http-server/Cargo.toml"
    path.write_text('[package]\nname="onlyalpha-http-server"\nversion=' + table + "\n")
    with pytest.raises(release.VersionSyncError):
        release.load_release_units(graph)
