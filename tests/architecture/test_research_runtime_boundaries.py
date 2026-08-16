from __future__ import annotations

import ast
from pathlib import Path


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
    defaults = Path("src/onlyalpha/runtime/defaults.py").read_text(encoding="utf-8")
    factory = Path("src/onlyalpha/runtime/research/factory.py").read_text(encoding="utf-8")
    assert "calculations = OnlyCalculationRegistry()" in defaults
    assert "OnlyIndicatorFactoryRegistry(calculations)" in defaults
    assert "components.calculations" in factory
    assert "_calculations" not in factory


def test_query_remains_downstream_and_absent_from_runtime_execution() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in Path("src/onlyalpha/runtime/research").glob("*.py"))
    assert "onlyalpha.research.query" not in source
