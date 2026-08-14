import ast
from pathlib import Path


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    }


def test_research_factor_plugin_has_no_trading_authority_or_mutable_factor_lifecycle_imports() -> None:
    forbidden = (
        "onlyalpha.runtime",
        "onlyalpha.cluster",
        "onlyalpha.strategy",
        "onlyalpha.broker",
        "onlyalpha.account",
        "onlyalpha.order",
        "onlyalpha.position",
        "onlyalpha.risk",
        "onlyalpha.reservation",
        "onlyalpha.execution",
        "onlyalpha.transaction",
        "onlyalpha.factor",
    )
    root = Path("packages/factor/onlyalpha-plugin-factors/src/onlyalpha_plugin_factors")
    for path in root.glob("*.py"):
        imports = _imports(path)
        assert not any(name.startswith(forbidden) for name in imports), (path, imports)


def test_factor_backend_cannot_hide_indicator_implementation_or_create_parallel_authority() -> None:
    root = Path("packages/factor/onlyalpha-plugin-factors/src/onlyalpha_plugin_factors")
    imports = set().union(*(_imports(path) for path in root.glob("*.py")))
    assert not any(name.startswith(("onlyalpha.indicator", "onlyalpha_plugin_indicators")) for name in imports)
    names = {path.name.lower() for path in root.glob("*.py")}
    assert not any(token in name for name in names for token in ("store", "job", "graph", "runtime"))


def test_calculation_core_does_not_depend_on_concrete_factor_plugin() -> None:
    for path in Path("src/onlyalpha/calculation").glob("*.py"):
        assert not any(name.startswith("onlyalpha_plugin_factors") for name in _imports(path)), path
