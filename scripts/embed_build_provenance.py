"""Generate the immutable OnlyAlpha source-provenance package resource at build time."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

_GIT_REVISION = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_CARRIED_PROVENANCE = Path("src/onlyalpha/_build_provenance.json")
_CARRIED_PROVENANCE_DIGEST = Path("src/onlyalpha/_build_provenance.sha256")


def validate_build_source_revision(revision: str) -> str:
    if _GIT_REVISION.fullmatch(revision) is None:
        raise ValueError("ONLYALPHA_BUILD_SOURCE_REVISION_INVALID")
    return revision


def read_git_build_source_revision(repository_root: Path) -> str:
    """Discover source identity only at a repository root that owns Git metadata."""

    if not (repository_root / ".git").exists():
        raise ValueError("ONLYALPHA_BUILD_SOURCE_REVISION_UNAVAILABLE")
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
    return validate_build_source_revision(revision)


def build_provenance_bytes(repository_root: Path, revision: str) -> bytes:
    exact_revision = validate_build_source_revision(revision)
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
        "source_revision": exact_revision,
    }
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def load_carried_build_provenance(repository_root: Path) -> bytes:
    """Verify the exact canonical carrier embedded by an earlier build phase."""

    source = repository_root / _CARRIED_PROVENANCE
    digest_source = repository_root / _CARRIED_PROVENANCE_DIGEST
    try:
        raw = source.read_bytes()
        digest = digest_source.read_bytes()
        payload = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("ONLYALPHA_BUILD_PROVENANCE_INVALID") from exc
    expected_fields = {
        "distribution_name",
        "distribution_version",
        "schema_version",
        "source_provenance_authority",
        "source_repository",
        "source_revision",
    }
    if not isinstance(payload, dict) or set(payload) != expected_fields:
        raise ValueError("ONLYALPHA_BUILD_PROVENANCE_INVALID")
    revision = payload.get("source_revision")
    if not isinstance(revision, str):
        raise ValueError("ONLYALPHA_BUILD_PROVENANCE_INVALID")
    try:
        canonical = build_provenance_bytes(repository_root, revision)
    except ValueError as exc:
        raise ValueError("ONLYALPHA_BUILD_PROVENANCE_INVALID") from exc
    expected_digest = (hashlib.sha256(raw).hexdigest() + "\n").encode()
    if raw != canonical or digest != expected_digest:
        raise ValueError("ONLYALPHA_BUILD_PROVENANCE_INVALID")
    return canonical


def resolve_build_provenance_bytes(repository_root: Path) -> bytes:
    """Derive at a Git source boundary or verify an already-carried artifact fact."""

    carrier_exists = (repository_root / _CARRIED_PROVENANCE).exists() or (
        repository_root / _CARRIED_PROVENANCE_DIGEST
    ).exists()
    git_exists = (repository_root / ".git").exists()
    carried = load_carried_build_provenance(repository_root) if carrier_exists else None
    revision = read_git_build_source_revision(repository_root) if git_exists else None
    if carried is None and revision is None:
        raise ValueError("ONLYALPHA_BUILD_SOURCE_REVISION_UNAVAILABLE")
    if carried is not None and revision is not None:
        derived = build_provenance_bytes(repository_root, revision)
        if carried != derived:
            raise ValueError("ONLYALPHA_BUILD_PROVENANCE_CONFLICT")
    return carried if carried is not None else build_provenance_bytes(repository_root, revision or "")


def write_build_provenance(repository_root: Path, destination: Path, provenance: bytes) -> Path:
    del repository_root
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(provenance)
    destination.with_name("_build_provenance.sha256").write_bytes(
        (hashlib.sha256(provenance).hexdigest() + "\n").encode()
    )
    return destination


def write_transported_build_provenance(repository_root: Path, destination: Path, revision: str) -> Path:
    """Materialize a revision already derived by an isolated boundary's host wrapper."""

    return write_build_provenance(repository_root, destination, build_provenance_bytes(repository_root, revision))


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
    if args.revision is None:
        provenance = resolve_build_provenance_bytes(repository_root)
        write_build_provenance(repository_root, args.destination, provenance)
    else:
        write_transported_build_provenance(repository_root, args.destination, args.revision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
