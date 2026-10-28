"""The released wheel runs without the backend or repository on sys.path."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_locked_agent_wheel_in_an_independent_installation(tmp_path):
    root = Path(__file__).resolve().parents[3]
    requirements = tmp_path / "requirements.txt"
    wheel_dir = tmp_path / "wheels"
    environment = tmp_path / "env"

    def run(*args, cwd=root, extra_env=None):
        result = subprocess.run(
            args,
            cwd=cwd,
            env={**os.environ, "UV_NO_SYNC": "1", **(extra_env or {})},
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result

    run(
        "uv",
        "export",
        "--offline",
        "--locked",
        "--package",
        "onlyalpha-agent",
        "--no-dev",
        "--no-emit-workspace",
        "--output-file",
        str(requirements),
    )
    run("uv", "build", "--offline", "--package", "onlyalpha-agent", "--wheel", "--out-dir", str(wheel_dir))
    run("uv", "venv", "--offline", "--python", sys.executable, str(environment))
    python = str(environment / "bin/python")
    # Frozen sync consumes exact wheel URLs/hashes from uv.lock. A pip-style resolver
    # additionally needs registry-index cache entries which frozen preparation does not create.
    run(
        "uv",
        "sync",
        "--offline",
        "--frozen",
        "--package",
        "onlyalpha-agent",
        "--no-dev",
        "--no-install-workspace",
        "--no-editable",
        extra_env={"UV_PROJECT_ENVIRONMENT": str(environment)},
    )
    wheel = next(wheel_dir.glob("*.whl"))
    run("uv", "pip", "install", "--offline", "--python", python, "--no-deps", str(wheel))
    result = run(
        python,
        "-I",
        "-c",
        """
import importlib.util,json
from onlyalpha_agent.app import create_app
from onlyalpha_agent.config import Settings
from onlyalpha_agent.workflow import current_identity
assert importlib.util.find_spec('onlyalpha') is None
app=create_app(Settings('unused',b'e'*32,b's'*32))
print(json.dumps({'workflow':current_identity(),'paths':sorted(app.openapi()['paths'])}))
""",
        cwd=tmp_path,
    )
    proof = json.loads(result.stdout)
    assert len(proof["workflow"]) == 64
    assert "/api/v1/agent/sessions" in proof["paths"]
    assert all("research" not in p and "generation" not in p for p in proof["paths"])
    assert "onlyalpha==" not in requirements.read_text()
