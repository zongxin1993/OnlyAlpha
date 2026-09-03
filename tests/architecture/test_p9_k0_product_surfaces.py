"""Freeze the audited P9.K.0 product and direct-construction surfaces."""

from __future__ import annotations

import ast
import subprocess
import tomllib
from pathlib import Path

import pytest

from tests.architecture._p9_k0_guard_helpers import canonical_imports, canonical_imports_for_path, module_name

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).parents[2]
CONSTRUCTOR_OWNERS = {
    "onlyalpha.OnlyEngine": "OnlyEngine",
    "onlyalpha.engine.OnlyEngine": "OnlyEngine",
    "onlyalpha.engine.engine.OnlyEngine": "OnlyEngine",
    "onlyalpha.OnlyRuntime": "OnlyRuntime",
    "onlyalpha.runtime.OnlyRuntime": "OnlyRuntime",
    "onlyalpha.runtime.runtime.OnlyRuntime": "OnlyRuntime",
    "onlyalpha.OnlyBacktestRuntime": "OnlyBacktestRuntime",
    "onlyalpha.runtime.OnlyBacktestRuntime": "OnlyBacktestRuntime",
    "onlyalpha.runtime.backtest.OnlyBacktestRuntime": "OnlyBacktestRuntime",
    "onlyalpha.runtime.backtest.runtime.OnlyBacktestRuntime": "OnlyBacktestRuntime",
    "onlyalpha.OnlySimRuntime": "OnlySimRuntime",
    "onlyalpha.runtime.OnlySimRuntime": "OnlySimRuntime",
    "onlyalpha.runtime.sim.OnlySimRuntime": "OnlySimRuntime",
    "onlyalpha.runtime.sim.runtime.OnlySimRuntime": "OnlySimRuntime",
    "onlyalpha.OnlyLiveRuntime": "OnlyLiveRuntime",
    "onlyalpha.runtime.OnlyLiveRuntime": "OnlyLiveRuntime",
    "onlyalpha.runtime.live.OnlyLiveRuntime": "OnlyLiveRuntime",
    "onlyalpha.runtime.live.runtime.OnlyLiveRuntime": "OnlyLiveRuntime",
    "onlyalpha.OnlyResearchRuntime": "OnlyResearchRuntime",
    "onlyalpha.runtime.OnlyResearchRuntime": "OnlyResearchRuntime",
    "onlyalpha.runtime.research.OnlyResearchRuntime": "OnlyResearchRuntime",
    "onlyalpha.runtime.research.runtime.OnlyResearchRuntime": "OnlyResearchRuntime",
}
PROTECTED_CONSTRUCTOR_MODULES = frozenset(qualified.rpartition(".")[0] for qualified in CONSTRUCTOR_OWNERS)

EXPECTED_CONSOLE_ENTRY_POINTS = {
    ("packages/onlyalpha-http-server/pyproject.toml", "onlyalpha-http-server", "onlyalpha_http_server.main:main"),
    (
        "plugs/onlyalpha-plugin-miniqmt/pyproject.toml",
        "onlyalpha-miniqmt",
        "onlyalpha_plugin_miniqmt.doctor:main",
    ),
    (
        "plugs/onlyalpha-plugin-tushare/pyproject.toml",
        "onlyalpha-tushare",
        "onlyalpha_plugin_tushare.doctor:main",
    ),
    ("pyproject.toml", "onlyalpha-research-worker", "onlyalpha.research.worker_main:main"),
    ("pyproject.toml", "onlyalpha-backtest-worker", "onlyalpha.backtest.worker_main:main"),
}

