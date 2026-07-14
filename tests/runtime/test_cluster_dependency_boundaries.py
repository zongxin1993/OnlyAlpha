import ast
from pathlib import Path


def test_cluster_modules_do_not_import_forbidden_concrete_runtime_resources() -> None:
    forbidden = {
        "onlyalpha.gateway",
        "onlyalpha.engine",
        "onlyalpha.storage",
        "onlyalpha.cache.memory",
        "onlyalpha.market_data.cache",
        "onlyalpha.market_data.aggregation",
    }
    for path in Path("src/onlyalpha/cluster").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = {
            node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert not any(
            imported == prefix or imported.startswith(prefix + ".") for imported in imports for prefix in forbidden
        ), f"{path} imports a forbidden concrete Runtime resource"

        names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert "OnlyBacktestClock" not in names
        assert "OnlyLiveClock" not in names
