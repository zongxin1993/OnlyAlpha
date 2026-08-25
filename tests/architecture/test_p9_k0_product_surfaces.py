"""Freeze the audited P9.K.0 product and direct-construction surfaces."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).parents[2]
CONSTRUCTOR_NAMES = {
    "OnlyEngine",
    "OnlyRuntime",
    "OnlyBacktestRuntime",
    "OnlySimRuntime",
    "OnlyLiveRuntime",
    "OnlyResearchRuntime",
}

EXPECTED_CONSOLE_ENTRY_POINTS = {
    ("packages/api/onlyalpha-api/pyproject.toml", "onlyalpha-api", "onlyalpha_api.main:main"),
    (
        "packages/api/onlyalpha-api/pyproject.toml",
        "onlyalpha-artifact-api",
        "onlyalpha_api.artifact_main:main",
    ),
    (
        "packages/provider/onlyalpha-plugin-miniqmt/pyproject.toml",
        "onlyalpha-miniqmt",
        "onlyalpha_plugin_miniqmt.doctor:main",
    ),
    (
        "packages/provider/onlyalpha-plugin-tushare/pyproject.toml",
        "onlyalpha-tushare",
        "onlyalpha_plugin_tushare.doctor:main",
    ),
    ("pyproject.toml", "onlyalpha", "onlyalpha.cli:main"),
    ("pyproject.toml", "onlyalpha-research-worker", "onlyalpha.research.worker_main:main"),
}

# This is the exact K0 allowlist. Entries include internal composition, classified
# operator/test tooling, examples, and known migration debt. Any new construction
# site requires an explicit architecture-contract update.
EXPECTED_DIRECT_CONSTRUCTION_SITES = {
    ("examples/committed_execution_report.py", "OnlyEngine"),
    ("scripts/regenerate_recovery_baselines.py", "OnlyEngine"),
    ("scripts/regenerate_result_fixtures.py", "OnlyEngine"),
    ("src/onlyalpha/cli.py", "OnlyEngine"),
    ("src/onlyalpha/research/execution/worker.py", "OnlyEngine"),
    ("src/onlyalpha/runtime/backtest/factory.py", "OnlyBacktestRuntime"),
    ("src/onlyalpha/runtime/research/factory.py", "OnlyResearchRuntime"),
    ("src/onlyalpha/runtime/sim/factory.py", "OnlySimRuntime"),
    ("src/onlyalpha/scenario/runner.py", "OnlyEngine"),
}

EXPECTED_TOP_LEVEL_EXPORTS = {
    "OnlyBacktestClock",
    "OnlyBacktestRuntime",
    "OnlyBarSubscription",
    "OnlyClock",
    "OnlyClockView",
    "OnlyCluster",
    "OnlyClusterConfig",
    "OnlyClusterContext",
    "OnlyClusterLoader",
    "OnlyClusterRegistry",
    "OnlyClusterRunConfig",
    "OnlyDemoCluster",
    "OnlyDemoRecord",
    "OnlyEngine",
    "OnlyEvent",
    "OnlyEventBus",
    "OnlyLiveClock",
    "OnlyLiveRuntime",
    "OnlyMarketDataCache",
    "OnlyMarketDataPipeline",
    "OnlyMarketDataSnapshot",
    "OnlyMemoryCache",
    "OnlyResearchRuntime",
    "OnlyRuntime",
    "OnlyRuntimeState",
    "OnlyRuntimeStatus",
    "OnlySqliteStorage",
    "OnlyTimerEvent",
    "OnlyTimerId",
    "OnlyVirtualClock",
}


def _console_entry_points() -> set[tuple[str, str, str]]:
    result: set[tuple[str, str, str]] = set()
    for path in sorted(ROOT.rglob("pyproject.toml")):
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        scripts = document.get("project", {}).get("scripts", {})
        assert isinstance(scripts, dict)
        relative = path.relative_to(ROOT).as_posix()
        result.update((relative, name, target) for name, target in scripts.items())
    return result


def _called_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _direct_construction_sites() -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    roots = (ROOT / "src", ROOT / "packages", ROOT / "scripts", ROOT / "examples")
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            if "tests" in path.relative_to(ROOT).parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and (name := _called_name(node)) in CONSTRUCTOR_NAMES:
                    result.add((path.relative_to(ROOT).as_posix(), name))
    return result


def _top_level_exports() -> set[str]:
    path = ROOT / "src/onlyalpha/__init__.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
    )
    value = ast.literal_eval(assignment.value)
    assert isinstance(value, list) and all(isinstance(item, str) for item in value)
    return set(value)


def test_console_entry_point_set_is_frozen() -> None:
    assert _console_entry_points() == EXPECTED_CONSOLE_ENTRY_POINTS


def test_direct_engine_and_runtime_construction_sites_are_frozen() -> None:
    assert _direct_construction_sites() == EXPECTED_DIRECT_CONSTRUCTION_SITES


def test_top_level_python_surface_is_frozen() -> None:
    assert _top_level_exports() == EXPECTED_TOP_LEVEL_EXPORTS
