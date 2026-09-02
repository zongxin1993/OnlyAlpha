"""Mechanical guard for the canonical repository taxonomy."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLUGIN_NAME = re.compile(r"^onlyalpha-plugin-[a-z0-9]+(?:-[a-z0-9]+)*$")
COMPONENT_NAME = re.compile(r"^onlyalpha-[a-z0-9]+-[a-z0-9]+(?:-[a-z0-9]+)*$")
FORBIDDEN = {
    "apps/onlyalpha-web",
    "packages/api",
    "packages/provider",
    "packages/market",
    "packages/protocol",
    "packages/fake",
    "packages/indicator",
    "packages/factor",
    "packages/target",
}


def test_plugin_and_component_directories_follow_taxonomy() -> None:
    assert all(path.name and PLUGIN_NAME.fullmatch(path.name) for path in (ROOT / "plugs").iterdir())
    assert all(path.name and COMPONENT_NAME.fullmatch(path.name) for path in (ROOT / "packages").iterdir())
    assert not any((ROOT / relative).exists() for relative in FORBIDDEN)
    assert not (ROOT / "apps").exists()


def test_distribution_metadata_matches_repository_identity() -> None:
    for parent in (ROOT / "plugs", ROOT / "packages"):
        for project in parent.glob("*/pyproject.toml"):
            metadata = tomllib.loads(project.read_text(encoding="utf-8"))
            assert metadata["project"]["name"] == project.parent.name
    web = tomllib.loads((ROOT / "packages/onlyalpha-http-server/pyproject.toml").read_text(encoding="utf-8"))
    assert web["project"]["name"] == "onlyalpha-http-server"


def test_core_does_not_import_concrete_plugin_namespaces() -> None:
    concrete = tuple(path.name for path in (ROOT / "plugs").glob("*/src/*") if path.is_dir())
    for source in (ROOT / "src/onlyalpha").rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert not any(re.search(rf"\b(?:from|import)\s+{re.escape(name)}\b", text) for name in concrete), source


def test_workspace_has_no_legacy_category_paths() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert not any(path in text for path in FORBIDDEN)
