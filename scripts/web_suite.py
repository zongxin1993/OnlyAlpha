from __future__ import annotations

import argparse
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

from openapi_contract import check_generated_client

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "packages/onlyalpha-web-console"


def _run(*command: str, cwd: Path = WEB) -> None:
    completed = subprocess.run(command, cwd=cwd, env=os.environ.copy(), check=False)
    if completed.returncode:
        raise SystemExit(completed.returncode)


def static() -> None:
    _run("uv", "run", "python", "scripts/openapi_contract.py", "check", cwd=ROOT)
    try:
        check_generated_client()
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    for command in (("npm", "run", "lint"), ("npm", "run", "format:check"), ("npm", "run", "typecheck")):
        _run(*command)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("static", "unit", "build", "e2e", "all"))
    mode = parser.parse_args(argv).mode
    if mode in ("static", "all"):
        static()
    if mode in ("unit", "all"):
        _run("npm", "run", "test:coverage")
    if mode in ("build", "all"):
        _run("npm", "run", "build")
    if mode in ("e2e", "all"):
        _run("npm", "run", "e2e")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
