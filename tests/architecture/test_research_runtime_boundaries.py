from __future__ import annotations

import ast
from pathlib import Path

from onlyalpha.runtime.defaults import only_default_engine_services


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    }


def test_research_runtime_orchestration_has_no_trading_authority_dependency() -> None:
    forbidden = (
        "onlyalpha.account",
        "onlyalpha.broker",
        "onlyalpha.cluster",
        "onlyalpha.execution",
        "onlyalpha.market.product",
        "onlyalpha.order",
        "onlyalpha.position",
        "onlyalpha.reservation",
        "onlyalpha.risk",
        "onlyalpha.settlement",
        "onlyalpha.runtime.trading_facade",
        "onlyalpha.runtime.runtime",
    )
    product_modules = (
        "environment.py",
        "errors.py",
        "plan.py",
        "planning.py",
        "result.py",
        "runtime.py",
    )
    root = Path("src/onlyalpha/runtime/research")
    for name in product_modules:
        imports = _imports(root / name)
        assert not any(value.startswith(forbidden) for value in imports), (name, imports)


def test_trading_runtime_modules_do_not_depend_on_research_runtime() -> None:
    root = Path("src/onlyalpha/runtime")
    for directory in ("backtest", "sim", "streaming"):
        for path in (root / directory).glob("*.py"):
            assert not any(value.startswith("onlyalpha.runtime.research") for value in _imports(path)), path


def test_research_plan_has_no_cluster_market_or_new_semantic_identity() -> None:
    source = Path("src/onlyalpha/runtime/research/plan.py").read_text(encoding="utf-8")
    assert not any(
        token in source for token in ("Cluster", "MarketProduct", "workload_fingerprint", "commit(", "Store")
    )


def test_shared_calculation_registry_is_explicit_and_research_uses_no_indicator_private_state() -> None:
    defaults_path = Path("src/onlyalpha/runtime/defaults.py")
    defaults = ast.parse(defaults_path.read_text(encoding="utf-8"))
    composition = next(
        node
        for node in defaults.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "only_default_engine_services"
    )
    registry_constructors = [
        node
        for node in ast.walk(composition)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "OnlyCalculationRegistry"
    ]
    assert len(registry_constructors) == 1

    assignments = {
        target.id: node.value
        for node in composition.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert "calculations" in assignments
    indicator_compositions = [
        node
        for node in ast.walk(composition)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "OnlyIndicatorFactoryRegistry"
    ]
    assert len(indicator_compositions) == 1
    assert [ast.unparse(arg) for arg in indicator_compositions[0].args] == ["calculations"]

    factory_path = Path("src/onlyalpha/runtime/research/factory.py")
    factory = ast.parse(factory_path.read_text(encoding="utf-8"))
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"OnlyCalculationRegistry", "OnlyIndicatorFactoryRegistry"}
        for node in ast.walk(factory)
    )
    assert any(
        isinstance(node, ast.Attribute)
        and node.attr == "calculations"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "components"
        for node in ast.walk(factory)
    )

    services = only_default_engine_services(fail_fast=True)
    assert services.assembler.components.calculations is not None


def test_query_remains_downstream_and_absent_from_runtime_execution() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in Path("src/onlyalpha/runtime/research").glob("*.py"))
    assert "onlyalpha.research.query" not in source
