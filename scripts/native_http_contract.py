"""Build and project the current native route/type declarations; never start a Host."""

from __future__ import annotations

import functools
import hashlib
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.rust_kernel_check import compiler_environment, prepare_cargo_home

ROOT = Path(__file__).resolve().parents[1]


@functools.lru_cache(maxsize=2)
def native_executable(*, release: bool = True) -> Path:
    # An installed executable or a previous image's metadata is not source proof.
    target = ROOT / "test-results/rust-kernel/target"
    env = compiler_environment(os.environ, target)
    env["RUSTUP_TOOLCHAIN"] = tomllib.loads((ROOT / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
    prepare_cargo_home(Path("/usr/local/cargo/registry"), Path(env["CARGO_HOME"]))
    operation = os.environ.get("ONLYALPHA_DEV_VERIFICATION_OPERATION_ID", "inner-loop")
    output = ROOT / "test-results/native-http-contract" / operation
    output.mkdir(parents=True, exist_ok=True)
    profile = "release" if release else "debug"
    command = [
        "cargo",
        "build",
        "--frozen",
        "--offline",
        "-j",
        "1",
        "-p",
        "onlyalpha-http-server",
        "--bin",
        "onlyalpha-http-server",
        "--message-format=json",
    ]
    if release:
        command.append("--release")
    with (output / f"build-{profile}.log").open("w") as log:
        built = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=log,
            check=False,
        )
    (output / f"cargo-artifacts-{profile}.jsonl").write_text(built.stdout)
    built.check_returncode()
    executables = {
        Path(item["executable"])
        for line in built.stdout.splitlines()
        if (item := json.loads(line)).get("reason") == "compiler-artifact"
        and item.get("executable") is not None
        and item["target"]["name"] == "onlyalpha-http-server"
    }
    if len(executables) != 1:
        raise ValueError("NATIVE_CONTRACT_EXECUTABLE_UNPROVABLE")
    executable = executables.pop()
    size = executable.stat().st_size
    if release and size > 128 * 1024 * 1024:
        raise ValueError("NATIVE_ARTIFACT_RESOURCE_LIMIT")
    (output / f"executable-{profile}.json").write_text(
        json.dumps(
            {
                "executable": str(executable),
                "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                "bytes": size,
                "operation_id": operation,
            },
            indent=2,
        )
        + "\n"
    )
    return executable


@functools.lru_cache(maxsize=1)
def _documents() -> dict[str, Any]:
    executable = native_executable(release=False)
    output = (
        ROOT
        / "test-results/native-http-contract"
        / os.environ.get("ONLYALPHA_DEV_VERIFICATION_OPERATION_ID", "inner-loop")
    )
    documents: dict[str, Any] = {}
    for kind in ("openapi", "websocket"):
        # No operational configuration, user-data, key, assets, SDK or provider
        # environment exists here. Actual startup would fail, rather than connect.
        first = subprocess.run(
            [str(executable), f"--export-{kind}"], cwd=output, env={}, capture_output=True, check=True
        ).stdout
        second = subprocess.run(
            [str(executable), f"--export-{kind}"], cwd=output, env={}, capture_output=True, check=True
        ).stdout
        if first != second:
            raise ValueError("NATIVE_CONTRACT_EXPORT_NONDETERMINISTIC")
        documents[kind] = json.loads(first)
        (output / f"{kind}.json").write_bytes(first)
    return documents


def exported(kind: str) -> dict[str, Any]:
    value = _documents()[kind]
    if not isinstance(value, dict):
        raise ValueError("NATIVE_CONTRACT_EXPORT_OBJECT_REQUIRED")
    return value


def schema_document(document: dict[str, Any], name: str) -> dict[str, Any]:
    """Select the exact reachable closure; translate only local JSON pointers."""
    definitions = document["components"]["schemas"]
    selected: dict[str, Any] = {}

    def translate(value: Any) -> Any:
        if isinstance(value, list):
            return [translate(item) for item in value]
        if not isinstance(value, dict):
            return value
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key == "$ref":
                if not item.startswith("#/components/schemas/"):
                    raise ValueError("NATIVE_SCHEMA_REFERENCE_INVALID")
                target = item.removeprefix("#/components/schemas/")
                if target not in selected:
                    selected[target] = None
                    selected[target] = translate(definitions[target])
                result[key] = f"#/$defs/{target}"
            else:
                result[key] = translate(item)
        return result

    root = translate(definitions[name])
    return {**root, "$defs": selected}
