"""Real non-publishing Rust/Python SMA boundary proof in the sole Linux dev lane."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.rust_kernel_check import compiler_environment, prepare_cargo_home  # noqa: E402
from scripts.strategy_reference_check import compare_reference  # noqa: E402


def main() -> int:
    if sys.platform != "linux":
        raise ValueError("CALCULATION_WORKER_LINUX_DEV_REQUIRED")
    target = {"aarch64": "aarch64-unknown-linux-gnu", "x86_64": "x86_64-unknown-linux-gnu"}[platform.machine()]
    artifacts = ROOT / "test-results/calculation-worker"
    artifacts.mkdir(parents=True, exist_ok=True)
    env = compiler_environment(os.environ, artifacts / "target")
    prepare_cargo_home(Path("/usr/local/cargo/registry"), Path(env["CARGO_HOME"]))
    # This inspects one frozen hermetic test materialization. It does not select
    # a historical artifact or create/admit an official Runtime Generation.
    artifact = subprocess.check_output(
        [sys.executable, "-B", "-I", "-m", "onlyalpha_calculation_worker.worker", "--describe"],
        cwd="/",
        env={},
        text=True,
    ).strip()
    if len(artifact) != 64 or any(c not in "0123456789abcdef" for c in artifact):
        raise ValueError("CALCULATION_WORKER_ARTIFACT_INVALID")
    for profile in ("debug", "release"):
        subprocess.run(
            [
                "cargo",
                "build",
                "-p",
                "onlyalpha-calculation-bridge",
                "--bin",
                "calculation-bridge-check",
                "--frozen",
                "--offline",
                "--target",
                target,
                "-j1",
                *(["--release"] if profile == "release" else []),
            ],
            cwd=ROOT,
            env=env,
            check=True,
        )
        executable = Path(env["CARGO_TARGET_DIR"]) / target / profile / "calculation-bridge-check"
        print(
            "BRIDGE",
            profile,
            "executable_sha256",
            hashlib.sha256(executable.read_bytes()).hexdigest(),
            "worker_artifact",
            artifact,
            flush=True,
        )
        completed = subprocess.run(
            [str(executable), sys.executable, artifact, str(ROOT / "test-data/domain/fact-records-v1.jsonl")],
            cwd=ROOT,
            env=env,
            check=False,
            text=True,
            capture_output=True,
        )
        print(completed.stdout, end="", flush=True)
        print(completed.stderr, end="", file=sys.stderr, flush=True)
        completed.check_returncode()
        base = next(
            json.loads(line)["record"]
            for line in (ROOT / "test-data/domain/fact-records-v1.jsonl").read_text().splitlines()
            if json.loads(line).get("id") == "bar"
        )
        compare_reference(completed.stdout, base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
