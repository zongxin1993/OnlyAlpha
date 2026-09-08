"""Generate the immutable OnlyAlpha source-provenance package resource at build time."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

_GIT_REVISION = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")


def resolve_build_source_revision(repository_root: Path, explicit_revision: str | None = None) -> str:
    revision = explicit_revision or os.environ.get("ONLYALPHA_BUILD_SOURCE_REVISION")
    if revision is None:
        try:
            revision = subprocess.run(
                ("git", "-C", str(repository_root), "rev-parse", "HEAD"),
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
        except (FileNotFoundError, subprocess.SubprocessError) as exc:
            raise ValueError("ONLYALPHA_BUILD_SOURCE_REVISION_UNAVAILABLE") from exc
    if _GIT_REVISION.fullmatch(revision) is None:
        raise ValueError("ONLYALPHA_BUILD_SOURCE_REVISION_INVALID")
    return revision


def build_provenance_bytes(repository_root: Path, revision: str) -> bytes:
    project = repository_root / "pyproject.toml"
    version = next(
        line.split("=", 1)[1].strip().strip('"')
        for line in project.read_text(encoding="utf-8").splitlines()
        if line.startswith("version = ")
    )
    payload = {
        "distribution_name": "onlyalpha",
        "distribution_version": version,
        "schema_version": 1,
        "source_provenance_authority": "ONLYALPHA_GIT",
        "source_repository": "OnlyAlpha",
        "source_revision": revision,
    }
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def write_build_provenance(repository_root: Path, destination: Path, revision: str | None = None) -> Path:
    exact_revision = resolve_build_source_revision(repository_root, revision)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(build_provenance_bytes(repository_root, exact_revision))
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--revision")
    parser.add_argument(
        "--destination",
        type=Path,
        default=Path("src/onlyalpha/_build_provenance.json"),
    )
    args = parser.parse_args()
    repository_root = Path(__file__).resolve().parents[1]
    write_build_provenance(repository_root, args.destination, args.revision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
