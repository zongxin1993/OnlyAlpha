"""Manifest-derived release metadata, usable by dependency-free runtime preflight."""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND_MANIFEST = Path("packages/backend/Cargo.toml")
WEB_PACKAGE_PATH = Path("packages/frontend/package.json")


class VersionSyncError(ValueError):
    """Invalid or inconsistent release metadata."""


def validate_release_version(version: str) -> None:
    if (
        not isinstance(version, str)
        or re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version) is None
    ):
        raise VersionSyncError(f"release version must be canonical X.Y.Z: {version!r}")


def plugin_release_unit(name: str) -> str:
    """Preserve the original distribution-derived release IDs, including history."""
    if not isinstance(name, str) or re.fullmatch(r"onlyalpha-[a-z0-9]+(?:-[a-z0-9]+)*", name) is None:
        raise VersionSyncError(f"invalid plugin distribution name: {name!r}")
    return "plugin-" + name.removeprefix("onlyalpha-plugin-")


def plugin_release_members(
    root: Path, read_text: Callable[[Path], str] | None = None
) -> list[tuple[str, Path, dict[str, Any], bool]]:
    """Resolve plugin ownership from exact workspace members and declared names."""
    raw = read_text if read_text is not None else lambda path: (root / path).read_text(encoding="utf-8")
    cargo = tomllib.loads(raw(Path("Cargo.toml")))["workspace"]["members"]
    python = tomllib.loads(raw(Path("pyproject.toml")))["tool"]["uv"]["workspace"]["members"]
    result = []
    owners: dict[str, Path] = {}
    names: dict[Path, str] = {}
    seen: set[tuple[Path, bool]] = set()
    for members, filename, section, rust in (
        (cargo, "Cargo.toml", "package", True),
        (python, "pyproject.toml", "project", False),
    ):
        for member in members:
            if not isinstance(member, str):
                raise VersionSyncError("invalid plugin workspace path")
            directory = Path(member)
            if (
                not directory.parts
                or directory.is_absolute()
                or ".." in directory.parts
                or directory.as_posix() != member
            ):
                raise VersionSyncError("invalid plugin workspace path")
            if directory.parts[0] != "plugs":
                continue
            package = tomllib.loads(raw(directory / filename))[section]
            name = package["name"]
            unit = plugin_release_unit(name)
            if (
                owners.get(unit, directory) != directory
                or names.get(directory, name) != name
                or (directory, rust) in seen
            ):
                raise VersionSyncError("ambiguous plugin release-unit ownership")
            owners[unit] = directory
            names[directory] = name
            seen.add((directory, rust))
            result.append((unit, directory, package, rust))
    return result


def load_release_units(root: Path = ROOT, revision: str | None = None) -> dict[str, str]:
    def raw(path: Path) -> str:
        if revision is None:
            return (root / path).read_text(encoding="utf-8")
        # Read the authority present in this exact historical tree. This is Git
        # publication history, never an installed-runtime compatibility path.
        original = {
            BACKEND_MANIFEST: Path("packages/onlyalpha-http-server/Cargo.toml"),
            WEB_PACKAGE_PATH: Path("packages/onlyalpha-web-console/package.json"),
        }.get(path)
        if original is not None:
            candidates = subprocess.check_output(
                ["git", "-C", str(root), "ls-tree", "-r", "--name-only", revision, "--", str(path), str(original)],
                text=True,
            ).splitlines()
            if len(candidates) != 1:
                raise VersionSyncError("historical release metadata authority is missing or ambiguous")
            path = Path(candidates[0])
        return subprocess.check_output(["git", "-C", str(root), "show", f"{revision}:{path.as_posix()}"], text=True)

    try:
        cargo = tomllib.loads(raw(Path("Cargo.toml")))
        library_version = cargo["workspace"]["package"]["version"]

        def resolved_version(value: Any) -> str:
            if isinstance(value, str):
                return value
            if isinstance(value, dict) and set(value) == {"workspace"} and value["workspace"] is True:
                return str(library_version)
            raise VersionSyncError("invalid workspace version inheritance")

        backend = tomllib.loads(raw(BACKEND_MANIFEST))["package"]["version"]
        # Exact historical metadata may inherit the old workspace version. Current
        # check_versions requires an independent backend authority after cutover.
        units = {"libs": library_version, "backend": resolved_version(backend)}
        units["frontend"] = json.loads(raw(WEB_PACKAGE_PATH))["version"]
        for unit, _, package, rust in plugin_release_members(root, raw):
            value = resolved_version(package["version"]) if rust else package["version"]
            if unit in units and units[unit] != value:
                raise VersionSyncError("conflicting plugin version projections")
            units[unit] = value
        python = tomllib.loads(raw(Path("pyproject.toml")))
        for member in python["tool"]["uv"]["workspace"]["members"]:
            if member == "packages/agent":
                package = tomllib.loads(raw(Path(member) / "pyproject.toml"))["project"]
                if package["name"] != "onlyalpha-agent":
                    raise VersionSyncError("invalid Agent distribution authority")
                units["agent"] = package["version"]
        for version in units.values():
            validate_release_version(version)
        return dict(sorted(units.items()))
    except (OSError, KeyError, TypeError, ValueError, subprocess.CalledProcessError) as error:
        raise VersionSyncError("cannot establish exact release-unit metadata") from error


def validate_inventory(base: dict[str, str], candidate: dict[str, str]) -> bool:
    """Explicit historical introduction and approved single-unit retirements only.

    The initial 0.1.0 establishes the line. Later version transitions use normal
    explicit selections. Agent and Generic T0 Cash have individually approved retirements.
    """
    if base.keys() == candidate.keys():
        return False
    if (
        candidate.keys() - base.keys() == {"agent"}
        and not base.keys() - candidate.keys()
        and candidate["agent"] == "0.1.0"
    ):
        return True
    if base.keys() - candidate.keys() in ({"agent"}, {"plugin-generic-t0-cash"}) and not candidate.keys() - base.keys():
        return False
    raise VersionSyncError("release-unit inventory changed; explicit inventory migration is required")
