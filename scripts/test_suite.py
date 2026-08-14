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
    "packages/market/onlyalpha-market-generic-t0-cash/tests",
    "packages/market/onlyalpha-market-cn-ashare/tests",
    "packages/provider/onlyalpha-plugin-tushare/tests",
    "packages/provider/onlyalpha-plugin-miniqmt/tests",
    "packages/indicator/onlyalpha-plugin-indicators/tests",
)


class OnlyTestLane(StrEnum):
    CALCULATION = "calculation"
    RESEARCH_CALCULATION = "research-calculation"
    RESEARCH_JOB = "research-job"
    RESEARCH_DATASET = "research-dataset"
    FAST = "fast"
    INTEGRATION = "integration"
    ASHARE = "ashare"
    RECOVERY = "recovery"
    SIM_RECOVERY = "sim-recovery"
    MINIQMT_CONTRACT = "miniqmt-contract"
    MINIQMT_LOCAL = "miniqmt-local"
    CORE_FULL = "core-full"
    EXHAUSTIVE = "exhaustive"
    RELEASE = "release"


@dataclass(frozen=True, slots=True)
class Lane:
    paths: tuple[str, ...]
    expression: str
    workers: str
    dist: str
    durations: int = 20


LANES = {
    OnlyTestLane.CALCULATION: Lane(
        (
            "tests/calculation",
            "tests/indicator",
            "tests/plugin/test_calculation_plugin_discovery.py",
            "tests/architecture/test_calculation_plugin_boundaries.py",
            "packages/indicator/onlyalpha-plugin-indicators/tests",
        ),
        "not external",
        "4",
        "worksteal",
    ),
    OnlyTestLane.RESEARCH_CALCULATION: Lane(
        (
            "tests/research/calculation",
            "tests/calculation",
            "tests/architecture/test_research_calculation_boundaries.py",
            "tests/architecture/test_calculation_plugin_boundaries.py",
            "packages/indicator/onlyalpha-plugin-indicators/tests/test_research_characterization.py",
        ),
        "not external",
        "4",
        "worksteal",
    ),
    OnlyTestLane.RESEARCH_JOB: Lane(
        (
            "tests/research/job",
            "tests/architecture/test_research_calculation_boundaries.py",
        ),
        "not external",
        "2",
        "worksteal",
    ),
    OnlyTestLane.RESEARCH_DATASET: Lane(
        (
            "tests/research/dataset",
            "tests/cache",
            "tests/architecture/test_research_dataset_boundaries.py",
            "tests/architecture/test_historical_provider_boundaries.py",
            "packages/provider/onlyalpha-plugin-tushare/tests/test_provider.py",
            "packages/provider/onlyalpha-plugin-tushare/tests/test_historical.py",
            "packages/provider/onlyalpha-plugin-miniqmt/tests/test_historical.py",
        ),
        "not external",
        "4",
        "worksteal",
    ),
    OnlyTestLane.FAST: Lane(
        WORKSPACE_TESTS,
        "(unit or contract or architecture) and not (recovery or sim_recovery or conformance or external or performance or exhaustive or slow)",
        "8",
        "worksteal",
    ),
    OnlyTestLane.INTEGRATION: Lane(
        ("tests",),
        "(integration or scenario) and not (recovery or sim_recovery or conformance or external or performance or exhaustive or slow)",
        "6",
        "worksteal",
    ),
    OnlyTestLane.ASHARE: Lane(WORKSPACE_TESTS, "conformance and not external and not exhaustive", "4", "worksteal"),
    OnlyTestLane.RECOVERY: Lane(WORKSPACE_TESTS, "recovery and not external and not exhaustive", "8", "worksteal", 100),
    OnlyTestLane.SIM_RECOVERY: Lane(
        WORKSPACE_TESTS,
        "sim_recovery and not external and not exhaustive",
        "4",
        "worksteal",
        100,
    ),
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
    OnlyTestLane.CORE_FULL: Lane(
        WORKSPACE_TESTS,
        "not (recovery or sim_recovery or conformance or external or requires_network or requires_tushare or requires_local_qmt or requires_broker_account or performance or exhaustive or slow)",
        "8",
        "worksteal",
        100,
    ),
    OnlyTestLane.EXHAUSTIVE: Lane(WORKSPACE_TESTS, "exhaustive and not external", "8", "worksteal", 100),
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
            "packages/indicator/onlyalpha-plugin-indicators/src/onlyalpha_plugin_indicators",
            "packages/factor/onlyalpha-plugin-factors/src/onlyalpha_plugin_factors",
        ],
        [
            "uv",
            "run",
            "mypy",
            "--config-file",
            "packages/market/onlyalpha-market-generic-t0-cash/pyproject.toml",
            "packages/market/onlyalpha-market-generic-t0-cash/src/onlyalpha_market_generic_t0_cash",
        ],
        [
            "uv",
            "run",
            "mypy",
            "--config-file",
            "packages/market/onlyalpha-market-cn-ashare/pyproject.toml",
            "packages/market/onlyalpha-market-cn-ashare/src/onlyalpha_market_cn_ashare",
        ],
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
    for lane in (
        OnlyTestLane.RESEARCH_JOB,
        OnlyTestLane.RESEARCH_CALCULATION,
        OnlyTestLane.CALCULATION,
        OnlyTestLane.RESEARCH_DATASET,
        OnlyTestLane.CORE_FULL,
        OnlyTestLane.RECOVERY,
        OnlyTestLane.SIM_RECOVERY,
        OnlyTestLane.ASHARE,
        OnlyTestLane.MINIQMT_CONTRACT,
    ):
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
    command = [
        "uv",
        "run",
        "python",
        "-m",
        "pytest",
        "-c",
        str(ROOT / "pyproject.toml"),
        *lane.paths,
        "--import-mode=importlib",
        "-q",
        "-m",
        lane.expression,
        f"--durations={args.durations or lane.durations}",
        "-p",
        "scripts.pytest_layering",
        "-p",
        "scripts.pytest_metrics",
        "--benchmark-disable",
    ]
    if args.coverage:
        coverage_source = (
            "src/onlyalpha/research/job"
            if name is OnlyTestLane.RESEARCH_JOB
            else "src/onlyalpha/research/calculation"
            if name is OnlyTestLane.RESEARCH_CALCULATION
            else "packages/indicator/onlyalpha-plugin-indicators/src/onlyalpha_plugin_indicators"
            if name is OnlyTestLane.CALCULATION
            else "src/onlyalpha/research/dataset"
            if name is OnlyTestLane.RESEARCH_DATASET
            else "src/onlyalpha"
        )
        coverage_output = (
            "research-job-coverage"
            if name is OnlyTestLane.RESEARCH_JOB
            else "research-calculation-coverage"
            if name is OnlyTestLane.RESEARCH_CALCULATION
            else "calculation-coverage"
            if name is OnlyTestLane.CALCULATION
            else "research-dataset-coverage"
            if name is OnlyTestLane.RESEARCH_DATASET
            else "coverage"
        )
        command.extend(
            [
                f"--cov={coverage_source}",
                "--cov-branch",
                "--cov-report=",
                f"--cov-report=json:test-results/coverage/{coverage_output}.json",
                f"--cov-report=xml:test-results/coverage/{coverage_output}.xml",
                "--cov-fail-under=82",
            ]
        )
        workers = "0"
    if workers != "0":
        command.extend(["-n", workers, "--dist", dist])
    metric_path = ROOT / "test-results" / "metrics" / f"{name.value}.json"
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
    if args.coverage:
        coverage_path = (
            ROOT
            / "test-results"
            / "coverage"
            / (
                "calculation-coverage.json"
                if name is OnlyTestLane.CALCULATION
                else "research-job-coverage.json"
                if name is OnlyTestLane.RESEARCH_JOB
                else "research-calculation-coverage.json"
                if name is OnlyTestLane.RESEARCH_CALCULATION
                else "research-dataset-coverage.json"
                if name is OnlyTestLane.RESEARCH_DATASET
                else "coverage.json"
            )
        )
        if coverage_path.is_file():
            totals = json.loads(coverage_path.read_text(encoding="utf-8"))["totals"]
            line_rate = 100 * totals["covered_lines"] / totals["num_statements"]
            branch_rate = 100 * totals["covered_branches"] / totals["num_branches"]
            print(f"Coverage baseline: lines={line_rate:.2f}% branches={branch_rate:.2f}%")
            if name is OnlyTestLane.RESEARCH_DATASET and branch_rate < 70:
                print("Research Dataset branch coverage must be at least 70%", file=sys.stderr)
                code = 1
    if metric_path.is_file():
        metrics = json.loads(metric_path.read_text(encoding="utf-8"))
        print(f"Lane {name.value}: {metrics['collected']} collected in {metrics['total_seconds']:.2f}s")
        if metrics["collected"] == 0 and code == 0:
            code = 5
    else:
        print(f"Lane {name.value}: metrics were not produced", file=sys.stderr)
        if code == 0:
            code = 2
    return code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("lane", choices=[lane.value for lane in OnlyTestLane])
    parser.add_argument("--workers")
    parser.add_argument("--dist", choices=("load", "loadscope", "loadfile", "worksteal"))
    parser.add_argument("--durations", type=int)
    parser.add_argument("--no-parallel", action="store_true")
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="collect branch coverage once for this lane; disables xdist for deterministic data",
    )
    args = parser.parse_args()
    lane = OnlyTestLane(args.lane)
    return release(args) if lane is OnlyTestLane.RELEASE else execute(lane, args)


if __name__ == "__main__":
    raise SystemExit(main())