# This is the exact K0 allowlist. Entries include internal composition, classified
# operator/test tooling and known migration debt. Any new construction
# site requires an explicit architecture-contract update.
EXPECTED_DIRECT_CONSTRUCTION_SITES = {
    ("scripts/regenerate_recovery_baselines.py", "OnlyEngine"),
    ("scripts/regenerate_result_fixtures.py", "OnlyEngine"),
    ("src/onlyalpha/research/execution/worker.py", "OnlyEngine"),
    ("src/onlyalpha/backtest/worker.py", "OnlyEngine"),
    ("src/onlyalpha/runtime/backtest/factory.py", "OnlyBacktestRuntime"),
    ("src/onlyalpha/runtime/research/factory.py", "OnlyResearchRuntime"),
    ("src/onlyalpha/runtime/sim/factory.py", "OnlySimRuntime"),
    ("src/onlyalpha/scenario/runner.py", "OnlyEngine"),
}

EXPECTED_DIRECT_CONSTRUCTION_CLASSIFICATION = {
    ("scripts/regenerate_recovery_baselines.py", "OnlyEngine"): "TEST TOOLING",
    ("scripts/regenerate_result_fixtures.py", "OnlyEngine"): "TEST TOOLING",
    ("src/onlyalpha/research/execution/worker.py", "OnlyEngine"): "OPERATOR / INFRASTRUCTURE",
    ("src/onlyalpha/backtest/worker.py", "OnlyEngine"): "OPERATOR / INFRASTRUCTURE",
    ("src/onlyalpha/runtime/backtest/factory.py", "OnlyBacktestRuntime"): "ALLOWED INTERNAL",
    ("src/onlyalpha/runtime/research/factory.py", "OnlyResearchRuntime"): "ALLOWED INTERNAL",
    ("src/onlyalpha/runtime/sim/factory.py", "OnlySimRuntime"): "ALLOWED INTERNAL",
    ("src/onlyalpha/scenario/runner.py", "OnlyEngine"): "OPERATOR / INFRASTRUCTURE",
}

EXPECTED_CONSTRUCTOR_IMPORT_OWNERS = {
    ("scripts/pytest_metrics.py", "OnlyEngine"): "TEST TOOLING",
    ("scripts/regenerate_recovery_baselines.py", "OnlyEngine"): "TEST TOOLING",
    ("scripts/regenerate_result_fixtures.py", "OnlyEngine"): "TEST TOOLING",
    ("src/onlyalpha/application/engine_inspection.py", "OnlyEngine"): "ALLOWED INTERNAL",
    ("src/onlyalpha/application/engine_runner.py", "OnlyEngine"): "ALLOWED INTERNAL",
    ("src/onlyalpha/application/engine_runner.py", "OnlyRuntime"): "ALLOWED INTERNAL",
    ("src/onlyalpha/collector/backtest.py", "OnlyBacktestRuntime"): "ALLOWED INTERNAL",
    ("src/onlyalpha/engine/engine.py", "OnlyResearchRuntime"): "ALLOWED INTERNAL",
    ("src/onlyalpha/engine/engine.py", "OnlyRuntime"): "ALLOWED INTERNAL",
    ("src/onlyalpha/research/execution/worker.py", "OnlyEngine"): "OPERATOR / INFRASTRUCTURE",
    ("src/onlyalpha/backtest/worker.py", "OnlyEngine"): "OPERATOR / INFRASTRUCTURE",
    ("src/onlyalpha/runtime/backtest/driver.py", "OnlyBacktestRuntime"): "ALLOWED INTERNAL",
    ("src/onlyalpha/runtime/backtest/factory.py", "OnlyBacktestRuntime"): "ALLOWED INTERNAL",
    ("src/onlyalpha/runtime/backtest/run_plan.py", "OnlyBacktestRuntime"): "ALLOWED INTERNAL",
    ("src/onlyalpha/runtime/research/__init__.py", "OnlyResearchRuntime"): "ALLOWED INTERNAL",
    ("src/onlyalpha/runtime/research/factory.py", "OnlyResearchRuntime"): "ALLOWED INTERNAL",
    ("src/onlyalpha/runtime/sim/__init__.py", "OnlySimRuntime"): "ALLOWED INTERNAL",
    ("src/onlyalpha/runtime/sim/factory.py", "OnlySimRuntime"): "ALLOWED INTERNAL",
    ("src/onlyalpha/runtime/live/__init__.py", "OnlyLiveRuntime"): "ALLOWED INTERNAL",
    ("src/onlyalpha/runtime/live/runtime.py", "OnlyRuntime"): "ALLOWED INTERNAL",
    ("src/onlyalpha/runtime/trading_facade.py", "OnlyRuntime"): "ALLOWED INTERNAL",
    ("src/onlyalpha/scenario/runner.py", "OnlyEngine"): "OPERATOR / INFRASTRUCTURE",
}

