"""Build the native Shipping resources in the canonical frozen tool environment."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_algorithm_sdk import install
from scripts.dev_verification import CUT_METADATA, source_inputs
from scripts.native_http_contract import native_executable

ROOT = Path(__file__).resolve().parents[1]
BUILD_ENVIRONMENT = {"NODE_ENV": "production", "VITE_ONLYALPHA_LOCAL_SESSION": "true"}


def web_environment(environment: dict[str, str]) -> dict[str, str]:
    return {**{key: value for key, value in environment.items() if not key.startswith("VITE_")}, **BUILD_ENVIRONMENT}


def _digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _files(directory: Path) -> dict[str, str]:
    files = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("NATIVE_ARTIFACT_SYMLINK")
        relative = path.relative_to(directory).as_posix()
        if path.is_file() and relative not in {"manifest.json", "deployment.json"}:
            files[relative] = _digest(path)
    return files


def verify_artifacts(
    directory: Path, inputs: dict[str, str], version: str, *, runtime_root: Path | None = None
) -> dict[str, Any]:
    if directory.is_symlink() or (directory / "manifest.json").is_symlink():
        raise ValueError("NATIVE_ARTIFACT_SYMLINK")
    manifest = json.loads((directory / "manifest.json").read_text())
    if not isinstance(manifest, dict):
        raise ValueError("NATIVE_ARTIFACT_INPUT_MISMATCH")
    if (
        set(manifest)
        != {
            "schema_version",
            "version",
            "runtime_root",
            "source_inputs",
            "build_environment",
            "algorithm_artifact",
            "files",
        }
        or manifest["schema_version"] != 1
        or manifest["version"] != version
        or manifest["runtime_root"] != str(runtime_root or directory)
        or manifest["source_inputs"] != inputs
        or manifest["build_environment"] != BUILD_ENVIRONMENT
    ):
        raise ValueError("NATIVE_ARTIFACT_INPUT_MISMATCH")
    if (
        not isinstance(manifest["algorithm_artifact"], str)
        or len(manifest["algorithm_artifact"]) != 64
        or any(c not in "0123456789abcdef" for c in manifest["algorithm_artifact"])
    ):
        raise ValueError("NATIVE_ARTIFACT_IDENTITY_INVALID")
    if not isinstance(manifest["files"], dict) or not manifest["files"]:
        raise ValueError("NATIVE_ARTIFACT_FILES_INVALID")
    for name in manifest["files"]:
        path = Path(name)
        if not isinstance(name, str) or path.is_absolute() or ".." in path.parts or path.as_posix() != name:
            raise ValueError("NATIVE_ARTIFACT_PATH_INVALID")
    if _files(directory) != manifest["files"]:
        raise ValueError("NATIVE_ARTIFACT_CONTENT_MISMATCH")
    return manifest


def build(directory: Path) -> dict[str, Any]:
    operation = os.environ["ONLYALPHA_DEV_VERIFICATION_OPERATION_ID"]
    cut = json.loads((ROOT / CUT_METADATA).read_text())
    inputs = source_inputs(ROOT)
    if cut["operation_id"] != operation or cut["inputs"] != inputs or directory.exists() or not directory.is_absolute():
        raise ValueError("NATIVE_BUILD_FROZEN_INPUT_REQUIRED")
    directory.mkdir(parents=True)
    (directory / "bin").mkdir()
    shutil.copy2(native_executable(), directory / "bin/onlyalpha-backend")
    artifact = install(directory / "wheels", directory / "algorithms")
    (directory / "algorithm-artifact.sha256").write_text(artifact + "\n")
    with (directory / "web-build.log").open("w") as log:
        result = subprocess.run(
            ["npm", "run", "build", "--", "--outDir", str(directory / "web"), "--emptyOutDir"],
            cwd=ROOT / "packages/frontend",
            env=web_environment(dict(os.environ)),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    result.check_returncode()
    shutil.copytree(ROOT / "database/postgres/migrations", directory / "schema")
    if source_inputs(ROOT) != inputs:
        raise ValueError("NATIVE_BUILD_SOURCE_CHANGED")
    version = tomllib.loads((ROOT / "packages/backend/Cargo.toml").read_text())["package"]["version"]
    manifest = {
        "schema_version": 1,
        "version": version,
        "runtime_root": str(directory),
        "source_inputs": inputs,
        "build_environment": BUILD_ENVIRONMENT,
        "algorithm_artifact": artifact,
        "files": _files(directory),
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    verify_artifacts(directory, inputs, version)
    return manifest


def main() -> None:
    directory = ROOT / "test-results/native-workstation" / os.environ["ONLYALPHA_DEV_VERIFICATION_OPERATION_ID"]
    manifest = build(directory)
    print(
        json.dumps(
            {
                "artifact_root": str(directory),
                "version": manifest["version"],
                "algorithm_artifact": manifest["algorithm_artifact"],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
