"""Measure the maintained public Python SDK through current owning test lanes.

Rust compiler/vector/replay evidence remains independent of Python coverage.
The original branch/global policy lives in pyproject.toml; PR diff policy lives
in third-party-quality.yml. This runner writes test evidence, never source inputs.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANES = ("python-contract", "database", "research-product-certification")


def main() -> int:
    output = ROOT / "test-results" / "coverage"
    output.mkdir(parents=True, exist_ok=True)
    (output / "coverage.json").unlink(missing_ok=True)
    (output / "coverage.xml").unlink(missing_ok=True)
    # No stale fragments from another checkout or earlier failed attempt.
    with tempfile.TemporaryDirectory(prefix="canonical-", dir=output) as directory:
        env = os.environ.copy()
        env["COVERAGE_FILE"] = str(Path(directory) / ".coverage")
        env["COVERAGE_RCFILE"] = str(ROOT / "pyproject.toml")
        print("Coverage source: maintained public onlyalpha SDK; branch/global82 and PR diff90 unchanged", flush=True)
        print(
            "Runner/gateway/Rust functionality is tested separately; sealed -I/env={} installed workers have no injected coverage and confer no measured child-process percentage",
            flush=True,
        )
        for lane in LANES:
            command = [
                sys.executable,
                "-m",
                "coverage",
                "run",
                "--parallel-mode",
                "scripts/test_suite.py",
                "--no-parallel",
                lane,
            ]
            print(f"Coverage test owner: {lane}", flush=True)
            code = subprocess.run(command, cwd=ROOT, env=env, check=False).returncode
            if code:
                return code
        code = subprocess.run(
            [sys.executable, "-m", "coverage", "combine", directory], cwd=ROOT, env=env, check=False
        ).returncode
        if code:
            return code
        # Coverage writes diagnostic artifacts before returning threshold failure.
        # Emit both forms and the missing-line report while preserving that failure.
        status = 0
        for args in (
            ("json", "-o", str(output / "coverage.json")),
            ("xml", "-o", str(output / "coverage.xml")),
            ("report",),
        ):
            code = subprocess.run([sys.executable, "-m", "coverage", *args], cwd=ROOT, env=env, check=False).returncode
            if code and not status:
                status = code
        return status


if __name__ == "__main__":
    raise SystemExit(main())
