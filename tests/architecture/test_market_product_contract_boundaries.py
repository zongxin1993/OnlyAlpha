from __future__ import annotations

import ast
from pathlib import Path

PRODUCT_ROOT = Path("src/onlyalpha/market/product")
CORE_ROOT = Path("src/onlyalpha")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
        elif isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
    return imports


def test_market_product_core_contract_has_no_concrete_market_or_runtime_dependency() -> None:
    forbidden_imports = (
        "onlyalpha.market.ashare_rules",
        "onlyalpha.market.profiles",
        "onlyalpha.reference.ashare",
        "onlyalpha.runtime",
        "onlyalpha_plugin_",
    )
    forbidden_tokens = (
        "Ashare",
        "CN_A_SHARE",
        "GENERIC_T0",
        "XSHG",
        "XSHE",
        "OnlyRuntimeMode",
        "OrderManager",
        "PositionManager",
        "AccountManager",
        "RiskManager",
        "ExecutionProcessor",
    )
    violations: list[str] = []
    for path in sorted(PRODUCT_ROOT.glob("*.py")):
        for imported in _imports(path):
            if any(imported == value or imported.startswith(f"{value}.") for value in forbidden_imports):
                violations.append(f"{path}: import {imported}")
        source = path.read_text(encoding="utf-8")
        violations.extend(f"{path}: token {token}" for token in forbidden_tokens if token in source)
    assert not violations


def test_research_does_not_depend_on_trading_market_product_contract() -> None:
    research_root = CORE_ROOT / "runtime" / "research"
    assert all(
        "onlyalpha.market.product" not in path.read_text(encoding="utf-8")
        for path in sorted(research_root.rglob("*.py"))
    )


def test_product_identity_is_not_a_core_behavior_selector() -> None:
    violations: list[str] = []
    for path in sorted(CORE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.If, ast.Match)):
                continue
            subject = node.test if isinstance(node, ast.If) else node.subject
            if any(
                isinstance(item, ast.Attribute) and item.attr in {"product_id", "product_version"}
                for item in ast.walk(subject)
            ):
                violations.append(f"{path}:{node.lineno}")
    assert not violations


def test_binding_is_an_authority_bundle_not_a_trading_service() -> None:
    tree = ast.parse((PRODUCT_ROOT / "binding.py").read_text(encoding="utf-8"))
    methods = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert not methods & {"submit_order", "apply_trade", "update_position", "on_bar", "calculate_pnl"}