ROOT_PUBLIC_CONTRACT = {
    "OnlyBacktestClock",
    "OnlyBarSubscription",
    "OnlyClock",
    "OnlyClockView",
    "OnlyEvent",
    "OnlyEventBus",
    "OnlyLiveClock",
    "OnlyMarketDataCache",
    "OnlyMarketDataPipeline",
    "OnlyMarketDataSnapshot",
    "OnlyMemoryCache",
    "OnlyRuntimeState",
    "OnlyRuntimeStatus",
    "OnlySqliteStorage",
    "OnlyTimerEvent",
    "OnlyTimerId",
    "OnlyVirtualClock",
}

ROOT_PUBLIC_VALUE_READ_ONLY = {
    "OnlyAccountEquity",
    "OnlyCurrency",
    "OnlyMoney",
    "OnlyPrice",
    "OnlyQuantity",
}

HISTORICAL_ROOT_MIGRATION_DEBT = {
    "OnlyBacktestRuntime",
    "OnlyCluster",
    "OnlyClusterConfig",
    "OnlyClusterContext",
    "OnlyClusterLoader",
    "OnlyClusterRegistry",
    "OnlyClusterRunConfig",
    "OnlyDemoCluster",
    "OnlyDemoRecord",
    "OnlyEngine",
    "OnlyLiveRuntime",
    "OnlyResearchRuntime",
    "OnlyRuntime",
}
ROOT_KNOWN_MIGRATION_DEBT: frozenset[str] = frozenset()

EXPECTED_TOP_LEVEL_EXPORTS = ROOT_PUBLIC_CONTRACT | ROOT_KNOWN_MIGRATION_DEBT
EXPECTED_TOP_LEVEL_BINDINGS = (EXPECTED_TOP_LEVEL_EXPORTS | ROOT_PUBLIC_VALUE_READ_ONLY) - {
    "OnlyRuntimeState",
    "OnlyRuntimeStatus",
}

FORBIDDEN_ROOT_MUTATION_CAPABILITIES = {
    "OnlyPostgresMigrationAuthority",
    "OnlyResearchScheduler",
    "OnlyResearchWorkerService",
    "OnlyStrategyFreezeApplicationService",
    "OnlyStrategyFreezeService",
    "OnlyStrategyPromotionApplicationService",
    "OnlyStrategyPromotionService",
    "OnlyStrategyRevisionStore",
}


def _console_entry_points() -> set[tuple[str, str, str]]:
    result: set[tuple[str, str, str]] = set()
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*pyproject.toml"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    for relative_path in sorted(filter(None, listed.stdout.splitlines())):
        path = ROOT / relative_path
        if not path.is_file():
            continue
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        scripts = document.get("project", {}).get("scripts", {})
        assert isinstance(scripts, dict)
        relative = path.relative_to(ROOT).as_posix()
        result.update((relative, name, target) for name, target in scripts.items())
    return result


def _import_bindings(tree: ast.Module, module_name: str | None) -> dict[str, str]:
    result: dict[str, str] = {}
    package = None if module_name is None else module_name.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".", maxsplit=1)[0]
                result[local] = alias.name if alias.asname else local
        elif isinstance(node, ast.ImportFrom):
            if any(alias.name == "*" for alias in node.names):
                continue
            imported_module = node.module or ""
            if node.level:
                if package is None:
                    continue
                package_parts = package.split(".")
                retained = len(package_parts) - (node.level - 1)
                imported_module = ".".join((*package_parts[:retained], *(node.module or "").split(".")))
            for alias in node.names:
                result[alias.asname or alias.name] = f"{imported_module}.{alias.name}"
    return result


