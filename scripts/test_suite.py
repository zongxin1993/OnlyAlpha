from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_TESTS = (
    "tests",
    "packages/fake/onlyalpha-plugin-broker-virtual/tests",
    "packages/provider/onlyalpha-plugin-tushare/tests",
    "packages/provider/onlyalpha-plugin-miniqmt/tests",
)


class OnlyTestLane(StrEnum):
    FAST = "fast"
    INTEGRATION = "integration"
    ASHARE = "ashare"
    RECOVERY = "recovery"
    MINIQMT_CONTRACT = "miniqmt-contract"
    MINIQMT_LOCAL = "miniqmt-local"
    FULL = "full"
    RELEASE = "release"


@dataclass(frozen=True, slots=True)
class Lane:
    paths: tuple[str, ...]
    expression: str
    workers: str
    dist: str
    durations: int = 20


LANES = {
    OnlyTestLane.FAST: Lane(
        WORKSPACE_TESTS,
        "(unit or contract or architecture) and not (external or slow or performance or recovery)",
        "8",
        "worksteal",
    ),
    OnlyTestLane.INTEGRATION: Lane(
        ("tests",),
        "(integration or scenario) and not (recovery or external or slow or performance or conformance)",
        "6",
        "worksteal",
    ),
    OnlyTestLane.ASHARE: Lane(
        ("tests", "packages/provider/onlyalpha-plugin-miniqmt/tests"), "conformance and not external", "4", "worksteal"
    ),
    OnlyTestLane.RECOVERY: Lane(("tests",), "recovery and not external", "8", "worksteal", 100),
    OnlyTestLane.MINIQMT_CONTRACT: Lane(
        ("packages/provider/onlyalpha-plugin-miniqmt/tests",),
        "contract and miniqmt and not external",
        "auto",
        "worksteal",
    ),
    OnlyTestLane.MINIQMT_LOCAL: Lane(
        ("packages/provider/onlyalpha-plugin-miniqmt/tests",),
        "miniqmt and external and requires_local_qmt and windows and not requires_broker_account",
        "0",
        "no",
    ),
    OnlyTestLane.FULL: Lane(
        WORKSPACE_TESTS,
        "not (external or requires_network or requires_tushare or requires_local_qmt or requires_broker_account or performance)",
        "8",
        "worksteal",
        100,
    ),
}


def run(command: list[str], env: dict[str, str] | None = None) -> int:
    print("> " + subprocess.list2cmdline(command), flush=True)
    return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode


def release(args: argparse.Namespace) -> int:
    commands = [
        ["uv", "run", "ruff", "check", "src", "tests", "examples", "packages", "scripts"],
        ["uv", "run", "ruff", "format", "--check", "src", "tests", "examples", "packages", "scripts"],
        ["uv", "run", "mypy", "src/onlyalpha"],
        [
            "uv",
            "run",
            "mypy",
            "--config-file",
            "packages/provider/onlyalpha-plugin-tushare/pyproject.toml",
            "packages/provider/onlyalpha-plugin-tushare/src/onlyalpha_plugin_tushare",
        ],
        [
            "uv",
            "run",
            "mypy",
            "--config-file",
            "packages/provider/onlyalpha-plugin-miniqmt/pyproject.toml",
            "packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt",
        ],
        ["uv", "run", "python", "scripts/version_sync.py", "check"],
    ]
    for command in commands:
        code = run(command)
        if code:
            return code
    for lane in (OnlyTestLane.FULL, OnlyTestLane.RECOVERY, OnlyTestLane.ASHARE):
        code = execute(lane, args)
        if code:
            return code
    return run(["uv", "build", "--all-packages"])


def execute(name: OnlyTestLane, args: argparse.Namespace) -> int:
    lane = LANES[name]
    workers = "0" if args.no_parallel else (args.workers or lane.workers)
    dist = args.dist or lane.dist
    if name is OnlyTestLane.MINIQMT_LOCAL:
        if sys.platform != "win32":
            print("miniqmt-local requires Windows", file=sys.stderr)
            return 2
        if not os.environ.get("userdata_mini_path") and not os.environ.get("ONLYALPHA_MINIQMT_PATH"):
            print("miniqmt-local requires userdata_mini_path or ONLYALPHA_MINIQMT_PATH", file=sys.stderr)
            return 2
        try:
            __import__("xtquant")
        except ImportError:
            print("miniqmt-local requires an importable xtquant SDK", file=sys.stderr)
            return 2
    groups = tuple((path,) for path in lane.paths)
    metric_paths: list[Path] = []
    for index, paths in enumerate(groups):
        if not paths:
            continue
        command = [
            "uv",
            "run",
            "python",
            "-m",
            "pytest",
            "-c",
            str(ROOT / "pyproject.toml"),
            *paths,
            "-q",
            "-m",
            lane.expression,
            f"--durations={args.durations or lane.durations}",
            "-p",
            "scripts.pytest_layering",
            "-p",
            "scripts.pytest_metrics",
        ]
        if workers != "0":
            command.extend(["-n", workers, "--dist", dist])
        metric_path = ROOT / ".test-metrics" / f"{name.value}.part{index}.json"
        metric_paths.append(metric_path)
        env = os.environ.copy()
        env.update(
            {
                "ONLYALPHA_TEST_LANE": name.value,
                "ONLYALPHA_TEST_METRICS": str(metric_path),
                "ONLYALPHA_TEST_WORKERS": workers,
                "ONLYALPHA_TEST_DIST": dist if workers != "0" else "no",
            }
        )
        code = run(command, env)
        if code not in (0, 5):
            return code
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in metric_paths]
    if payloads:
        merged = payloads[0]
        for key in (
            "collected",
            "passed",
            "failed",
            "skipped",
            "total_seconds",
            "setup_seconds",
            "call_seconds",
            "teardown_seconds",
            "cache_hit_count",
            "engine_run_count",
            "sqlite_database_count",
            "parquet_write_count",
        ):
            merged[key] = sum(payload[key] for payload in payloads)
        merged["slowest_tests"] = sorted(
            (test for payload in payloads for test in payload["slowest_tests"]),
            key=lambda item: item["seconds"],
            reverse=True,
        )[:20]
        for key in ("marker_counts", "path_counts"):
            merged[key] = {
                item: sum(payload[key].get(item, 0) for payload in payloads)
                for item in sorted({item for payload in payloads for item in payload[key]})
            }
        merged["tests"] = {
            nodeid: seconds for payload in payloads for nodeid, seconds in payload.get("tests", {}).items()
        }
        (ROOT / ".test-metrics" / f"{name.value}.json").write_text(
            json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"Lane {name.value}: {merged['collected']} collected in {merged['total_seconds']:.2f}s")
        if merged["collected"] == 0:
            print(f"Lane {name.value} selected no tests", file=sys.stderr)
            return 5
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("lane", choices=[lane.value for lane in OnlyTestLane])
    parser.add_argument("--workers")
    parser.add_argument("--dist", choices=("load", "loadscope", "loadfile", "worksteal"))
    parser.add_argument("--durations", type=int)
    parser.add_argument("--no-parallel", action="store_true")
    args = parser.parse_args()
    lane = OnlyTestLane(args.lane)
    return release(args) if lane is OnlyTestLane.RELEASE else execute(lane, args)


if __name__ == "__main__":
    raise SystemExit(main())
