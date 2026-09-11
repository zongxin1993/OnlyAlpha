"""Build-time immutable provenance helper for the Orchestrator distribution."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

_GIT_REVISION = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_CARRIED = Path("src/onlyalpha_agent_orchestrator/_build_provenance.json")
_CARRIED_DIGEST = Path("src/onlyalpha_agent_orchestrator/_build_provenance.sha256")


def _revision(value: str) -> str:
    if _GIT_REVISION.fullmatch(value) is None:
        raise ValueError("ONLYALPHA_AGENT_ORCHESTRATOR_BUILD_SOURCE_REVISION_INVALID")
    return value


def _version(project_root: Path) -> str:
    return next(
        line.split("=", 1)[1].strip().strip('"')
        for line in (project_root / "pyproject.toml").read_text(encoding="utf-8").splitlines()
        if line.startswith("version = ")
    )


def build_provenance_bytes(project_root: Path, revision: str) -> bytes:
    payload = {
        "distribution_name": "onlyalpha-agent-orchestrator",
        "distribution_version": _version(project_root),
        "schema_version": 1,
        "source_provenance_authority": "ONLYALPHA_GIT",
        "source_repository": "OnlyAlpha",
        "source_revision": _revision(revision),
    }
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _git_repository(project_root: Path) -> Path | None:
    for candidate in (project_root, *project_root.parents):
        if (candidate / ".git").exists() and (candidate / "PROJECT_CONSTITUTION.md").is_file():
            return candidate
    return None


def _git_revision(repository_root: Path) -> str:
    try:
        value = subprocess.run(
            ("git", "-C", str(repository_root), "rev-parse", "HEAD"),
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise ValueError("ONLYALPHA_AGENT_ORCHESTRATOR_BUILD_SOURCE_REVISION_UNAVAILABLE") from exc
    return _revision(value)


def _carried_provenance(project_root: Path) -> bytes:
    try:
        raw = (project_root / _CARRIED).read_bytes()
        digest = (project_root / _CARRIED_DIGEST).read_bytes()
        payload = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("ONLYALPHA_AGENT_ORCHESTRATOR_BUILD_PROVENANCE_INVALID") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("source_revision"), str):
        raise ValueError("ONLYALPHA_AGENT_ORCHESTRATOR_BUILD_PROVENANCE_INVALID")
    canonical = build_provenance_bytes(project_root, payload["source_revision"])
    expected_digest = (hashlib.sha256(raw).hexdigest() + "\n").encode()
    if raw != canonical or digest != expected_digest:
        raise ValueError("ONLYALPHA_AGENT_ORCHESTRATOR_BUILD_PROVENANCE_INVALID")
    return raw


def resolve_build_provenance_bytes(project_root: Path) -> bytes:
    carrier_exists = (project_root / _CARRIED).exists() or (project_root / _CARRIED_DIGEST).exists()
    carried = _carried_provenance(project_root) if carrier_exists else None
    repository = _git_repository(project_root)
    revision = _git_revision(repository) if repository is not None else None
    if carried is None and revision is None:
        raise ValueError("ONLYALPHA_AGENT_ORCHESTRATOR_BUILD_SOURCE_REVISION_UNAVAILABLE")
    if carried is not None and revision is not None and carried != build_provenance_bytes(project_root, revision):
        raise ValueError("ONLYALPHA_AGENT_ORCHESTRATOR_BUILD_PROVENANCE_CONFLICT")
    return carried if carried is not None else build_provenance_bytes(project_root, revision or "")


def write_build_provenance(destination: Path, provenance: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(provenance)
    destination.with_name("_build_provenance.sha256").write_bytes(
        (hashlib.sha256(provenance).hexdigest() + "\n").encode()
    )
