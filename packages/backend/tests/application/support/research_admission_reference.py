"""Controlled executable preparation through the owning Rust Runtime implementation."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

from scripts.build_algorithm_sdk import install
from scripts.dev_verification import source_inputs
from scripts.embed_build_provenance import resolve_build_provenance_bytes

ROOT = Path(__file__).resolve().parents[5]


def call(binary: Path, request: dict[str, Any]) -> dict[str, Any]:
    result = subprocess.run(
        [str(binary)], input=json.dumps(request), text=True, capture_output=True, check=True, timeout=30
    )
    value = json.loads(result.stdout)
    if not isinstance(value, dict) or "error" in value:
        diagnostic = "\n".join(
            line
            for line in result.stderr.splitlines()
            if line.startswith(("native-environment phase=", "[runtime-environment]"))
        )
        raise ValueError(f"NATIVE_RESEARCH_FIXTURE_FAILED: {value}\n{diagnostic}")
    return value


def build(
    root: Path,
    native_executable: Path,
    *,
    work_id: str | None = "research-input-fixture",
    preparation_kind: str = "FACTOR",
    candidate_record: dict[str, Any] | None = None,
    draft_record: dict[str, Any] | None = None,
    algorithm_bundle: tuple[Path, Path, str] | None = None,
) -> dict[str, Any]:
    assert not root.exists()
    candidate = candidate_record or {
        "name": "收盘价观察",
        "purpose": "准入测试",
        "hypothesis": "fixture",
        "expression": {"input": "close"},
    }
    factor = call(
        native_executable,
        {
            "op": "factor-reference",
            "candidate": candidate,
            "draft": draft_record,
            "factor_id": "private.factor.admission",
        },
    )
    release = root.with_name(root.name + "-release")
    release.mkdir()
    wheels, installation = release / "wheels", release / "algorithms"
    artifact = install(wheels, installation)
    if algorithm_bundle is not None:
        original_wheels, _, _ = algorithm_bundle
        expected = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in original_wheels.glob("*.whl")}
        actual = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in wheels.glob("*.whl")}
        if actual != expected:
            raise ValueError("NATIVE_RESEARCH_FIXTURE_WHEEL_MISMATCH")
    (release / "bin").mkdir()
    binary = release / "bin/onlyalpha-backend"
    shutil.copyfile(native_executable, binary)
    subprocess.run(["strip", "--strip-all", str(binary)], check=True, timeout=30)
    binary.chmod(0o500)
    (release / "source-provenance.json").write_bytes(resolve_build_provenance_bytes(ROOT))
    files = {
        str(path.relative_to(release)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in release.rglob("*")
        if path.is_file()
    }
    (release / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "runtime_root": str(release),
                "version": "0.11.1",
                "algorithm_artifact": artifact,
                "files": files,
                "source_inputs": source_inputs(ROOT),
            }
        )
    )
    prepared = call(
        binary,
        {
            "op": "runtime-environment",
            "preparation_kind": preparation_kind,
            "release_root": str(release),
            "runtime_root": str(root),
            "factor": factor,
            "algorithm_artifact": artifact,
            "fresh": True,
            "bind_work": work_id,
            "activation_command": str(uuid4()),
            "at": "2026-10-29T00:00:00Z",
        },
    )
    manifest = prepared["manifest"]
    shutil.copyfile(binary, root / "native-executor")
    (root / "native-executor").chmod(0o500)
    return {
        **factor,
        "generation": manifest["runtime_generation_fingerprint"],
        "runtime_root": str(root),
        "installation": str(installation),
        "algorithm_artifact": artifact,
        "executor_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "core_execution_fingerprint": hashlib.sha256(
            json.dumps(manifest["core_execution"], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
