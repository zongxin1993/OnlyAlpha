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
            name.startswith(("onlyalpha_plugin_indicators", "onlyalpha_plugin_factors", "onlyalpha_plugin_targets"))
            for name in imports
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


def test_calculation_identity_has_one_authority_and_excludes_implementation_identity() -> None:
    calculation = Path("src/onlyalpha/calculation")
    fingerprint_calls: list[Path] = []
    for path in calculation.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "only_canonical_fingerprint"
            ):
                fingerprint_calls.append(path)
    assert set(fingerprint_calls) == {calculation / "definition.py", calculation / "graph.py"}
    semantic_source = "\n".join(path.read_text(encoding="utf-8") for path in calculation.glob("*.py"))
    for forbidden in ("class_path", "factor_path", "runtime_id", "cluster_id", "created_at", "uuid4"):
        assert forbidden not in semantic_source
