"""Measure the complete canonical offline and real-database correctness evidence.

This runner does not select tests. Each subprocess uses test_suite.py's owning lane.
The global source/branch/threshold policy remains in pyproject.toml.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANES = ("research-postgres", "market-data-clickhouse", "database-acceptance", "recovery", "core-full")


@contextmanager
def _database_source_provenance(env: dict[str, str]) -> Iterator[int]:
    paths = tuple(ROOT / "src" / "onlyalpha" / name for name in ("_build_provenance.json", "_build_provenance.sha256"))
    if any(path.is_symlink() for path in paths):
        raise ValueError("coverage source provenance must not be a symlink")
    saved = {path: path.read_bytes() if path.exists() else None for path in paths}
    try:
        yield subprocess.run(
            [sys.executable, "scripts/embed_build_provenance.py"], cwd=ROOT, env=env, check=False
        ).returncode
    finally:
        for path, original in saved.items():
            if original is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(original)


def main() -> int:
    output = ROOT / "test-results" / "coverage"
    output.mkdir(parents=True, exist_ok=True)
    # Never combine stale evidence from another checkout or failed attempt.
    with tempfile.TemporaryDirectory(prefix="canonical-", dir=output) as directory:
        env = os.environ.copy()
        env["COVERAGE_FILE"] = str(Path(directory) / ".coverage")
        env["COVERAGE_RCFILE"] = str(ROOT / "pyproject.toml")

        # Match the canonical database-compose prerequisite: packaged research
        # algorithms require the build's exact Git source-provenance carrier.
        def run_lane(lane: str) -> int:
            command = [sys.executable, "-m", "coverage", "run", "--parallel-mode", "scripts/test_suite.py", lane]
            print(f"Coverage: {lane}", flush=True)
            return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode

        with _database_source_provenance(env) as code:
            if code:
                return code
            for lane in LANES[:3]:
                code = run_lane(lane)
                if code:
                    return code
        # Source-checkout tests require the original no-carrier boundary.
        for lane in LANES[3:]:
            code = run_lane(lane)
            if code:
                return code
        for args in (
            ("combine", directory),
            ("json", "-o", str(output / "coverage.json")),
            ("xml", "-o", str(output / "coverage.xml")),
            ("report",),
        ):
            code = subprocess.run([sys.executable, "-m", "coverage", *args], cwd=ROOT, env=env, check=False).returncode
            if code:
                return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
