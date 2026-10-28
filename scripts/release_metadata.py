"""Manifest-derived release metadata, usable by dependency-free runtime preflight."""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
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
        for member in cargo["workspace"]["members"]:
            if Path(member).parts[0] == "plugs":
                package = tomllib.loads(raw(Path(member) / "Cargo.toml"))["package"]
                value = package["version"]
                units["plugin-" + package["name"].removeprefix("onlyalpha-plugin-")] = resolved_version(value)
        python = tomllib.loads(raw(Path("pyproject.toml")))
        for member in python["tool"]["uv"]["workspace"]["members"]:
            if member == "packages/agent":
                package = tomllib.loads(raw(Path(member) / "pyproject.toml"))["project"]
                if package["name"] != "onlyalpha-agent":
                    raise VersionSyncError("invalid Agent distribution authority")
                units["agent"] = package["version"]
            if Path(member).parts[0] == "plugs":
                package = tomllib.loads(raw(Path(member) / "pyproject.toml"))["project"]
                unit = "plugin-" + package["name"].removeprefix("onlyalpha-plugin-")
                units.setdefault(unit, package["version"])
        for version in units.values():
            validate_release_version(version)
        return dict(sorted(units.items()))
    except (OSError, KeyError, TypeError, ValueError, subprocess.CalledProcessError) as error:
        raise VersionSyncError("cannot establish exact release-unit metadata") from error


def validate_inventory(base: dict[str, str], candidate: dict[str, str]) -> bool:
    """ADR 0146's sole inventory introduction, not a publication or arbitrary inventory override.

    The initial 0.1.0 establishes the line. Later version transitions use normal
    explicit selections. Removal, other additions and other initial versions fail closed.
    """
    if base.keys() == candidate.keys():
        return False
    if (
        candidate.keys() - base.keys() == {"agent"}
        and not base.keys() - candidate.keys()
        and candidate["agent"] == "0.1.0"
    ):
        return True
    raise VersionSyncError("release-unit inventory changed; explicit inventory migration is required")
