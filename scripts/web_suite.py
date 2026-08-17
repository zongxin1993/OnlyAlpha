from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps/onlyalpha-web"
OPENAPI = ROOT / "contracts/research-api/v2/openapi.json"
GENERATED = WEB / "src/api/research/generated.ts"


def _run(*command: str, cwd: Path = WEB) -> None:
    completed = subprocess.run(command, cwd=cwd, env=os.environ.copy(), check=False)
    if completed.returncode:
        raise SystemExit(completed.returncode)


def _check_generated_contract() -> None:
    with tempfile.TemporaryDirectory(prefix="onlyalpha-openapi-") as raw:
        candidate = Path(raw) / "generated.ts"
        _run(str(WEB / "node_modules/.bin/openapi-typescript"), str(OPENAPI), "-o", str(candidate))
        if candidate.read_bytes() != GENERATED.read_bytes():
            raise SystemExit("generated Research API TypeScript contract is stale; run npm run api:generate")


def static() -> None:
    _run("uv", "run", "python", "scripts/export_research_openapi.py", "check", cwd=ROOT)
    _check_generated_contract()
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
