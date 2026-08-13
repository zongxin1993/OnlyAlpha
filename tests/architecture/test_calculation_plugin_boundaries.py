import ast
from pathlib import Path


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    }


def test_core_does_not_import_calculation_plugins_or_own_concrete_algorithms() -> None:
    for path in Path("src/onlyalpha").rglob("*.py"):
        imports = _imports(path)
        assert not any(
            name.startswith(("onlyalpha_plugin_indicators", "onlyalpha_plugin_factors")) for name in imports
        ), path
    forbidden = {"macd", "ema", "sma", "rsi", "atr", "bollinger", "rolling_return", "rolling_volatility", "zscore"}
    assert not forbidden.intersection(
        path.name for path in Path("src/onlyalpha/indicator").iterdir() if any(path.glob("*.py"))
    )


def test_semantic_definition_layer_has_no_runtime_or_trading_authority_imports() -> None:
    forbidden = (
        "onlyalpha.runtime",
        "onlyalpha.cluster",
        "onlyalpha.account",
        "onlyalpha.broker",
        "onlyalpha.order",
        "onlyalpha.position",
        "onlyalpha.transaction",
    )
    for path in Path("src/onlyalpha/calculation").glob("*.py"):
        imports = _imports(path)
        assert not any(name.startswith(forbidden) for name in imports), (path, imports)
