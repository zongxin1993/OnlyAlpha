"""Plan GitHub Releases from exact first-parent mainline version transitions."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from pathlib import Path


def _git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *arguments], text=True).strip()


def _version(root: Path, commit: str) -> tuple[str, tuple[int, int, int]]:
    value = tomllib.loads(_git(root, "show", f"{commit}:pyproject.toml"))["project"]["version"]
    if not isinstance(value, str) or re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value) is None:
        raise ValueError("Release version must be canonical X.Y.Z")
    major, minor, patch = map(int, value.split("."))
    return value, (major, minor, patch)


def plan_releases(root: Path, before: str, after: str) -> list[dict[str, str]]:
    for boundary in (before, after):
        if re.fullmatch(r"[0-9a-f]{40}", boundary) is None or boundary == "0" * 40:
            raise ValueError("Exact nonzero push commit boundaries required")
    ancestry = subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", before, after], check=False)
    if ancestry.returncode != 0:
        raise ValueError("Push before must be an ancestor of after")
    commits = _git(root, "rev-list", "--first-parent", "--reverse", f"{before}..{after}").splitlines()
    if commits and _git(root, "rev-parse", f"{commits[0]}^1") != before:
        raise ValueError("Push boundaries must share the first-parent mainline")
    previous, numbers = _version(root, before)
    releases = []
    for commit in commits:
        version, candidate = _version(root, commit)
        if candidate == numbers:
            continue
        major, minor, patch = numbers
        if candidate not in {(major, minor, patch + 1), (major, minor + 1, 0), (major + 1, 0, 0)}:
            raise ValueError(f"Invalid release transition: {previous} -> {version}")
        releases.append({"previous_version": previous, "version": version, "tag": f"v{version}", "sha": commit})
        previous, numbers = version, candidate
    return releases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before")
    parser.add_argument("after")
    args = parser.parse_args()
    print(json.dumps(plan_releases(Path(__file__).resolve().parents[1], args.before, args.after)))


if __name__ == "__main__":
    main()
