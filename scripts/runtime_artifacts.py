"""Shared artifact schema and exact bundled pair; verification needs only stdlib."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

BUILD_ENVIRONMENT = {"NODE_ENV": "production", "VITE_ONLYALPHA_LOCAL_SESSION": "true"}
CONTRACTS = {"openapi.json": "openapi", "market-data-stream.schema.json": "websocket"}


def encode(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def product_versions(root: Path) -> tuple[str, str]:
    backend = tomllib.loads((root / "packages/backend/Cargo.toml").read_text())["package"]["version"]
    frontend = json.loads((root / "packages/frontend/package.json").read_text())["version"]
    for value in (backend, frontend):
        if (
            not isinstance(value, str)
            or re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value) is None
        ):
            raise ValueError("NATIVE_ARTIFACT_VERSION_INVALID")
    return backend, frontend


def _digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _files(directory: Path) -> dict[str, str]:
    files = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("NATIVE_ARTIFACT_SYMLINK")
        name = path.relative_to(directory).as_posix()
        if path.is_file() and name not in {"manifest.json", "deployment.json"}:
            files[name] = _digest(path)
    return files


def verify_receipt(receipt: dict[str, Any], inputs: dict[str, str]) -> None:
    selected = {
        "schema_version": 1,
        "source_inputs": inputs,
        "versions": receipt["versions"],
        "build": receipt["build"],
    }
    if "sources" in receipt:
        selected["sources"] = receipt["sources"]
    if (
        set(receipt) - {"sources"} != {"sha256", "versions", "build"}
        or hashlib.sha256(encode(selected)).hexdigest() != receipt["sha256"]
    ):
        raise ValueError("RELEASE_INPUT_RECEIPT_MISMATCH")


def _pair(files: dict[str, str], inputs: dict[str, str], backend: str, frontend: str) -> dict[str, Any]:
    web = {name: sha for name, sha in files.items() if name.startswith("web/")}
    if not web or "bin/onlyalpha-backend" not in files:
        raise ValueError("NATIVE_ARTIFACT_COMPONENT_MISSING")
    for name in CONTRACTS:
        if (
            files.get("contracts/" + name) != inputs.get("contracts/product-api/v2/" + name)
            or "contracts/" + name not in files
        ):
            raise ValueError("NATIVE_ARTIFACT_CONTRACT_MISMATCH")
    return {
        "policy": "EXACT_BUNDLED_PAIR",
        "api_major": 2,
        "backend_version": backend,
        "frontend_version": frontend,
        "backend_sha256": files["bin/onlyalpha-backend"],
        "frontend_sha256": hashlib.sha256(encode(web)).hexdigest(),
        "openapi_sha256": files["contracts/openapi.json"],
        "stream_sha256": files["contracts/market-data-stream.schema.json"],
    }


def _agent(directory: Path, inputs: dict[str, str]) -> dict[str, str] | None:
    root = directory / "agent"
    if not root.exists():
        return None
    record = json.loads((root / "installation.json").read_text())
    if (
        set(record) != {"workflow", "project_sha256", "openapi_sha256"}
        or re.fullmatch(r"[0-9a-f]{64}", record["workflow"]) is None
    ):
        raise ValueError("NATIVE_AGENT_ARTIFACT_INVALID")
    if (
        record["project_sha256"] != _digest(root / "project.toml")
        or record["project_sha256"] != inputs.get("packages/agent/pyproject.toml")
        or record["openapi_sha256"] != _digest(root / "openapi.json")
        or record["openapi_sha256"] != inputs.get("contracts/agent-api/v1/openapi.json")
    ):
        raise ValueError("NATIVE_AGENT_ARTIFACT_MISMATCH")
    version = tomllib.loads((root / "project.toml").read_text())["project"]["version"]
    return {**record, "version": version}


def verify_artifacts(
    directory: Path,
    inputs: dict[str, str],
    version: str,
    *,
    frontend_version: str,
    runtime_root: Path | None = None,
    manifest_sha256: str | None = None,
) -> dict[str, Any]:
    if directory.is_symlink() or (directory / "manifest.json").is_symlink():
        raise ValueError("NATIVE_ARTIFACT_SYMLINK")
    raw = (directory / "manifest.json").read_bytes()
    if manifest_sha256 is not None and hashlib.sha256(raw).hexdigest() != manifest_sha256:
        raise ValueError("NATIVE_ARTIFACT_SELECTION_MISMATCH")
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or set(manifest) - {"release_inputs", "agent"} != {
        "schema_version",
        "version",
        "runtime_root",
        "source_inputs",
        "build_environment",
        "algorithm_artifact",
        "files",
        "default_pair",
    }:
        raise ValueError("NATIVE_ARTIFACT_INPUT_MISMATCH")
    if (
        type(manifest["schema_version"]) is not int
        or manifest["schema_version"] != 2
        or manifest["version"] != version
        or manifest["runtime_root"] != str(runtime_root or directory)
        or manifest["source_inputs"] != inputs
        or manifest["build_environment"] != BUILD_ENVIRONMENT
    ):
        raise ValueError("NATIVE_ARTIFACT_INPUT_MISMATCH")
    if "release_inputs" in manifest:
        verify_receipt(manifest["release_inputs"], inputs)
        versions = manifest["release_inputs"]["versions"]
        if versions.get("backend") != version or versions.get("frontend") != frontend_version:
            raise ValueError("NATIVE_ARTIFACT_PAIR_MISMATCH")
    if manifest.get("agent") != _agent(directory, inputs):
        raise ValueError("NATIVE_AGENT_ARTIFACT_MISMATCH")
    if (
        "release_inputs" in manifest
        and manifest.get("agent") is not None
        and manifest["release_inputs"]["versions"].get("agent") != manifest["agent"]["version"]
    ):
        raise ValueError("NATIVE_AGENT_RELEASE_MISMATCH")
    identity = manifest["algorithm_artifact"]
    if not isinstance(identity, str) or re.fullmatch(r"[0-9a-f]{64}", identity) is None:
        raise ValueError("NATIVE_ARTIFACT_IDENTITY_INVALID")
    if not isinstance(manifest["files"], dict) or not manifest["files"]:
        raise ValueError("NATIVE_ARTIFACT_FILES_INVALID")
    for name in manifest["files"]:
        if (
            not isinstance(name, str)
            or Path(name).is_absolute()
            or ".." in Path(name).parts
            or Path(name).as_posix() != name
        ):
            raise ValueError("NATIVE_ARTIFACT_PATH_INVALID")
    files = _files(directory)
    if files != manifest["files"]:
        raise ValueError("NATIVE_ARTIFACT_CONTENT_MISMATCH")
    if (directory / "algorithm-artifact.sha256").read_text() != identity + "\n":
        raise ValueError("NATIVE_ARTIFACT_IDENTITY_INVALID")
    if encode(manifest["default_pair"]) != encode(_pair(files, inputs, version, frontend_version)):
        raise ValueError("NATIVE_ARTIFACT_PAIR_MISMATCH")
    return manifest


def seal(
    root: Path, directory: Path, inputs: dict[str, str], selection: dict[str, Any] | None = None
) -> dict[str, Any]:
    from scripts.dev_verification import source_inputs
    from scripts.market_data_stream_contract import document as stream_document

    if (directory / "manifest.json").exists() or source_inputs(root) != inputs:
        raise ValueError("NATIVE_ARTIFACT_FROZEN_INPUT_REQUIRED")
    backend, frontend = product_versions(root)
    (directory / "contracts").mkdir()
    for name, flag in CONTRACTS.items():
        original = root / "contracts/product-api/v2" / name
        result = subprocess.run(
            [str(directory / "bin/onlyalpha-backend"), "--export-" + flag],
            env={},
            capture_output=True,
            check=True,
            timeout=30,
        )
        exported = json.loads(result.stdout)
        projected = stream_document(exported) if flag == "websocket" else exported
        if encode(projected) != encode(json.loads(original.read_bytes())):
            raise ValueError("NATIVE_ARTIFACT_CONTRACT_MISMATCH")
        shutil.copyfile(original, directory / "contracts" / name)
    files = _files(directory)
    manifest = {
        "schema_version": 2,
        "version": backend,
        "runtime_root": str(directory),
        "source_inputs": inputs,
        "build_environment": BUILD_ENVIRONMENT,
        "algorithm_artifact": (directory / "algorithm-artifact.sha256").read_text().removesuffix("\n"),
        "files": files,
        "default_pair": _pair(files, inputs, backend, frontend),
    }
    agent = _agent(directory, inputs)
    if agent is not None:
        manifest["agent"] = agent
    if selection is not None:
        manifest["release_inputs"] = selection
    if source_inputs(root) != inputs:
        raise ValueError("NATIVE_ARTIFACT_SOURCE_CHANGED")
    (directory / "manifest.json").write_bytes(encode(manifest))
    return verify_artifacts(directory, inputs, backend, frontend_version=frontend)