def _qualified_name(expression: ast.expr, bindings: dict[str, str]) -> str | None:
    parts: list[str] = []
    current = expression
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    owner = bindings.get(current.id)
    if owner is None:
        return None
    return ".".join((owner, *reversed(parts)))


def _construction_sites_in_source(source: str, *, module_name: str | None = None) -> set[str]:
    tree = ast.parse(source)
    bindings = _import_bindings(tree, module_name)
    return {
        constructor
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (qualified := _qualified_name(node.func, bindings)) is not None
        and (constructor := CONSTRUCTOR_OWNERS.get(qualified)) is not None
    }


def _direct_construction_sites() -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    roots = (ROOT / "src", ROOT / "packages", ROOT / "scripts", ROOT / "examples")
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            if "tests" in path.relative_to(ROOT).parts:
                continue
            source = path.read_text(encoding="utf-8")
            for name in _construction_sites_in_source(source, module_name=module_name(path, ROOT)):
                result.add((path.relative_to(ROOT).as_posix(), name))
    return result


def _constructor_imports_in_source(source: str, *, module: str | None = None) -> set[str]:
    result: set[str] = set()
    constructor_modules: dict[str, set[str]] = {}
    for qualified, constructor in CONSTRUCTOR_OWNERS.items():
        owner, _, symbol = qualified.rpartition(".")
        if symbol == constructor:
            constructor_modules.setdefault(owner, set()).add(constructor)
    for capability in canonical_imports(source, module=module):
        kind, imported = capability[:2]
        if kind == "module":
            result.update(constructor_modules.get(imported, ()))
        elif len(capability) == 3:
            constructor = CONSTRUCTOR_OWNERS.get(f"{imported}.{capability[2]}")
            if constructor is not None:
                result.add(constructor)
    return result


def _protected_constructor_wildcards(source: str, *, module: str | None = None) -> set[str]:
    return {
        capability[1]
        for capability in canonical_imports(source, module=module)
        if capability[0] == "symbol" and capability[2] == "*" and capability[1] in PROTECTED_CONSTRUCTOR_MODULES
    }


def _constructor_import_owners() -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for root in (ROOT / "src", ROOT / "packages", ROOT / "scripts", ROOT / "examples"):
        for path in sorted(root.rglob("*.py")):
            if "tests" in path.relative_to(ROOT).parts:
                continue
            source = path.read_text(encoding="utf-8")
            imports = canonical_imports_for_path(path, ROOT)
            assert not {
                capability[1]
                for capability in imports
                if capability[0] == "symbol" and capability[2] == "*" and capability[1] in PROTECTED_CONSTRUCTOR_MODULES
            }, f"{path.relative_to(ROOT)} wildcard-imports protected constructor authority"
            imported = _constructor_imports_in_source(source, module=module_name(path, ROOT))
            result.update((path.relative_to(ROOT).as_posix(), name) for name in imported)
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


def _target_names(target: ast.expr) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.List, ast.Tuple)):
        return {name for item in target.elts for name in _target_names(item)}
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    return set()


def _module_scope_statements(statements: list[ast.stmt]) -> tuple[ast.stmt, ...]:
    result: list[ast.stmt] = []
    for node in statements:
        result.append(node)
        nested: list[list[ast.stmt]] = []
        if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While)):
            nested.extend((node.body, node.orelse))
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            nested.append(node.body)
        elif isinstance(node, (ast.Try, ast.TryStar)):
            nested.extend((node.body, node.orelse, node.finalbody))
            nested.extend(handler.body for handler in node.handlers)
        elif isinstance(node, ast.Match):
            nested.extend(case.body for case in node.cases)
        for body in nested:
            result.extend(_module_scope_statements(body))
    return tuple(result)


