"""Build the independently installed Agent closure from the one frozen workspace lock."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def install(destination: Path) -> dict[str, str]:
    if destination.exists():
        raise ValueError("AGENT_INSTALLATION_ALREADY_EXISTS")
    destination.mkdir()
    environment = destination / "env"
    venv.EnvBuilder(with_pip=False, symlinks=False).create(environment)
    context = {
        **os.environ,
        "UV_PROJECT_ENVIRONMENT": str(environment),
        "UV_LINK_MODE": "copy",
        "UV_COMPILE_BYTECODE": "false",
    }
    subprocess.run(
        [
            "uv",
            "sync",
            "--offline",
            "--frozen",
            "--package",
            "onlyalpha-agent",
            "--no-dev",
            "--no-install-workspace",
            "--no-editable",
        ],
        cwd=ROOT,
        env=context,
        check=True,
    )
    wheels = destination / "wheels"
    subprocess.run(
        ["uv", "build", "--offline", "--package", "onlyalpha-agent", "--wheel", "--out-dir", str(wheels)],
        cwd=ROOT,
        check=True,
    )
    (wheel,) = wheels.glob("onlyalpha_agent-*.whl")
    python = environment / "bin/python"
    subprocess.run(
        ["uv", "pip", "install", "--offline", "--python", str(python), "--no-deps", str(wheel)],
        cwd=ROOT,
        env=context,
        check=True,
    )
    alias = environment / "lib64"
    if alias.is_symlink() and alias.readlink() == Path("lib"):
        alias.unlink()
    for path in environment.rglob("*"):
        if path.is_symlink():
            target = path.resolve(strict=True)
            if not target.is_file():
                raise ValueError("AGENT_INSTALLATION_SYMLINK")
            raw = target.read_bytes()
            path.unlink()
            path.write_bytes(raw)
            path.chmod(0o555 if path.parent == environment / "bin" else 0o444)
    identity = subprocess.check_output(
        [
            str(python),
            "-B",
            "-I",
            "-c",
            "import importlib.util; assert importlib.util.find_spec('onlyalpha') is None; from onlyalpha_agent.workflow import current_identity; print(current_identity())",
        ],
        cwd=destination,
        env={},
        text=True,
    ).strip()
    shutil.copyfile(ROOT / "packages/agent/pyproject.toml", destination / "project.toml")
    shutil.copyfile(ROOT / "contracts/agent-api/v1/openapi.json", destination / "openapi.json")
    record = {
        "workflow": identity,
        "project_sha256": hashlib.sha256((destination / "project.toml").read_bytes()).hexdigest(),
        "openapi_sha256": hashlib.sha256((destination / "openapi.json").read_bytes()).hexdigest(),
    }
    (destination / "installation.json").write_text(json.dumps(record, sort_keys=True) + "\n")
    for path in destination.rglob("*"):
        if path.is_file():
            path.chmod(0o555 if path.parent == environment / "bin" else 0o444)
    return record
