"""Plan GitHub Releases from exact first-parent mainline version transitions."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.version_sync import load_release_units, next_release_version  # noqa: E402


def _git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *arguments], text=True).strip()


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
    previous = load_release_units(root, before)
    releases = []
    for commit in commits:
        candidate = load_release_units(root, commit)
        if candidate.keys() != previous.keys():
            raise ValueError("Release-unit inventory changed without an explicit inventory migration")
        for unit, version in candidate.items():
            old = previous[unit]
            if version == old:
                continue
            if version not in {next_release_version(old, level) for level in ("patch", "minor", "major")}:
                raise ValueError(f"Invalid release transition: {unit}: {old} -> {version}")
            releases.append(
                {"unit": unit, "previous_version": old, "version": version, "tag": f"{unit}-v{version}", "sha": commit}
            )
        previous = candidate
    return releases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before")
    parser.add_argument("after")
    args = parser.parse_args()
    print(json.dumps(plan_releases(Path(__file__).resolve().parents[1], args.before, args.after)))


if __name__ == "__main__":
    main()