def _top_level_bindings(source: str) -> set[str]:
    tree = ast.parse(source)
    result: set[str] = set()
    for node in _module_scope_statements(tree.body):
        if isinstance(node, ast.Import):
            result.update(alias.asname or alias.name.split(".", maxsplit=1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert all(alias.name != "*" for alias in node.names), "root wildcard import cannot be audited exactly"
            result.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            result.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            result.update(name for target in targets for name in _target_names(target))
    return {name for name in result if not name.startswith("_")}


def test_console_entry_point_set_is_frozen() -> None:
    assert _console_entry_points() == EXPECTED_CONSOLE_ENTRY_POINTS


def test_direct_engine_and_runtime_construction_sites_are_frozen() -> None:
    assert _direct_construction_sites() == EXPECTED_DIRECT_CONSTRUCTION_SITES
    assert set(EXPECTED_DIRECT_CONSTRUCTION_CLASSIFICATION) == EXPECTED_DIRECT_CONSTRUCTION_SITES


def test_engine_alias_cannot_bypass_constructor_ownership_guard() -> None:
    source = "from onlyalpha import OnlyEngine as Engine\nEngine(config)\n"
    assert _construction_sites_in_source(source) == {"OnlyEngine"}


def test_engine_and_runtime_constructor_import_ownership_is_frozen() -> None:
    assert _constructor_import_owners() == set(EXPECTED_CONSTRUCTOR_IMPORT_OWNERS)
    assert set(EXPECTED_CONSTRUCTOR_IMPORT_OWNERS.values()) == {
        "ALLOWED INTERNAL",
        "OPERATOR / INFRASTRUCTURE",
        "TEST TOOLING",
    }


def test_engine_assignment_alias_is_blocked_at_capability_import_boundary() -> None:
    source = "from onlyalpha import OnlyEngine\nFactory = OnlyEngine\nFactory(config)\n"
    assert _construction_sites_in_source(source) == set()
    assert _constructor_imports_in_source(source) == {"OnlyEngine"}


def test_engine_module_import_is_a_constructor_capability_acquisition() -> None:
    source = "import onlyalpha.engine as engine\nFactory = engine.OnlyEngine\n"
    assert _constructor_imports_in_source(source) == {"OnlyEngine"}


@pytest.mark.parametrize(
    "source",
    (
        "from onlyalpha import *\n",
        "from onlyalpha.engine import *\n",
        "from onlyalpha.runtime import *\n",
        "from onlyalpha.runtime.backtest import *\n",
    ),
)
def test_protected_constructor_wildcard_import_fails_closed(source: str) -> None:
    assert _protected_constructor_wildcards(source)


def test_explicit_constructor_alias_remains_deterministic() -> None:
    source = "from onlyalpha.engine import OnlyEngine as Engine\n"
    assert not _protected_constructor_wildcards(source)
    assert _constructor_imports_in_source(source) == {"OnlyEngine"}


def test_top_level_python_surface_is_frozen() -> None:
    assert ROOT_PUBLIC_CONTRACT.isdisjoint(ROOT_PUBLIC_VALUE_READ_ONLY)
    assert ROOT_PUBLIC_CONTRACT.isdisjoint(ROOT_KNOWN_MIGRATION_DEBT)
    assert ROOT_PUBLIC_VALUE_READ_ONLY.isdisjoint(ROOT_KNOWN_MIGRATION_DEBT)
    assert ROOT_KNOWN_MIGRATION_DEBT == frozenset()
    assert len(HISTORICAL_ROOT_MIGRATION_DEBT) == 13
    assert _top_level_exports() == EXPECTED_TOP_LEVEL_EXPORTS
    source = (ROOT / "src/onlyalpha/__init__.py").read_text(encoding="utf-8")
    assert _top_level_bindings(source) == EXPECTED_TOP_LEVEL_BINDINGS
    assert FORBIDDEN_ROOT_MUTATION_CAPABILITIES.isdisjoint(EXPECTED_TOP_LEVEL_BINDINGS)


def test_root_implicit_import_is_a_frozen_reachable_binding() -> None:
    source = "from onlyalpha.strategy.store import DangerousCapability\n__all__ = []\n"
    assert _top_level_bindings(source) == {"DangerousCapability"}
    assert _top_level_bindings(source) != EXPECTED_TOP_LEVEL_BINDINGS
