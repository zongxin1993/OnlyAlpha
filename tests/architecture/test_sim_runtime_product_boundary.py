from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

_SOURCE_ROOT = Path(__file__).parents[2] / "src" / "onlyalpha"
_SIM_ROOT = _SOURCE_ROOT / "runtime" / "sim"


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(path: Path) -> frozenset[str]:
    names: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return frozenset(names)


def test_sim_product_has_no_legacy_or_concrete_runtime_dependency() -> None:
    imports = {name for path in _SIM_ROOT.glob("*.py") for name in _imports(path)}
    forbidden = (
        "onlyalpha.runtime.paper",
        "onlyalpha.runtime.backtest",
        "onlyalpha.runtime.shadow",
    )

    assert not any(name.startswith(forbidden) for name in imports)


def test_sim_product_does_not_import_shadow_execution_or_economic_authorities() -> None:
    forbidden_names = {
        "OnlyShadowExecutionService",
        "OnlyAccountManager",
        "OnlyPositionManager",
        "OnlyRiskManager",
        "OnlyOrderManager",
        "OnlyFeeEngine",
        "OnlySettlementManager",
        "OnlyTransactionCoordinator",
        "OnlyStrategyLedgerManager",
    }
    referenced: set[str] = set()
    constructed: set[str] = set()
    for path in _SIM_ROOT.glob("*.py"):
        tree = _tree(path)
        referenced.update(node.id for node in ast.walk(tree) if isinstance(node, ast.Name))
        constructed.update(
            node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        )

    assert forbidden_names.isdisjoint(referenced)
    assert forbidden_names.isdisjoint(constructed)


def test_sim_identity_does_not_enter_strategy_facade_or_trading_kernel_branches() -> None:
    paths = [
        _SOURCE_ROOT / "strategy" / "context.py",
        _SOURCE_ROOT / "runtime" / "trading_facade.py",
        *(_SOURCE_ROOT / "runtime" / "trading").glob("*.py"),
    ]
    for path in paths:
        tree = _tree(path)
        comparisons = [node for node in ast.walk(tree) if isinstance(node, (ast.Compare, ast.If, ast.Match, ast.IfExp))]
        assert all(
            "SIM"
            not in {
                child.value
                for child in ast.walk(node)
                if isinstance(child, ast.Constant) and isinstance(child.value, str)
            }
            for node in comparisons
        ), path
